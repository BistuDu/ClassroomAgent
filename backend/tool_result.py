"""Different projections of the same operation, without lossy generic clipping."""
import copy
import json
from typing import Any, Literal
from pydantic import Field
from .models import Model
from .config import settings

class ToolDetails(Model):
    schemaVersion: Literal[2] = 2
    status: Literal['completed','partial','failed'] = 'completed'
    target: dict[str,Any] = Field(default_factory=dict)
    data: Any = None
    changes: dict[str,Any] = Field(default_factory=dict)
    artifacts: list[dict[str,Any]] = Field(default_factory=list)
    issues: list[dict[str,Any]] = Field(default_factory=list)
    operationRecord: dict[str,Any] | None = None

class ToolResult(Model):
    ok: bool
    waiting: bool = False
    content: list[dict[str,Any]]
    details: ToolDetails
    isError: bool = False
    terminate: bool = False
    # Kept for the internal idempotency cache, never used to assemble new UI facts.
    data: Any = None
    error: dict[str,Any] | None = None


def safe(value):
    from .tool_summary import safe as redact_payload
    return redact_payload(value)


def scene_tree(scene):
    d=scene.model_dump() if hasattr(scene,'model_dump') else scene
    content=d['content']
    out={k:d[k] for k in ('id','planPageId','title','type','sourceIds')}
    out.update(readback={'tool':'read_stage','sceneId':d['id'],'detail':'source'},
        actions=[{'id':a['id'],'type':a['type'],'audioStatus':a['audioStatus']} for a in d['actions']])
    if d['type']=='slide': out['elements']=[{'id':e['id'],'type':e['type'],'path':'/content/elements/'+str(i)} for i,e in enumerate(content['elements'])]
    elif d['type']=='interactive': out['simulation']={k:content[k] for k in ('variables','controls','presets','initialState')};out['htmlChars']=len(content['html'])
    else: out['questions']=[{'id':q['id'],'options':len(q['options'])} for q in content['questions']]
    return out


def stage_summary(data):
    return {'stageId':data['id'],'revision':data['revision'],'title':data['title'],
        'pages':[{'slotId':p['id'],'title':p['title'],'type':p['type']} for p in data['approvedPlan']['pages']],
        'outstandingCount':len(data.get('outstanding',[])),
        'readback':{'tool':'read_stage','stageId':data['id'],'detail':'tree'}}


def project(name,data):
    if name in ('create_stage','edit_deck') and isinstance(data,dict) and 'scenes' in data:
        return {**stage_summary(data),**({'reused':data.get('reused',False)} if name=='create_stage' else {})}
    if name=='generate_scene':
        tree=scene_tree(data['scene']);tree['stageId']=data['stageId'];tree['readback']['stageId']=data['stageId']
        return {k:v for k,v in data.items() if k!='scene'} | {'scene':tree}
    if name=='generate_actions':
        return {k:v for k,v in data.items() if k!='actions'} | {'actions':[{'id':a['id'],'type':a['type'],'textChars':len(a['text']),'audioStatus':a['audioStatus']} for a in data['actions']]}
    if name=='render_scene_preview': return {k:v for k,v in data.items() if k!='image'}
    return copy.deepcopy(data)


def success(name,data,waiting=False):
    model_data=project(name,data)
    status=data.get('status','completed') if isinstance(data,dict) else 'completed'
    if status not in ('completed','partial','failed'): status='completed'
    execution_failed=isinstance(data,dict) and data.get('executed') is False
    if execution_failed: status='failed'
    is_error=execution_failed or status=='failed'
    image=data.get('image') if isinstance(data,dict) else None
    content=[{'type':'text','text':json.dumps(safe(model_data),ensure_ascii=False)}]
    artifacts=[]
    if image:
        content.append({'type':'image','data':image['data'],'mimeType':image['mimeType']})
        artifacts.append({'mediaId':data.get('mediaId'),'mimeType':image['mimeType'],'url':'/api/media/'+data['mediaId']})
    details_data={k:v for k,v in data.items() if k!='image'} if image else model_data if name in {'generate_scene','generate_actions'} else data
    target={k:data[k] for k in ('stageId','sceneId','slotId','revision') if k in data} if isinstance(data,dict) else {}
    details=ToolDetails(status=status,target=target,data=safe(details_data),changes=safe(data.get('changes',{})) if isinstance(data,dict) else {},artifacts=artifacts,issues=safe(data.get('issues',[])) if isinstance(data,dict) else [])
    return ToolResult(ok=not is_error,waiting=waiting,content=content,details=details,isError=is_error,terminate=waiting,data=data).model_dump()


def failure(code,message,stage_id=None):
    error={'code':code,'message':settings.redact(message)}
    if stage_id:error['stageId']=stage_id
    return ToolResult(ok=False,content=[{'type':'text','text':json.dumps(error,ensure_ascii=False)}],
        details=ToolDetails(status='failed',target={'stageId':stage_id} if stage_id else {},data=error,issues=[dict(error,stageId=stage_id)] if stage_id else [error]),isError=True,error=error).model_dump()
