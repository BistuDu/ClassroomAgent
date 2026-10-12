"""Durable timeline projection, v1. Raw events remain the source of truth."""
import json
from datetime import datetime
from typing import Literal, Any
from pydantic import Field
from .models import Model


class TimelineNode(Model):
    id: str
    source: Literal['pi','workbench','legacy'] = 'legacy'
    sessionId: str
    runId: str | None = None
    messageId: str | None = None
    segmentId: str | None = None
    toolCallId: str | None = None
    kind: Literal['user','assistant','reasoning','tool','question','course','operation','system']
    status: Literal['running','streaming','completed','failed','cancelled','interrupted','partial','waiting','answered'] = 'completed'
    firstSeq: int
    lastSeq: int
    createdAt: str
    updatedAt: str
    data: dict[str, Any] = Field(default_factory=dict)


class WorkbenchEvent(Model):
    version: int = 2
    source: Literal['pi','workbench','legacy'] = 'workbench'
    capturedAt: str | None = None
    eventType: str | None = None
    payload: dict[str, Any] | None = None
    sessionId: str
    runId: str | None = None
    seq: int
    kind: str
    data: dict[str, Any]
    createdAt: str
    timeline: list[TimelineNode] = Field(default_factory=list)


class BridgeEvent(Model):
    protocolVersion: int = 2
    seq: int | None = None
    capturedAt: str | None = None
    payload: dict[str, Any] | None = None
    result: Any = None
    sessionId: str
    runId: str
    type: str
    messageId: str | None = None
    segmentId: str | None = None
    requestId: str | None = None
    name: str | None = None
    text: str | None = None
    failed: bool | None = None
    stopReason: str | None = None
    sessionFile: str | None = None
    error: str | None = None
    waiting: bool | None = None
    cancelled: bool | None = None
    toolCalls: int | None = None
    tools: list[str] | None = None
    args: dict[str, Any] | None = None
    argumentChars: int | None = None
    operationId: str | None = None
    reason: str | None = None
    willRetry: bool | None = None
    tokensBefore: int | None = None
    estimatedTokensAfter: int | None = None


def project_legacy(store, event):
    sid, kind, body, seq = event['sessionId'], event['kind'], event['data'], event['seq']
    context = store.find('timeline_context',sid) or {'runId':None,'messageId':None,'segmentId':None}
    run = body.get('runId') or context['runId']
    if kind == 'run_started':
        context.update(runId=run,messageId=None,segmentId=None)
    mid = body.get('messageId') or context['messageId'] or run
    segment = body.get('segmentId') or context['segmentId']
    changed=[]

    def node(key, category, updates, status='completed', append=False):
        prior = store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone()
        value = json.loads(prior[0]) if prior else {'id':key,'sessionId':sid,'runId':run,
            'messageId':mid,'segmentId':segment,'toolCallId':body.get('requestId'), 'kind':category,
            'firstSeq':seq,'createdAt':event['createdAt'],'data':{'detailsAvailable':False} if category=='tool' else {}}
        if append:
            updates = {**updates,'text':value['data'].get('text','')+updates.get('text','')}
        value['data'].update(updates)
        value.update(lastSeq=seq,updatedAt=event['createdAt'],status=status)
        if category=='tool' and status not in ('running','streaming'):
            value['data']['durationMs']=max(0,round((datetime.fromisoformat(event['createdAt'])-datetime.fromisoformat(value['createdAt'])).total_seconds()*1000))
        store.db.execute('INSERT INTO timeline VALUES (?,?,?,?,?) ON CONFLICT(session,id) DO UPDATE SET last_seq=excluded.last_seq,body=excluded.body',
                         (sid,key,value['firstSeq'],seq,json.dumps(value,ensure_ascii=False)))
        changed.append(value)
        return value

    if kind == 'user_message':
        node('user:'+body.get('messageId',str(seq)),'user',body)
    elif kind == 'assistant_started':
        context.update(messageId=body['messageId'],segmentId=None)
    elif kind == 'text_delta':
        if not segment:
            segment = 'legacy:'+str(seq)
            context['segmentId']=segment
        node('text:'+str(mid)+':'+segment,'assistant',{'text':body.get('text','')},'streaming',True)
    elif kind in ('reasoning_started','reasoning_delta','reasoning_finished'):
        summary_segment=body.get('segmentId') or 'summary'
        node('reasoning:'+str(mid)+':'+summary_segment,'reasoning',
             {'text':body.get('text',''),'source':'provider_summary'} if kind=='reasoning_delta' else {'source':'provider_summary'},
             'completed' if kind=='reasoning_finished' else 'streaming',kind=='reasoning_delta')
    elif kind in ('text_finished','assistant_finished'):
        for row in store.db.execute('SELECT body FROM timeline WHERE session=? ORDER BY first_seq',(sid,)).fetchall():
            item=json.loads(row[0])
            if item['kind'] in ('assistant','reasoning') and item['status']=='streaming' and item['messageId']==mid and (kind=='assistant_finished' or (item['kind']=='assistant' and item['segmentId']==segment)):
                node(item['id'],item['kind'],{'stopReason':body.get('stopReason')},'failed' if body.get('stopReason') in ('length','error') else 'cancelled' if body.get('stopReason')=='aborted' else 'completed')
        context['segmentId']=None
    elif kind in ('tool_preparing','tool_prepared','tool_started','tool_parameters','tool_finished','tool_error'):
        request=body.get('requestId',str(seq))
        key='tool:'+str(run)+':'+request
        if kind in ('tool_preparing','tool_prepared'):
            node(key,'tool',{**body,'phase':'preparing' if kind=='tool_preparing' else 'ready'},'streaming')
        elif kind=='tool_started':
            # Legacy text must stop before tool cards; never merge across a call.
            if context.get('segmentId'):
                node('text:'+str(mid)+':'+context['segmentId'],'assistant',{},'completed')
                context['segmentId']=None
            node(key,'tool',{**body,'phase':'executing'},'running')
        elif kind=='tool_parameters':
            node(key,'tool',{**body,'detailsAvailable':True,'phase':'executing'},'running')
        else:
            status='failed' if kind=='tool_error' or body.get('failed') else 'completed'
            node(key,'tool',{**body,'phase':'finished'},status)
    elif kind=='question':
        record=store.find('question',body['id']) or {}
        node('question:'+body['id'],'question',{**body,**{k:record[k] for k in ('answer','approved','answeredAt') if k in record}},'answered' if record.get('answeredAt') else 'waiting')
    elif kind=='question_answered':
        node('question:'+body['questionId'],'question',body,'answered')
    elif kind in ('course_created','course_updated'):
        node('course:'+str(seq),'course',body)
    elif kind=='user_operation':
        node('operation:'+body['operationId'],'operation',body,body.get('status','running'))
    elif kind in ('compaction_started','compaction_finished'):
        status='running' if kind=='compaction_started' else 'cancelled' if body.get('cancelled') else 'failed' if body.get('failed') else 'completed'
        node('compaction:'+str(run)+':'+body['operationId'],'system',
             {**body,'phase':'compaction','message':body.get('text','')},status)
    elif kind in ('run_failed','run_cancelled','interrupted','run_settled'):
        terminal='cancelled' if kind=='run_cancelled' else 'interrupted' if kind=='interrupted' else 'failed' if kind=='run_failed' else 'completed'
        for row in store.db.execute('SELECT body FROM timeline WHERE session=? ORDER BY first_seq',(sid,)).fetchall():
            item=json.loads(row[0])
            if item['status'] in ('running','streaming') and (item['kind'] in ('tool','assistant','reasoning') or item['data'].get('phase')=='compaction'):
                node(item['id'],item['kind'],{},terminal if item['kind']!='tool' or terminal!='completed' else 'interrupted')
        if kind!='run_settled' or body.get('outstanding'):
            node('system:'+str(seq),'system',body,terminal)
        context.update(messageId=None,segmentId=None)
    store.put('timeline_context',sid,context)
    return changed


def project(store,event):
    if event.get('version',1)<2:return project_legacy(store,event)
    sid,run,seq=event['sessionId'],event.get('runId'),event['seq']
    body=event['data'];kind=event.get('eventType') or event['kind'];changed=[]
    def node(key,category,updates,status='completed',append=False):
        row=store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone()
        value=json.loads(row[0]) if row else {'id':key,'source':'pi','sessionId':sid,'runId':run,'messageId':body.get('messageId'),
            'segmentId':str(body.get('contentIndex')) if body.get('contentIndex') is not None else None,'toolCallId':body.get('toolCallId'),
            'kind':category,'firstSeq':seq,'createdAt':event['createdAt'],'data':{}}
        if append:updates={**updates,'text':value['data'].get('text','')+updates.get('text','')}
        value['data'].update(updates);value.update(lastSeq=seq,updatedAt=event['createdAt'],status=status)
        store.db.execute('INSERT INTO timeline VALUES (?,?,?,?,?) ON CONFLICT(session,id) DO UPDATE SET last_seq=excluded.last_seq,body=excluded.body',
                         (sid,key,value['firstSeq'],seq,json.dumps(value,ensure_ascii=False)))
        changed.append(value);return value
    if event.get('source')!='pi':
        # Workbench can annotate delivery/answer/interruption, never invent an Agent result.
        if kind=='question_answered':
            key='question:'+body['questionId']
            if store.db.execute('SELECT 1 FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone():node(key,'question',body,'answered')
        if kind in ('run_failed','run_cancelled','interrupted'):
            for row in store.db.execute('SELECT body FROM timeline WHERE session=?',(sid,)).fetchall():
                item=json.loads(row[0])
                if item.get('source')=='pi' and (not run or item['runId']==run) and item['status'] in ('running','streaming'):
                    status='cancelled' if kind=='run_cancelled' else 'interrupted'
                    node(item['id'],item['kind'],{'workspaceStatus':status,'sdkStatus':item['status'],'interruption':body.get('error') or body.get('message') or '执行已中断，未收到 SDK 结束结果'},status)
        return changed
    mid=body.get('messageId');ci=str(body.get('contentIndex',0))
    text_key=lambda index:'pi:text:'+str(run)+':'+str(mid)+':'+str(index)
    thinking_key=lambda index:'pi:thinking:'+str(run)+':'+str(mid)+':'+str(index)
    tool_key=lambda id:'tool:'+str(run)+':'+str(id)
    if kind=='message_start' and body.get('role')=='user':
        m=body.get('message',{});content=m.get('content','')
        text=content if isinstance(content,str) else ''.join(c.get('text','') for c in content if c.get('type')=='text')
        node('user:'+str(mid),'user',{'text':text})
    elif kind=='message_update':
        subtype=body.get('updateType','')
        if subtype=='text_delta':node(text_key(ci),'assistant',{'text':body.get('delta','')},'streaming',True)
        elif subtype=='text_end':node(text_key(ci),'assistant',{},'completed')
        elif subtype.startswith('thinking_'):
            updates={'source':'pi','format':'thinking','publicSummary':False}
            if body.get('textAvailable') or isinstance(body.get('delta'),str) or isinstance(body.get('text'),str):
                updates['textAvailable']=True
            if subtype=='thinking_delta' and isinstance(body.get('delta'),str):updates['text']=body['delta']
            if subtype=='thinking_end' and isinstance(body.get('text'),str):updates['text']=body['text']
            node(thinking_key(ci),'reasoning',updates,'completed' if subtype=='thinking_end' else 'streaming',subtype=='thinking_delta')
        elif subtype.startswith('toolcall_') and body.get('toolCallId'):
            key=tool_key(body['toolCallId'])
            prior=store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone()
            count=(json.loads(prior[0])['data'].get('argumentChars',0) if prior else 0)+body.get('deltaChars',0)
            data={'name':body['toolName'],'phase':'ready' if subtype=='toolcall_end' else 'preparing','argumentChars':count}
            if 'args' in body:
                data.update(target_context(body['args'],store))
                data['detailsAvailable']=True;store.capture_tool(event,parameters=body['args'])
            node(key,'tool',data,'streaming')
    elif kind=='message_end' and body.get('role')=='assistant':
        status='failed' if body.get('stopReason') in ('length','error') else 'cancelled' if body.get('stopReason')=='aborted' else 'completed'
        for index,c in enumerate(body.get('content',[])):
            if c['type']=='text':node(text_key(index),'assistant',{'text':c['text'],'stopReason':body.get('stopReason'),'error':body.get('errorMessage')},status)
            elif c['type']=='thinking' and isinstance(c.get('thinking'),str):
                node(thinking_key(index),'reasoning',{'source':'pi','format':'thinking','publicSummary':False,
                    'textAvailable':True,'text':c['thinking'],'stopReason':body.get('stopReason')},status)
            elif c['type']=='toolCall':
                key=tool_key(c['id']);row=store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone()
                if not row or json.loads(row[0])['status']=='streaming':
                    store.capture_tool({**event,'data':{**body,'toolCallId':c['id']}},parameters=c['arguments'])
                    node(key,'tool',{'name':c['name'],'detailsAvailable':True,'phase':'ready',**target_context(c['arguments'],store)},'streaming')
        for row in store.db.execute('SELECT body FROM timeline WHERE session=?',(sid,)).fetchall():
            item=json.loads(row[0])
            if item['messageId']==mid and item['kind']=='reasoning' and item['status']=='streaming':node(item['id'],'reasoning',{},status)
    elif kind.startswith('tool_execution_'):
        key=tool_key(body['toolCallId']);name=body['toolName']
        if kind=='tool_execution_start':
            store.capture_tool(event,parameters=body.get('args',{}))
            args=body.get('args',{})
            context=target_context(args,store)
            node(key,'tool',{'name':name,'phase':'executing','detailsAvailable':True,'executingAt':event['createdAt'],**context},'running')
        elif kind=='tool_execution_update':
            row=store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone()
            if row and json.loads(row[0])['data'].get('phase')=='finished':return changed
            node(key,'tool',{'name':name,'progress':body.get('partialResult')},'running')
        elif kind=='tool_execution_end':
            result=body.get('result') or {};detail=result.get('details') or {};data=detail.get('data')
            store.capture_tool(event,result=result)
            row=store.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(sid,key)).fetchone();prior=json.loads(row[0]) if row else None
            ended=datetime.fromisoformat(event['createdAt']);started=datetime.fromisoformat(prior['data'].get('executingAt',prior['createdAt'])) if prior else ended
            err=data if isinstance(data,dict) and 'code' in data else {'message':' '.join(c.get('text','') for c in result.get('content',[]) if c.get('type')=='text')} if body.get('isError') else None
            updates={'name':name,'phase':'finished','detailsAvailable':True,'failed':bool(body.get('isError')),'error':err,
                'durationMs':max(0,round((ended-started).total_seconds()*1000)),
                'preparationMs':max(0,round((started-datetime.fromisoformat(prior['createdAt'])).total_seconds()*1000)) if prior else 0}
            if isinstance(data,dict) and data.get('passed') is False and not body.get('isError'):updates['conclusion']='发现问题'
            node(key,'tool',updates,'failed' if body.get('isError') else 'partial' if detail.get('status')=='partial' else 'completed')
            if name=='ask_user' and not body.get('isError') and isinstance(data,dict) and data.get('id'):
                q=store.find('question',data['id']) or {};node('question:'+data['id'],'question',{**data,**{k:q[k] for k in ('answer','approved','answeredAt') if k in q}},'answered' if q.get('answeredAt') else 'waiting')
    elif kind in ('compaction_start','compaction_end','auto_retry_start','auto_retry_end'):
        end=kind.endswith('_end');phase='compaction' if kind.startswith('compaction') else 'retry'
        status='completed' if end else 'running'
        if body.get('aborted'):status='cancelled'
        elif end and (body.get('errorMessage') and not body.get('willRetry') or body.get('success') is False):status='failed'
        node('pi:status:'+str(run)+':'+str(body.get('operationId',phase)),'system',{**body,'phase':phase,'message':('上下文整理' if phase=='compaction' else '模型重试')+('结束' if end else '中…')},status)
    return changed


def target_label(args,store=None):
    return target_context(args,store).get('target')


def target_context(args,store=None):
    """Resolve a human target and its stable page position for timeline display."""
    if not isinstance(args,dict):return {}
    if args.get('tasks'):
        labels=[]
        page_labels=[]
        for task in args['tasks']:
            course=store.find('stage',task.get('stageId','')) if store else None
            scope=task.get('scope',{})
            if course and scope.get('kind')=='pages':
                pages=course.get('approvedPlan',{}).get('pages',[])
                indexes={p.get('id'):i+1 for i,p in enumerate(pages)}
                page_labels.extend(f"P{indexes[page_id]}" for page_id in scope.get('pageIds',[]) if page_id in indexes)
            labels.append(f"{course['title'] if course else task.get('stageId','')} · {task.get('work','')} · {'整课' if scope.get('kind')=='course' else ', '.join(scope.get('pageIds',[]))}")
        context={'target':'；'.join(labels)}
        if page_labels:
            context['pageLabel']='/'.join(dict.fromkeys(page_labels))
        return context
    if store and args.get('stageId'):
        course=store.find('stage',args['stageId'])
        if course:
            pages=course.get('approvedPlan',{}).get('pages',[])
            page_id=args.get('pageId')
            scene_id=args.get('sceneId')
            operation_scene_ids=[
                op.get('target',{}).get('sceneId')
                for op in args.get('operations',[])
                if isinstance(op,dict) and isinstance(op.get('target'),dict) and op['target'].get('sceneId')
            ]
            scene_ids=[scene_id] if scene_id else operation_scene_ids
            # patch_stage targets a scene; edit_deck and generation tools target a plan slot.
            scene=next((s for s in course.get('scenes',[]) if s.get('id') in scene_ids or (page_id and s.get('planPageId')==page_id)),None)
            page_id=page_id or (scene or {}).get('planPageId')
            # edit_deck insert carries the new page inside `page`.
            if not page_id and isinstance(args.get('page'),dict):
                page_id=args['page'].get('id')
            page=next((p for p in pages if p.get('id')==page_id),None)
            target=course['title']
            if page or scene:
                title=(scene or page).get('title','')
                target += ' · '+title if title else ''
                page_ids=[page_id]
                page_ids.extend(
                    s.get('planPageId') for s in course.get('scenes',[])
                    if s.get('id') in scene_ids and s.get('planPageId')
                )
                indexes={p.get('id'):i+1 for i,p in enumerate(pages)}
                index=indexes.get(page_id)
                context={'target':target,'pageTitle':title}
                if index is not None:
                    labels=[f'P{indexes[page]}' for page in dict.fromkeys(page_ids) if page in indexes]
                    context.update(pageIndex=index,pageLabel='/'.join(labels))
                return context
            return {'target':target}
    target=' · '.join(str(v) for v in (args.get('stageId'),args.get('sceneId') or args.get('pageId')) if v) or None
    return {'target':target} if target else {}
