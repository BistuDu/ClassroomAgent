import base64
import json
import jsonpointer
from .config import settings
from .courses import fail
from .models import Scene, Stage, Action, Model, audio_signature, scene_fingerprint, uid, digest
from .providers import validate_teacher
from .tool_args import TOOLS
from .tool_result import success, scene_tree, stage_summary
from .document_tools import read, grep, page_text, cursor, cursor_index
from .models import Teacher
from .store import now
from .run_context import RunContext, active_operation, WRITE_TOOLS
from .operations import OperationRecord
from .legacy_tasks import pending_page

class ActionOutput(Model):
    actions: list[Action]


class Tools:
    def __init__(self, courses, providers, inspection, narration):
        self.courses, self.providers, self.inspection = courses, providers, inspection
        self.store = courses.store
        self.narration = narration
        self.context=RunContext(courses)
        self.operations=OperationRecord(self.store)

    async def call(self, session_id, run_id, request_id, name, raw, on_progress=None):
        self.store.require_session(session_id)
        run=self.store.find('run',run_id)
        if not run or run['sessionId']!=session_id:fail('RUN_SCOPE','运行不属于当前对话')
        operation,cached=self.operations.begin(session_id,run_id,request_id,name,raw)
        if cached:return cached
        context=None;before=None;changes={};token=None
        try:
            if name=='set_course_tasks':
                fail('TOOL_REMOVED','任务登记工具已移除；请读取目标课程/页面后直接调用业务工具，旧历史仍可查看')
            if name not in TOOLS:fail('UNKNOWN_TOOL','工具不在白名单中')
            args=TOOLS[name][0].model_validate(raw);args=getattr(args,'root',args)
            session=self.store.require_session(session_id)
            if session['runId']!=run_id or session['state']!='running' or session['pendingQuestion']:
                fail('WAITING_OR_STOPPED','当前运行已停止或等待用户，禁止继续调用工具')
            self.context.ensure(session_id,run_id)
            target_id=getattr(args,'stageId',None)
            if target_id:self.courses.scope(session_id,target_id)
            context=self.context.select(session_id,run_id,name,args)
            if context:self.courses.scope(session_id,target_id,True)
            before=self.courses.stage(target_id) if target_id else None
            if before:operation['inputRevision']=before.revision
            token=active_operation.set(context)
            data=await self.execute(session_id,run_id,request_id,name,args,on_progress)
            self.context.observe(session_id,run_id,name,args,data)
            if context:self.context.record(context,before,data)
            target_id=target_id or (data.get('stageId') if isinstance(data,dict) else None)
            if target_id:
                self.store.link_course(session_id,target_id)
                after=self.courses.stage(target_id)
                if isinstance(data,dict):
                    data.setdefault('stageId',target_id)
                    for issue in data.get('issues',[]):
                        if isinstance(issue,dict):issue.setdefault('stageId',target_id)
                if before and before.id==after.id:
                    changes=self.courses.changes(before,after)
                    if isinstance(data,dict) and name not in ('read_stage','grep_stage','list_scenes','fetch_url','web_search','render_scene_preview','check_scene'):
                        data.setdefault('changes',changes)
            result=success(name,data,waiting=name=='ask_user')
            if name=='check_scene' and data.get('executed') is False and any(i.get('code') in ('BROWSER_MISSING','FRONTEND_MISSING') for i in data.get('issues',[])):
                self.store.put('run',run_id,{**self.store.get('run',run_id),'haltFeedback':True})
            if name=='generate_tts' and any(v['status'] in ('uncertain','not_run','cancelled') for v in data['segments']):
                self.store.put('run',run_id,{**self.store.get('run',run_id),'haltFeedback':True})
            return self.operations.finish(operation,result,changes)
        except BaseException as exc:
            if context and before:self.context.record(context,before,error=exc)
            self.operations.fail(operation,exc)
            raise
        finally:
            if token is not None:active_operation.reset(token)

    async def execute(self, sid, run, request, name, args, on_progress=None):
        c, p = self.courses, self.providers
        if name == 'ask_user':
            return c.ask(sid, args)
        if name == 'read_skill':
            identifier=args.skillId or args.skill
            skill=c.read_skill(identifier,args.path,run)
            segment = page_text(skill.pop('text'),args.offset,args.limit,**skill)
            segment['coverage'] = {'start': segment['offset'],
                                   'end': segment['offset'] + len(segment['text']),
                                   'total': segment['total'], 'completeBody': segment['offset'] == 0 and not segment['hasMore']}
            return segment
        if name == 'web_search':
            results=await p.search(args.query,args.limit)
            if self.store.get('session',sid)['state']!='running':fail('RUN_STOPPED','运行已停止')
            return c.sources_batch(sid,results,args.stageId)
        if name == 'fetch_url':
            if args.url:
                raw=await p.fetch(args.url)
                if self.store.get('session',sid)['state']!='running':fail('RUN_STOPPED','运行已停止')
                saved=c.sources_batch(sid,[raw],args.stageId);source=saved['sources'][0]
            else:
                session=self.store.get('session',sid)
                available=c.stage(args.stageId).sources if args.stageId else session['sources']
                sources=[v.model_dump() if hasattr(v,'model_dump') else v for v in available]
                source=next((v for v in sources if v['id']==args.sourceId),None)
                if not source:fail('SOURCE_MISSING','来源不属于当前会话')
                if source.get('sourceVersion','')!=args.sourceVersion:fail('STALE_CURSOR','来源版本已经变化')
                saved={'revision':c.stage(args.stageId).revision if args.stageId else None}
            if args.stageId:self.store.put('source_access',sid+':'+args.stageId+':'+source['id'],{'sourceVersion':source['sourceVersion']})
            record=self.store.find('source',source['id']+':'+source.get('sourceVersion',''))
            text=record['text'] if record else source.get('excerpt','')
            return page_text(text,args.offset,args.limit,sourceId=source['id'],sourceVersion=source.get('sourceVersion',''),title=source['title'],url=source['url'],completeness=record['completeness'] if record else 'excerpt_only',revision=saved['revision'],stageId=args.stageId)
        if name == 'create_stage':
            data=c.create(sid,args.theme,args.approvalId)
            return {**stage_summary(data),'reused':data['reused'],'approvalId':data['approvalId']}
        if name == 'list_stages':
            session=self.store.require_session(sid)
            query=args.query.strip().casefold()
            stages=[{'id':s['id'],'title':s['title'],'revision':s['revision'],'updatedAt':s['updatedAt'],
                'savedPageCount':len(s['scenes']),'plannedPageCount':len(s['approvedPlan']['pages']),
                'status':c.view(s['id'])['status'],'linked':s['id'] in session.get('linkedStageIds',[]),
                'courseStatus':c.summary(c.stage(s['id']))['courseStatus'],
                'unfinishedTasks':pending_page(session,s['id'],args.taskOffset)} for s in self.store.list('stage') if self.store.owned('stage',s['id']) and query in s['title'].casefold()]
            identity=digest({'query':query,'taskOffset':args.taskOffset,'stages':stages});start=cursor_index(args.cursor,identity);end=min(start+args.limit,len(stages))
            return {'stages':stages[start:end],'query':args.query,'total':len(stages),'currentStageId':session.get('activeStageId'),'activeStageId':session.get('activeStageId'),'hasMore':end<len(stages),'nextCursor':cursor(identity,end) if end<len(stages) else None,'access':'仅当前用户课程；发现或关联不代表新任务授权'}
        if name == 'list_voices':
            return p.voices()
        stage = c.scope(sid, args.stageId)
        if name == 'read_stage': return {**read(Stage.model_validate(c.view(stage.id)),args), 'courseStatus':c.summary(stage)['courseStatus']}
        if name == 'grep_stage': return grep(stage,args)
        if name == 'list_scenes':
            summary=c.summary(stage)
            return {'stageId':stage.id,'revision':stage.revision,'ready':summary['ready'],'pages':[
                {'slotId':page.id,'pageId':page.id,'title':page.title,'type':page.type,
                 'sceneId':next((s.id for s in stage.scenes if s.planPageId==page.id),None),
                 'status':'needs_attention' if any(i['slotId']==page.id for i in summary['issues']) else 'ready'} for page in stage.approvedPlan.pages],
                'issues':summary['issues'],'outstanding':summary['outstanding'],'courseStatus':summary['courseStatus'],'hasMore':False}
        if name == 'patch_stage':
            return c.patch(sid,args,repair_run=run)
        if name == 'rename_stage':
            return c.rename(sid,args)
        if name == 'edit_deck':
            return c.edit(sid,args)
        if name == 'set_teacher_voice':
            teacher=args.teacher or Teacher(model=settings.bailian_tts_model,voice=args.voiceId,
                speed=args.speed if args.speed is not None else stage.teacher.speed if stage.teacher else 1,
                language=stage.teacher.language if stage.teacher else 'Chinese')
            validate_teacher(teacher)
            if teacher.model!=settings.bailian_tts_model:fail('VOICE_INCOMPATIBLE','只允许当前配置模型的兼容预设音色')
            saved=c.mutate(sid,stage.id,args.expectedRevision,lambda d:d.update(teacher=teacher.model_dump()))
            return {'stageId':stage.id,'revision':saved['revision'],'teacher':saved['teacher'],'changes':c.changes(stage,c.stage(stage.id)),'readback':{'tool':'list_scenes','stageId':stage.id}}
        if name == 'generate_image':
            c.scope(sid,stage.id,True)
            return await p.image(stage.id,args.prompt,getattr(args,'size',None),run+':'+request)
        if name == 'generate_scene':
            c.scope(sid,stage.id,True)
            page = next((v for v in stage.approvedPlan.pages if v.id==args.pageId),None)
            if not page:
                fail('PAGE_NOT_FOUND','方案中无此页面')
            old = next((s for s in stage.scenes if s.planPageId==page.id),None)
            if old:
                c.repair(run,stage.id,page.id)
            scene_id = old.id if old else uid('scene')
            available={s['id']:s for s in self.store.require_session(sid)['sources']}
            for source in stage.sources:
                pool=available.get(source.id)
                if source.id in args.sourceIds and pool and pool['sourceVersion']!=source.sourceVersion:
                    access=self.store.find('source_access',sid+':'+stage.id+':'+source.id) or {}
                    if access.get('sourceVersion')!=source.sourceVersion:fail('SOURCE_VERSION_CONFLICT','课程与会话来源版本不一致，请 fetch_url 显式续读目标课来源版本后重试')
                available[source.id]=source.model_dump()
            sources=[available[i] for i in dict.fromkeys(args.sourceIds) if i in available]
            if len(sources)!=len(set(args.sourceIds)):
                fail('SOURCE_MISSING','来源标识未实际读取')
            media = [self.store.get('media',i) for i in args.mediaIds]
            if any(m['stageId']!=stage.id or not m['mime'].startswith('image/') for m in media):
                fail('MEDIA_SCOPE','配图不属于本课')
            if stage.revision != args.expectedRevision:
                fail('REVISION_CONFLICT','生成前请读取课程最新版本')
            c.generation_attempt(run,stage.id,page.id,'scene')
            result = await p.generate({'slide':'slides','interactive':'simulation','quiz':'quiz'}[page.type], {'stageId':stage.id,'sceneId':scene_id,'page':page.model_dump(),'brief':args.brief,'plan':stage.approvedPlan.model_dump(),'theme':stage.theme.model_dump(),'sources':sources,'media':media}, Scene.model_json_schema())
            result.update(id=scene_id,planPageId=page.id,type=page.type,actions=[],sourceIds=args.sourceIds)
            scene = Scene.model_validate(result)
            def save(doc):
                existing={v['id']:v for v in doc['sources']}
                for source in sources:
                    if source['id'] in existing and existing[source['id']]['sourceVersion']!=source['sourceVersion']:fail('SOURCE_VERSION_CONFLICT','来源已变化，未保存页面')
                    existing[source['id']]=source
                doc['sources']=list(existing.values())
                doc['scenes'] = [s for s in doc['scenes'] if s['planPageId']!=page.id]+[scene.model_dump()]
                order=[v['id'] for v in doc['approvedPlan']['pages']]
                doc['scenes'].sort(key=lambda s:order.index(s['planPageId']))
            saved = c.mutate(sid,stage.id,args.expectedRevision,save,repair_run=run)
            return {'stageId':stage.id,'sceneId':scene.id,'slotId':page.id,'revision':saved['revision'],'scene':scene.model_dump(),'displacedActionIds':[a.id for a in old.actions] if old else [],'displacedAudioIds':[a.audioId for a in old.actions if a.audioId] if old else [],'issues':[i for i in c.summary(c.stage(stage.id))['issues'] if i['sceneId']==scene.id]}
        scene = next((s for s in stage.scenes if s.id==args.sceneId),None)
        if not scene:
            fail('SCENE_NOT_FOUND','页面不存在')
        if name == 'generate_actions':
            if scene.actions:
                c.repair(run,stage.id,scene.planPageId)
            c.scope(sid,stage.id,True)
            if stage.revision != args.expectedRevision:
                fail('REVISION_CONFLICT','生成前请读取课程最新版本')
            c.generation_attempt(run,stage.id,scene.planPageId,'actions')
            discussions = [{'sceneId':s.id, 'topic':a.topic, 'initiatorId':a.initiatorId}
                           for s in stage.scenes for a in s.actions if a.type=='discussion' and s.id!=scene.id]
            output = ActionOutput.model_validate(await p.generate('narration', {'stageId':stage.id,'page':{'id':scene.planPageId},'scene':scene.model_dump(),'plan':stage.approvedPlan.model_dump(),'existingDiscussions':discussions,'guidance':args.guidance}, ActionOutput.model_json_schema()))
            def save(doc):
                next(s for s in doc['scenes'] if s['id']==scene.id)['actions']=[a.model_dump() for a in output.actions]
            saved=c.mutate(sid,stage.id,args.expectedRevision,save,repair_run=run if scene.actions else None)
            return {'stageId':stage.id,'sceneId':scene.id,'slotId':scene.planPageId,'revision':saved['revision'],'actions':next(s for s in saved['scenes'] if s['id']==scene.id)['actions'],'displacedAudioIds':[a.audioId for a in scene.actions if a.audioId],'issues':[i for i in c.summary(c.stage(stage.id))['issues'] if i['sceneId']==scene.id],'readback':{'tool':'read_stage','stageId':stage.id,'sceneId':scene.id,'path':'/actions','detail':'source'}}
        if name == 'generate_tts':
            return await self.narration.agent(sid,stage,scene,args.force,args.actionIds,on_progress)
        if name == 'render_scene_preview':
            return await self.inspection.preview(stage,scene,args.width,args.height,args.state)
        if name == 'check_scene':
            return await self.inspection.check(stage,scene,args)
        fail('UNKNOWN_TOOL','工具未实现')
