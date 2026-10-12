import asyncio
import base64
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode, urlparse
from .config import settings
from .courses import fail, DomainError
from .models import Stage, Scene, uid, scene_fingerprint, audio_signature, digest, render_fingerprint, visual_fingerprint, program_fingerprint
from .store import now


class Inspection:
    def __init__(self, courses, providers):
        self.courses,self.providers=courses,providers
        self.store=courses.store
        self.tokens={}
        self.browser_lock=asyncio.Semaphore(1)

    def authorize(self, stage_id, token):
        entry=self.tokens.get(token)
        if not entry or entry['stageId']!=stage_id or entry['expires']<time.monotonic():
            fail('PREVIEW_AUTH','内部预览凭据无效或过期')
        stage=self.courses.stage(stage_id)
        scene=next((s for s in stage.scenes if s.id==entry['sceneId']),None)
        if not scene or render_fingerprint(stage,scene,store=self.store)!=entry['fingerprint']:
            fail('PREVIEW_STALE','页面版本已经变化')
        return stage

    @asynccontextmanager
    async def page(self, stage, scene, width, height):
        if not settings.capabilities()['preview']['available']:
            fail('BROWSER_MISSING','请在 Python 项目内安装 Playwright Chromium，见 README')
        if not (settings.data_dir.parent/'frontend/dist/index.html').is_file():
            fail('FRONTEND_MISSING','请先构建前端：npm run build')
        from playwright.async_api import async_playwright
        token=secrets.token_urlsafe(32)
        self.tokens[token]={'stageId':stage.id,'sceneId':scene.id,'fingerprint':render_fingerprint(stage,scene,store=self.store),'expires':time.monotonic()+300}
        browser=None
        try:
            async with self.browser_lock, async_playwright() as playwright:
                browser=await playwright.chromium.launch(headless=True)
                context=await browser.new_context(viewport={'width':width,'height':height},device_scale_factor=1)
                allowed=urlparse(settings.openmaic_origin).netloc
                async def restrict(route):
                    if urlparse(route.request.url).netloc not in ('',allowed):
                        await route.abort()
                    else:
                        await route.continue_()
                await context.route('**/*',restrict)
                page=await context.new_page()
                page.openmaic_errors=[]
                page.on('pageerror',lambda error:page.openmaic_errors.append(str(error)))
                page.set_default_timeout(8000)
                url=settings.openmaic_origin+'/preview?'+urlencode({'stage':stage.id,'scene':scene.id,'token':token})
                await page.goto(url,wait_until='networkidle',timeout=20000)
                await page.wait_for_function('window.openmaicPreview?.ready === true || !!document.querySelector("[data-preview-error]")',timeout=10000)
                if await page.locator('[data-preview-error]').count():
                    fail('PREVIEW_LOAD',await page.locator('[data-preview-error]').inner_text())
                await page.evaluate('document.fonts.ready')
                await page.wait_for_function('Array.from(document.images).every(i=>i.complete)')
                if await page.locator('[data-preview-error]').count():
                    fail('PREVIEW_LOAD',await page.locator('[data-preview-error]').inner_text())
                try:
                    yield page
                finally:
                    await context.close()
                    await browser.close()
                    browser=None
        finally:
            self.tokens.pop(token,None)
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def widget(self,page,type,payload=None):
        return await page.evaluate('(args)=>window.openmaicPreview.request(args.type,args.payload)',{'type':type,'payload':payload or {}})

    def current(self,stage,scene,mode='program'):
        fn=render_fingerprint if mode=='render' else visual_fingerprint if mode=='visual' else program_fingerprint
        current=self.courses.stage(stage.id)
        target=next((s for s in current.scenes if s.id==scene.id),None)
        if not target or fn(current,target,store=self.store)!=fn(stage,scene,store=self.store):
            fail('INSPECTION_STALE','检查期间页面或音频已改变，结果不适用于新版本')

    async def preview(self,stage,scene,width,height,state):
        if state is not None and scene.type!='interactive':
            fail('PREVIEW_STATE','只有实验支持状态预览')
        if state is not None:
            scene.content.validate_state(state)
        async with self.page(stage,scene,width,height) as page:
            actual=await self.widget(page,'SET_STATE',{'state':state}) if state is not None else await self.widget(page,'GET_STATE') if scene.type=='interactive' else None
            # SET_STATE may update Canvas/SVG in the next animation frame.
            await page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            if page.openmaic_errors:
                fail('PREVIEW_RUNTIME', settings.redact('; '.join(page.openmaic_errors))[:2000])
            body=await page.screenshot(type='png',full_page=False)
            targets=await page.locator('[data-element-id]').evaluate_all('(nodes)=>nodes.map(n=>({id:n.dataset.elementId,rect:{x:n.getBoundingClientRect().x,y:n.getBoundingClientRect().y,width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height}}))')
        self.current(stage,scene,'render')
        media=self.providers.save_media(stage.id,body,'image/png',{'width':width,'height':height,'kind':'snapshot'})
        snapshot={'id':uid('snapshot'),'stageId':stage.id,'sceneId':scene.id,'revision':stage.revision,'fingerprintVersion':2,'fingerprint':render_fingerprint(stage,scene,width,height,actual.get('state') if isinstance(actual,dict) else None,self.store),'viewport':{'width':width,'height':height},'state':actual,'mediaId':media['id'],'createdAt':now()}
        self.store.put('snapshot',snapshot['id'],snapshot)
        return {**snapshot,'snapshotId':snapshot['id'],'targets':targets,'image':{'data':base64.b64encode(body).decode(),'mimeType':'image/png'}}

    async def check(self,stage,scene,args):
        try:
            return await self._check(stage,scene,args)
        except Exception as exc:
            if args.mode=='visual' or (isinstance(exc,DomainError) and exc.code=='INSPECTION_STALE'):
                raise
            self.current(stage,scene)
            code=getattr(exc,'code','INSPECTION_EXECUTION')
            message=settings.redact(str(exc))[:2000]
            report={'id':uid('inspection'),'stageId':stage.id,'sceneId':scene.id,'revision':stage.revision,'fingerprint':program_fingerprint(stage,scene,self.store),'fingerprintVersion':2,'executed':False,'mode':'program','passed':False,'issues':[{'code':code,'location':scene.id,'severity':'error','message':message}],'findings':[message],'coverage':['检查执行失败；未确认任何浏览器检查通过'],'uncovered':['浏览器渲染、交互与视口检查未完成'],'createdAt':now()}
            report['reportId']=report['id']
            self.store.put('inspection',report['id'],report)
            return report

    async def _check(self,stage,scene,args):
        fingerprint=visual_fingerprint(stage,scene,self.store) if args.mode=='visual' else program_fingerprint(stage,scene,self.store)
        if args.mode=='visual':
            if not args.snapshotId or args.passed is None:
                fail('VISUAL_REQUIRED','视觉结论需引用真实 snapshotId，并明确 passed 与 findings')
            snapshot=self.store.get('snapshot',args.snapshotId)
            expected_render=render_fingerprint(stage,scene,snapshot['viewport']['width'],snapshot['viewport']['height'],snapshot.get('state',{}).get('state') if isinstance(snapshot.get('state'),dict) else None,self.store)
            snapshot_valid=snapshot['fingerprint']==expected_render if snapshot.get('fingerprintVersion')==2 else snapshot['fingerprint']==scene_fingerprint(stage,scene)
            if snapshot['stageId']!=stage.id or snapshot['sceneId']!=scene.id or not snapshot_valid:
                fail('SNAPSHOT_STALE','截图与当前页面版本不匹配')
            if snapshot['viewport']!={'width':1280,'height':720}:
                fail('VISUAL_VIEWPORT','完成门禁要求当前页面的默认 1280×720 截图结论')
            report={'id':uid('inspection'),'stageId':stage.id,'sceneId':scene.id,'revision':stage.revision,'fingerprint':fingerprint,'fingerprintVersion':2,'executed':True,'renderFingerprint':snapshot['fingerprint'],'mode':'visual','snapshotId':args.snapshotId,'passed':args.passed,'findings':args.findings,'coverage':['1280×720 真实截图的模型视觉判断', '截图实验状态：'+str(snapshot.get('state'))],'uncovered':args.uncovered+['科学正确性与教学效果未经过独立评测'],'createdAt':now()}
            self.current(stage,scene,'visual')
            report['reportId']=report['id']
            self.store.put('inspection',report['id'],report)
            return report
        issues=[]
        coverage=[]
        def issue(code,location,message,severity='error',details=None):
            entry={'code':code,'location':location,'message':message,'severity':severity}
            if details is not None:
                entry['details']=details
            issues.append(entry)
        # Stored documents are validated again rather than trusting previous generation.
        Stage.model_validate(stage.model_dump())
        coverage.append('Pydantic 文档、元素/动作/来源引用')
        if not scene.actions:
            issue('NO_ACTIONS',scene.id,'缺少教学动作')
        for action in scene.actions:
            if action.type=='speech':
                media=self.store.find('media',action.audioId) if action.audioId else None
                if action.audioStatus!='ready' or action.audioSignature!=audio_signature(action,stage.teacher) or not media or not (settings.data_dir/'media'/media['file']).is_file():
                    issue('AUDIO_INVALID',action.id,'讲稿缺少当前签名的可读音频')
        coverage.append('讲稿音频签名与本地媒体')
        async with self.page(stage,scene,1280,720) as page:
            errors=page.openmaic_errors
            result=await page.evaluate('''() => ({
                broken:Array.from(document.images).filter(i=>!i.naturalWidth).map(i=>i.src),
                formula:Array.from(document.querySelectorAll('[data-render-error]')).map(n=>n.textContent),
                elements:Array.from(document.querySelectorAll('[data-element-id]')).map(n=>{
                    const clientWidth=n.clientWidth, clientHeight=n.clientHeight;
                    const scrollWidth=n.scrollWidth, scrollHeight=n.scrollHeight;
                    const excessX=scrollWidth-clientWidth, excessY=scrollHeight-clientHeight;
                    return {id:n.dataset.elementId,type:n.dataset.elementType,
                        clientWidth,clientHeight,scrollWidth,scrollHeight,excessX,excessY,
                        overflow:excessX>2||excessY>2,
                        rect:{x:n.offsetLeft,y:n.offsetTop,width:n.offsetWidth,height:n.offsetHeight}};
                }),
                zoom:!!document.querySelector('[aria-label="放大幻灯片"]')
            })''')
            for url in result['broken']:
                issue('IMAGE_LOAD',scene.id,'配图无法加载：'+url)
            for error in result['formula']:
                issue('FORMULA_RENDER',scene.id,error)
            if scene.type=='slide':
                for element in result['elements']:
                    rect=element['rect']
                    if rect['x']<0 or rect['y']<0 or rect['x']+rect['width']>scene.content.width+1 or rect['y']+rect['height']>scene.content.height+1:
                        issue('CANVAS_BOUNDS',element['id'],'元素超出逻辑画布')
                    if element['overflow']:
                        directions=[]
                        if element['excessX']>2:
                            directions.append(f"横向溢出 {element['excessX']}px（容器宽度 {element['clientWidth']}px，内容宽度 {element['scrollWidth']}px）")
                        if element['excessY']>2:
                            directions.append(f"纵向溢出 {element['excessY']}px（容器高度 {element['clientHeight']}px，内容高度 {element['scrollHeight']}px）")
                        measurements={key:element[key] for key in ('type','clientWidth','clientHeight','scrollWidth','scrollHeight','excessX','excessY')}
                        issue('ELEMENT_OVERFLOW',element['id'],'内容超出元素容器：'+'；'.join(directions),details={**measurements,'tolerancePx':2})
                ids={e['id'] for e in result['elements']}
                for action in scene.actions:
                    if action.type in ('spotlight','laser') and action.elementId not in ids:
                        issue('ACTION_TARGET',action.id,'实际 DOM 缺少指示目标')
                if not result['zoom']:
                    issue('ZOOM_MISSING',scene.id,'缺少窄屏放大入口')
            coverage.append('1280×720 正式 DOM、图片加载、公式和明显溢出')
            if scene.type=='interactive':
                await self.check_simulation(page,scene,issue,coverage)
            for error in errors:
                issue('RUNTIME_ERROR',scene.id,error)
        if scene.type in ('interactive','quiz'):
            async with self.page(stage,scene,375,812) as page:
                if scene.type=='interactive':
                    frame=next(f for f in page.frames if f!=page.main_frame)
                    for selector in scene.content.controls:
                        node=frame.locator(selector)
                        if not await node.count():
                            issue('MOBILE_CONTROL',selector,'窄屏缺少控件')
                            continue
                        if await node.is_visible():
                            await node.scroll_into_view_if_needed()
                            box=await node.bounding_box()
                            if box and (box['x']<0 or box['x']+box['width']>376):
                                issue('MOBILE_OVERFLOW',selector,'控件超出窄屏，主要操作不可达')
                    await self.widget(page,'RESET')
                else:
                    overflow=await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
                    if overflow:
                        issue('MOBILE_OVERFLOW',scene.id,'测验主要内容横向溢出')
                coverage.append('375×812 主要控件/题目可达性')
        else:
            async with self.page(stage,scene,375,812) as page:
                if await page.locator('[data-canvas]').count()!=1:
                    issue('MOBILE_CANVAS',scene.id,'窄屏逻辑画布缺失')
                coverage.append('375×812 幻灯片缩放与放大入口')
        self.current(stage,scene)
        report={'id':uid('inspection'),'stageId':stage.id,'sceneId':scene.id,'revision':stage.revision,'fingerprint':fingerprint,'fingerprintVersion':2,'executed':True,'mode':'program','passed':not any(i['severity']=='error' for i in issues),'issues':issues,'findings':[i['location']+'：'+i['message'] for i in issues],'coverage':coverage,'uncovered':['其他视口、未声明参数状态、科学正确性及完整教学效果'],'createdAt':now()}
        report['reportId']=report['id']
        self.store.put('inspection',report['id'],report)
        return report

    async def check_simulation(self,page,scene,issue,coverage):
        content=scene.content
        frame=next(f for f in page.frames if f!=page.main_frame)
        initial=await self.widget(page,'GET_STATE')
        def equal(a,b):
            return all(a.get(k)==v for k,v in b.items())
        if not equal(initial['state'],content.initialState):
            issue('INITIAL_STATE',scene.id,'实验初值与文档不一致')
        observations=[]
        for preset in content.presets:
            reply=await self.widget(page,'SET_STATE',{'state':preset.state})
            if not equal(reply['state'],preset.state):
                issue('PRESET_STATE',preset.name,'预设参数没有真实生效')
            observations.append(digest(reply['observation']))
            coverage.append('实验预设 '+preset.name+'：'+str(preset.state))
        if len(set(observations))<2:
            issue('OBSERVATION_STATIC',scene.id,'至少两组代表参数需要产生不同可观察结果')
        var=content.variables[0]
        await self.widget(page,'RESET')
        before=await self.widget(page,'GET_STATE')
        locator=frame.locator(var.selector)
        if not await locator.count():
            issue('CONTROL_MISSING',var.selector,'声明的手动控件不存在')
        else:
            value=var.max if var.default!=var.max else var.min
            if await locator.get_attribute('type') == 'range':
                await locator.focus()
                await locator.press('End' if value==var.max else 'Home')
                value=float(await locator.input_value())
            else:
                await locator.fill(str(value))
                await locator.press('Tab')
            await page.wait_for_timeout(150)
            after=await self.widget(page,'GET_STATE')
            if after['state'].get(var.name)!=value or digest(after['observation'])==digest(before['observation']):
                issue('MANUAL_NO_UPDATE',var.selector,'手动输入未更新状态或观察结果')
            coverage.append('手动控件 '+var.selector+' → '+str(value))
        for probe in content.dragProbes:
            await self.widget(page,'RESET')
            before=await self.widget(page,'GET_STATE')
            node=frame.locator(probe.selector)
            box=await node.bounding_box()
            if not box:
                issue('DRAG_TARGET',probe.selector,'拖动目标不可见')
                continue
            x,y=box['x']+box['width']/2,box['y']+box['height']/2
            await page.mouse.move(x,y)
            await page.mouse.down()
            await page.mouse.move(x+probe.dx,y+probe.dy,steps=10)
            await page.mouse.up()
            after=await self.widget(page,'GET_STATE')
            if digest(before['state'])==digest(after['state']) or digest(before['observation'])==digest(after['observation']):
                issue('DRAG_NO_UPDATE',probe.selector,'拖动未产生真实状态和观察变化')
            coverage.append('拖动 '+probe.selector+f' ({probe.dx},{probe.dy})')
        widget_actions = [action for action in scene.actions if action.type.startswith('widget_')]
        for action in widget_actions:
            kind={'widget_setState':'SET_STATE','widget_highlight':'HIGHLIGHT','widget_annotation':'ANNOTATION','widget_reveal':'REVEAL'}[action.type]
            try:
                await self.widget(page,kind,{'state':action.state,'target':action.target,'content':action.content})
            except Exception as exc:
                issue('WIDGET_ACK',action.id,str(exc))
        if widget_actions:
            coverage.append('教学动作 ACK：'+', '.join(action.id for action in widget_actions))
        await self.widget(page,'PAUSE')
        await self.widget(page,'RESUME')
        reset=await self.widget(page,'RESET')
        if not equal(reset['state'],content.initialState):
            issue('RESET_INVALID',scene.id,'重置未恢复声明初值')
        coverage.extend(['实验初值、控件手动输入、观察值更新','暂停/恢复与 reset'])
