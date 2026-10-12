"""Shared speech synthesis and durable user jobs; independent of Agent execution."""
import asyncio
from pydantic import Field
from .models import Model, Teacher, uid, digest, audio_signature
from .config import settings
from .courses import fail
from .providers import validate_teacher
from .store import now


class SpeechEdit(Model):
    sessionId: str
    expectedRevision: int = Field(ge=1)
    requestId: str = Field(min_length=1,max_length=200)
    text: str = Field(min_length=1,max_length=600)


class NarrationRequest(Model):
    sessionId: str
    expectedRevision: int = Field(ge=1)
    requestId: str = Field(min_length=1,max_length=200)
    actionIds: list[str] | None = None
    force: bool = False


class TeacherVoiceEdit(Model):
    sessionId: str
    expectedRevision: int = Field(ge=1)
    requestId: str = Field(min_length=1, max_length=200)
    voice: str


class Narration:
    def __init__(self,courses,providers):
        self.courses,self.providers,self.store=courses,providers,courses.store
        self.tasks={}
        for job in self.store.list('narration_job'):
            if job['status']=='running':
                job.update(status='interrupted',updatedAt=now())
                for segment in job['segments']:
                    if segment['status'] in ('pending','requesting','downloading'):
                        segment.update(status='interrupted',error={'code':'INTERRUPTED','message':'服务重启；可重新提交以复用音频或续下载，未知付费结果不会自动重放'})
                with self.store.transaction():
                    self.store.put('narration_job',job['id'],job)
                    self.courses.release_operation(job['sessionId'],job['id'])
                    self.publish(job)

    def publish(self,job):
        self.store.event(job['sessionId'],'user_operation',{'operationId':job['id'],'operation':'narration',
            'label':'重新配音','status':job['status'],'stageId':job['stageId'],'sceneId':job['sceneId'],
            'segments':job['segments'],'target':job.get('target'),'updatedAt':job['updatedAt']})

    def set_voice(self, stage_id, args):
        sid = args.sessionId
        self.courses.scope(sid,stage_id)
        key = sid + ':' + args.requestId
        request_hash = digest({'stageId':stage_id, **args.model_dump()})
        with self.courses.lock(stage_id), self.store.transaction():
            prior = self.store.find('voice_request', key)
            if prior:
                if prior['requestHash'] != request_hash:
                    fail('REQUEST_CONFLICT', '同一请求标识不能用于不同老师音色')
                return prior['result']
            stage = self.courses.scope(sid, stage_id)
            teacher = Teacher(model=settings.bailian_tts_model, voice=args.voice,
                              speed=stage.teacher.speed if stage.teacher else 1.0,
                              language=stage.teacher.language if stage.teacher else 'Chinese')
            validate_teacher(teacher)
            self.courses.acquire_operation(sid, stage_id, args.requestId, 'teacher_voice')
            result = self.courses.mutate(sid, stage_id, args.expectedRevision,
                lambda doc:doc.update(teacher=teacher.model_dump()), actor='user', operation_id=args.requestId)
            self.store.put('voice_request', key, {'requestHash':request_hash, 'result':result})
            self.store.event(sid, 'user_operation', {'operationId':args.requestId, 'operation':'teacher_voice',
                'label':'设置老师声音', 'status':'completed', 'stageId':stage_id, 'revision':result['revision']})
            self.courses.release_operation(sid, args.requestId)
            return result

    async def segment(self,sid,stage_id,scene_id,action_id,signature,*,actor='agent',operation_id=None,force=False,on_state=None):
        c=self.courses
        stage=c.scope(sid,stage_id,actor=='agent')
        if actor=='user': c.user_authorize(sid,stage_id,operation_id)
        action=next((a for s in stage.scenes if s.id==scene_id for a in s.actions if a.id==action_id and a.type=='speech'),None)
        if not action or audio_signature(action,stage.teacher)!=signature:
            fail('AUDIO_STALE','讲稿或音色已经变化，旧结果不能绑定')
        media=next((m for m in self.store.list('media') if m.get('stageId')==stage_id and m.get('signature')==signature and (settings.data_dir/'media'/m['file']).is_file()),None)
        reused=bool(media) and not force
        if force or not media:
            media=await self.providers.tts(stage_id,action.text,stage.teacher,signature,force=force,on_state=on_state)
        with c.lock(stage_id):
            current=c.scope(sid,stage_id,actor=='agent')
            target=next((a for s in current.scenes if s.id==scene_id for a in s.actions if a.id==action_id),None)
            if not target or audio_signature(target,current.teacher)!=signature:
                fail('AUDIO_STALE','合成期间讲稿或音色已变化，旧音频已保存但未绑定')
            if not (target.audioStatus=='ready' and target.audioId==media['id'] and target.audioSignature==signature):
                def change(doc):
                    a=next(a for s in doc['scenes'] if s['id']==scene_id for a in s['actions'] if a['id']==action_id)
                    a.update(audioId=media['id'],audioSignature=signature,audioStatus='ready',duration=media['duration'])
                c.mutate(sid,stage_id,current.revision,change,bind_audio=True,actor=actor,operation_id=operation_id)
        return {'actionId':action_id,'mediaId':media['id'],'duration':media['duration'],'status':'ready','reused':reused}

    async def segments(self,sid,stage_id,scene_id,segments,*,actor='agent',operation_id=None,force=False,on_change=None):
        fatal=False
        for segment in segments:
            if fatal:
                segment['status']='not_run'
                if on_change:await on_change(segment)
                continue
            def state_update(state):
                segment['status']=state
            try:
                stage=self.courses.stage(stage_id)
                action=next(a for s in stage.scenes if s.id==scene_id for a in s.actions if a.id==segment['actionId'])
                reused=not force and action.audioStatus=='ready' and action.audioSignature==segment['signature'] and action.audioId
                async with asyncio.timeout(settings.provider_timeout_seconds+90):
                    result=await self.segment(sid,stage_id,scene_id,segment['actionId'],segment['signature'],actor=actor,operation_id=operation_id,force=force,on_state=state_update)
                segment.update(result,status='ready',reused=result.get('reused',bool(reused)))
            except asyncio.CancelledError:
                segment['status']='cancelled'
                for remaining in segments[segments.index(segment)+1:]:remaining['status']='not_run'
                if on_change:await on_change(segment)
                raise
            except Exception as exc:
                code=getattr(exc,'code','NARRATION_FAILED')
                task=self.store.find('media_task','tts_'+stage_id+'_'+segment['signature'])
                status='stale' if code=='AUDIO_STALE' else 'uncertain' if code=='MEDIA_UNCERTAIN' or task and task.get('status')=='requesting' else 'failed'
                segment.update(status=status,error={'code':code,'message':settings.redact(str(exc))[:1000] or type(exc).__name__})
                fatal=status=='uncertain' or code in ('MISSING_CONFIG','VOICE_INCOMPATIBLE','TTS_MODEL','RUN_STOPPED','WAITING_FOR_USER','CANCELLED') or any(v in str(exc) for v in ('HTTP 401','HTTP 403','InvalidApiKey','Unauthorized','AccessDenied'))
            if on_change:await on_change(segment)
        ready=sum(v['status']=='ready' for v in segments)
        return 'completed' if ready==len(segments) else 'partial' if ready else 'failed'

    async def agent(self,sid,stage,scene,force=False,action_ids=None,on_progress=None):
        actions=[a for a in scene.actions if a.type=='speech']
        if action_ids is not None:
            if not action_ids or len(action_ids)!=len(set(action_ids)) or not set(action_ids)<={a.id for a in actions}:fail('SPEECH_NOT_FOUND','actionIds 必须是本页唯一的 speech ID')
            actions=[a for a in actions if a.id in action_ids]
        if not actions:fail('SPEECH_NOT_FOUND','本页无 speech，请先生成讲稿')
        segments=[{'actionId':a.id,'signature':audio_signature(a,stage.teacher),'status':'pending'} for a in actions]
        async def update(segment):
            if on_progress:
                public=[{k:v for k,v in s.items() if k!='signature'} for s in segments]
                await on_progress({'content':[{'type':'text','text':f"已处理 {sum(s['status'] not in ('pending','requesting','downloading') for s in segments)}/{len(segments)} 段"}], 'details':{'target':{'stageId':stage.id,'sceneId':scene.id},'segments':public}})
        status=await self.segments(sid,stage.id,scene.id,segments,force=force,on_change=update)
        return {'stageId':stage.id,'sceneId':scene.id,'revision':self.courses.stage(stage.id).revision,'status':status,
                'segments':[{k:v for k,v in s.items() if k!='signature'} for s in segments],
                'counts':{v:sum(s['status']==v for s in segments) for v in {s['status'] for s in segments}}}

    def start(self,stage_id,scene_id,args):
        sid=args.sessionId; self.courses.scope(sid,stage_id); key=sid+':'+args.requestId
        request_hash=digest({'stageId':stage_id,'sceneId':scene_id,**args.model_dump()})
        with self.courses.lock(stage_id), self.store.transaction():
            prior=self.store.find('narration_request',key)
            if prior:
                if prior['requestHash']!=request_hash: fail('REQUEST_CONFLICT','同一请求 ID 对应不同配音内容')
                return self.store.get('narration_job',prior['jobId'])
            stage=self.courses.scope(sid,stage_id)
            if stage.revision!=args.expectedRevision: fail('REVISION_CONFLICT','课程版本已更新，请刷新后配音')
            scene=next((s for s in stage.scenes if s.id==scene_id),None)
            if not scene: fail('SCENE_NOT_FOUND','页面不存在')
            actions=[a for a in scene.actions if a.type=='speech']
            if args.actionIds is not None:
                if not args.actionIds or len(args.actionIds)!=len(set(args.actionIds)) or not set(args.actionIds)<={a.id for a in actions}:
                    fail('SPEECH_NOT_FOUND','配音范围必须是本页已有 speech 动作')
                actions=[a for a in actions if a.id in args.actionIds]
            if not actions: fail('SPEECH_NOT_FOUND','本页没有讲稿，请先制作讲稿')
            job_id=uid('narration')
            self.courses.acquire_operation(sid,stage_id,job_id,'narration')
            job={'id':job_id,'sessionId':sid,'stageId':stage_id,'sceneId':scene_id,'requestId':args.requestId,
                 'force':args.force,
                 'target':stage.title+' · '+scene.title,'status':'running','createdAt':now(),'updatedAt':now(),
                 'segments':[{'actionId':a.id,'signature':audio_signature(a,stage.teacher),'status':'pending'} for a in actions]}
            self.store.put('narration_request',key,{'requestHash':request_hash,'jobId':job_id})
            self.store.put('narration_job',job_id,job); self.publish(job)
        task=asyncio.create_task(self.run(job)); self.tasks[job_id]=task
        task.add_done_callback(lambda _:self.tasks.pop(job_id,None))
        return job

    async def run(self,job):
        async def update(segment):
            job['updatedAt']=now()
            with self.store.transaction():self.store.put('narration_job',job['id'],job);self.publish(job)
        try:
            job['status']=await self.segments(job['sessionId'],job['stageId'],job['sceneId'],job['segments'],actor='user',operation_id=job['id'],force=job.get('force',False),on_change=update)
        except asyncio.CancelledError:
            job['status']='interrupted'
            for segment in job['segments']:
                if segment['status'] in ('pending','requesting','downloading'):segment['status']='not_run'
        finally:
            job['updatedAt']=now()
            with self.store.transaction():
                self.store.put('narration_job',job['id'],job)
                self.courses.release_operation(job['sessionId'],job['id']);self.publish(job)

    async def close(self):
        tasks=list(self.tasks.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
