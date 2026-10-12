"""Read-only old task hints, never an execution or authorization protocol."""
import copy


def public(task):
    return {k:copy.deepcopy(task[k]) for k in ('taskId','stageId','scope','work','registeredRevision','requestText','state') if k in task} | {'legacy':True,'readOnly':True}


def historical_tasks(session,run=None):
    items=[public(t) for t in session.get('unfinishedTasks',{}).values()]
    if run:
        items.extend(public(t) for t in run.get('courseTasks',{}).values())
    # v2 hints remain unmodified. They are candidates to re-read, never authorization.
    for source,value in [('unfinishedGoals',session.get('unfinishedGoals',{})),('courseTargets',(run or {}).get('courseTargets',{}))]:
        items.extend({'stageId':stage_id,'source':source,'hint':copy.deepcopy(hint),'legacy':True,'readOnly':True} for stage_id,hint in value.items())
    return {'items':items[:20],'total':len(items),'hasMore':len(items)>20,'readOnly':True,
            'instruction':'历史待续信息仅供核实原请求；重新读取真实课程，不恢复登记工具'}


def pending_page(session,stage_id,offset=0):
    items=[public(t) for t in session.get('unfinishedTasks',{}).values() if t.get('stageId')==stage_id]
    end=min(offset+20,len(items))
    return {'items':items[offset:end],'total':len(items),'offset':offset,'hasMore':end<len(items),
            'nextOffset':end if end<len(items) else None,'readOnly':True}
