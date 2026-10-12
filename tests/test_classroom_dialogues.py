"""Controlled acceptance for topic lifetimes. No supplier calls or fabricated browser success."""
import asyncio
import json
import sqlite3
import uuid
import unittest
from copy import deepcopy

import test_classroom_runtime as fixtures
from backend.classroom_models import ClassroomCommand, ClassroomAck, PlaybackCursor, NewClassroom
from backend.classroom_runtime import RoundState
from backend.courses import DomainError


class DirectorModel(fixtures.FakeModel):
    decision = {'next':'wait'}
    async def generate(self, system, messages, tools, on_delta):
        if system.startswith('You are the Director of a multi-agent classroom.'):
            self.calls += 1
            self.requests.append(deepcopy({'system':system,'messages':messages,'tools':tools}))
            decision = {'next':'teacher'} if not json.loads(messages[0]['content'])['spokenRoleIds'] else self.decision
            return {'text':json.dumps(decision),'calls':[],'usage':{},'finishReason':'stop'}
        return await super().generate(system,messages,tools,on_delta)


class DialogueTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ClassroomTests.asyncSetUp
    asyncTearDown = fixtures.ClassroomTests.asyncTearDown
    state = fixtures.ClassroomTests.state
    add_test_pages = fixtures.ClassroomTests.add_test_pages

    def command(self, kind, **kwargs):
        return ClassroomCommand(requestId=str(uuid.uuid4()),controllerId='browser',kind=kind,**kwargs)

    def cursor(self):
        return PlaybackCursor(sceneId=self.rooms.get(self.cid)['cursor']['sceneId'],instanceId='instance',experimentState={'angle':30})

    async def speech(self, final='waiting_user'):
        room=await self.state('waiting_audio');p=room['pending']
        await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=room['generation'],operationId=p['operationId'],sceneId=room['cursor']['sceneId'],status='completed',result={'ended':True}))
        return await self.state(final)

    async def test_wait_followup_end_new_topic_and_explicit_continue(self):
        self.model=DirectorModel();self.runtime.model=self.model
        await self.rooms.command(self.cid,self.command('question',text='旧话题独有词：折射',cursor=self.cursor()))
        room=await self.speech();did=room['activeDialogueId'];rid=room['roundId']
        await self.rooms.command(self.cid,self.command('question',text='请进一步解释',cursor=self.cursor()))
        room=await self.speech();self.assertEqual(room['activeDialogueId'],did);self.assertNotEqual(room['roundId'],rid)
        self.assertIn('旧话题独有词',json.dumps(self.model.requests[-2]['messages'],ensure_ascii=False))
        self.model.decision={'next':'end','reason':'topic_complete'}
        await self.rooms.command(self.cid,self.command('question',text='现在明白了',cursor=self.cursor()))
        room=await self.speech('waiting_lesson');self.assertIsNone(room['activeDialogueId']);self.assertIsNotNone(room['returnCursor'])
        self.assertEqual(self.rooms.dialogue(did)['status'],'completed')
        self.assertEqual(self.rooms.dialogue(did)['endReason'],'topic_complete')
        paid_after_end=self.model.calls;tts_after_end=self.tts.calls
        await self.rooms.command(self.cid,self.command('continue',cursor=self.cursor()))
        ended_room=self.rooms.get(self.cid);restore=ended_room['pending']
        self.assertEqual(ended_room['state'],'waiting_tool')
        self.assertEqual((self.model.calls,self.tts.calls),(paid_after_end,tts_after_end))
        await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=ended_room['generation'],operationId=restore['operationId'],sceneId='scene1',instanceId='instance',status='completed',result={'restored':True}))
        self.assertEqual(self.rooms.get(self.cid)['state'],'lecture')
        self.model.decision={'next':'wait'}
        before=len(self.model.requests)
        await self.rooms.command(self.cid,self.command('question',text='新的独立问题',cursor=self.cursor()))
        room=await self.speech();self.assertNotEqual(room['activeDialogueId'],did)
        new_requests=json.dumps(self.model.requests[before:],ensure_ascii=False)
        self.assertNotIn('旧话题独有词',new_requests)
        self.assertEqual(len(self.rooms.list_dialogues('stage1')['items']),2)
        paid=self.model.calls;tts=self.tts.calls
        await self.rooms.command(self.cid,self.command('continue',cursor=self.cursor()))
        room=self.rooms.get(self.cid);self.assertEqual(room['state'],'waiting_tool');p=room['pending']
        self.assertEqual(self.model.calls,paid);self.assertEqual(self.tts.calls,tts)
        await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=room['generation'],operationId=p['operationId'],sceneId='scene1',instanceId='instance',status='completed',result={'restored':True}))
        self.assertEqual(self.rooms.get(self.cid)['state'],'lecture')

    async def test_budget_and_bad_end_are_not_normal_completion(self):
        original_paid = self.runtime.paid
        async def spent_budget(*args, **kwargs):
            result, elapsed = await original_paid(*args, **kwargs)
            return result, self.runtime.config.classroom_generation_timeout_seconds if args[1].startswith('actor:') else elapsed
        self.runtime.paid = spent_budget
        await self.rooms.command(self.cid,self.command('question',text='预算',cursor=self.cursor()))
        room=await self.speech();did=room['activeDialogueId']
        self.assertEqual(self.rooms.dialogue(did)['status'],'waiting_user')
        self.assertTrue(any(e['kind']=='budget_reached' for e in self.rooms.dialogue_events(did)))
        self.runtime.paid = original_paid; model=DirectorModel();model.decision={'next':'end','reason':'nonsense'};self.runtime.model=model
        await self.rooms.command(self.cid,self.command('question',text='错误调度',cursor=self.cursor()))
        room=await self.state('waiting_audio');p=room['pending']
        await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=room['generation'],operationId=p['operationId'],sceneId='scene1',status='completed',result={'ended':True}))
        await asyncio.wait_for(self.runtime.tasks[self.cid],2)
        self.assertEqual(self.rooms.get(self.cid)['state'],'interrupted')
        self.assertEqual(self.rooms.dialogue(did)['status'],'interrupted')
        self.assertNotEqual(self.rooms.dialogue(did)['endReason'],'topic_complete')

    async def test_exit_confirmation_navigation_and_stale_receipt(self):
        await self.rooms.command(self.cid,self.command('question',text='保留这个话题',cursor=self.cursor()))
        room=await self.state('waiting_audio');p=room['pending'];did=room['activeDialogueId'];before=deepcopy(room)
        with self.assertRaises(DomainError) as error:
            await self.rooms.command(self.cid,self.command('navigate',cursor=self.cursor()))
        self.assertEqual(error.exception.code,'CLASSROOM_CONFIRMATION');self.assertEqual(self.rooms.get(self.cid),before)
        with self.assertRaises(DomainError):
            await self.rooms.command(self.cid,self.command('navigate',cursor=self.cursor(),confirmEnd=True,expectedDialogueId=did,expectedGeneration=room['generation']-1))
        self.rooms.update(self.cid,attempts={'scene1':'grade1'},consumedDiscussions={'discussion1':'joined'})
        cmd=self.command('navigate',cursor=self.cursor(),confirmEnd=True,expectedDialogueId=did,expectedGeneration=room['generation'])
        result=await self.rooms.command(self.cid,cmd);same=await self.rooms.command(self.cid,cmd)
        self.assertEqual(result['generation'],same['generation']);self.assertEqual(result['attempts'],{'scene1':'grade1'})
        self.assertEqual(result['consumedDiscussions'],{'discussion1':'joined'});self.assertEqual(result['state'],'paused')
        self.assertEqual(result['cursor']['experimentState'],{'angle':30});self.assertIsNone(result['activeDialogueId'])
        with self.assertRaises(DomainError):
            await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=room['generation'],operationId=p['operationId'],sceneId='scene1',status='completed',result={'ended':True}))
        new_args=NewClassroom(stageId='stage1',expectedRevision=1,requestId='resume-learning')
        new=self.rooms.create(new_args);self.assertEqual(new,self.rooms.create(new_args))
        self.assertEqual(new['id'],self.cid);self.assertEqual(new['attempts'],{'scene1':'grade1'});self.assertEqual(new['consumedDiscussions'],{'discussion1':'joined'})
        self.assertIsNone(new['activeDialogueId']);self.assertEqual(self.rooms.list_dialogues('stage1')['items'][0]['id'],did)
        self.assertEqual(self.courses.stage('stage1').revision,1)

    async def test_legacy_migration_body_identity_details_and_ownership(self):
        room=self.rooms.get(self.cid);room.pop('activeDialogueId');self.store.put('learning',self.cid,room)
        for kind,data in [('user_message',{'text':'原问题'}),('tool_start',{'name':'spotlight','parameters':{'elementId':'x'}}),('tool_end',{'name':'spotlight','result':{'ok':True}})]:
            body=json.dumps({'classroomId':self.cid,'roundId':'original-round','toolCallId':'old-call','kind':kind,'data':data,'eventId':kind,'generation':0,'createdAt':room['createdAt'],'speakerId':'teacher'})
            self.store.db.execute('INSERT INTO learning_events(classroom,event_id,body) VALUES(?,?,?)',(self.cid,kind,body))
        original=[tuple(r) for r in self.store.db.execute('SELECT seq,event_id,body FROM learning_events')]
        self.rooms.migrate_dialogues();self.rooms.migrate_dialogues()
        self.assertEqual(original,[tuple(r) for r in self.store.db.execute('SELECT seq,event_id,body FROM learning_events')])
        did='legacy:'+self.cid;items=self.rooms.list_dialogues('stage1')['items'];self.assertEqual(len(items),1);self.assertEqual(items[0]['type'],'legacy')
        self.assertNotIn('summary',items[0]);self.assertEqual(len(self.rooms.dialogue_events(did)),3)
        self.assertEqual(self.rooms.dialogue_tool_details(did,'original-round','old-call')['parameters'],{'elementId':'x'})
        record=self.rooms.dialogue(did);self.store.put('learning_dialogue',did,{**record,'ownerId':'other'})
        with self.assertRaises(DomainError):self.rooms.dialogue_events(did)
        with self.assertRaises(DomainError):self.rooms.dialogue_tool_details(did,'original-round','old-call')
        self.assertEqual(self.rooms.list_dialogues('stage1')['items'],[])

    async def test_final_message_filter_and_frozen_event_identity(self):
        record=self.rooms.begin_dialogue(self.cid,'独立话题');did=record['id']
        self.rooms.emit(self.cid,'message_end',{'text':'早期有效发言'},speakerId='teacher',messageId='m')
        for i in range(550):self.rooms.emit(self.cid,'text_delta',{'text':'增量'},messageId='delta')
        self.assertIn('早期有效发言',json.dumps(self.runtime.bounded_history(self.cid),ensure_ascii=False))
        self.rooms.update(self.cid,generation=1,roundId='r')
        state=RoundState(classroomId=self.cid,roundId='r',generation=1,dialogueId=did,sceneId='scene1')
        self.runtime.active(state)
        self.rooms.set_dialogue_status(self.cid,'completed','topic_complete');self.rooms.begin_dialogue(self.cid,'新话题')
        with self.assertRaises(DomainError):self.runtime.active(state)
        self.assertNotIn('早期有效发言',json.dumps(self.runtime.bounded_history(self.cid),ensure_ascii=False))

    async def test_repeated_role_reply_waits_with_no_progress_reason(self):
        self.model=DirectorModel();self.model.decision={'next':'teacher'};self.runtime.model=self.model
        await self.rooms.command(self.cid,self.command('question',text='重复检测',cursor=self.cursor()))
        for _ in range(2):
            room=await self.state('waiting_audio');p=room['pending']
            await self.rooms.ack(self.cid,ClassroomAck(controllerId='browser',generation=room['generation'],operationId=p['operationId'],sceneId='scene1',status='completed',result={'ended':True}))
            await asyncio.wait_for(self.runtime.tasks[self.cid],2)
        room=self.rooms.get(self.cid);self.assertEqual(room['state'],'waiting_user')
        dialogue=self.rooms.dialogue(room['activeDialogueId'])
        self.assertEqual(dialogue['endReason'],'no_progress');self.assertNotEqual(dialogue['status'],'completed')
