"""Verified read evidence and per-operation bounds, without model task registration."""
import copy
import re
from contextvars import ContextVar
from .courses import fail
from .models import digest
from .store import now

active_operation = ContextVar('active_operation', default=None)
WRITE_TOOLS = {'rename_stage','patch_stage','edit_deck','set_teacher_voice','generate_image',
               'generate_scene','generate_actions','generate_tts','render_scene_preview','check_scene','web_search','fetch_url'}


def issue_key(issue):
    return digest({k:issue.get(k) for k in ('slotId','sceneId','code','status','actionId','mode')})


class RunContext:
    def __init__(self, courses):
        self.courses, self.store = courses, courses.store

    def ensure(self, sid, run_id):
        self.store.require_session(sid)
        run = self.store.get('run', run_id)
        if run.get('sessionId') != sid: fail('RUN_SCOPE','运行不属于当前对话')
        context = run.get('runContext')
        if context:
            if context['sessionId'] != sid or context['ownerId'] != self.store.owner_id:
                fail('ACCESS_OWNER','运行上下文不属于当前用户')
            return copy.deepcopy(context)
        context = {'sessionId':sid,'runId':run_id,'ownerId':self.store.owner_id,
                   'sourceMessageId':run.get('sourceMessageId'),'courses':{},'createdAt':now()}
        self.store.put('run',run_id,{**run,'runContext':context})
        return context

    def save(self, context):
        run = self.store.get('run',context['runId'])
        self.store.put('run',context['runId'],{**run,'runContext':context})

    def verified(self, sid, run_id, stage, pages, *, whole=False):
        context = self.ensure(sid,run_id)
        prior = context['courses'].get(stage.id,{})
        # Old page evidence cannot be carried across a revision changed outside this run.
        same = prior.get('confirmedRevision') == stage.revision
        entry = {**prior,'stageId':stage.id,'title':stage.title,'confirmedRevision':stage.revision,
                 'verifiedPageIds':sorted(set(pages) | set(prior.get('verifiedPageIds',[]) if same else [])),
                 'wholeRead':whole or bool(same and prior.get('wholeRead')),'verifiedAt':now()}
        entry.setdefault('baselineIssueKeys',[issue_key(i) for i in self.courses.summary(stage)['issues']])
        entry.setdefault('targetPageIds',[])
        entry.setdefault('operated',False)
        entry.setdefault('fullCourse',False)
        context['courses'][stage.id] = entry
        self.save(context)

    def observe(self, sid, run_id, name, args, data):
        stage_id = getattr(args,'stageId',None)
        if not stage_id or name not in {'read_stage','list_scenes','grep_stage'}: return
        stage = self.courses.stage(stage_id)
        whole = False
        pages = set()
        if name == 'list_scenes':
            pages = {p.id for p in stage.approvedPlan.pages};whole=True
        elif name == 'grep_stage':
            scene_ids = {m.get('sceneId') for m in data['matches']}
            pages = {s.planPageId for s in stage.scenes if s.id in scene_ids}
        elif args.sceneId:
            pages = {s.planPageId for s in stage.scenes if s.id == args.sceneId}
        elif not args.path:
            # A truncated whole-course read is not proof of receiving all page IDs.
            whole = data['offset']==0 and not data['hasMore']
            if whole: pages = {p.id for p in stage.approvedPlan.pages}
        else:
            match = re.match(r'^/scenes/(\d+)(?:/|$)',args.path)
            if match and int(match[1]) < len(stage.scenes):
                pages = {stage.scenes[int(match[1])].planPageId}
        self.verified(sid,run_id,stage,pages,whole=whole)

    def approval(self,sid,run_id,stage_id,approval_id):
        approval = self.store.get('plan_approval',approval_id)
        if approval.get('sessionId') != sid or approval.get('approvedRunId') != run_id:
            return  # Historical approval is a prerequisite, not a new full-course request.
        stage = self.courses.stage(stage_id)
        self.verified(sid,run_id,stage,{p.id for p in stage.approvedPlan.pages},whole=True)
        context = self.ensure(sid,run_id)
        context['courses'][stage_id].update(fullCourse=True,approvalId=approval_id,operated=True)
        self.save(context)

    def request_pages(self,stage,name,args):
        if name=='patch_stage':
            from .document_tools import target_path
            pages=set();fields=set();doc=stage.model_dump()
            for op in args.operations:
                if op.op=='test':continue
                path=target_path(doc,op.target.model_dump() if op.target else None,op.path)
                parts=path.split('/')
                if len(parts)>=3 and parts[1]=='scenes' and parts[2].isdigit() and int(parts[2])<len(stage.scenes):
                    pages.add(stage.scenes[int(parts[2])].planPageId)
                    fields.add('page_metadata' if len(parts)>3 and parts[3] in {'title','brief','sourceIds'} else 'page')
                elif path in ('/title','/description'): fields.add('course_metadata')
                else:fields.add('course')
            return pages,fields
        if name=='edit_deck':
            if args.operation in ('rename','set_brief','set_sources','delete'):return {args.pageId},{'directory'}
            if args.operation=='insert':return set(),{'course'}
            return set(args.order),{'course'}
        if getattr(args,'sceneId',None):
            scene=next((s for s in stage.scenes if s.id==args.sceneId),None)
            if not scene:fail('SCENE_NOT_FOUND','页面不存在或不属于目标课')
            return {scene.planPageId},set()
        if getattr(args,'pageId',None):return {args.pageId},set()
        return set(),{'course'}

    def select(self,sid,run_id,name,args):
        if name not in WRITE_TOOLS or not getattr(args,'stageId',None) or name=='fetch_url' and not args.url:return None
        stage=self.courses.stage(args.stageId)
        pages,fields=self.request_pages(stage,name,args)
        # The document tool owns precise migration errors for obsolete patch paths.
        if name=='patch_stage' and fields & {'course_metadata','page_metadata'}:return None
        context=self.ensure(sid,run_id);entry=context['courses'].get(stage.id)
        if not entry:fail('TARGET_UNVERIFIED','先 read_stage 或 list_scenes 核实目标课程和页面，不使用预览作为写入目标')
        if stage.revision!=entry['confirmedRevision']:fail('REVISION_CONFLICT','目标课程在读取后已变化，请重新读取')
        revision=getattr(args,'expectedRevision',stage.revision)
        if revision!=stage.revision:fail('REVISION_CONFLICT',f'预期版本 {revision}，实际 {stage.revision}；请重新读取')
        if not pages<=set(entry['verifiedPageIds']):fail('PAGE_UNVERIFIED','目标页未在当前版本读取，请读取该页或目录后重试')
        if 'course' in fields and not entry['wholeRead']:fail('COURSE_SCOPE','课程整体操作需要先读取完整目录；单页读取不扩大为全课')
        # Each call is bounded to its actual target. A tree read never authorizes automatic work on every page.
        return {'manager':self,'sid':sid,'runId':run_id,'stageId':stage.id,'name':name,
                'pages':pages,'fields':fields,'allowCourse':'course' in fields,
                'baselineRevision':stage.revision}

    def validate_change(self,context,old,candidate):
        if old.id!=context['stageId']:fail('RUN_SCOPE','提交课程与操作目标不一致')
        before={s.planPageId:s for s in old.scenes};after={s.planPageId:s for s in candidate.scenes}
        changed={p for p in before.keys()|after.keys() if (before[p].model_dump() if p in before else None)!=(after[p].model_dump() if p in after else None)}
        if not context['allowCourse'] and not changed<=context['pages']:fail('PAGE_SCOPE','实际修改超出当前操作的页面范围')
        old_sources={s.id:s.model_dump() for s in old.sources};new_sources={s.id:s.model_dump() for s in candidate.sources}
        changed_sources={s for s in old_sources.keys()|new_sources.keys() if old_sources.get(s)!=new_sources.get(s)}
        affected={s.planPageId for s in candidate.scenes if set(s.sourceIds)&changed_sources}
        if not context['allowCourse'] and not affected<=context['pages']:fail('PAGE_SCOPE','来源变更影响当前操作之外的页面')
        if not context['allowCourse']:
            if any(getattr(old,k)!=getattr(candidate,k) for k in ('title','description','theme','teacher')):
                fail('COURSE_SCOPE','单页操作不能修改全课配置')
            old_pages={p.id:p.model_dump() for p in old.approvedPlan.pages};new_pages={p.id:p.model_dump() for p in candidate.approvedPlan.pages}
            changed_slots={p for p in old_pages.keys()|new_pages.keys() if old_pages.get(p)!=new_pages.get(p)}
            if not changed_slots<=context['pages']:fail('PAGE_SCOPE','目录修改超出当前操作页面')

    def record(self,context,before,data=None,error=None):
        if not context:return
        state=self.ensure(context['sid'],context['runId']);entry=state['courses'][context['stageId']]
        after=self.courses.stage(context['stageId'])
        changes=self.courses.changes(before,after)
        previous={issue_key(i) for i in self.courses.summary(before)['issues']}
        current={issue_key(i) for i in self.courses.summary(after)['issues']}
        entry['invalidatedIssueKeys']=sorted(set(entry.get('invalidatedIssueKeys',[])) | (current-previous))
        operation_key=digest({'tool':context['name'],'pages':sorted(context['pages'])})
        errors=entry.setdefault('operationErrors',{})
        failed=error or isinstance(data,dict) and (data.get('executed') is False or data.get('status')=='failed')
        if failed:
            errors[operation_key]={'stageId':after.id,'code':getattr(error,'code','OPERATION_FAILED'),
                'status':'failed','message':str(error) if error else '工具未完成执行，请查看实际调用回执',
                'tool':context['name'],'pageIds':sorted(context['pages'])}
        else:errors.pop(operation_key,None)
        entry['confirmedRevision']=after.revision
        entry['verifiedPageIds']=[p for p in entry['verifiedPageIds'] if p in {v.id for v in after.approvedPlan.pages}]
        # Explicit insertion has a known new page ID; unrelated pages are never added by writing.
        if context['name']=='edit_deck' and not error:
            entry['verifiedPageIds']=sorted(set(entry['verifiedPageIds'])|({p.id for p in after.approvedPlan.pages}-{p.id for p in before.approvedPlan.pages}))
        entry['targetPageIds']=sorted(set(entry['targetPageIds'])|context['pages']|{s.planPageId for s in after.scenes if s.id in changes['sceneIds']})
        entry['operated']=True
        self.save(state)

    def feedback(self,sid,run_id):
        context=self.ensure(sid,run_id);results=[];issues=[]
        for stage_id,entry in context['courses'].items():
            if not entry.get('operated'):continue
            if not self.store.owned('stage',stage_id):
                problem={'stageId':stage_id,'code':'TARGET_UNAVAILABLE','status':'failed','message':'本轮目标课程已不可读取，请重新确认目标'}
                results.append({'stageId':stage_id,'title':entry.get('title',stage_id),'ready':False,'courseReady':False,'issues':[problem],'outstanding':[problem['message']]})
                issues.append(problem);continue
            stage=self.courses.stage(stage_id);summary=self.courses.summary(stage)
            scoped=summary['issues'] if entry['fullCourse'] else [i for i in summary['issues'] if i['slotId'] in entry['targetPageIds'] and (issue_key(i) not in entry['baselineIssueKeys'] or issue_key(i) in entry.get('invalidatedIssueKeys',[]))]
            scoped=[*scoped,*entry.get('operationErrors',{}).values()]
            results.append({'stageId':stage_id,'title':stage.title,'revision':stage.revision,'ready':not scoped,
                'courseReady':summary['ready'],'scope':{'kind':'course' if entry['fullCourse'] else 'pages','pageIds':entry['targetPageIds']},
                'issues':scoped,'outstanding':[i['message'] for i in scoped],
                'courseOutstandingCount':len(summary['issues']),'courseStatus':summary['courseStatus']})
            issues.extend(scoped)
        return {'scope':'run-context','courses':results,'issues':issues,
                'instruction':'仅处理当前操作范围内新增缺项；课程状态来自真实保存数据。旧缺项只报告，不自动扩大本轮工作。'}

    def preserve(self,sid,run_id):
        context=self.ensure(sid,run_id)
        if any(e.get('operated') for e in context['courses'].values()):
            # Recovery evidence, not a task registry or an authorization ticket.
            self.store.patch_session(sid,lastRunContext=context)
