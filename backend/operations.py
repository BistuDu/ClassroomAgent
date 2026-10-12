"""Durable tool receipts. Audit and replay do not grant write permission."""
from .models import digest
from .store import now
from .courses import fail
from .tool_result import project, safe, failure


def compact_parameters(value):
    if isinstance(value,dict):return {k:compact_parameters(v) for k,v in value.items()}
    if isinstance(value,list):
        return [compact_parameters(v) for v in value] if len(value)<=50 else {'count':len(value),'hash':digest(value)}
    if isinstance(value,str) and len(value)>240:return {'chars':len(value),'hash':digest(value)}
    return safe(value)


class OperationRecord:
    def __init__(self,store):self.store=store

    def begin(self,sid,run_id,request_id,name,raw):
        self.store.require_session(sid)
        key=run_id+':'+request_id;request_hash=digest({'name':name,'parameters':raw})
        with self.store.transaction():
            prior=self.store.find('operation_record',key)
            if prior:
                if prior['sessionId']!=sid or prior['ownerId']!=self.store.owner_id:fail('ACCESS_OWNER','操作记录不属于当前用户')
                if prior['parameterHash']!=request_hash:fail('REQUEST_CONFLICT','同一工具请求标识不能对应不同名称或参数')
                target=prior.get('stageId')
                if target and not self.store.owned('stage',target):fail('ACCESS_OWNER','重放目标课程已失去归属')
                result=self.store.cached_call(run_id,request_id)
                if result:return prior,result
                fail('OPERATION_UNCERTAIN','该操作曾开始但未收到完整回执；先读取实际状态，不自动重放写入或付费请求')
            record={'id':key,'sessionId':sid,'runId':run_id,'requestId':request_id,'ownerId':self.store.owner_id,
                    'sourceMessageId':self.store.get('run',run_id).get('sourceMessageId'),
                    'tool':name,'parameterHash':request_hash,'parametersSummary':compact_parameters(raw),
                    'stageId':raw.get('stageId'),'inputRevision':raw.get('expectedRevision'),
                    'status':'started','startedAt':now(),'sdkEvents':{}}
            # SDK start is often persisted before its Python RPC request arrives.
            rows=self.store.db.execute("SELECT kind,seq FROM events WHERE session=? AND json_extract(body,'$.runId')=? AND json_extract(body,'$.toolCallId')=? AND json_extract(body,'$._source')='pi' ORDER BY seq",(sid,run_id,request_id))
            record['sdkEvents']={kind:seq for kind,seq in rows}
            # Old receipts have no parameter hash. Do not invent evidence from a new request.
            cached=self.store.cached_call(run_id,request_id)
            if cached:
                if name=='set_course_tasks':
                    target=(cached.get('details') or {}).get('data') or {}
                    for task in target.get('tasks',[]):
                        if not self.store.owned('stage',task['stageId']):fail('ACCESS_OWNER','旧回执目标不属于当前用户')
                    return None,cached
                fail('LEGACY_RECEIPT_UNVERIFIED','旧回执缺少参数哈希；请以新的请求标识读取实际状态后继续')
            self.store.put('operation_record',key,record)
            return record,None

    def finish(self,record,result,changes=None):
        summary=project(record['tool'],result.get('data')) if result.get('data') is not None else result.get('error')
        # Read tools deliver requested text to the model; audit stores only its digest/length.
        if record['tool'] in {'read_stage','grep_stage','read_skill','fetch_url','web_search'}:
            summary=compact_parameters(summary)
        detail=result.get('details') or {};target=detail.get('target') or {}
        record.update(stageId=target.get('stageId') or record.get('stageId'),
                      outputRevision=target.get('revision'),resultSummary=safe(summary),
                      changes=safe(changes or detail.get('changes') or {}),error=result.get('error'),
                      status='completed' if result.get('ok') else 'failed',finishedAt=now())
        with self.store.transaction():
            # A start event can arrive while execution is in progress; preserve its association.
            latest=self.store.find('operation_record',record['id']) or {}
            record['sdkEvents']=latest.get('sdkEvents',{})
            self.store.put('operation_record',record['id'],record)
            result['details']['operationRecord']={k:record.get(k) for k in ('id','requestId','tool','parameterHash','parametersSummary','inputRevision','outputRevision','status','changes','error')}
            self.store.cache_call(record['runId'],record['requestId'],result)
        return result

    def fail(self,record,exc):
        result=failure(getattr(exc,'code','TOOL_ERROR'),str(exc) or type(exc).__name__,record.get('stageId'))
        return self.finish(record,result)
