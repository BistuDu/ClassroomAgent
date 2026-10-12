"""Tool event summaries and complete tool payloads with credential redaction."""
import json
import re
from functools import lru_cache
from pathlib import Path
from .config import settings


def safe(value):
    if isinstance(value,dict):
        sensitive={'apikey','api_key','authorization','token','access_token','refresh_token','secret','api_secret','password'}
        return {k:'[redacted]' if k.lower().replace('-','_') in sensitive else safe(v) for k,v in value.items()}
    if isinstance(value,list):
        return [safe(v) for v in value]
    if isinstance(value,str):
        value = settings.redact(value)
        # Preserve URLs and business fields, masking only credentials in query values.
        return re.sub(r'([?&](?:signature|x-amz-signature|x-amz-credential|x-amz-security-token|x-oss-signature|x-oss-credential|ossaccesskeyid|access_token|token|api_key)=)[^&\s"<>]+',
                      r'\1[redacted]',value,flags=re.IGNORECASE)
    return value


@lru_cache(maxsize=8)
def _session_parameters(file_path, modified_ns, size):
    """Index completed SDK tool calls to recover parameters in older timeline records."""
    calls={}
    with Path(file_path).open() as stream:
        for line in stream:
            try:
                record=json.loads(line)
            except ValueError:
                continue  # An active writer can leave the final line incomplete.
            if not isinstance(record,dict):
                continue
            message=record.get('message') or {}
            if not isinstance(message,dict) or message.get('role')!='assistant' or not isinstance(message.get('content'),list):
                continue
            for block in message.get('content',[]):
                if isinstance(block,dict) and block.get('type')=='toolCall' and isinstance(block.get('id'),str) and isinstance(block.get('arguments'),dict):
                    calls[block['id']]={'name':block.get('name'),'parameters':safe(block['arguments'])}
    return calls


def parameter_details(store,node):
    data=node['data']
    if data.get('parametersComplete') and isinstance(data.get('parameters'),dict):
        return {'parametersAvailable':True,'parametersComplete':True,'parameters':safe(data['parameters'])}
    session=store.find('session',node['sessionId']) or {}
    file=session.get('piSessionFile')
    if file:
        try:
            path=Path(file).resolve()
            if path.is_relative_to((settings.data_dir/'pi/sessions').resolve()):
                stat=path.stat()
                call=_session_parameters(str(path),stat.st_mtime_ns,stat.st_size).get(node['toolCallId'])
                if call and call['name']==data.get('name'):
                    return {'parametersAvailable':True,'parametersComplete':True,'parameters':safe(call['parameters'])}
        except (OSError,ValueError):
            pass
    parameters=data.get('parameters')
    return {'parametersAvailable':isinstance(parameters,dict),'parametersComplete':False,'parameters':safe(parameters)}


def tool_details(store, name, args, result=None):
    target = args.get('skill') or args.get('query') or args.get('url') or ''
    stage=store.find('stage',args.get('stageId',''))
    if stage:
        target=stage['title']
        scene=next((s for s in stage['scenes'] if s['id']==args.get('sceneId') or s['planPageId']==args.get('pageId')),None)
        page=next((p for p in stage['approvedPlan']['pages'] if p['id']==args.get('pageId')),None)
        if scene or page:
            target += ' · '+(scene or page)['title']
    value={'name':name,'target':safe(target),'parameters':safe(args),'parametersComplete':True,'detailsAvailable':True}
    if result is not None:
        data=result.get('data') or {}
        fields=('revision','id','mediaId','width','height','duration','model','passed','findings','coverage','uncovered','segments','waiting','question','outstanding','name','title','description','operation','affectedPage','generatedContentStale','displacedSceneId','order','path','total','text','content','voices','defaultVoice','status','trust','message','updated','updatedPages','ops','quality','changes','readback')
        if isinstance(data,dict):
            summary={k:data[k] for k in fields if k in data}
            for k in ('scene','actions','sources','pages','matches'):
                if k in data:
                    summary[k+'Count']=len(data[k]) if isinstance(data[k],list) else 1
            if isinstance(data.get('scene'),dict):
                summary['sceneTitle']=data['scene'].get('title')
        else:
            summary={'count':len(data)} if isinstance(data,list) else {'value':data}
        value.update(result=safe(summary),failed=not result.get('ok',False),error=safe(result.get('error')),
                     conclusion='发现问题' if isinstance(data,dict) and data.get('passed') is False else '完成' if result.get('ok') else '失败')
    return value
