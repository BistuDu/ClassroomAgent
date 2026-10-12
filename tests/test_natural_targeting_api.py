"""Isolated HTTP acceptance; never import the live app with its real data directory."""
import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
from backend.config import settings
from backend.runtime import Message
from backend.tool_args import TOOLS
from backend.courses import DomainError
from test_tool_contracts import classroom
from test_course_tasks import own


class NaturalApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=patch('backend.config.ROOT',Path(self.tmp.name));self.root.start()
        sys.modules.pop('backend.app',None)
        self.module=importlib.import_module('backend.app')
        self.store=self.module.store;self.c=self.module.courses;self.runtime=self.module.runtime
        self.runtime.run=AsyncMock()
        self.a=classroom();self.b=self.a.model_copy(deep=True);self.b.id='b'
        own(self.store,self.a);own(self.store,self.b)
        self.sid=self.store.session('course')['id']
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app),base_url='http://isolated.test')
    async def asyncTearDown(self):
        await self.client.aclose();await self.runtime.close();await self.module.narration.close();await self.module.providers.close()
        self.store.close();sys.modules.pop('backend.app',None);self.root.stop();self.tmp.cleanup()
    async def send(self,body):
        result=await self.client.post(f'/api/sessions/{self.sid}/messages',json=body)
        if result.status_code==200:
            await asyncio.sleep(0)
        return result
    def idle(self):
        self.store.patch_session(self.sid,state='idle',operation=None)
    async def verify(self,run,stage='course',scene=None):
        return await self.runtime.tools.call(self.sid,run,'read-'+stage+(scene or ''),'read_stage',
            {'stageId':stage,**({'sceneId':scene} if scene else {})})

    async def test_exact_legacy_payload_replay_and_preview_navigation(self):
        body={'messageId':'old-message','text':'修改第一页','stageId':'course','targetStageIds':['course']}
        accepted=await self.send(body);self.assertEqual(accepted.status_code,200)
        await self.client.patch(f'/api/sessions/{self.sid}/active-course',json={'stageId':'b'})
        again=await self.send(body);self.assertEqual(again.json(),accepted.json())
        bad=await self.send({**body,'targetStageIds':[]});self.assertEqual(bad.json()['error']['code'],'MESSAGE_CONFLICT')
        self.assertEqual(self.runtime.run.await_count,1)
        run=self.store.get('run',accepted.json()['runId']);self.assertEqual(run['previewStageId'],'course');self.assertNotIn('courseTasks',run)

    async def test_same_name_question_refresh_answer_and_scope(self):
        first=await self.send({'messageId':'request','text':'给折射课补语音'})
        run=first.json()['runId']
        question=self.c.ask(self.sid,TOOLS['ask_user'][0].model_validate({'kind':'question','question':'昨天两页还是今天三页？',
            'requestText':'给折射课补语音','candidates':[{'stageId':'course','revision':1,'label':'昨天两页'},{'stageId':'b','revision':1,'label':'今天三页'}]}).root)
        self.runtime.context.preserve(self.sid,run);self.store.patch_session(self.sid,operation=None)
        await self.client.patch(f'/api/sessions/{self.sid}/active-course',json={'stageId':'b'})
        restored=(await self.client.get(f'/api/sessions/{self.sid}')).json()['pendingQuestion'];self.assertEqual(restored['id'],question['id'])
        answer=await self.send({'messageId':'answer','text':'昨天两页那个','questionId':question['id'],'stageId':'b'})
        self.assertEqual(answer.status_code,200);record=self.store.get('run',answer.json()['runId'])
        self.assertEqual(record['previousRequest']['text'],'给折射课补语音');self.assertEqual(record['answeredQuestion']['candidates'],restored['candidates'])
        await self.verify(record['id'],scene='s1')
        self.assertIn('course',self.store.get('run',record['id'])['runContext']['courses'])

    async def test_stale_deleted_or_foreign_candidate_stops_before_paid_call(self):
        response=await self.send({'messageId':'request','text':'给折射课补语音'});run=response.json()['runId']
        self.module.providers.generate=AsyncMock();self.module.providers.image=AsyncMock()
        self.store.put('stage','course',{**self.a.model_dump(),'revision':2})
        await self.verify(run)
        with self.assertRaises(DomainError) as e:await self.runtime.tools.call(self.sid,run,'stale','generate_scene',{'stageId':'course','expectedRevision':1,'pageId':'p1','brief':'重做'})
        self.assertEqual(e.exception.code,'REVISION_CONFLICT')
        self.store.put('course_owner','b',{'ownerId':'foreign'})
        with self.assertRaises(DomainError):await self.verify(run,stage='b')
        self.store.put('course_owner','course',{'ownerId':'local','deletedAt':'now'})
        with self.assertRaises(DomainError):await self.runtime.tools.call(self.sid,run,'deleted','generate_scene',{'stageId':'course','expectedRevision':2,'pageId':'p1','brief':'重做'})
        self.assertNotIn('courseTasks',self.store.get('run',run))
        self.module.providers.generate.assert_not_awaited();self.module.providers.image.assert_not_awaited()

    async def test_approval_creation_replay_and_prior_approval_not_scope(self):
        first=await self.send({'messageId':'plan','text':'新建一门课'})
        question=self.c.ask(self.sid,TOOLS['ask_user'][0].model_validate({'kind':'plan_approval','question':'确认新课？','plan':self.a.approvedPlan.model_dump()}).root)
        self.store.patch_session(self.sid,operation=None)
        denied=await self.client.post(f'/api/sessions/{self.sid}/messages',json={'messageId':'wrong','text':'确认','approve':True,'questionId':question['id'],'planVersion':99})
        self.assertEqual(denied.status_code,409);self.assertEqual(len(self.store.list('stage')),2)
        approval=await self.send({'messageId':'approve','text':'确认','approve':True,'questionId':question['id'],'planVersion':question['planVersion']})
        self.assertEqual(approval.status_code,200)
        new=self.c.create(self.sid,self.a.theme,question['id']);same=self.c.create(self.sid,self.a.theme,question['id'])
        self.assertEqual(new['id'],same['id']);self.assertNotEqual(new['id'],'course')
        self.assertTrue(self.store.get('run',approval.json()['runId'])['runContext']['courses'][new['id']]['fullCourse'])
        self.c.release_courses(approval.json()['runId']);self.idle()
        local=await self.send({'messageId':'local','text':'仅修改第一页','stageId':new['id']})
        record=self.store.get('run',local.json()['runId']);self.assertNotIn('courseTasks',record)
        await self.verify(record['id'],stage=new['id'])
        reused=self.c.create(self.sid,self.a.theme,question['id']);self.assertTrue(reused['reused'])
        self.assertFalse(self.store.get('run',record['id'])['runContext']['courses'][new['id']]['fullCourse'])

    async def test_course_occupancy_conflict_precedes_generation(self):
        response=await self.send({'messageId':'request','text':'重做第一页'});run=response.json()['runId']
        await self.verify(run,scene='s1');other=self.store.session('course')['id']
        self.c.claim_course(other,'course','other-run','agent');self.module.providers.generate=AsyncMock()
        with self.assertRaises(DomainError) as e:
            await self.runtime.tools.call(self.sid,run,'paid','generate_scene',{'stageId':'course','expectedRevision':1,'pageId':'p1','brief':'重做'})
        self.assertEqual(e.exception.code,'COURSE_BUSY');self.module.providers.generate.assert_not_awaited()

if __name__=='__main__':unittest.main()
