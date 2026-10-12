"""Isolated Skill acceptance: live generation, real SDK, controlled UI retry."""
import asyncio, json, os, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import config
PROJECT=config.ROOT
FIXTURE=Path(tempfile.mkdtemp(prefix='skill-alignment-',dir=PROJECT/'data'))
(FIXTURE/'data').mkdir()
shutil.copytree(PROJECT/'skills',FIXTURE/'skills')
for name in ('frontend','generators','contracts','agent-runtime','node_modules'):
    (FIXTURE/name).symlink_to(PROJECT/name,target_is_directory=True)
(FIXTURE/'data/browsers').symlink_to(PROJECT/'data/browsers',target_is_directory=True)
config.ROOT=FIXTURE
config.settings.openmaic_port=8011
config.settings.openmaic_origin='http://127.0.0.1:8011'
from backend import app as service
from backend.models import Stage,Plan,PlanPage,Teacher,digest
from backend.store import now
from fastapi.responses import JSONResponse

ui_attempts=[]
@service.app.middleware('http')
async def retry_fixture(request,call_next):
    if request.method=='POST' and request.url.path.endswith('/messages'):
        body=json.loads(await request.body())
        ui_attempts.append(body)
        (FIXTURE/'ui-requests.json').write_text(json.dumps(ui_attempts,ensure_ascii=False,indent=2))
        if len(ui_attempts)==1:
            return JSONResponse({'error':{'code':'ACCEPTANCE_RETRY','message':'验收：首次发送失败，请重试原消息'}},status_code=503)
        os.environ['NODE_OPTIONS']='--import='+str(PROJECT/'tests/sdk-preload.mjs')
        os.environ['OPENMAIC_FIXTURE_STEPS']=json.dumps([['read_skill',{'skillId':id}] for id in ('workshop-style','feynman-learning')]+[['ask_user',{'kind':'question','question':'已真实读取两项 Skill。是否继续？','options':['继续','暂停']}]],ensure_ascii=False)
        os.environ['OPENMAIC_FIXTURE_CONTEXT']=str(FIXTURE/'ui-contexts.jsonl')
    return await call_next(request)

original_request=service.providers.request
async def capture_request(*args,**kwargs):
    body=kwargs.get('json')
    if body and ('messages' in body or 'instructions' in body):
        with (FIXTURE/'generation-inputs.jsonl').open('a') as log:
            log.write(json.dumps(body,ensure_ascii=False)+'\n')
    return await original_request(*args,**kwargs)
service.providers.request=capture_request

def seed(id,method,pages):
    plan=Plan(title=method+'：牛顿第二定律验收',audience='初中生',objectives=['解释力和质量如何影响加速度'],pages=pages)
    stage=Stage(id=id,title=plan.title,approvedPlan=plan,teacher=Teacher(model=config.settings.bailian_tts_model,voice=config.settings.bailian_tts_voice),updatedAt=now())
    service.store.put('stage',id,stage.model_dump());service.store.put('course_owner',id,{'ownerId':service.store.owner_id})
    service.store.put('course_approval',id,{'planHash':digest(plan.model_dump()),'approvalId':'acceptance-approved'})
    return stage,service.store.session(id)

async def live_run(stage,session,prompt,run):
    service.store.patch_session(session['id'],state='running',runId=run)
    service.store.put('run',run,{'id':run,'sessionId':session['id'],'state':'running','metadataVersion':3,'courseTasks':{},'haltFeedback':True})
    await service.runtime.run(service.store.get('session',session['id']),prompt,False,run+'-message')
    record=service.store.get('run',run)
    (FIXTURE/(run+'.json')).write_text(json.dumps({'run':record,'timeline':service.store.timeline(session['id']),'course':service.courses.stage(stage.id).model_dump(),'events':service.store.events(session['id']),'details':service.store.list('pi_tool_detail')},ensure_ascii=False,indent=2))
    print(json.dumps({'run':run,'state':record['state'],'error':record.get('error'),'pages':len(service.courses.stage(stage.id).scenes)},ensure_ascii=False),flush=True)
    if record['state']=='failed':raise RuntimeError(record.get('error'))

async def generate():
    workshop,ws=seed('workshop-acceptance','工作坊',[PlanPage(id='p1',title='先预测，再验证',type='slide',brief='工作坊：用两个小车的力质量对比让学生先预测，再指出验证方法'),PlanPage(id='p2',title='亲手改变力和质量',type='interactive',brief='工作坊：F=ma，滑块改变F和m，先预测再观察a，提供两组预设，单位明确，图像可恢复'),PlanPage(id='p3',title='检验你的预测',type='quiz',brief='工作坊：两道单选诊断力质量与加速度，解析不提前泄露')])
    lecture,ls=seed('lecture-acceptance','讲授',[PlanPage(id='p1',title='由关系到定律',type='slide',brief='大师讲授：清晰解释F=ma，先阐明合外力再论证比例关系，用简洁结构和例子，不默认安排动手任务')])
    common='这是隔离验收课程，方案已批准。本次只生成页面和讲解动作，不生成TTS、图片，不执行检查，不追求整课就绪。先完整读取显式Skill，再read_stage或list_scenes核实目标页和最新版本，然后直接调用业务工具。调用generate_scene时把方案的教学方法落实到brief，调用generate_actions时落实到guidance，每次写入使用最新revision。完成后停止，不扩展范围。'
    await live_run(workshop,ws,'/workshop-style '+common+'目标课程workshop-acceptance，生成p1/p2/p3及各自的动作。','live-workshop')
    await live_run(lecture,ls,'/lecture-style '+common+'目标课程lecture-acceptance，只生成p1和动作。','live-lecture')
    before=service.courses.stage(workshop.id).model_dump()
    await live_run(workshop,ws,'/pro-editing 本次只修改workshop-acceptance的p1中标题文字的字号：设为36。先read_stage读取真实sceneId、elementId及revision，登记p1的edit范围，再用patch_stage最小修改。不要改变其他元素、页面、动作、媒体，不要重新生成，不要检查或TTS。完成后停止。','live-edit')
    after=service.courses.stage(workshop.id).model_dump()
    summary={'fixture':str(FIXTURE),'generationRequests':len((FIXTURE/'generation-inputs.jsonl').read_text().splitlines()),'workshopPageTypes':[s['type'] for s in after['scenes']],'lecturePageTypes':[s.type for s in service.courses.stage(lecture.id).scenes],'noAudio':not service.store.list('media'),'otherPagesUnchanged':before['scenes'][1:]==after['scenes'][1:],'actionsPreserved':before['scenes'][0]['actions']==after['scenes'][0]['actions']}
    (FIXTURE/'live-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False),flush=True)

async def main():
    import uvicorn
    print('FIXTURE='+str(FIXTURE),flush=True)
    server=uvicorn.Server(uvicorn.Config(service.app,host='127.0.0.1',port=8011,access_log=False,log_level='warning'))
    serving=asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():await serving
        await asyncio.sleep(.05)
    if '--live' in sys.argv:
        await generate()
    else:
        service.store.session()
    print('BROWSER_READY http://127.0.0.1:8011/',flush=True)
    await serving
if __name__=='__main__':asyncio.run(main())
