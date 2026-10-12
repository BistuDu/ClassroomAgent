import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.config import ROOT
from backend.models import Action, audio_signature, digest
from test_tool_contracts import classroom


class ClassroomApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch('backend.config.ROOT', Path(self.temp.name))
        self.patch.start()
        sys.modules.pop('backend.app', None)
        self.module = importlib.import_module('backend.app')
        await self.module.classroom_runtime.initialize()
        self.store = self.module.store
        self.stage = classroom()
        self.stage.scenes[0].actions.append(Action(id='discussion1', type='discussion', topic='为何变化', initiatorId='curious'))
        self.store.put('stage', self.stage.id, self.stage.model_dump())
        self.store.put('course_owner', self.stage.id, {'ownerId': 'local'})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app), base_url='http://isolated.test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.module.classrooms.close()
        await self.module.runtime.close()
        await self.module.narration.close()
        await self.module.providers.close()
        self.store.close()
        sys.modules.pop('backend.app', None)
        self.patch.stop()
        self.temp.cleanup()

    async def create(self, **extra):
        response = await self.client.post('/api/classrooms', json={'stageId': 'course', 'expectedRevision': 1, 'requestId': 'create', **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_restore_ownership_and_media(self):
        first = await self.create()
        same = await self.create()
        self.assertEqual(first['id'], same['id'])
        resumed = await self.create(requestId='resume-again')
        self.assertEqual(first['id'], resumed['id'])
        self.store.put('learning', first['id'], {**first, 'ownerId': 'other'})
        response = await self.client.get('/api/classrooms/' + first['id'])
        self.assertEqual(response.status_code, 403)
        self.store.put('media', 'foreign', {'id': 'foreign', 'stageId': 'course', 'ownerId': 'other', 'file': 'x.wav', 'mime': 'audio/wav'})
        response = await self.client.get('/api/media/foreign')
        self.assertEqual(response.status_code, 403)

    async def test_skip_without_model_and_progress_version_guard(self):
        session = await self.create()
        cid = session['id']
        args = {'controllerId': 'browser', 'requestId': 'start', 'kind': 'start'}
        response = await self.client.post(f'/api/classrooms/{cid}/commands', json=args)
        self.assertEqual(response.status_code, 200, response.text)
        cursor = {'sceneId': 's1', 'actionId': 'discussion1', 'playing': False}
        response = await self.client.post(f'/api/classrooms/{cid}/progress', json={'controllerId': 'browser', 'generation': 0, 'cursor': cursor, 'markerId': 'discussion1'})
        self.assertEqual(response.json()['state'], 'discussion_prompt', response.text)
        response = await self.client.post(f'/api/classrooms/{cid}/commands', json={**args, 'requestId': 'skip', 'kind': 'skip', 'markerId': 'discussion1'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['consumedDiscussions'], {'discussion1': 'skipped'})
        self.assertFalse(self.store.list('learning_op'))
        self.store.put('stage', 'course', {**self.stage.model_dump(), 'scenes': []})
        response = await self.client.post(f'/api/classrooms/{cid}/progress', json={'controllerId': 'browser', 'generation': 0, 'cursor': cursor})
        self.assertEqual(response.status_code, 409)
        response=await self.client.get(f'/api/classrooms/{cid}')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['state'],'version_conflict')

    async def test_classroom_media_pin_survives_course_changes_and_cleanup(self):
        from backend.courses import DomainError
        media_dir = Path(self.temp.name) / 'data/media'
        media_dir.mkdir(parents=True)
        (media_dir / 'retained.wav').write_bytes(b'fixture')
        self.store.put('media','retained',{'id':'retained','stageId':'course','ownerId':'local','file':'retained.wav','mime':'audio/wav'})
        session = await self.create()
        self.module.classrooms.reference_media(session['id'],'retained')
        with self.assertRaises(DomainError) as exc:
            self.store.remove_media('retained',media_dir)
        self.assertEqual(exc.exception.code,'MEDIA_REFERENCED')
        self.store.put('course_owner','course',{'ownerId':'local','deletedAt':'fixture'})
        response = await self.client.get('/api/media/retained')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.headers['cache-control'].startswith('private'))
        self.assertTrue((media_dir / 'retained.wav').is_file())

    async def test_partial_marker_patch_keeps_speech_identity_and_audio(self):
        from backend.tool_args import Patch
        from backend.models import program_fingerprint, visual_fingerprint
        # User operation exercises the actual single-page patch pipeline.
        sid = self.store.session('course')['id']
        stage = self.stage.model_copy(deep=True)
        speech = stage.scenes[0].actions[0]
        speech.audioId = 'speech-audio'
        speech.audioSignature = audio_signature(speech, stage.teacher)
        speech.audioStatus, speech.duration = 'ready', 1
        media_dir = Path(self.temp.name) / 'data' / 'media'
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / 'speech.wav').write_bytes(b'fixture')
        self.store.put('media', speech.audioId, {'id': speech.audioId, 'stageId': 'course', 'mime': 'audio/wav', 'file': 'speech.wav'})
        self.store.put('stage', 'course', stage.model_dump())
        self.store.put('course_approval', 'course', {'planHash': digest(stage.approvedPlan.model_dump())})
        self.store.patch_session(sid, state='running', runId='run')
        self.store.put('run', 'run', {'id': 'run', 'sessionId': sid, 'state': 'running', 'courseTasks': {}})
        await self.module.runtime.tools.call(sid,'run','read-current','read_stage',{'stageId':'course'})
        args = {'stageId': 'course', 'expectedRevision': 1, 'operations': [{'op': 'replace', 'target': {'sceneId': 's1', 'actionId': 'discussion1'}, 'path': '/topic', 'value': '新的讨论'}]}
        result = await self.module.runtime.tools.call(sid, 'run', 'patch', 'patch_stage', args)
        self.assertTrue(result['ok'], result)
        saved = self.module.courses.stage('course')
        self.assertEqual(saved.scenes[0].actions[0].audioId, speech.audioId)
        self.assertEqual(saved.scenes[0].actions[0].id, speech.id)
        self.assertEqual(saved.scenes[0].actions[-1].topic, '新的讨论')

    async def test_quiz_evidence_is_actual_and_classroom_scoped(self):
        from backend.models import Stage
        value = self.stage.model_dump()
        value['approvedPlan']['pages'][1]['type'] = 'quiz'
        value['scenes'][1].update(type='quiz', content={'type':'quiz', 'questions':[{'id':'q1','text':'光从空气斜着进入水会怎样？', 'options':[{'id':'a','text':'通常折射'},{'id':'b','text':'始终不拐弯'}], 'answer':'a','explanation':'在分界面发生折射。'}]})
        self.stage = Stage.model_validate(value)
        self.store.put('stage','course',self.stage.model_dump())
        session = await self.create()
        cid = session['id']
        response = await self.client.post(f'/api/classrooms/{cid}/commands', json={'controllerId':'browser','requestId':'nav','kind':'navigate','cursor':{'sceneId':'s2'}})
        self.assertEqual(response.status_code,200,response.text)
        evidence = self.module.classrooms.context(cid)
        self.assertNotIn('answer',evidence['questions'][0])
        self.assertEqual(evidence['attempt']['status'],'not_submitted')
        response = await self.client.post('/api/courses/course/quiz-attempts', json={'attemptId':'quiz1','classroomId':cid,'sceneId':'s2','revision':1,'answers':{'q1':'b'}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['results'][0]['correct'])
        self.assertEqual(self.module.classrooms.context(cid)['attempt']['results'][0]['selected'],'b')
        self.assertFalse(self.store.list('learning_op'))
        resumed = await self.create(requestId='resume-quiz')
        self.assertEqual(resumed['id'], cid)
        self.assertEqual(self.module.classrooms.context(cid)['attempt']['results'][0]['selected'], 'b')

    async def test_course_dialogue_routes_pagination_and_ownership(self):
        room=await self.create();cid=room['id'];rooms=self.module.classrooms
        first=rooms.begin_dialogue(cid,'话题一');rooms.emit(cid,'tool_start',{'name':'read_classroom_context','parameters':{}},roundId='r',toolCallId='call')
        rooms.emit(cid,'tool_end',{'name':'read_classroom_context','result':{'ok':True}},roundId='r',toolCallId='call')
        rooms.set_dialogue_status(cid,'completed','topic_complete');second=rooms.begin_dialogue(cid,'话题二')
        response=await self.client.get('/api/courses/course/classroom-dialogues?limit=1')
        self.assertEqual(response.status_code,200);page=response.json();self.assertEqual(page['items'][0]['id'],first['id']);self.assertNotIn('summary',page['items'][0])
        response=await self.client.get('/api/courses/course/classroom-dialogues',params={'cursor':page['nextCursor']})
        self.assertEqual(response.json()['items'][0]['id'],second['id'])
        response=await self.client.get('/api/classroom-dialogues/'+first['id']+'/history?limit=1')
        self.assertEqual(response.status_code,200);self.assertEqual(len(response.json()),1)
        response=await self.client.get('/api/classroom-dialogues/'+first['id']+'/tool-details?roundId=r&callId=call')
        self.assertEqual(response.json(),{'parameters':{},'result':{'ok':True}})
        self.store.put('learning_dialogue',first['id'],{**first,'ownerId':'other'})
        for endpoint in ('history','tool-details?roundId=r&callId=call'):
            response=await self.client.get('/api/classroom-dialogues/'+first['id']+'/'+endpoint)
            self.assertEqual(response.status_code,403)

    async def test_legacy_command_hash_replay(self):
        room=await self.create();cid=room['id']
        from backend.classroom_models import ClassroomCommand
        args=ClassroomCommand(requestId='old',controllerId='browser',kind='pause')
        old=args.model_dump(exclude={'confirmEnd','expectedDialogueId','expectedGeneration'})
        self.store.put('learning_request',cid+':old',{'hash':digest(old),'state':'completed'})
        response=await self.client.post(f'/api/classrooms/{cid}/commands',json=old)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['generation'],0)
        response=await self.client.post(f'/api/classrooms/{cid}/commands',json={**old,'confirmEnd':True})
        self.assertEqual(response.status_code,409)
