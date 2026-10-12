import asyncio
import json
import os
from pathlib import Path
from pydantic import Field
from .config import ROOT, settings
from .courses import DomainError, fail
from .models import Model, Plan, uid, digest, Stage
from .store import now
from .tool_result import failure
from .run_context import RunContext
from .legacy_tasks import historical_tasks

class Message(Model):
    messageId: str = Field(min_length=1, max_length=200)
    text: str = Field(default='', max_length=30000)
    questionId: str | None = None
    planVersion: int | None = None
    approve: bool = False
    stageId: str | None = None
    targetStageIds: list[str] = Field(default_factory=list,max_length=20)


class Runtime:
    def __init__(self, store, courses, tools):
        self.store,self.courses,self.tools=store,courses,tools
        self.context=RunContext(courses)
        self.tasks={}
        self.processes={}
        self.write_locks={}
        for occupancy in store.list('course_operation'):
            courses.release_courses(occupancy['operationId'])
        for session in store.list('session'):
            if session['state']=='running' or (session.get('operation') or {}).get('kind')=='agent':
                store.patch_session(session['id'],state='waiting_for_user' if session['pendingQuestion'] else 'failed',operation=None)
                if session.get('runId') and store.find('run',session['runId']):self.preserve_goals(session['id'],session['runId'])
                store.event(session['id'],'interrupted',{'message':'服务重启导致运行中断；已保存成果保留，可发送继续请求'})

    async def submit(self, sid, message):
        self.store.require_session(sid)
        prior=self.store.find('message',sid+':'+message.messageId)
        if prior:
            request=message.model_dump()
            legacy_hash=digest({k:v for k,v in request.items() if k not in ('stageId','targetStageIds')}) if 'stageId' not in message.model_fields_set and 'targetStageIds' not in message.model_fields_set else None
            if prior.get('requestHash') not in (digest(request),legacy_hash):
                fail('MESSAGE_CONFLICT','同一消息标识不能对应不同内容')
            return prior['accepted']
        session=self.store.require_session(sid)
        if sid in self.tasks and session['pendingQuestion'] and message.questionId==session['pendingQuestion']['id']:
            try:
                await asyncio.wait_for(asyncio.shield(self.tasks[sid]),5)
            except asyncio.TimeoutError:
                fail('RUN_ACTIVE','正在结束提问，请稍后重试回答')
            session=self.store.get('session',sid)
        if session.get('operation'):
            fail('OPERATION_ACTIVE','当前会话有讲稿或配音操作，请等待完成')
        if sid in self.tasks or session['state']=='running':
            fail('RUN_ACTIVE','当前会话正在制作，请等待或停止后继续')
        if not message.text.strip() and not message.approve:
            fail('EMPTY_MESSAGE','请输入需求或回答')
        question=session['pendingQuestion']
        run_id=uid('run')
        preview=message.stageId if 'stageId' in message.model_fields_set else session.get('activeStageId')
        targets=list(dict.fromkeys(message.targetStageIds))
        for target in ([preview] if preview else [])+targets:self.courses.scope(sid,target)
        text=settings.redact(message.text or '我确认当前完整课程方案，请开始制作。')
        approval=None
        previous=self.store.find('run',question.get('runId','')) if question else None
        answer_chain=(previous or {}).get('answerChain',[])+([question['id']] if question else [])
        with self.store.transaction():
            if question:
                if message.questionId!=question['id']:fail('QUESTION_MISMATCH','回答必须关联当前待回答问题')
                if question['kind']=='plan_approval':
                    if message.planVersion!=question['planVersion']:fail('PLAN_VERSION','方案已更新，请确认当前版本')
                    if message.approve:
                        approval=self.courses.approve(sid,question,run_id)
                    else:
                        approval=self.store.get('plan_approval',question['id'])
                        self.store.put('plan_approval',question['id'],{**approval,'state':'rejected'})
                session['pendingQuestion']=None
            elif message.questionId or message.approve:fail('NO_QUESTION','当前没有可批准的问题')
            session.update(state='running',runId=run_id,operation={'kind':'agent','id':run_id})
            accepted={'sessionId':sid,'runId':run_id}
            self.store.put('session',sid,session)
            self.store.put('message',sid+':'+message.messageId,{'sessionId':sid,'messageId':message.messageId,'text':text,
                'questionId':message.questionId,'stageId':preview,'targetStageIds':targets,'accepted':accepted,'requestHash':digest(message.model_dump())})
            self.store.put('run',run_id,{'id':run_id,'sessionId':sid,'state':'running','createdAt':now(),
                'previewStageId':preview,'targetStageIds':targets,
                'sourceMessageId':message.messageId,'answerChain':answer_chain,'answeredQuestion':question,
                'previousRequest':self.store.find('message',sid+':'+(previous or {}).get('sourceMessageId','')) if question else None,
                'metadataVersion':4})
            self.context.ensure(sid,run_id)
            if message.approve and approval and approval['kind']=='update':
                self.context.approval(sid,run_id,approval['stageId'],approval['approvalId'])
            if not session.get('title'):self.store.patch_session(sid,title=text[:50])
            self.store.event(sid,'message_submitted',{'text':text,'messageId':message.messageId,'questionId':message.questionId,
                'stageId':preview,'targetStageIds':targets})
            if question:
                self.store.put('question',question['id'],{**question,'answer':text,'approved':message.approve,'answeredAt':now()})
                self.store.event(sid,'question_answered',{'questionId':question['id'],'answer':text,'approved':message.approve,'messageId':message.messageId})
            self.store.put('chat',message.messageId,{'id':message.messageId,'sessionId':sid,'role':'user','text':text,'createdAt':now()})
            self.store.event(sid,'run_started',accepted)
        task=asyncio.create_task(self.run(session,text,bool(question),message.messageId))
        self.tasks[sid]=task
        task.add_done_callback(lambda _:self.tasks.pop(sid,None))
        return accepted

    async def send(self,process,session,kind,**body):
        lock=self.write_locks.setdefault(session['runId'],asyncio.Lock())
        async with lock:
            process.stdin.write((json.dumps({'protocolVersion':2,'sessionId':session['id'],'runId':session['runId'],'type':kind,**body},ensure_ascii=False)+'\n').encode())
            await process.stdin.drain()

    def completion(self,sid,run):
        session=self.store.require_session(sid);record=self.store.get('run',run)
        allowed=session['state']=='running' and not session['pendingQuestion'] and not record.get('haltFeedback')
        feedback=self.context.feedback(sid,run)
        return {**feedback,'allowed':bool(allowed and feedback['courses'])}

    def preserve_goals(self,sid,run):
        self.context.preserve(sid,run)

    async def run(self,session,text,answer,user_message_id):
        sid,run=session['id'],session['runId'];process=None;stderr_task=None;settled=False
        workers=set();tool_lock=asyncio.Lock()
        async def stderr_reader():
            log=settings.data_dir/'logs'/f'{run}.log';log.parent.mkdir(parents=True,exist_ok=True)
            with log.open('a') as target:
                while line:=await process.stderr.readline():target.write(settings.redact(line.decode(errors='replace')))
        async def execute(message):
            async with tool_lock:
                request=message['requestId']
                async def progress(value):
                    await self.send(process,session,'tool_progress',requestId=request,result=value)
                try:
                    async with asyncio.timeout(settings.provider_timeout_seconds+150):
                        result=await self.tools.call(sid,run,request,message['name'],message['args'],on_progress=progress)
                except Exception as exc:
                    result=self.store.cached_call(run,request) if getattr(exc,'code','') not in ('REQUEST_CONFLICT','ACCESS_OWNER','LEGACY_RECEIPT_UNVERIFIED','OPERATION_UNCERTAIN') else None
                    result=result or failure(getattr(exc,'code','TOOL_ERROR'),str(exc),(message.get('args') or {}).get('stageId'))
                    if getattr(exc,'code','') in ('MEDIA_UNCERTAIN','MISSING_CONFIG','REPAIR_BUDGET','GENERATION_BUDGET','BROWSER_MISSING','FRONTEND_MISSING','VOICE_INCOMPATIBLE'):
                        self.store.put('run',run,{**self.store.get('run',run),'haltFeedback':True})
                await self.send(process,session,'tool_result',requestId=request,result=result)
        try:
            if not settings.capabilities()['creation']['available']:fail('MISSING_CONFIG','请配置完整 CREATION_* 后重新发送继续请求')
            skill_resources = await asyncio.to_thread(self.courses.begin_skill_run, run)
            env={k:v for k,v in os.environ.items() if k not in {'DEEPSEEK_API_KEY','TAVILY_API_KEY','BAILIAN_API_KEY','CREATION_API_KEY','IMAGE_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY'}}
            env['PI_CODING_AGENT_DIR']=str(settings.data_dir/'pi')
            process=await asyncio.create_subprocess_exec('node','agent-runtime/main.ts',cwd=ROOT,env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=24_000_000)
            self.processes[run]=process;stderr_task=asyncio.create_task(stderr_reader())
            record=self.store.get('run',run)
            linked=[self.courses.stage(i) for i in self.store.get('session',sid).get('linkedStageIds',[]) if self.store.owned('stage',i)]
            approvals=[{'approvalId':a['approvalId'],'kind':a['kind'],'stageId':a.get('stageId'),'title':a['plan']['title'],'createdStageId':a.get('createdStageId')}
                for a in self.store.list('plan_approval') if a['sessionId']==sid and a['state'] in ('approved','created')][:20]
            context={'stageId':record.get('previewStageId'),'previewStageId':record.get('previewStageId'),
                'legacyTargetHints':record.get('targetStageIds',[]),
                'runContext':self.context.ensure(sid,run),
                'lastRunContext':self.store.get('session',sid).get('lastRunContext'),
                'linkedCourses':{'items':[{'stageId':v.id,'title':v.title,'revision':v.revision} for v in linked[:20]],'total':len(linked),'hasMore':len(linked)>20},
                'approvals':approvals,'legacyTasks':historical_tasks(self.store.get('session',sid),record),
                'answeredQuestion':record.get('answeredQuestion'),'previousRequest':record.get('previousRequest'),
                'unresolvedTaskHint':self.store.get('session',sid).get('unresolvedTaskHint'),
                'capabilities':settings.capabilities(),
                'instruction':'依据当前用户正文和对话理解课程/页面及工作，正文优先于预览。先 list_stages 发现并 read_stage/list_scenes 核实目标与版本，再直接调用业务工具。页面操作使用稳定标识，跨课先读取对应课。只执行用户要求与本次新增失效的必要修复，不因目录可读而自动完善全课。歧义 ask_user，保存 candidates/requestText。旧任务和 lastRunContext 只供恢复参考，重新读取实际目标，不作为写入授权。普通明确修改无需例行确认，新课先完整方案批准并传 approvalId。课程就绪来自 CourseStatus，不来自自然语言宣称。'}
            await self.send(process,session,'answer_question' if answer else 'start_run',text=text,userMessageId=user_message_id,context=context,skillResources=skill_resources,sessionFile=session['piSessionFile'],config={**settings.creation,'thinkingLevel':settings.thinking_level,'contextWindow':settings.creation_context_window,'maxTokens':settings.creation_max_tokens,'compaction':settings.creation_compaction,'maxToolCalls':settings.max_tool_calls,'runTimeoutMs':settings.run_timeout_seconds*1000,'providerTimeoutMs':settings.provider_timeout_seconds*1000})
            async with asyncio.timeout(settings.run_timeout_seconds+10):
                while line:=await process.stdout.readline():
                    try:message=json.loads(line)
                    except ValueError:fail('PROTOCOL_FORMAT','Node stdout 返回了非 JSONL 消息')
                    if message.get('protocolVersion')!=2 or message.get('sessionId')!=sid or message.get('runId')!=run:fail('PROTOCOL_SCOPE','Node 消息版本或关联标识错误')
                    kind=message['type']
                    if kind in ('session_ready','session_saved'):
                        file=message.get('sessionFile')
                        if file:
                            path=Path(file).resolve()
                            if not path.is_relative_to((settings.data_dir/'pi/sessions').resolve()):fail('SESSION_PATH','SDK 会话路径越界')
                            self.store.patch_session(sid,piSessionFile=str(path))
                    elif kind=='skill_diagnostics':
                        diagnostics={k:v for k,v in message.items() if k not in ('protocolVersion','sessionId','runId','type')}
                        self.store.put('skill_diagnostics',run,diagnostics)
                    elif kind=='pi_event':
                        self.store.pi_event(sid,run,message)
                        await self.send(process,session,'event_ack',seq=message['seq'])
                    elif kind=='tool_request':
                        task=asyncio.create_task(execute(message));workers.add(task)
                    elif kind=='completion_request':
                        await self.send(process,session,'completion_result',requestId=message['requestId'],result=self.completion(sid,run))
                    elif kind=='failed':fail(message.get('errorCode','AGENT_FAILED'),settings.redact(message['error']))
                    elif kind=='settled':
                        # Node only sends this after receiving ACKs for all subscribed events.
                        await asyncio.gather(*workers)
                        settled=True;current=self.store.get('session',sid)
                        feedback=self.completion(sid,run);results=feedback.get('courses',[])
                        ready=bool(results) and all(c['ready'] for c in results)
                        state='waiting_for_user' if current['pendingQuestion'] else 'cancelled' if current['state']=='cancelled' or message.get('cancelled') else 'completed' if ready else 'idle'
                        self.store.patch_session(sid,state=state)
                        self.store.put('run',run,{**self.store.get('run',run),'state':state,'settledAt':now()})
                        compat={'stageId':results[0]['stageId'],'outstanding':results[0]['outstanding']} if len(results)==1 else {'stageId':None,'outstanding':[]}
                        self.store.event(sid,'run_settled',{'state':state,'courses':results,**compat});break
                    else:fail('PROTOCOL_TYPE','未知 Node 协议消息')
            if not settled:fail('PROCESS_EXIT',f'Agent 子进程在结算前退出，退出码 {process.returncode}')
        except asyncio.CancelledError:
            self.store.patch_session(sid,state='cancelled');record=self.store.get('run',run)
            if record['state']!='cancelled':
                self.store.put('run',run,{**record,'state':'cancelled','settledAt':now()});self.store.event(sid,'run_cancelled',{'runId':run})
        except Exception as exc:
            current=self.store.get('session',sid)
            state='waiting_for_user' if current['pendingQuestion'] else 'cancelled' if current['state']=='cancelled' else 'failed'
            self.store.patch_session(sid,state=state)
            self.store.put('run',run,{**self.store.get('run',run),'state':state,'error':settings.redact(str(exc))})
            self.store.event(sid,'run_failed',{'state':state,'error':settings.redact(str(exc))[:2000]})
        finally:
            for task in workers:
                if not task.done():task.cancel()
            await asyncio.gather(*workers,return_exceptions=True)
            try:
                self.preserve_goals(sid,run)
            finally:
                self.courses.release_courses(run,sid)
            current=self.store.get('session',sid)
            if (current.get('operation') or {}).get('id')==run:self.store.patch_session(sid,operation=None)
            if process and process.returncode is None:
                process.terminate()
                try:await asyncio.wait_for(process.wait(),3)
                except asyncio.TimeoutError:process.kill();await process.wait()
            if stderr_task:await stderr_task
            self.processes.pop(run,None);self.write_locks.pop(run,None)
            self.courses.end_skill_run(run)

    async def cancel(self,run):
        record=self.store.get('run',run)
        sid=record['sessionId']
        current=self.store.get('session',sid)
        if current['runId']!=run:
            fail('RUN_OLD','不能取消旧运行')
        if record['state']!='running':
            return {'state':record['state']}
        with self.store.transaction():
            self.store.patch_session(sid,state='cancelled')
            self.store.put('run',run,{**record,'state':'cancelled','settledAt':now()})
            self.store.event(sid,'run_cancelled',{'runId':run})
        if process:=self.processes.get(run):
            try:
                await self.send(process,current,'cancel_run')
            except (BrokenPipeError,ConnectionResetError):
                pass
        if task:=self.tasks.get(sid):
            task.cancel()
        return {'state':'cancelled'}

    async def close(self):
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
