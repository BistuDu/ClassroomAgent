"""Readiness calculated from current documents, audio and inspection fingerprints."""
from .models import audio_signature, report_matches
from .config import settings


class CourseStatus:
    def __init__(self,courses):self.courses=courses

    def calculate(self, stage):
        issues=[]
        def add(code,state,page,scene,message,action=None,mode=None):
            issues.append({'stageId':stage.id,'code':code,'status':state,'slotId':page.id,'sceneId':scene.id if scene else None,
                'actionId':action,'mode':mode,'message':message,'revision':stage.revision,
                'readback':{'tool':'read_stage','stageId':stage.id,'sceneId':scene.id if scene else None,'detail':'source'}})
        inspections=self.courses.store.list('inspection')
        for page in stage.approvedPlan.pages:
            scene=next((s for s in stage.scenes if s.planPageId==page.id),None)
            if not scene:
                add('PAGE_MISSING','missing',page,None,f'缺页：{page.title}');continue
            if scene.type=='slide':
                for e in scene.content.elements:
                    if e.type=='image':
                        m=self.courses.store.find('media',e.mediaId)
                        if not m or not (settings.data_dir/'media'/m['file']).is_file():add('IMAGE_UNREADABLE','failed',page,scene,f'{scene.title}：配图 {e.id} 不可读取')
            if not any(a.type=='speech' for a in scene.actions):add('SPEECH_MISSING','missing',page,scene,f'{scene.title}：缺少老师讲解')
            for a in scene.actions:
                if a.type=='speech':
                    m=self.courses.store.find('media',a.audioId) if a.audioId else None
                    if a.audioStatus!='ready' or a.audioSignature!=audio_signature(a,stage.teacher) or not m or not (settings.data_dir/'media'/m['file']).is_file():
                        add('AUDIO_INVALID','stale' if a.audioStatus=='stale' else 'failed' if a.audioStatus=='failed' else 'missing',page,scene,f'{scene.title}：讲解 {a.id} 音频未就绪',a.id)
            for mode in ('program','visual'):
                reports=[i for i in inspections if i['stageId']==stage.id and i['sceneId']==scene.id and i['mode']==mode]
                matching=[i for i in reports if report_matches(i,stage,scene,self.courses.store)]
                label='程序' if mode=='program' else '视觉'
                if not reports:add('CHECK_MISSING','missing',page,scene,f'{scene.title}：尚未进行{label}检查',mode=mode)
                elif not matching:add('CHECK_STALE','stale',page,scene,f'{scene.title}：{label}检查报告已过期，需检查当前版本',mode=mode)
                elif matching[0].get('executed') is False:add('CHECK_UNEXECUTED','uncovered',page,scene,f'{scene.title}：{label}检查未完成',mode=mode)
                elif not matching[0]['passed']:add('CHECK_FAILED','failed',page,scene,f'{scene.title}：当前版本{label}检查失败：'+'；'.join((matching[0].get('findings') or ['查看报告'])[:3]),mode=mode)
        pages=[]
        for page in stage.approvedPlan.pages:
            scene=next((s for s in stage.scenes if s.planPageId==page.id),None)
            pending=[i for i in issues if i['slotId']==page.id]
            speech=[a for a in scene.actions if a.type=='speech'] if scene else []
            pages.append({'pageId':page.id,'sceneId':scene.id if scene else None,'content':bool(scene),
                'actionCount':len(scene.actions) if scene else 0,'speechCount':len(speech),
                'audioReadyCount':sum(not any(i['code']=='AUDIO_INVALID' and i['actionId']==a.id for i in pending) for a in speech),
                'program':next((i['status'] for i in pending if i.get('mode')=='program'),'passed') if scene else 'missing',
                'visual':next((i['status'] for i in pending if i.get('mode')=='visual'),'passed') if scene else 'missing',
                'ready':not pending})
        status={'stageId':stage.id,'revision':stage.revision,'plannedPageCount':len(stage.approvedPlan.pages),
                'savedPageCount':len(stage.scenes),'ready':not issues,'outstandingCount':len(issues),'pages':pages}
        return {'ready':not issues,'outstanding':[i['message'] for i in issues],'issues':issues,
                'inspections':[i for i in inspections if i['stageId']==stage.id],'courseStatus':status}

