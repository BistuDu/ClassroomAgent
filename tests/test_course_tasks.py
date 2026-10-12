"""Task-free execution: verified reads, replay, isolation, recovery and true readiness."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from backend.courses import Courses,DomainError
from backend.models import digest,program_fingerprint,visual_fingerprint
from backend.store import Store
from backend.tools import Tools
from backend.tool_args import TOOLS
from backend.runtime import Runtime,Message
from backend.narration import Narration
from backend.providers import Providers
from backend.inspection import Inspection
from test_tool_contracts import classroom


def own(store,stage):
    store.put('stage',stage.id,stage.model_dump())
    store.put('course_owner',stage.id,{'ownerId':'local'})
    store.put('course_approval',stage.id,{'planHash':digest(stage.approvedPlan.model_dump())})


class TaskFreeContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=patch('backend.config.ROOT',Path(self.tmp.name));self.root.start()
        self.store=Store(Path(self.tmp.name)/'db.sqlite3');self.c=Courses(self.store)
        self.a=classroom();own(self.store,self.a)
        self.b=self.a.model_copy(deep=True);self.b.id='course_b';own(self.store,self.b)
        self.sid=self.store.session(self.a.id)['id'];self.run='run_test'
        self.store.patch_session(self.sid,state='running',runId=self.run)
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':4,'sourceMessageId':'m1'})
        self.p=Providers(self.store);self.n=Narration(self.c,self.p)
        self.t=Tools(self.c,self.p,Inspection(self.c,self.p),self.n)
        self.seq=0
    async def asyncTearDown(self):
        await self.n.close();await self.p.close();self.store.close();self.root.stop();self.tmp.cleanup()
    async def call(self,name,args,request=None):
        self.seq+=1
        return await self.t.call(self.sid,self.run,request or f'req{self.seq}',name,args)
    async def read(self,stage='course',scene=None):
        return await self.call('read_stage',{'stageId':stage,**({'sceneId':scene} if scene else {})})
    def change(self,stage='course',scene='s1',revision=1):
        return {'stageId':stage,'expectedRevision':revision,'operations':[{'op':'replace_text',
            'target':{'sceneId':scene,'elementId':'note'},'path':'/text','old':'角度比较','new':'更新例子'}]}

    async def test_no_registration_tool_and_new_run_has_no_task_fields(self):
        self.assertNotIn('set_course_tasks',TOOLS)
        runtime=Runtime(self.store,self.c,self.t);runtime.run=AsyncMock()
        self.store.patch_session(self.sid,state='idle',operation=None)
        accepted=await runtime.submit(self.sid,Message(messageId='new',text='修改第一页'))
        await runtime.tasks[self.sid]
        run=self.store.get('run',accepted['runId'])
        self.assertNotIn('courseTasks',run);self.assertNotIn('unfinishedTasks',self.store.get('session',self.sid))
        self.assertEqual(run['runContext']['sourceMessageId'],'new')
        await runtime.close()

    async def test_read_then_direct_write_without_registering(self):
        await self.read(scene='s1')
        result=await self.call('patch_stage',self.change())
        self.assertTrue(result['ok']);self.assertEqual(result['data']['revision'],2)
        self.assertNotIn('角度比较',result['content'][0]['text'])
        record=self.store.get('operation_record',self.run+':req2')
        self.assertEqual(record['inputRevision'],1);self.assertEqual(record['outputRevision'],2)
        self.assertEqual(record['changes']['sceneIds'],['s1'])
        self.assertEqual(self.c.stage('course_b').revision,1)

    async def test_unread_wrong_page_and_foreign_rejected_before_paid_calls(self):
        self.p.generate=AsyncMock()
        with self.assertRaises(DomainError) as e:await self.call('generate_scene',{'stageId':'course','expectedRevision':1,'pageId':'p1','brief':'重做'})
        self.assertEqual(e.exception.code,'TARGET_UNVERIFIED')
        await self.read(scene='s1')
        with self.assertRaises(DomainError):await self.call('generate_scene',{'stageId':'course','expectedRevision':1,'pageId':'p2','brief':'重做'})
        with self.assertRaises(DomainError):await self.call('patch_stage',self.change(stage='course_b'))
        self.store.put('course_owner','course_b',{'ownerId':'foreign'})
        with self.assertRaises(DomainError):await self.read(stage='course_b')
        self.p.generate.assert_not_awaited();self.assertEqual(self.c.stage('course').revision,1)

    async def test_scope_does_not_expand_from_first_write_or_preview(self):
        await self.read(scene='s1');await self.call('patch_stage',self.change())
        self.store.link_course(self.sid,'course_b',active=True)
        with self.assertRaises(DomainError):await self.call('patch_stage',self.change(scene='s2',revision=2))
        ctx=self.t.context.ensure(self.sid,self.run)
        self.assertEqual(ctx['courses']['course']['targetPageIds'],['p1'])
        self.assertFalse(ctx['courses']['course']['fullCourse'])
        self.assertNotIn('course_b',ctx['courses'])

    async def test_hash_replay_and_changed_parameters_rejected(self):
        await self.read()
        args=self.change();result=await self.call('patch_stage',args,'once')
        replay=await self.call('patch_stage',args,'once');self.assertEqual(replay,result)
        changed=copy.deepcopy(args);changed['operations'][0]['new']='别的内容'
        with self.assertRaises(DomainError) as e:await self.call('patch_stage',changed,'once')
        self.assertEqual(e.exception.code,'REQUEST_CONFLICT');self.assertEqual(self.c.stage('course').revision,2)

    async def test_incomplete_receipt_never_replays_paid_request(self):
        await self.read();args={'stageId':'course','prompt':'光线'}
        self.t.operations.begin(self.sid,self.run,'uncertain','generate_image',args)
        self.p.image=AsyncMock()
        with self.assertRaises(DomainError) as e:await self.call('generate_image',args,'uncertain')
        self.assertEqual(e.exception.code,'OPERATION_UNCERTAIN');self.p.image.assert_not_awaited()

    async def test_stale_revision_and_occupancy_precede_provider(self):
        await self.read();self.p.generate=AsyncMock()
        doc=self.store.get('stage','course');doc['revision']=2;self.store.put('stage','course',doc)
        with self.assertRaises(DomainError) as e:await self.call('generate_scene',{'stageId':'course','expectedRevision':1,'pageId':'p1','brief':'重做'})
        self.assertEqual(e.exception.code,'REVISION_CONFLICT')
        await self.read();other=self.store.session('course')['id'];self.c.claim_course(other,'course','other','agent')
        with self.assertRaises(DomainError) as e:await self.call('generate_scene',{'stageId':'course','expectedRevision':2,'pageId':'p1','brief':'重做'})
        self.assertEqual(e.exception.code,'COURSE_BUSY');self.p.generate.assert_not_awaited()

    async def test_restart_preserves_context_receipt_and_old_fields_readonly(self):
        self.store.patch_session(self.sid,unfinishedTasks={'old':{'taskId':'old','stageId':'course','scope':{'kind':'pages','pageIds':['p1']},'work':'edit','state':'unfinished'}})
        old=copy.deepcopy(self.store.get('session',self.sid)['unfinishedTasks'])
        await self.read(scene='s1');args=self.change();result=await self.call('patch_stage',args,'saved')
        Runtime(self.store,self.c,self.t)
        self.assertEqual(await self.call('patch_stage',args,'saved'),result)
        self.assertEqual(self.store.get('session',self.sid)['unfinishedTasks'],old)
        self.assertEqual(self.store.get('session',self.sid)['lastRunContext']['courses']['course']['targetPageIds'],['p1'])
        reopened=Store(Path(self.tmp.name)/'db.sqlite3')
        try:
            restored=Tools(Courses(reopened),self.p,self.t.inspection,self.n)
            self.assertEqual(await restored.call(self.sid,self.run,'saved','patch_stage',args),result)
            self.assertEqual(restored.context.ensure(self.sid,self.run)['courses']['course']['confirmedRevision'],2)
            ctx=reopened.get('run',self.run);ctx['runContext']['ownerId']='foreign';reopened.put('run',self.run,ctx)
            with self.assertRaises(DomainError) as invalid:restored.context.ensure(self.sid,self.run)
            self.assertEqual(invalid.exception.code,'ACCESS_OWNER')
            ctx['runContext']['ownerId']='local';reopened.put('run',self.run,ctx)
        finally:reopened.close()
        with self.assertRaises(DomainError) as e:await self.call('set_course_tasks',{'tasks':[]})
        self.assertEqual(e.exception.code,'TOOL_REMOVED');self.assertEqual(self.store.get('session',self.sid)['unfinishedTasks'],old)

    async def test_legacy_cached_registration_remains_visible_without_new_mutation(self):
        prior={'ok':True,'details':{'data':{'tasks':[{'stageId':'course'}]}}}
        self.store.cache_call(self.run,'old',prior)
        before=self.store.get('stage','course')
        result=await self.call('set_course_tasks',{'tasks':[]},'old')
        self.assertEqual(result,prior);self.assertEqual(before,self.store.get('stage','course'))
        self.assertIsNone(self.store.find('operation_record',self.run+':old'))

    async def test_course_status_uses_actual_media_and_reports(self):
        summary=self.c.summary(self.a)
        self.assertFalse(summary['ready']);self.assertEqual(summary['courseStatus']['savedPageCount'],2)
        self.assertEqual(summary['courseStatus']['pages'][0]['speechCount'],3)
        for mode,fn in [('program',program_fingerprint),('visual',visual_fingerprint)]:
            self.store.put('inspection',mode,{'id':mode,'stageId':'course','sceneId':'s1','mode':mode,'passed':True,'executed':True,
                'fingerprintVersion':2,'fingerprint':fn(self.a,self.a.scenes[0],self.store)})
        await self.read(scene='s1');await self.call('patch_stage',self.change())
        summary=self.c.summary(self.c.stage('course'))
        self.assertTrue(any(i['code']=='CHECK_STALE' for i in summary['issues']))
        self.assertFalse(summary['ready'])
        f=self.t.context.feedback(self.sid,self.run)
        self.assertTrue(all(i['slotId']=='p1' for i in f['issues']))
        self.assertFalse(f['courses'][0]['courseReady'])

    async def test_read_only_does_not_trigger_completion_repair(self):
        await self.read();await self.call('list_stages',{})
        self.assertEqual(self.t.context.feedback(self.sid,self.run)['courses'],[])
        self.assertEqual(self.c.stage('course').revision,1)

    async def test_failed_operation_not_marked_ready_then_success_clears_error(self):
        await self.read(scene='s1')
        args=self.change();args['operations'][0]['old']='不存在的正文'
        with self.assertRaises(DomainError):await self.call('patch_stage',args)
        feedback=self.t.context.feedback(self.sid,self.run)
        self.assertFalse(feedback['courses'][0]['ready'])
        self.assertEqual(self.c.stage('course').revision,1)
        await self.call('patch_stage',self.change())
        self.assertFalse(self.t.context.ensure(self.sid,self.run)['courses']['course']['operationErrors'])

    async def test_missing_operated_course_reports_failure(self):
        await self.read(scene='s1');await self.call('patch_stage',self.change())
        self.store.put('course_owner','course',{'ownerId':'foreign'})
        feedback=self.t.context.feedback(self.sid,self.run)
        self.assertFalse(feedback['courses'][0]['ready'])
        self.assertEqual(feedback['issues'][0]['code'],'TARGET_UNAVAILABLE')

    async def test_two_courses_isolate_versions_context_and_operation_records(self):
        await self.read(scene='s1');await self.read(stage='course_b',scene='s2')
        await self.call('patch_stage',self.change(),'a-edit')
        await self.call('patch_stage',self.change(stage='course_b',scene='s2'),'b-edit')
        a=self.c.stage('course');b=self.c.stage('course_b')
        self.assertEqual(a.scenes[1].content.elements[1].text,'角度比较')
        self.assertEqual(b.scenes[0].content.elements[1].text,'角度比较')
        self.assertEqual(self.store.get('operation_record',self.run+':a-edit')['stageId'],'course')
        self.assertEqual(self.store.get('operation_record',self.run+':b-edit')['stageId'],'course_b')

    async def test_stop_gate_and_atomic_cross_page_patch(self):
        await self.read();args=self.change();args['operations']+=self.change(scene='s2')['operations']
        with self.assertRaises(DomainError):await self.call('patch_stage',args)
        self.assertEqual(self.c.stage('course').revision,1)
        self.store.patch_session(self.sid,state='cancelled')
        with self.assertRaises(DomainError) as e:await self.call('patch_stage',self.change())
        self.assertEqual(e.exception.code,'WAITING_OR_STOPPED')

if __name__=='__main__':unittest.main()
