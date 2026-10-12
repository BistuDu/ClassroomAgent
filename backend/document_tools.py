"""Bounded versioned reads and stable target resolution, shared by tools/feedback."""
import base64
import json
import re
import jsonpointer
from bs4 import BeautifulSoup
from .models import digest
from .courses import fail
from .tool_result import scene_tree


def page_text(text,offset,limit,**meta):
    if offset>len(text): fail('READ_OFFSET','offset 超过内容长度')
    end=min(offset+limit,len(text))
    return {**meta,'text':text[offset:end],'offset':offset,'total':len(text),'nextOffset':end if end<len(text) else None,'hasMore':end<len(text)}

def cursor(identity,index):
    return base64.urlsafe_b64encode(json.dumps({'identity':identity,'index':index}).encode()).decode()

def cursor_index(value,identity):
    if not value:return 0
    try:
        decoded=json.loads(base64.urlsafe_b64decode(value));index=decoded['index']
        if decoded['identity']!=identity: fail('STALE_CURSOR','课程/来源或查询已变化，请重新读取')
        if not isinstance(index,int) or index<0: raise ValueError()
        return index
    except (ValueError,KeyError,TypeError): fail('INVALID_CURSOR','续查游标无效')

def resolve_scene(stage,scene_id):
    index=next((i for i,s in enumerate(stage.scenes) if s.id==scene_id),None)
    if index is None: fail('SCENE_NOT_FOUND','稳定页面 ID 不存在')
    return index,stage.scenes[index]

def target_path(doc,target,path):
    if path and not path.startswith('/'): fail('PATCH_ARGUMENT','path 必须是 JSON Pointer')
    if not target:return path
    if path.startswith('/scenes/'): fail('PATCH_TARGET_CONFLICT','稳定 target 仅允许相对路径，不能同时指定全局 scenes 下标')
    i=next((i for i,s in enumerate(doc['scenes']) if s['id']==target['sceneId']),None)
    if i is None: fail('SCENE_NOT_FOUND','稳定页面目标不存在')
    scene=doc['scenes'][i];prefix=f'/scenes/{i}'
    for field,list_path in (('elementId','/content/elements'),('actionId','/actions')):
        if target.get(field):
            items=jsonpointer.resolve_pointer(scene,list_path,default=[])
            j=next((j for j,e in enumerate(items) if e['id']==target[field]),None)
            if j is None: fail('TARGET_NOT_FOUND',f'{field} 不存在')
            prefix+=list_path+'/'+str(j)
    return prefix+path

def read(stage,args):
    if args.offset and args.revision is None: fail('REVISION_REQUIRED','分页续读必须提供 revision')
    if args.revision is not None and args.revision!=stage.revision: fail('STALE_CURSOR','读取版本已过期')
    doc=stage.model_dump();prefix=''
    if args.sceneId:
        i,scene=resolve_scene(stage,args.sceneId);doc=scene.model_dump();prefix=f'/scenes/{i}'
        if args.path.startswith('/scenes/'):fail('READ_TARGET_CONFLICT','sceneId 的 path 必须相对页面')
    value=jsonpointer.resolve_pointer(doc,args.path)
    if args.detail=='tree':
        def tree(v,path):
            if isinstance(v,list):return [tree(item,path+'/'+str(i)) for i,item in enumerate(v)]
            if isinstance(v,dict):
                if 'content' in v and 'actions' in v:return scene_tree(v)
                if v.get('type')=='interactive':return {k:tree(x,path+'/'+k) for k,x in v.items() if k!='html'}|{'htmlChars':len(v['html']),'readback':{'detail':'source','path':path+'/html'}}
                if v.get('type')=='speech':return {k:v[k] for k in ('id','type','audioStatus') if k in v}|{'textChars':len(v.get('text','')),'readback':{'detail':'source','path':path}}
                if 'excerpt' in v:return {k:v[k] for k in ('id','title','url','sourceVersion','completeness') if k in v}|{'excerptChars':len(v['excerpt'])}
                return {k:tree(x,path+'/'+k) for k,x in v.items()}
            if isinstance(v,str) and len(v)>240:return {'type':'string','chars':len(v),'readback':{'detail':'source','path':path}}
            return v
        if not args.sceneId and not args.path:
            value={'stageId':stage.id,'revision':stage.revision,'title':stage.title,'theme':stage.theme.model_dump(),'teacher':stage.teacher.model_dump() if stage.teacher else None,'sources':[tree(s.model_dump(),'/sources/'+str(i)) for i,s in enumerate(stage.sources)],'pages':[p.model_dump() for p in stage.approvedPlan.pages],'scenes':[scene_tree(s) for s in stage.scenes]}
        else:value=tree(value,prefix+args.path)
    if args.detail=='text': text='\n'.join(t for _,t in strings(value,text_only=True))
    else:text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
    return page_text(text,args.offset,args.limit,stageId=stage.id,sceneId=args.sceneId,revision=stage.revision,path=prefix+args.path,detail=args.detail)

def strings(value,path='',text_only=False):
    if isinstance(value,dict):
        for k,v in value.items():
            if text_only and k in ('audioId','audioSignature','mediaId','sourceIds','id','planPageId','selector','controls','type','updatedAt'): continue
            yield from strings(v,path+'/'+str(k).replace('~','~0').replace('/','~1'),text_only)
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from strings(v,path+'/'+str(i),text_only)
    elif isinstance(value,str):
        if text_only:
            if path.endswith('/html'):value=BeautifulSoup(value,'html.parser').get_text(' ',strip=True)
            elif not re.search(r'/(text|title|brief|explanation|label|alt|content|question|excerpt|rows/\d+/\d+|objectives/\d+|audience)$',path):return
        yield path,value

def grep(stage,args):
    identity=digest({'stageId':stage.id,'revision':stage.revision,'query':args.query,'scope':args.scope,'sceneId':args.sceneId})
    start=cursor_index(args.cursor,identity);matches=[]
    doc=stage.model_dump();prefix=''
    if args.sceneId:
        i,s=resolve_scene(stage,args.sceneId);doc=s.model_dump();prefix=f'/scenes/{i}'
    for path,value in strings(doc,prefix,text_only=args.scope=='text'):
        pos=0
        while (pos:=value.find(args.query,pos))>=0:
            scene_match=re.match(r'/scenes/(\d+)/',path)
            scene=stage.scenes[int(scene_match[1])] if scene_match else None
            matches.append({'path':path,'sceneId':scene.id if scene else None,'offset':pos,'text':value[max(0,pos-80):pos+len(args.query)+160],'snippetStart':max(0,pos-80),'readback':{'tool':'read_stage','stageId':stage.id,'detail':'source','path':path,'revision':stage.revision}})
            pos+=len(args.query)
    end=min(start+args.limit,len(matches))
    return {'stageId':stage.id,'revision':stage.revision,'matches':matches[start:end],'hasMore':end<len(matches),'nextCursor':cursor(identity,end) if end<len(matches) else None,'total':len(matches)}
