import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from .config import ROOT, settings
from .courses import Courses, DomainError, fail
from .inspection import Inspection
from .models import Model, digest, uid
from .providers import Providers
from .runtime import Runtime, Message
from .store import Store, now
from .tools import Tools
from .tool_summary import safe, parameter_details
from .narration import Narration, SpeechEdit, NarrationRequest, TeacherVoiceEdit
from .classrooms import Classrooms
from .classroom_runtime import ClassroomRuntime
from .classroom_models import NewClassroom, ClassroomCommand, ClassroomProgress, ClassroomAck

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(settings.data_dir/'browsers')
store=Store(settings.data_dir/'classroom.sqlite3')
courses=Courses(store)
providers=Providers(store)
inspection=Inspection(courses,providers)
narration=Narration(courses,providers)
runtime=Runtime(store,courses,Tools(courses,providers,inspection,narration))
classrooms=Classrooms(store,courses,providers)
classroom_runtime=ClassroomRuntime(classrooms)

@asynccontextmanager
async def lifespan(app):
    await classroom_runtime.initialize()
    try:
        yield
    finally:
        await runtime.close()
        await classrooms.close()
        await narration.close()
        await providers.close()
        store.close()

app=FastAPI(title='OpenMAIC Python Classroom',lifespan=lifespan,docs_url=None,redoc_url=None)

@app.middleware('http')
async def request_scope(request:Request,call_next):
    # Sandboxed experiments are opaque cross-site contexts. Reads still enforce media ownership.
    if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/media/'):
        origin=request.headers.get('origin')
        allowed={settings.openmaic_origin,'http://127.0.0.1:5173','http://localhost:5173'}
        if origin=='null' or (origin and origin not in allowed) or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'error':{'code':'REQUEST_ORIGIN','message':'实验或外部网站不能访问课程业务接口'}},status_code=403)
    try:
        parts=request.url.path.strip('/').split('/')
        if len(parts)>=3 and parts[0]=='api':
            if parts[1]=='courses':courses.stage(parts[2])
            elif parts[1]=='classroom-dialogues':classrooms.dialogue(parts[2])
            elif parts[1]=='classrooms':classrooms.get(parts[2])
            elif parts[1]=='sessions':store.require_session(parts[2])
            elif parts[1]=='runs':store.require_session(store.get('run',parts[2])['sessionId'])
            elif parts[1]=='narration-jobs':
                job=store.get('narration_job',parts[2]);store.require_session(job['sessionId']);courses.stage(job['stageId'])
        return await call_next(request)
    except DomainError as exc:
        return await domain_error(request,exc)
    except KeyError as exc:
        return JSONResponse({'error':{'code':'NOT_FOUND','message':str(exc)}},status_code=404)

@app.exception_handler(DomainError)
async def domain_error(request,exc):
    code=409 if exc.code in ('REVISION_CONFLICT','RUN_ACTIVE','OPERATION_ACTIVE','WAITING_FOR_USER','REQUEST_CONFLICT','PLAN_VERSION','QUESTION_MISMATCH','COURSE_BUSY','CLASSROOM_CONTROL','CLASSROOM_STALE','CLASSROOM_WAITING') else 403 if exc.code=='ACCESS_OWNER' else 400
    return JSONResponse({'error':{'code':exc.code,'message':exc.message}},status_code=code)

@app.exception_handler(ValidationError)
async def validation_error(request,exc):
    return JSONResponse({'error':{'code':'INVALID_DOCUMENT','message':str(exc)}},status_code=422)

class NewSession(Model):
    stageId:str|None=None

class Attempt(Model):
    attemptId:str=Field(min_length=1,max_length=200)
    sceneId:str
    revision:int=Field(ge=1)
    answers:dict[str,str]=Field(default_factory=dict)
    skip:bool=False
    classroomId:str|None=None

@app.post('/api/classrooms')
async def new_classroom(args:NewClassroom):
    return classrooms.create(args)

@app.get('/api/classrooms/{cid}')
async def classroom_snapshot(cid:str):
    try:
        return classrooms.get(cid,live=True)
    except DomainError as exc:
        if exc.code=='REVISION_CONFLICT':
            return classrooms.get(cid)
        raise

@app.post('/api/classrooms/{cid}/commands')
async def classroom_command(cid:str,args:ClassroomCommand):
    return await classrooms.command(cid,args)

@app.post('/api/classrooms/{cid}/progress')
async def classroom_progress(cid:str,args:ClassroomProgress):
    return classrooms.progress(cid,args)

@app.post('/api/classrooms/{cid}/ack')
async def classroom_ack(cid:str,args:ClassroomAck):
    return await classrooms.ack(cid,args)

@app.get('/api/classrooms/{cid}/history')
async def classroom_history(cid:str,after:int=0,limit:int=200):
    return classrooms.events(cid,after,limit)

@app.get('/api/classrooms/{cid}/tool-details')
async def classroom_tool_details(cid:str,callId:str,roundId:str):
    classrooms.get(cid)
    result={}
    for row in store.db.execute('SELECT body FROM learning_events WHERE classroom=? ORDER BY seq',(cid,)):
        event=json.loads(row['body'])
        if event.get('toolCallId')==callId and event.get('roundId')==roundId:
            if event['kind']=='tool_start':result['parameters']=event['data']['parameters']
            if event['kind']=='tool_end':result['result']=event['data']['result']
    return result

@app.get('/api/courses/{stageId}/classroom-dialogues')
async def course_dialogues(stageId:str,cursor:str|None=None,limit:int=50):
    return classrooms.list_dialogues(stageId,cursor,limit)

@app.get('/api/classroom-dialogues/{did}/history')
async def dialogue_history(did:str,after:int=0,limit:int=200):
    return classrooms.dialogue_events(did,after,limit)

@app.get('/api/classroom-dialogues/{did}/tool-details')
async def dialogue_tool_details(did:str,callId:str,roundId:str):
    return classrooms.dialogue_tool_details(did,roundId,callId)

@app.get('/api/classrooms/{cid}/events')
async def classroom_events(cid:str,request:Request,afterSeq:int=0):
    classrooms.get(cid)
    try:cursor=max(afterSeq,int(request.headers.get('last-event-id','0')))
    except ValueError:fail('EVENT_CURSOR','课堂事件游标无效')
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            entries=classrooms.events(cid,cursor)
            for event in entries:
                cursor=event['seq']
                yield f'id: {cursor}\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n'
            if not entries:
                yield ': heartbeat\n\n'
                await asyncio.sleep(.2)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.get('/api/capabilities')
async def capabilities():
    return settings.capabilities()

@app.get('/api/voices')
async def list_voices():
    return providers.voices()

@app.get('/api/skills')
async def skill_resources():
    return courses.skills.snapshot().public()

@app.post('/api/skills/reload')
async def reload_skill_resources():
    return await asyncio.to_thread(courses.reload_skills)

@app.patch('/api/courses/{stage_id}/teacher-voice')
async def set_teacher_voice(stage_id:str,args:TeacherVoiceEdit):
    return narration.set_voice(stage_id,args)

@app.post('/api/sessions')
async def new_session(args:NewSession):
    if args.stageId:
        stage=courses.stage(args.stageId)
        # Restore the most recently associated conversation; do not copy SDK history.
        links=sorted([r for r in store.list('course_link') if r['stageId']==args.stageId and store.owned('session',r['sessionId'])],key=lambda r:r['updatedAt'],reverse=True)
        existing=store.require_session(links[0]['sessionId']) if links else next((v for v in store.list('session') if store.owned('session',v['id']) and args.stageId in v.get('linkedStageIds',[v.get('stageId')])),None)
        if existing:return store.link_course(existing['id'],args.stageId,active=True)
        return store.session(stage.id)
    return store.session()

class ActiveCourse(Model):
    stageId: str

@app.patch('/api/sessions/{sid}/active-course')
async def active_course(sid:str,args:ActiveCourse):
    store.require_session(sid);courses.stage(args.stageId)
    return store.link_course(sid,args.stageId,active=True)

@app.get('/api/sessions')
async def list_sessions(q:str=''):
    summaries=[]
    for session in store.list('session'):
        if not store.owned('session',session['id']):continue
        first=next((m for m in reversed(store.list('chat')) if m['sessionId']==session['id'] and m['role']=='user'),None)
        title=session.get('title') or (first['text'][:50] if first else '新对话')
        if q.casefold() in title.casefold():
            row=store.db.execute('SELECT COALESCE(MAX(created),?) FROM events WHERE session=?',(session['createdAt'],session['id'])).fetchone()
            summaries.append({'id':session['id'],'stageId':session['stageId'],'activeStageId':session.get('activeStageId'),'linkedStageIds':session.get('linkedStageIds',[]),'title':title,'state':session['state'],'updatedAt':row[0]})
    return sorted(summaries,key=lambda s:s['updatedAt'],reverse=True)

@app.get('/api/sessions/{sid}/timeline')
async def timeline(sid:str,before:int|None=None,limit:int=50):
    store.get('session',sid)
    return store.timeline(sid,before,max(1,min(limit,100)))

@app.get('/api/sessions/{sid}/tool-details')
async def tool_details(sid:str,nodeId:str):
    store.get('session',sid)
    row=store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,nodeId)).fetchone()
    if not row:
        raise KeyError('工具调用不存在')
    node=json.loads(row[0])
    if node['kind']!='tool' or not node.get('runId') or not node.get('toolCallId'):
        fail('TOOL_DETAILS_UNAVAILABLE','此记录没有工具调用详情')
    if node.get('source')=='pi':
        entry=store.find('pi_tool_detail',sid+':'+node['runId']+':'+node['toolCallId'])
        return {'source':'pi','parametersAvailable':bool(entry and entry['parametersComplete']),
                'parametersComplete':bool(entry and entry['parametersComplete']),
                'parameters':entry['parameters'] if entry else None,
                'available':bool(entry and entry['result'] is not None),'result':entry['result'] if entry else None}
    result=store.cached_call(node['runId'],node['toolCallId'])
    return {**parameter_details(store,node),'source':'legacy','available':result is not None,'result':safe(result) if result is not None else None}

@app.patch('/api/courses/{stage_id}/scenes/{scene_id}/speech/{action_id}')
async def edit_speech(stage_id:str,scene_id:str,action_id:str,args:SpeechEdit):
    if not args.text.strip(): fail('EMPTY_SPEECH','讲稿不能为空')
    return courses.edit_speech(args.sessionId,stage_id,scene_id,action_id,args)

@app.post('/api/courses/{stage_id}/scenes/{scene_id}/tts')
async def regenerate_tts(stage_id:str,scene_id:str,args:NarrationRequest):
    return narration.start(stage_id,scene_id,args)

@app.get('/api/narration-jobs/{job_id}')
async def narration_job(job_id:str):
    return store.get('narration_job',job_id)

@app.get('/api/sessions/{sid}')
async def get_session(sid:str):
    session=store.get('session',sid)
    events=[{'seq':r[0],'kind':r[1],'data':json.loads(r[2]),'createdAt':r[3]} for r in store.db.execute('SELECT seq,kind,body,created FROM (SELECT * FROM events WHERE session=? ORDER BY seq DESC LIMIT 100) ORDER BY seq',(sid,))]
    chat=sorted([m for m in store.list('chat') if m['sessionId']==sid],key=lambda m:m['createdAt'])
    snapshot=store.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE session=?',(sid,)).fetchone()[0]
    return {**session,'events':events,'chat':chat,'snapshotSeq':snapshot}

@app.post('/api/sessions/{sid}/messages')
async def message(sid:str,args:Message):
    return await runtime.submit(sid,args)

@app.get('/api/sessions/{sid}/events')
async def events(sid:str,request:Request,after:int=0):
    store.get('session',sid)
    try:
        cursor=max(after,int(request.headers.get('last-event-id','0')))
    except ValueError:
        fail('EVENT_CURSOR','事件序号无效')
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            entries=store.events(sid,cursor)
            for event in entries:
                cursor=event['seq']
                yield f'id: {cursor}\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n'
            if not entries:
                yield ': heartbeat\n\n'
                await asyncio.sleep(.15)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.post('/api/runs/{run}/cancel')
async def cancel(run:str):
    return await runtime.cancel(run)

@app.get('/api/courses')
async def list_courses():
    summaries=[]
    for stage in store.list('stage'):
        if not store.owned('stage',stage['id']):continue
        view=courses.view(stage['id'])
        summaries.append({key:view[key] for key in ('id','title','revision','status','outstanding','updatedAt')})
    return summaries

@app.get('/api/courses/{id}')
async def get_course(id:str):
    return courses.view(id)

@app.get('/api/courses/{id}/inspections')
async def get_inspections(id:str):
    return courses.summary(courses.stage(id))

@app.get('/api/courses/{id}/quiz-attempts')
async def get_attempts(id:str):
    courses.stage(id)
    return [r for r in store.list('attempt') if r['stageId']==id]

@app.post('/api/courses/{id}/quiz-attempts')
async def grade(id:str,args:Attempt):
    key=id+':'+args.attemptId
    courses.stage(id)
    if prior:=store.find('attempt',key):
        if prior['requestHash']!=digest(args.model_dump(exclude_none=True)):
            fail('ATTEMPT_CONFLICT','相同提交标识不能对应不同答案')
        return prior
    stage=courses.stage(id)
    if args.revision!=stage.revision:
        fail('REVISION_CONFLICT','课程版本已更新，请重新打开课堂后作答')
    scene=next((s for s in stage.scenes if s.id==args.sceneId),None)
    if not scene or scene.type!='quiz':
        fail('QUIZ_SCENE','测验页不存在')
    questions={q.id:q for q in scene.content.questions}
    if not set(args.answers)<=set(questions):
        fail('QUIZ_QUESTION','答案包含未知题目')
    if not args.skip and set(args.answers)!=set(questions):
        fail('QUIZ_INCOMPLETE','请先回答全部问题，或选择跳过')
    results=[]
    for question in questions.values():
        selected=args.answers.get(question.id)
        if selected is not None and selected not in {o.id for o in question.options}:
            fail('QUIZ_OPTION','提交了未知选项，没有保存评分')
        result={'questionId':question.id,'selected':selected,'correct':None if args.skip else selected==question.answer}
        if not args.skip:
            result.update(answer=question.answer,explanation=question.explanation)
        results.append(result)
    record={'id':key,'stageId':id,'sceneId':scene.id,'revision':stage.revision,'status':'skipped' if args.skip else 'graded','results':results,'requestHash':digest(args.model_dump(exclude_none=True)),'createdAt':now()}
    with store.transaction():
        if args.classroomId:classrooms.associate_attempt(args.classroomId,id,scene,record)
        store.put('attempt',key,record)
    return record

@app.get('/api/media/{id}')
async def media(id:str):
    record=store.get('media',id)
    referenced=any(r['mediaId']==id and r['ownerId']==store.owner_id for r in store.list('learning_media'))
    if record.get('ownerId',store.owner_id)!=store.owner_id or not (store.owned('stage',record.get('stageId','')) or referenced):
        fail('ACCESS_OWNER','媒体不存在或不属于当前用户')
    directory=(settings.data_dir/'media').resolve()
    path=(directory/record['file']).resolve()
    if path.parent!=directory or not path.is_file():
        fail('MEDIA_PATH','媒体文件不存在或路径越界')
    return FileResponse(path,media_type=record['mime'],headers={'Cache-Control':'private, max-age=31536000, immutable'})

@app.get('/api/preview/{id}')
async def preview_data(id:str,token:str):
    return inspection.authorize(id,token).model_dump()

assets=ROOT/'frontend/dist/assets'
if assets.is_dir():
    app.mount('/assets',StaticFiles(directory=assets),name='assets')

@app.get('/')
@app.get('/preview')
async def frontend():
    file=ROOT/'frontend/dist/index.html'
    if not file.is_file():
        return JSONResponse({'error':'前端尚未构建。开发模式运行 npm run dev；正式预览先 npm run build。'},status_code=503)
    return FileResponse(file)
