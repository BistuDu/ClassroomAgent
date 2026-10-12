import asyncio
from copy import deepcopy
from unittest.mock import patch
import json
import tempfile
import unittest
from pathlib import Path

from backend.classroom_models import NewClassroom, ClassroomCommand, ClassroomAck, PlaybackCursor, ClassroomProgress
from backend.classroom_runtime import ClassroomRuntime
from backend.classroom_tools import tool_schemas, available_tool_names, capability_instructions
from backend.classrooms import Classrooms
from backend.config import Settings
from backend.courses import Courses, DomainError
from backend.models import Stage, Scene, Plan, PlanPage, Teacher, digest
from backend.store import Store


class LocalSettings(Settings):
    test_dir: Path

    @property
    def data_dir(self):
        return self.test_dir


class FakeModel:
    def __init__(self, tool=False):
        self.calls = 0
        self.tool = tool
        self.requests = []
        self.tool_call = None

    async def generate(self, system, messages, tools, on_delta):
        self.calls += 1
        self.requests.append(deepcopy({'system': system, 'messages': messages, 'tools': tools}))
        if system.startswith('You are the Director of a multi-agent classroom.'):
            evidence = json.loads(messages[0]['content'])
            spoken = evidence['spokenRoleIds']
            invited = ['teacher','curious','notetaker','thinker'] if '三位同学' in evidence['question'] else ['teacher']
            selected = next((role for role in invited if role not in spoken), 'wait')
            text, calls = json.dumps({'next':selected}), []
        elif (self.tool or self.tool_call) and not any(m['role'] == 'tool' for m in messages):
            text, calls = '', [self.tool_call or {'id': 'call1', 'name': 'widget_setState',
                               'arguments': '{"sceneId":"scene1","state":{"angle":45}}',
                               'parameters': {'sceneId': 'scene1', 'state': {'angle': 45}}}]
        else:
            text, calls = '光进入水中会发生折射。', []
        if text:
            on_delta(text[:3])
            on_delta(text[3:])
        return {'text': text, 'calls': calls, 'usage': {}, 'finishReason': 'stop'}

    async def close(self):
        pass


class FakeTTS:
    def __init__(self, store):
        self.store, self.calls = store, 0

    async def tts(self, stage_id, text, teacher, signature, **kwargs):
        self.calls += 1
        media = {'id': 'audio' + str(self.calls), 'stageId': stage_id,
                 'ownerId': 'local', 'mime': 'audio/wav', 'duration': 1, 'file': 'test.wav'}
        self.store.put('media', media['id'], media)
        return media


class ToolPolicyTests(unittest.TestCase):
    def test_exact_role_page_matrix_and_independent_schemas(self):
        expected = {
            'slide': ('spotlight', 'laser'),
            'interactive': ('widget_setState', 'widget_highlight',
                            'widget_annotation', 'widget_reveal'),
            'quiz': (), 'unknown': (),
        }
        for role in ('teacher', 'curious', 'notetaker', 'thinker', 'director', 'unknown'):
            for page in expected:
                with self.subTest(role=role, page=page):
                    names = expected[page] if role == 'teacher' else ()
                    self.assertEqual(available_tool_names(role, page), names)
                    self.assertEqual(tuple(t['name'] for t in tool_schemas(role, page)), names)
        schemas = tool_schemas('teacher', 'interactive')
        schemas[0]['parameters']['properties']['leak'] = {'type': 'string'}
        schemas[0]['parameters']['properties']['state']['type'] = 'string'
        schemas[0]['parameters']['required'].clear()
        fresh = tool_schemas('teacher', 'interactive')
        self.assertNotIn('leak', fresh[0]['parameters']['properties'])
        self.assertEqual(fresh[0]['parameters']['properties']['state'], {'type': 'object'})
        self.assertEqual(fresh[0]['parameters']['required'], ['sceneId', 'state'])

    def test_six_tool_contracts_and_pointer_alignment(self):
        definitions = [
            ('spotlight', '聚光突出幻灯片元素', {'elementId': {'type': 'string'}}),
            ('laser', '激光指示幻灯片元素', {'elementId': {'type': 'string'}}),
            ('widget_setState', '设置当前实验参数并读取真实观察', {'state': {'type': 'object'}}),
            ('widget_highlight', '突出实验控件', {'target': {'type': 'string'}}),
            ('widget_annotation', '添加临时实验注释', {'target': {'type': 'string'}, 'content': {'type': 'string'}}),
            ('widget_reveal', '显示实验声明内容', {'target': {'type': 'string'}}),
        ]
        actual = {t['name']: t for page in ('slide', 'interactive', 'quiz') for t in tool_schemas('teacher', page)}
        for name, description, fields in definitions:
            properties = {'sceneId': {'type': 'string'}, **fields} if name.startswith('widget_') else fields
            self.assertEqual(actual[name], {'name': name, 'description': description, 'parameters': {
                'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}})
        for page in ('slide', 'interactive', 'quiz'):
            tools = tool_schemas('teacher', page)
            prompt = capability_instructions(tools)
            for name, _, _ in definitions:
                self.assertEqual(name in prompt, name in available_tool_names('teacher', page))
        self.assertNotIn('实验', capability_instructions(tool_schemas('teacher', 'quiz')))


class ClassroomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = LocalSettings(_env_file=None, test_dir=Path(self.temp.name))
        self.store = Store(Path(self.temp.name) / 'store.sqlite3')
        self.courses = Courses(self.store)
        page = PlanPage(id='slot1', title='实验', type='interactive', brief='折射')
        scene = Scene(id='scene1', planPageId=page.id, title=page.title, brief=page.brief, type=page.type,
            content={'type': 'interactive', 'html': '<html><script>window.openmaicSimulation={};</script>' + ' ' * 100 + '</html>',
                     'variables': [{'name': 'angle', 'label': '角度', 'min': 0, 'max': 80, 'default': 30, 'selector': '#angle'}],
                     'initialState': {'angle': 30}, 'presets': [{'name': 'A', 'state': {'angle': 30}}, {'name': 'B', 'state': {'angle': 45}}],
                     'controls': ['#angle']},
            actions=[{'id': 'speech1', 'type': 'speech', 'text': '原讲稿'},
                     {'id': 'discussion1', 'type': 'discussion', 'topic': '为何弯折', 'initiatorId': 'curious'}])
        self.stage = Stage(id='stage1', title='折射', approvedPlan=Plan(title='折射', audience='初中', objectives=['理解折射'], pages=[page]),
                           teacher=Teacher(model='qwen3-tts-flash', voice='Cherry'), scenes=[scene])
        self.store.put('stage', self.stage.id, self.stage.model_dump())
        self.store.put('course_owner', self.stage.id, {'ownerId': 'local'})
        self.tts = FakeTTS(self.store)
        self.rooms = Classrooms(self.store, self.courses, self.tts, self.config)
        self.model = FakeModel()
        self.runtime = ClassroomRuntime(self.rooms, self.model)
        await self.runtime.initialize()
        self.session = self.rooms.create(NewClassroom(stageId='stage1', expectedRevision=1, requestId='create'))
        self.cid = self.session['id']

    async def asyncTearDown(self):
        await self.runtime.close()
        self.store.close()
        self.temp.cleanup()

    async def state(self, expected):
        for _ in range(100):
            session = self.rooms.get(self.cid)
            if session['state'] == expected:
                # The business waiting flag precedes LangGraph's durable
                # interrupt/checkpoint. Test commands resume only after that
                # boundary, so teardown cannot close an in-flight saver.
                task = self.runtime.tasks.get(self.cid)
                if task is not None:
                    await asyncio.wait_for(asyncio.shield(task), 2)
                return session
            if session['state'] == 'interrupted':
                self.fail(session['error'])
            await asyncio.sleep(.02)
        self.fail(f'等待 {expected} 超时: {self.rooms.get(self.cid)}')

    def command(self, kind, **kwargs):
        return ClassroomCommand(requestId=kind + str(self.model.calls), controllerId='browser', kind=kind, **kwargs)

    async def answer_audio(self):
        session = await self.state('waiting_audio')
        pending = session['pending']
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'],
            operationId=pending['operationId'], sceneId='scene1', status='completed', result={'ended': True}))
        return await self.state('waiting_user')

    def add_test_pages(self):
        stage = self.stage.model_dump()
        for scene_id, page_type, content in (
            ('slide1', 'slide', {'type': 'slide', 'elements': [
                {'id': 'title', 'type': 'text', 'x': 20, 'y': 20, 'width': 300, 'height': 80, 'text': '折射'}]}),
            ('quiz1', 'quiz', {'type': 'quiz', 'questions': [
                {'id': 'q1', 'text': '以下哪个描述符合折射？', 'options': [
                    {'id': 'A', 'text': '说法一'}, {'id': 'B', 'text': '说法二'}],
                 'answer': 'B', 'explanation': '仅提交后可读的解析'}]}),
        ):
            page = PlanPage(id='slot-' + scene_id, title=page_type, type=page_type, brief='折射')
            stage['approvedPlan']['pages'].append(page.model_dump())
            stage['scenes'].append(Scene(id=scene_id, planPageId=page.id, title=page.title,
                brief=page.brief, type=page_type, content=content).model_dump())
        self.stage = Stage.model_validate(stage)
        self.store.put('stage', self.stage.id, self.stage.model_dump())
        self.session = self.rooms.create(NewClassroom(stageId='stage1', expectedRevision=1, requestId='pages'))
        self.cid = self.session['id']

    def actor_state(self, actor='teacher', scene_id='scene1', suffix=''):
        session = self.rooms.get(self.cid)
        round_id = 'controlled-' + actor + '-' + scene_id + suffix
        self.rooms.update(self.cid, roundId=round_id, cursor={**session['cursor'], 'sceneId': scene_id})
        return {'classroomId': self.cid, 'roundId': round_id, 'generation': session['generation'],
                'question': '请解释当前页', 'initiator': '', 'actor': actor, 'count': 0,
                'toolCount': 0, 'modelCount': 0, 'spent': 0, 'messages': [], 'history': [],
                'result': {}, 'callIndex': 0, 'chunks': [], 'chunkIndex': 0, 'pendingId': '', 'messageId': ''}

    async def test_question_audio_wait_and_followup(self):
        cursor = PlaybackCursor(sceneId='scene1', actionId='speech1', experimentState={'angle': 30}, instanceId='frame')
        original = self.store.get('stage', 'stage1')
        await self.rooms.command(self.cid, self.command('question', text='为什么弯折？', cursor=cursor))
        await self.answer_audio()
        self.assertEqual(self.tts.calls, 1)
        self.assertEqual(self.store.get('stage', 'stage1'), original)
        await self.rooms.command(self.cid, self.command('question', text='再解释一次', cursor=cursor))
        await self.answer_audio()
        self.assertEqual(self.tts.calls, 2)
        messages = [e for e in self.rooms.events(self.cid) if e['kind'] == 'message_end']
        self.assertEqual(len(messages), 2)

    async def test_tool_actual_receipt_and_resume(self):
        self.model.tool = True
        cursor = PlaybackCursor(sceneId='scene1', actionId='speech1', experimentState={'angle': 30}, instanceId='frame')
        await self.rooms.command(self.cid, self.command('question', text='演示变化', cursor=cursor))
        session = await self.state('waiting_tool')
        self.assertEqual(self.tts.calls, 0)
        self.assertFalse(any(e['kind'] == 'tool_end' for e in self.rooms.events(self.cid)))
        pending = session['pending']
        args = ClassroomAck(controllerId='browser', generation=session['generation'], operationId=pending['operationId'],
                            sceneId='scene1', instanceId='frame', status='completed', result={'state': {'angle': 45}, 'observation': '折射角变化'})
        await self.rooms.ack(self.cid, args)
        await self.answer_audio()
        actor_requests = [r for r in self.model.requests if not r['system'].startswith('You are the Director of a multi-agent classroom.')]
        self.assertEqual(len(actor_requests), 2)
        for request in actor_requests:
            self.assertEqual(tuple(t['name'] for t in request['tools']), available_tool_names('teacher', 'interactive'))
            self.assertNotIn('spotlight', request['system'])
        self.assertTrue(any(m['role'] == 'tool' for m in actor_requests[1]['messages']))
        marker = '# Automatically supplied classroom evidence\n'
        evidence = json.loads(actor_requests[1]['system'].split(marker)[1])
        self.assertEqual(evidence['observed']['state'], {'angle':45})
        self.assertEqual(evidence['observed']['observation'], '折射角变化')
        self.assertEqual(actor_requests[1]['system'].count(marker), 1)
        self.assertFalse(any((m.get('content') or '').startswith('当前页真实证据：') for m in actor_requests[1]['messages']))
        before = self.model.calls
        await self.rooms.ack(self.cid, args)
        self.assertEqual(self.model.calls, before)
        await self.rooms.command(self.cid, self.command('continue'))
        session = self.rooms.get(self.cid)
        self.assertEqual(session['pending']['kind'], 'restore')
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'],
            operationId=session['pending']['operationId'], sceneId='scene1', instanceId='frame',
            status='completed', result={'restored': True}))
        self.assertEqual(self.rooms.get(self.cid)['state'], 'lecture')
        self.assertEqual(self.rooms.get(self.cid)['cursor']['experimentState'], {'angle': 30})

    async def test_isolation_replay_and_unknown(self):
        args = self.command('start')
        await self.rooms.command(self.cid, args)
        await self.rooms.command(self.cid, args)
        with self.assertRaises(DomainError):
            await self.rooms.command(self.cid, args.model_copy(update={'text': 'changed'}))
        with self.assertRaises(DomainError):
            self.rooms.lease(self.cid, 'other-browser')
        with self.assertRaises(DomainError):
            self.rooms.validate_tool(self.cid, 'curious', 'widget_setState', {'sceneId': 'scene1', 'state': {'angle': 45}})
        op = self.rooms.operation(self.cid, 'paid', 'tts', {'text': 'test'})
        self.rooms.finish_op(op, 'running')
        await self.runtime.close()
        self.runtime = ClassroomRuntime(self.rooms, FakeModel())
        await self.runtime.initialize()
        self.assertEqual(self.store.get('learning_op', op['id'])['state'], 'unknown')
        self.assertEqual(self.rooms.get(self.cid)['state'], 'interrupted')
        self.store.owner_id = 'other'
        with self.assertRaises(DomainError):
            self.rooms.get(self.cid)
        self.store.owner_id = 'local'

    async def test_discussion_consumption_and_cancelled_receipt(self):
        cursor = PlaybackCursor(sceneId='scene1', actionId='discussion1', experimentState={'angle':30}, instanceId='frame')
        await self.rooms.command(self.cid, self.command('start'))
        self.rooms.progress(self.cid, ClassroomProgress(controllerId='browser', generation=0, cursor=cursor, markerId='discussion1'))
        self.assertEqual(self.model.calls, 0)
        await self.rooms.command(self.cid, self.command('join', markerId='discussion1', cursor=cursor))
        session = await self.state('waiting_audio')
        pending = session['pending']
        self.assertEqual(self.rooms.get(self.cid)['consumedDiscussions']['discussion1'], 'joined')
        dialogue = self.rooms.dialogue(session['activeDialogueId'])
        self.assertEqual(dialogue['type'], 'discussion')
        self.assertEqual(dialogue['sourceClassroomId'], self.cid)
        await self.rooms.command(self.cid, self.command('stop', cursor=cursor))
        with self.assertRaises(DomainError):
            await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'], operationId=pending['operationId'], sceneId='scene1', status='completed', result={'ended':True}))
        self.assertEqual(self.store.get('learning_op', pending['operationId'])['state'], 'cancelled')
        self.assertEqual(self.rooms.get(self.cid)['state'], 'paused')

    async def test_failed_tts_explicit_text_only_and_cached_replay(self):
        from backend.courses import fail
        original = self.tts.tts
        async def broken(*args, **kwargs):
            fail('PROVIDER_HTTP', 'HTTP 503')
        self.tts.tts = broken
        cursor = PlaybackCursor(sceneId='scene1', experimentState={'angle':30}, instanceId='frame')
        await self.rooms.command(self.cid, self.command('question', text='说明折射', cursor=cursor))
        session = await self.state('audio_error')
        await self.rooms.command(self.cid, self.command('text_only'))
        await self.state('waiting_user')
        self.assertEqual(self.store.get('learning_op', session['pending']['operationId'])['result']['status'], 'text_only')
        self.tts.tts = original
        await self.rooms.command(self.cid, self.command('question', text='再说一次', cursor=cursor))
        session = await self.state('waiting_audio')
        p = session['pending']
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'], operationId=p['operationId'], sceneId='scene1', status='failed', result={'error':'NotAllowedError'}))
        before = self.tts.calls
        await self.rooms.command(self.cid, self.command('retry_audio'))
        self.assertEqual(self.tts.calls, before)
        await self.answer_audio()

    async def test_checkpoint_restart_rebind_and_context_budget(self):
        self.model.tool = True
        cursor = PlaybackCursor(sceneId='scene1', actionId='speech1', experimentState={'angle':30}, instanceId='old')
        await self.rooms.command(self.cid, self.command('question', text='演示', cursor=cursor))
        await self.state('waiting_tool')
        await self.runtime.close()
        self.runtime = ClassroomRuntime(self.rooms, self.model)
        await self.runtime.initialize()
        self.assertEqual(self.rooms.get(self.cid)['state'], 'interrupted')
        await self.rooms.command(self.cid, self.command('resume_interaction', cursor=cursor.model_copy(update={'instanceId':'new'})))
        session = self.rooms.get(self.cid)
        p = session['pending']
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'], operationId=p['operationId'], sceneId='scene1', instanceId='new', status='completed', result={'state':{'angle':45}}))
        await self.answer_audio()
        for i in range(90):
            self.rooms.emit(self.cid, 'message_end', {'text': '较早发言' * 1500}, speakerId='teacher', messageId=str(i))
        history = self.runtime.bounded_history(self.cid)
        self.assertLess(len(json.dumps(history, ensure_ascii=False).encode()) // 2, self.config.classroom_context_tokens)
        self.assertTrue(self.rooms.dialogue(self.rooms.get(self.cid)['activeDialogueId'])['summary'])
        self.assertGreater(len(self.rooms.events(self.cid, limit=500)), 90)

    async def test_intent_checkpoint_gap_and_role_history(self):
        self.model.tool = True
        cursor = PlaybackCursor(sceneId='scene1', actionId='speech1', experimentState={'angle':30}, instanceId='old')
        await self.rooms.command(self.cid, self.command('question',text='演示',cursor=cursor))
        session = await self.state('waiting_tool')
        await asyncio.sleep(.05)
        snapshot = await self.runtime.graph.aget_state(self.runtime.graph_config(self.cid))
        # Simulate a checkpoint written before prepare_tool, while business intent
        # survived. Re-execution must reuse its ID/hash across browser refresh.
        await self.runtime.graph.aupdate_state(self.runtime.graph_config(self.cid), snapshot.values, as_node='actor')
        original = self.store.get('learning_op',session['pending']['operationId'])
        await self.runtime.close()
        self.runtime = ClassroomRuntime(self.rooms,self.model)
        await self.runtime.initialize()
        await self.rooms.command(self.cid,self.command('resume_interaction',cursor=cursor.model_copy(update={'instanceId':'new'})))
        session = await self.state('waiting_tool')
        pending = session['pending']
        self.assertEqual(pending['operationId'],original['id'])
        self.assertEqual(self.store.get('learning_op',original['id'])['requestHash'],original['requestHash'])
        await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=session['generation'],operationId=pending['operationId'],sceneId='scene1',instanceId='new',status='completed',result={'state':{'angle':45}}))
        await self.answer_audio()
        history = self.runtime.bounded_history(self.cid)
        self.assertTrue(all(m['role']=='user' for m in history))
        self.assertEqual(self.rooms.context(self.cid)['observed']['state']['angle'],45)

    async def test_audio_completion_requires_actual_ended(self):
        cursor = PlaybackCursor(sceneId='scene1',experimentState={'angle':30},instanceId='frame')
        await self.rooms.command(self.cid,self.command('question',text='解释',cursor=cursor))
        session = await self.state('waiting_audio')
        pending = session['pending']
        with self.assertRaises(DomainError):
            await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=session['generation'],operationId=pending['operationId'],sceneId='scene1',status='completed'))
        self.assertEqual(self.store.get('learning_op',pending['operationId'])['state'],'pending')
        await self.answer_audio()

    async def test_explicit_invitation_reaches_three_independent_students(self):
        cursor = PlaybackCursor(sceneId='scene1',experimentState={'angle':30},instanceId='frame')
        await self.rooms.command(self.cid,self.command('question',text='请三位同学各自分享观察',cursor=cursor))
        speakers=[]
        for _ in range(4):
            session=await self.state('waiting_audio')
            p=session['pending'];speakers.append(p['speakerId'])
            await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=session['generation'],operationId=p['operationId'],sceneId='scene1',status='completed',result={'ended':True}))
            await asyncio.sleep(.05)
        await self.state('waiting_user')
        self.assertEqual(speakers,['teacher','curious','notetaker','thinker'])
        self.assertEqual(self.tts.calls,4)

    async def test_completed_model_and_tts_replay_checkpoint_gap(self):
        cursor=PlaybackCursor(sceneId='scene1',experimentState={'angle':30},instanceId='old')
        await self.rooms.command(self.cid,self.command('question',text='解释折射',cursor=cursor))
        session=await self.state('waiting_audio');await asyncio.sleep(.05)
        pending_id=session['pending']['operationId']
        snapshot=await self.runtime.graph.aget_state(self.runtime.graph_config(self.cid))
        model_id = self.cid + ':' + session['roundId'] + ':actor:0'
        legacy = self.store.get('learning_op', model_id)
        legacy['arguments'].pop('toolPolicy')
        legacy['arguments']['system'] += '可用聚光/激光和实验工具。'
        legacy['requestHash'] = digest(legacy['arguments'])
        self.store.put('learning_op', model_id, legacy)
        previous={**snapshot.values,'modelCount':0,'count':0,'messages':[],'result':{},'chunks':[],'chunkIndex':0,'history':[],'pendingId':''}
        await self.runtime.graph.aupdate_state(self.runtime.graph_config(self.cid),previous,as_node='director')
        self.rooms.update(self.cid,pending=None)
        await self.runtime.close()
        self.runtime=ClassroomRuntime(self.rooms,self.model);await self.runtime.initialize()
        before=(self.model.calls,self.tts.calls)
        await self.rooms.command(self.cid,self.command('resume_interaction',cursor=cursor.model_copy(update={'instanceId':'new'})))
        session=await self.state('waiting_audio')
        self.assertEqual(session['pending']['operationId'],pending_id)
        self.assertEqual((self.model.calls,self.tts.calls),before)
        self.assertEqual(self.store.get('learning_op', model_id)['requestHash'], legacy['requestHash'])
        self.assertEqual(self.store.get('learning_op', model_id)['arguments'], legacy['arguments'])
        await self.answer_audio()

    async def test_explicit_natural_continue_rebinds_restored_browser(self):
        cursor=PlaybackCursor(sceneId='scene1',experimentState={'angle':30},instanceId='old')
        await self.rooms.command(self.cid,self.command('question',text='解释',cursor=cursor))
        await self.answer_audio()
        before=self.model.calls
        await self.rooms.command(self.cid,self.command('question',text='明白了，继续讲课',cursor=cursor.model_copy(update={'instanceId':'new'})))
        session=self.rooms.get(self.cid)
        self.assertEqual(session['pending']['kind'],'restore')
        self.assertEqual(session['pending']['instanceId'],'new')
        self.assertEqual(self.model.calls,before)

    async def test_actual_actor_requests_follow_server_role_and_page(self):
        self.add_test_pages()
        for role in ('teacher', 'curious', 'notetaker', 'thinker'):
            for scene_id, page_type in (('slide1', 'slide'), ('scene1', 'interactive'), ('quiz1', 'quiz')):
                with self.subTest(role=role, page=page_type):
                    state = self.actor_state(role, scene_id)
                    with patch.object(self.runtime, 'write'):
                        await self.runtime.actor(state)
                    request = self.model.requests[-1]
                    self.assertEqual(request['tools'], tool_schemas(role, page_type))
                    instructions = capability_instructions(request['tools'])
                    self.assertIn(instructions, request['system'])
                    for name in available_tool_names('teacher', 'interactive') + ('spotlight', 'laser'):
                        self.assertEqual(name in request['system'], name in available_tool_names(role, page_type))
                    if role == 'teacher' and page_type == 'quiz':
                        self.assertNotIn('可用聚光/激光和实验工具', request['system'])
                    op = self.store.get('learning_op', self.cid + ':' + state['roundId'] + ':actor:0')
                    self.assertEqual(op['arguments']['toolPolicy']['tools'], request['tools'])
        state = self.actor_state('teacher', 'quiz1', '-unknown-page')
        with patch.object(self.rooms, 'context', return_value={'sceneId': 'quiz1', 'type': 'unknown'}), patch.object(self.runtime, 'write'):
            await self.runtime.actor(state)
        self.assertEqual(self.model.requests[-1]['tools'], [])
        before = self.model.calls
        with self.assertRaises(DomainError) as exc:
            await self.runtime.actor(self.actor_state('unknown'))
        self.assertEqual(exc.exception.code, 'CLASSROOM_TOOL_ROLE')
        self.assertEqual(self.model.calls, before)
        state = self.actor_state('teacher', 'quiz1', '-director')
        state['count'] = 1
        with patch.object(self.runtime, 'write'):
            await self.runtime.director(state)
        self.assertEqual(self.model.requests[-1]['tools'], [])

    async def test_quiz_illegal_widget_call_is_recorded_and_returned_without_delivery(self):
        self.add_test_pages()
        await self.rooms.command(self.cid, self.command('navigate', cursor=PlaybackCursor(sceneId='quiz1'),confirmEnd=True,expectedDialogueId=self.rooms.get(self.cid)['activeDialogueId'],expectedGeneration=self.rooms.get(self.cid)['generation']))
        original = self.store.get('stage', 'stage1')
        for target in ('quiz1', 'scene1'):
            self.model.tool_call = {'id': 'call-' + target, 'name': 'widget_setState',
                'arguments': json.dumps({'sceneId': target, 'state': {'angle': 45}}),
                'parameters': {'sceneId': target, 'state': {'angle': 45}}}
            await self.rooms.command(self.cid, self.command('question', text='调整实验', cursor=PlaybackCursor(sceneId='quiz1')))
            session = await self.state('waiting_audio')
            round_id = session['roundId']
            events = [e for e in self.rooms.events(self.cid) if e['roundId'] == round_id]
            self.assertTrue(any(e['kind'] == 'tool_start' and e['data']['parameters']['sceneId'] == target for e in events))
            end = next(e for e in events if e['kind'] == 'tool_end')
            self.assertFalse(end['data']['result']['ok'])
            self.assertIn('工具', end['data']['result']['error'])
            self.assertFalse(any(e['kind'] == 'execution_pending' for e in events))
            self.assertFalse(any(o['kind'] == 'tool' and o['roundId'] == round_id for o in self.store.list('learning_op')))
            followup = self.model.requests[-1]
            self.assertEqual(followup['tools'], tool_schemas('teacher', 'quiz'))
            feedback = next(m for m in followup['messages'] if m['role'] == 'tool')
            self.assertEqual(json.loads(feedback['content']), end['data']['result'])
            await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'],
                operationId=session['pending']['operationId'], sceneId='quiz1', status='completed', result={'ended': True}))
            await self.state('waiting_user')
        self.assertEqual(self.store.get('stage', 'stage1'), original)
        context = self.rooms.context(self.cid)
        with self.assertRaises(DomainError):
            self.rooms.validate_tool(self.cid, 'teacher', 'read_classroom_context', {})
        self.assertEqual(context['attempt'], {'status': 'not_submitted'})
        self.assertNotIn('answer', context['questions'][0])
        self.assertNotIn('explanation', context['questions'][0])

    async def test_invalid_tool_targets_produce_feedback_without_browser_delivery(self):
        self.add_test_pages()
        original = self.store.get('stage', 'stage1')
        invalid = [
            ('slide1', 'spotlight', {'elementId': 'missing'}),
            ('slide1', 'laser', {'sceneId': 'scene1', 'elementId': 'title'}),
            ('scene1', 'widget_setState', {'sceneId': 'scene1', 'state': {'angle': 999}}),
            ('scene1', 'widget_setState', {'sceneId': 'scene1', 'state': {'unknown': 45}}),
            ('scene1', 'widget_highlight', {'sceneId': 'scene1', 'target': '#missing'}),
            ('scene1', 'widget_reveal', {'sceneId': 'scene1', 'target': '#missing'}),
            ('scene1', 'widget_annotation', {'sceneId': 'scene1', 'target': '#angle', 'content': '注' * 501}),
            ('scene1', 'widget_annotation', {'sceneId': 'scene1', 'target': '#missing', 'content': '注'}),
            ('scene1', 'read_classroom_context', {'extra': True}),
            ('scene1', 'widget_setState', {'sceneId': 'scene1'}),
            ('scene1', 'invented_tool', {'sceneId': 'scene1'}),
        ]
        for i, (scene_id, name, parameters) in enumerate(invalid):
            with self.subTest(name=name, parameters=parameters):
                state = self.actor_state(scene_id=scene_id, suffix=str(i))
                self.model.tool_call = {'id': 'bad', 'name': name, 'parameters': parameters, 'arguments': json.dumps(parameters)}
                with patch.object(self.runtime, 'write'):
                    state.update(await self.runtime.actor(state))
                with patch.object(self.runtime, 'write') as events:
                    result = await self.runtime.prepare_tool(state)
                self.assertFalse(result['pendingId'])
                feedback = json.loads(result['messages'][-1]['content'])
                self.assertFalse(feedback['ok'])
                self.assertTrue(feedback['error'])
                self.assertEqual([c.args[0] for c in events.call_args_list], ['tool_start', 'tool_end'])
        # Presence in a page matrix is never proof of role authorization.
        with self.assertRaises(DomainError):
            self.rooms.validate_tool(self.cid, 'curious', 'read_classroom_context', {})
        self.assertFalse(any(o['kind'] == 'tool' for o in self.store.list('learning_op')))
        self.assertEqual(self.store.get('stage', 'stage1'), original)

    async def test_actual_failed_receipt_reaches_actor_without_success_observation(self):
        self.model.tool = True
        original = self.store.get('stage', 'stage1')
        await self.rooms.command(self.cid, self.command('question', text='演示', cursor=PlaybackCursor(
            sceneId='scene1', experimentState={'angle': 30}, instanceId='frame')))
        session = await self.state('waiting_tool')
        op_id = session['pending']['operationId']
        self.assertEqual(self.store.get('learning_op', op_id)['state'], 'pending')
        self.assertFalse(any(e['kind'] == 'tool_end' for e in self.rooms.events(self.cid)))
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'],
            operationId=op_id, sceneId='scene1', instanceId='frame', status='failed', result={'error': '控件未就绪'}))
        await self.answer_audio()
        feedback = next(m for m in self.model.requests[-2]['messages'] if m['role'] == 'tool')
        self.assertEqual(json.loads(feedback['content']), {'ok': False, 'status': 'failed', 'observation': {'error': '控件未就绪'}})
        self.assertEqual(self.store.get('learning_op', op_id)['state'], 'failed')
        self.assertIsNone(self.rooms.get(self.cid)['lastObservation'])
        self.assertEqual(self.rooms.get(self.cid)['cursor']['experimentState'], {'angle': 30})
        self.assertEqual(self.store.get('stage', 'stage1'), original)

    async def test_navigation_recomputes_tools_and_rejects_old_calls_and_ack(self):
        self.add_test_pages()
        self.model.tool = True
        await self.rooms.command(self.cid, self.command('question', text='演示', cursor=PlaybackCursor(
            sceneId='scene1', experimentState={'angle': 30}, instanceId='frame')))
        session = await self.state('waiting_tool')
        old_pending = session['pending']
        old_state = (await self.runtime.graph.aget_state(self.runtime.graph_config(self.cid))).values
        old_generation = session['generation']
        await self.rooms.command(self.cid, self.command('navigate', cursor=PlaybackCursor(sceneId='quiz1'),confirmEnd=True,expectedDialogueId=self.rooms.get(self.cid)['activeDialogueId'],expectedGeneration=self.rooms.get(self.cid)['generation']))
        with self.assertRaises(DomainError) as exc:
            await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=old_generation,
                operationId=old_pending['operationId'], sceneId='scene1', instanceId='frame',
                status='completed', result={'state': {'angle': 45}}))
        self.assertEqual(exc.exception.code, 'CLASSROOM_STALE')
        with patch.object(self.runtime, 'write') as events:
            with self.assertRaises(DomainError) as exc:
                await self.runtime.prepare_tool(old_state)
            self.assertEqual(exc.exception.code, 'CLASSROOM_STALE')
            events.assert_not_called()
        self.assertEqual(self.store.get('learning_op', old_pending['operationId'])['state'], 'cancelled')
        self.model.tool = False
        await self.rooms.command(self.cid, self.command('question', text='这道题什么意思', cursor=PlaybackCursor(sceneId='quiz1')))
        session = await self.state('waiting_audio')
        request = self.model.requests[-1]
        self.assertEqual(request['tools'], tool_schemas('teacher', 'quiz'))
        self.assertNotIn('widget_', request['system'])
        context = json.loads(request['system'].split('# Automatically supplied classroom evidence\n', 1)[1])
        self.assertEqual(context['attempt']['status'], 'not_submitted')
        self.assertNotIn('answer', context['questions'][0])
        self.assertIsNone(self.rooms.get(self.cid)['lastObservation'])
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=session['generation'],
            operationId=session['pending']['operationId'], sceneId='quiz1', status='completed', result={'ended': True}))
        await self.state('waiting_user')

    async def test_legacy_pending_and_unknown_intent_are_preserved_without_retry(self):
        for status in ('pending', 'unknown', 'running', 'failed'):
            state = self.actor_state(suffix='-legacy-' + status)
            args = {'system': '可用聚光/激光和实验工具', 'messages': [{'role': 'user', 'content': '旧问题'}], 'actor': 'teacher'}
            op = self.rooms.operation(self.cid, state['roundId'] + ':actor:0', 'model', args)
            if status != 'pending':
                self.rooms.finish_op(op, status, {'error': '旧操作结果不明'})
            saved = self.store.get('learning_op', op['id'])
            before = (self.model.calls, self.tts.calls)
            with patch.object(self.runtime, 'write'):
                with self.assertRaises(DomainError) as exc:
                    await self.runtime.actor(state)
            self.assertEqual(exc.exception.code, 'CLASSROOM_TOOL_POLICY' if status == 'pending' else 'CLASSROOM_UNCERTAIN')
            self.assertEqual(self.store.get('learning_op', op['id']), saved)
            self.assertEqual((self.model.calls, self.tts.calls), before)
        # The user can explicitly start a fresh question, with the current policy.
        state = self.actor_state(suffix='-fresh')
        with patch.object(self.runtime, 'write'):
            await self.runtime.actor(state)
        self.assertEqual(self.model.requests[-1]['tools'], tool_schemas('teacher', 'interactive'))

    async def test_completed_legacy_effect_replay_preserves_hash_without_redelivery(self):
        state = self.actor_state()
        call = {'id': 'legacy', 'name': 'widget_setState', 'parameters': {'sceneId': 'scene1', 'state': {'angle': 45}}}
        state.update(result={'calls': [call]}, messageId='old-message')
        arguments = {'name': call['name'], 'parameters': call['parameters'], 'sceneId': 'scene1', 'instanceId': 'old-frame',
                     'speakerId': 'teacher', 'toolCallId': call['id'], 'messageId': state['messageId']}
        op = self.rooms.operation(self.cid, state['roundId'] + ':tool:legacy', 'tool', arguments)
        self.rooms.finish_op(op, 'completed', {'status': 'completed', 'result': {'state': {'angle': 45}}})
        saved = self.store.get('learning_op', op['id'])
        with patch.object(self.runtime, 'write') as events:
            result = await self.runtime.prepare_tool(state)
        self.assertEqual([c.args[0] for c in events.call_args_list], ['tool_start', 'tool_end'])
        self.assertFalse(result['pendingId'])
        self.assertTrue(json.loads(result['messages'][-1]['content'])['ok'])
        self.assertEqual(self.store.get('learning_op', op['id']), saved)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.tts.calls, 0)

    async def test_new_pending_model_intent_resumes_with_matching_policy(self):
        state = self.actor_state(suffix='-new-pending')
        with patch.object(self.runtime, 'write'):
            await self.runtime.actor(state)
        op_id = self.cid + ':' + state['roundId'] + ':actor:0'
        saved = self.store.get('learning_op', op_id)
        self.rooms.finish_op(saved, 'pending')
        before = self.model.calls
        with patch.object(self.runtime, 'write'):
            await self.runtime.actor(state)
        replayed = self.store.get('learning_op', op_id)
        self.assertEqual(self.model.calls, before + 1)
        self.assertEqual(replayed['arguments'], saved['arguments'])
        self.assertEqual(replayed['requestHash'], saved['requestHash'])
        self.assertEqual(self.model.requests[-1]['tools'], saved['arguments']['toolPolicy']['tools'])
        # A pending intent for a different capability set cannot be widened.
        changed = deepcopy(replayed)
        changed['state'] = 'pending'
        changed['arguments']['toolPolicy']['tools'] = tool_schemas('teacher', 'slide')
        changed['requestHash'] = digest(changed['arguments'])
        self.store.put('learning_op', op_id, changed)
        before = self.model.calls
        with patch.object(self.runtime, 'write'):
            with self.assertRaises(DomainError) as exc:
                await self.runtime.actor(state)
        self.assertEqual(exc.exception.code, 'CLASSROOM_TOOL_POLICY')
        self.assertEqual(self.store.get('learning_op', op_id), changed)
        self.assertEqual(self.model.calls, before)

    async def test_legacy_pending_recovery_interrupts_and_keeps_history(self):
        await self.rooms.command(self.cid, self.command('question', text='解释', cursor=PlaybackCursor(sceneId='scene1')))
        session = await self.state('waiting_audio')
        snapshot = await self.runtime.graph.aget_state(self.runtime.graph_config(self.cid))
        model_id = self.cid + ':' + session['roundId'] + ':actor:0'
        legacy = self.store.get('learning_op', model_id)
        legacy['arguments'].pop('toolPolicy')
        legacy['requestHash'] = digest(legacy['arguments'])
        legacy['state'], legacy['result'] = 'pending', None
        self.store.put('learning_op', model_id, legacy)
        previous = {**snapshot.values, 'modelCount': 0, 'count': 0, 'messages': [], 'result': {},
                    'chunks': [], 'chunkIndex': 0, 'history': [], 'pendingId': ''}
        await self.runtime.graph.aupdate_state(self.runtime.graph_config(self.cid), previous, as_node='director')
        self.rooms.update(self.cid, pending=None)
        await self.runtime.close()
        self.runtime = ClassroomRuntime(self.rooms, self.model)
        await self.runtime.initialize()
        before = (self.model.calls, self.tts.calls)
        await self.rooms.command(self.cid, self.command('resume_interaction', cursor=PlaybackCursor(sceneId='scene1')))
        await self.runtime.tasks[self.cid]
        session = self.rooms.get(self.cid)
        self.assertEqual(session['state'], 'interrupted')
        self.assertIn('请重新提问', session['error'])
        self.assertEqual((self.model.calls, self.tts.calls), before)
        self.assertEqual(self.store.get('learning_op', model_id), legacy)
        self.assertTrue(any(e['kind'] == 'message_end' for e in self.rooms.events(self.cid)))
        await self.rooms.command(self.cid, self.command('question', text='重新解释', cursor=PlaybackCursor(sceneId='scene1')))
        await self.answer_audio()
        self.assertEqual(self.model.requests[-2]['tools'], tool_schemas('teacher', 'interactive'))

    async def test_completed_legacy_model_call_is_reauthorized_on_quiz(self):
        self.add_test_pages()
        state = self.actor_state(scene_id='quiz1', suffix='-legacy-completed')
        parameters = {'sceneId': 'scene1', 'state': {'angle': 45}}
        call = {'id': 'old-widget', 'name': 'widget_setState', 'parameters': parameters, 'arguments': json.dumps(parameters)}
        args = {'system': '旧模型具有全部工具', 'messages': [{'role': 'user', 'content': '旧问题'}], 'actor': 'teacher'}
        op = self.rooms.operation(self.cid, state['roundId'] + ':actor:0', 'model', args)
        self.rooms.finish_op(op, 'completed', {'text': '', 'calls': [call], 'usage': {}, 'finishReason': 'tool_calls'})
        saved = self.store.get('learning_op', op['id'])
        with patch.object(self.runtime, 'write'):
            result = await self.runtime.actor(state)
        with patch.object(self.runtime, 'write') as events:
            feedback = await self.runtime.prepare_tool({**state, **result})
        self.assertFalse(json.loads(feedback['messages'][-1]['content'])['ok'])
        self.assertEqual([c.args[0] for c in events.call_args_list], ['tool_start', 'tool_end'])
        self.assertEqual(self.store.get('learning_op', op['id']), saved)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.tts.calls, 0)



if __name__ == '__main__':
    unittest.main()

    async def test_directory_and_seventh_page_evidence_shared_by_all_roles(self):
        self.add_test_pages()
        stage = self.stage.model_dump()
        stage['description'] = '目录与当前页验收'
        for number in range(4, 8):
            page = PlanPage(id=f'slot{number}', title=f'第{number}页', type='slide', brief='当前页证据')
            stage['approvedPlan']['pages'].append(page.model_dump())
            stage['scenes'].append(Scene(id=f'scene{number}', planPageId=page.id, title=page.title,
                brief=page.brief, type='slide', content={'type':'slide','elements':[
                    {'id':'title','type':'text','x':20,'y':20,'width':300,'height':80,
                     'text':f'独有正文{number}'}]}).model_dump())
        self.store.put('stage', 'stage1', stage)
        self.cid = self.rooms.create(NewClassroom(stageId='stage1', expectedRevision=1, requestId='seven'))['id']
        for role in ('teacher', 'curious', 'notetaker', 'thinker'):
            state = self.actor_state(role, 'scene7')
            state['messages'] = [{'role':'user','content':'当前页真实证据：旧证据'},
                                 {'role':'user','content':'第七页讲什么？'}]
            with patch.object(self.runtime, 'write'):
                await self.runtime.actor(state)
            request = self.model.requests[-1]
            marker = '# Automatically supplied classroom evidence\n'
            self.assertEqual(request['system'].count(marker), 1)
            evidence = json.loads(request['system'].split(marker)[1])
            self.assertEqual(evidence['course'], {'title':'折射','description':'目录与当前页验收'})
            self.assertEqual((evidence['totalScenes'], evidence['remainingScenes']), (7, 2))
            self.assertEqual(len(evidence['sceneDirectory']), 5)
            self.assertTrue(all(set(entry) == {'id','title','type'} for entry in evidence['sceneDirectory']))
            self.assertEqual(evidence['sceneId'], 'scene7')
            self.assertEqual(evidence['elements'][0]['text'], '独有正文7')
            self.assertNotIn('独有正文4', request['system'])
            self.assertFalse(any(m.get('content','').startswith('当前页真实证据：') for m in request['messages']))

    async def test_pointer_raw_parameters_internal_binding_and_same_id_stale_page(self):
        self.add_test_pages()
        stage = self.stage.model_dump()
        page = PlanPage(id='slot-other', title='另一页', type='slide', brief='同ID')
        stage['approvedPlan']['pages'].append(page.model_dump())
        scene = deepcopy(stage['scenes'][1]); scene.update(id='slide2', planPageId=page.id, title=page.title)
        stage['scenes'].append(scene)
        self.store.put('stage', 'stage1', stage)
        self.cid = self.rooms.create(NewClassroom(stageId='stage1', expectedRevision=1, requestId='same-id'))['id']
        for name in ('spotlight', 'laser'):
            state = self.actor_state(scene_id='slide1', suffix=name)
            self.model.tool_call = {'id':name,'name':name,'parameters':{'elementId':'title'},
                                   'arguments':'{"elementId":"title"}'}
            with patch.object(self.runtime, 'write'):
                state.update(await self.runtime.actor(state))
            with patch.object(self.runtime, 'write') as events:
                result = await self.runtime.prepare_tool(state)
            pending = self.rooms.get(self.cid)['pending']
            self.assertEqual(events.call_args_list[0].args[1]['parameters'], {'elementId':'title'})
            self.assertEqual(pending['parameters'], {'elementId':'title','sceneId':'slide1'})
            op = self.store.get('learning_op', result['pendingId'])
            self.assertEqual(op['arguments']['parameters'], {'elementId':'title'})
            self.rooms.update(self.cid, cursor={**self.rooms.get(self.cid)['cursor'],'sceneId':'slide2'})
            with patch.object(self.runtime, 'write') as stale_events:
                with self.assertRaises(DomainError) as exc:
                    await self.runtime.prepare_tool(state)
            self.assertEqual(exc.exception.code, 'CLASSROOM_STALE')
            stale_events.assert_not_called()
            self.assertEqual(self.store.get('learning_op', op['id'])['state'], 'pending')

    async def test_legacy_pointer_recovery_keeps_intent_hash_and_history(self):
        self.add_test_pages()
        self.model.tool_call = {'id':'legacy-pointer','name':'spotlight',
            'parameters':{'elementId':'title'},'arguments':'{"elementId":"title"}'}
        await self.rooms.command(self.cid, self.command('question', text='聚光标题',
            cursor=PlaybackCursor(sceneId='slide1', instanceId='old')))
        session = await self.state('waiting_tool')
        snapshot = await self.runtime.graph.aget_state(self.runtime.graph_config(self.cid))
        original_call = snapshot.values['result']['calls'][0]
        original_call['parameters']['sceneId'] = 'slide1'
        original_call['arguments'] = json.dumps(original_call['parameters'])
        model_id = self.cid + ':' + session['roundId'] + ':actor:0'
        model = self.store.get('learning_op', model_id)
        model['arguments']['toolPolicy'] = {'version':1,'sceneId':'slide1','tools':[
            {'name':'spotlight','parameters':{'type':'object','properties':{'sceneId':{'type':'string'},'elementId':{'type':'string'}}}}]}
        model['result']['calls'] = [original_call]
        model['requestHash'] = digest(model['arguments'])
        self.store.put('learning_op', model_id, model)
        op_id = session['pending']['operationId']
        op = self.store.get('learning_op', op_id)
        op['arguments']['parameters'] = original_call['parameters']
        op['requestHash'] = digest(op['arguments'])
        self.store.put('learning_op', op_id, op)
        await self.runtime.graph.aupdate_state(self.runtime.graph_config(self.cid), snapshot.values, as_node='prepare_tool')
        self.rooms.emit(self.cid, 'tool_start', {'name':'read_classroom_context','parameters':{}},toolCallId='old-read')
        self.rooms.emit(self.cid, 'tool_end', {'name':'read_classroom_context','result':{'title':'旧记录'}},toolCallId='old-read')
        await self.runtime.close()
        self.runtime = ClassroomRuntime(self.rooms, self.model)
        await self.runtime.initialize()
        before = self.model.calls
        await self.rooms.command(self.cid, self.command('resume_interaction',
            cursor=PlaybackCursor(sceneId='slide1', instanceId='new')))
        current = self.rooms.get(self.cid)
        self.assertEqual(current['state'], 'waiting_tool')
        self.assertEqual(current['pending']['parameters'], {'sceneId':'slide1','elementId':'title'})
        self.assertEqual(current['pending']['instanceId'], 'new')
        self.assertEqual(self.store.get('learning_op', op_id)['requestHash'], op['requestHash'])
        self.assertEqual(self.store.get('learning_op', model_id), model)
        self.assertEqual(self.model.calls, before)
        self.assertTrue(any(e['data'].get('name')=='read_classroom_context' for e in self.rooms.events(self.cid)))
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=current['generation'],
            operationId=op_id, sceneId='slide1', instanceId='new', status='completed', result={'elementId':'title'}))
        current = await self.state('waiting_audio')
        await self.rooms.ack(self.cid, ClassroomAck(controllerId='browser', generation=current['generation'],
            operationId=current['pending']['operationId'], sceneId='slide1', status='completed', result={'ended':True}))
        await self.state('waiting_user')

    async def test_receipt_timeout_retains_pending_without_success(self):
        self.model.tool = True
        await self.rooms.command(self.cid, self.command('question', text='等待演示',
            cursor=PlaybackCursor(sceneId='scene1', instanceId='frame')))
        session = await self.state('waiting_tool')
        pending = session['pending']
        async def no_delay(seconds):
            return None
        with patch('backend.classroom_runtime.asyncio.sleep', no_delay):
            await self.runtime.timeout_receipt(self.cid, pending)
        current = self.rooms.get(self.cid)
        self.assertEqual(current['state'], 'interrupted')
        self.assertEqual(self.store.get('learning_op', pending['operationId'])['state'], 'pending')
        self.assertIsNone(current['lastObservation'])
        self.assertFalse(any(e['kind']=='tool_end' for e in self.rooms.events(self.cid)))
        self.assertTrue(any(e['kind']=='receipt_timeout' for e in self.rooms.events(self.cid)))
