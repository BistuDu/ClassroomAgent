"""Actual installed Pi SDK -> JSONL -> Python -> durable projection, no paid APIs."""
import asyncio
import json
import gzip
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.config import ROOT,settings
from backend.courses import Courses
from backend.inspection import Inspection
from backend.narration import Narration
from backend.providers import Providers
from backend.runtime import Runtime
from backend.store import Store
from backend.tools import Tools
from test_tool_contracts import classroom
from backend.models import digest

class SdkRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'data');self.patches=[]
        for name,value in [('creation_provider','test'),('creation_base_url',''),('creation_model','test-model'),('creation_api','openai-completions'),('creation_api_key','fixture-key'),('creation_thinking_level','off'),('provider_timeout_seconds',10),('run_timeout_seconds',30)]:
            p=patch.object(settings,name,value);p.start();self.patches.append(p)
        p=patch('backend.config.ROOT',Path(self.temp.name));p.start();self.patches.append(p)
        self.store=Store(Path(self.temp.name)/'test.sqlite3');self.c=Courses(self.store);self.p=Providers(self.store)
        self.stage=classroom();self.store.put('stage',self.stage.id,self.stage.model_dump())
        self.store.put('course_owner',self.stage.id,{'ownerId':'local'})
        self.store.put('course_approval',self.stage.id,{'planHash':digest(self.stage.approvedPlan.model_dump())})
        self.sid=self.store.session(self.stage.id)['id'];self.run='run_actual_sdk'
        self.store.patch_session(self.sid,state='running',runId=self.run,approvedPlan=self.stage.approvedPlan.model_dump(),planHash=digest(self.stage.approvedPlan.model_dump()))
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})
        self.n=Narration(self.c,self.p);self.tools=Tools(self.c,self.p,Inspection(self.c,self.p),self.n);self.runtime=Runtime(self.store,self.c,self.tools)
        # Runtime restart recovery is intentional. This fixture starts a fresh execution afterward.
        self.store.patch_session(self.sid,state='running')
        await self.tools.call(self.sid,self.run,'fixture-read','read_stage',{'stageId':self.stage.id})
        ctx=self.tools.context.ensure(self.sid,self.run);ctx['courses']['course']['baselineIssueKeys']=[];self.tools.context.save(ctx)
        self.requests=[];self.next_tools=[]
        settings.creation_base_url='https://fixture.invalid/v1'
        self.context_file=Path(self.temp.name)/'contexts.jsonl'
    async def asyncTearDown(self):
        await self.runtime.close();await self.n.close();await self.p.close();self.store.close()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    async def execute(self,text='修改第一页标题'):
        env={'NODE_OPTIONS':'--import='+str(ROOT/'tests/sdk-preload.mjs'),'OPENMAIC_FIXTURE_STEPS':json.dumps(self.next_tools),'OPENMAIC_FIXTURE_CONTEXT':str(self.context_file)}
        with patch.dict(os.environ,env):
            await asyncio.wait_for(self.runtime.run(self.store.get('session',self.sid),text,False,'user-message'),30)
        self.requests=[json.loads(line) for line in self.context_file.read_text().splitlines()] if self.context_file.exists() else []
        evidence_dir=os.environ.get('OPENMAIC_ACCEPTANCE_DIR')
        if evidence_dir:
            folder=Path(evidence_dir);folder.mkdir(parents=True,exist_ok=True)
            with gzip.open(folder/(self._testMethodName+'-'+self.run+'.json.gz'),'wt',encoding='utf-8') as evidence:
                json.dump({
                'modelSource':'controlled fixture at ModelRuntime provider boundary; actual SDK session, hooks and subscription',
                'run':self.store.get('run',self.run),'requests':self.requests,'events':self.store.events(self.sid),
                'timeline':self.store.timeline(self.sid,limit=500),'details':self.store.list('pi_tool_detail')},evidence,ensure_ascii=False,indent=2)
        return self.store.get('run',self.run)
    async def test_sdk_results_and_bounded_completion_in_same_loop(self):
        self.next_tools=[('edit_deck',{'stageId':'course','expectedRevision':1,'operation':'rename','pageId':'p1','title':'新标题'})]
        result=await self.execute()
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        self.assertEqual(self.c.stage('course').scenes[0].title,'新标题')
        # A tool turn, normal final text, one no-progress completion turn, then stop.
        self.assertEqual(len(self.requests),3)
        nodes=self.store.timeline(self.sid)['nodes'];tools=[n for n in nodes if n['kind']=='tool']
        self.assertEqual(len(tools),1);self.assertEqual(tools[0]['status'],'completed')
        users=[n for n in nodes if n['kind']=='user'];self.assertEqual(len(users),1);self.assertEqual(users[0]['data']['text'],'修改第一页标题')
        detail=self.store.get('pi_tool_detail',self.sid+':'+self.run+':'+tools[0]['toolCallId']);self.assertEqual(detail['parameters']['title'],'新标题')
        tool_message=next(m for m in self.requests[1]['messages'] if m['role']=='toolResult')
        self.assertNotIn('fontSize',json.dumps(tool_message['content']));self.assertIn('revision',json.dumps(tool_message['content']))
        context=' '.join(str(m.get('content')) for m in self.requests[2]['messages'])
        self.assertIn('CHECK_MISSING',context)
        self.assertNotIn('CHECK_MISSING',' '.join(n['data'].get('text','') for n in nodes if n['kind']=='assistant'))

    async def test_sdk_registers_and_executes_rename_stage(self):
        record=self.store.get('run',self.run);record['courseTasks']={};self.store.put('run',self.run,record)
        await self.tools.call(self.sid,self.run,'rename-read','read_stage',{'stageId':'course'})
        self.next_tools=[('rename_stage',{'stageId':'course','expectedRevision':1,'title':'光的反射'})]
        result=await self.execute('把课程改名为光的反射')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        saved=self.c.stage('course');self.assertEqual(saved.title,'光的反射');self.assertEqual(saved.approvedPlan.title,'光的反射')
        tool=next(n for n in self.store.timeline(self.sid)['nodes'] if n['kind']=='tool')
        self.assertEqual(tool['data']['name'],'rename_stage');self.assertEqual(tool['status'],'completed')
        detail=self.store.get('pi_tool_detail',self.sid+':'+self.run+':'+tool['toolCallId'])
        self.assertEqual(detail['parameters']['title'],'光的反射')
    async def test_sdk_parameter_rejection_has_no_business_cache(self):
        self.next_tools=[('check_scene',{'stageId':'course','sceneId':'s1','mode':'program','passed':True})]
        result=await self.execute('检查第一页')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        node=next(n for n in self.store.timeline(self.sid)['nodes'] if n['kind']=='tool');self.assertEqual(node['status'],'failed')
        self.assertIsNone(self.store.cached_call(self.run,node['toolCallId']))
        detail=self.store.get('pi_tool_detail',self.sid+':'+self.run+':'+node['toolCallId']);self.assertTrue(detail['parameters']['passed']);self.assertTrue(detail['result']['content'])
    async def test_progress_is_durable_before_tool_end(self):
        self.next_tools=[('generate_tts',{'stageId':'course','sceneId':'s1'})]
        observations=[]
        async def segment(sid,stage,scene,action,signature,**kwargs):
            if action=='a2':
                await asyncio.sleep(.03)
                events=self.store.events(self.sid)
                observations.append(any(e['kind']=='tool_execution_update' for e in events))
                observations.append(not any(e['kind']=='tool_execution_end' for e in events))
            return {'actionId':action,'mediaId':'m'+action,'duration':1,'status':'ready'}
        self.n.segment=segment
        result=await self.execute('配音第一页')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        # Allow the independent stdout reader to run between segment updates.
        events=self.store.events(self.sid)
        updates=[e['seq'] for e in events if e['kind']=='tool_execution_update'];ends=[e['seq'] for e in events if e['kind']=='tool_execution_end']
        self.assertTrue(updates);self.assertLess(max(updates),min(ends));self.assertEqual(observations,[True,True])
    async def test_cancel_keeps_saved_receipts_without_inventing_tool_end(self):
        self.next_tools=[('generate_tts',{'stageId':'course','sceneId':'s1'})]
        started=asyncio.Event()
        async def segment(*args,**kwargs):
            started.set();await asyncio.Event().wait()
        self.n.segment=segment
        env={'NODE_OPTIONS':'--import='+str(ROOT/'tests/sdk-preload.mjs'),'OPENMAIC_FIXTURE_STEPS':json.dumps(self.next_tools),'OPENMAIC_FIXTURE_CONTEXT':str(self.context_file)}
        with patch.dict(os.environ,env):
            task=asyncio.create_task(self.runtime.run(self.store.get('session',self.sid),'配音',False,'cancel-message'))
            self.runtime.tasks[self.sid]=task
            await asyncio.wait_for(started.wait(),5)
            await self.runtime.cancel(self.run);await task
        nodes=self.store.timeline(self.sid)['nodes'];tool=next(n for n in nodes if n['kind']=='tool')
        self.assertEqual(tool['status'],'cancelled');self.assertEqual(tool['data']['sdkStatus'],'running')
        detail=self.store.get('pi_tool_detail',self.sid+':'+self.run+':'+tool['toolCallId']);self.assertIsNone(detail['result'])
        self.runtime.tasks.pop(self.sid,None)

    async def test_thinking_text_reaches_durable_timeline_via_sdk(self):
        record=self.store.get('run',self.run);record['courseTasks']={};self.store.put('run',self.run,record)
        thinking='先确认课程目标，再选择工具。'
        with patch.dict(os.environ,{'OPENMAIC_FIXTURE_THINKING':thinking}):
            result=await self.execute('你好')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        nodes=self.store.timeline(self.sid)['nodes']
        thoughts=[n for n in nodes if n['kind']=='reasoning']
        self.assertEqual(len(thoughts),1)
        self.assertEqual(thoughts[0]['data']['text'],thinking)
        self.assertEqual(thoughts[0]['status'],'completed')
        self.assertEqual(sum(n['kind']=='assistant' for n in nodes),1)
        self.assertNotIn('fixture-opaque-signature',json.dumps(self.store.events(self.sid)))

    async def test_discover_read_mixed_scopes_execute_feedback_via_sdk(self):
        record=self.store.get('run',self.run);record.pop('runContext',None);self.store.put('run',self.run,record)
        other=self.stage.model_copy(deep=True);other.id='course_b';other.title='牛顿定律'
        from test_course_tasks import own
        own(self.store,other)
        self.next_tools=[('list_stages',{}),('read_stage',{'stageId':'course','sceneId':'s1'}),
            ('read_stage',{'stageId':'course_b','sceneId':'s2'}),
            ('edit_deck',{'stageId':'course','expectedRevision':1,'operation':'rename','pageId':'p1','title':'新例子'}),
            ('edit_deck',{'stageId':'course_b','expectedRevision':1,'operation':'rename','pageId':'p2','title':'牛顿第二页'}),
            ('patch_stage',{'stageId':'course','expectedRevision':2,'operations':[{'op':'replace_text',
                'target':{'sceneId':'s2','elementId':'note'},'path':'/text','old':'角度比较','new':'越界'}]})]
        result=await self.execute('改折射第一页，再修改牛顿第二页')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        self.assertEqual(self.c.stage('course').scenes[1].title,'页面2')
        self.assertEqual(self.c.stage('course_b').scenes[1].title,'牛顿第二页')
        nodes=[n for n in self.store.timeline(self.sid)['nodes'] if n['kind']=='tool']
        self.assertEqual(len(nodes),6);self.assertTrue(all(n['source']=='pi' for n in nodes))
        self.assertEqual(nodes[-1]['status'],'failed')
        for node in nodes:
            receipt=self.store.get('operation_record',self.run+':'+node['toolCallId'])
            self.assertIn('tool_execution_end',receipt['sdkEvents'])
            self.assertIn('tool_execution_start',receipt['sdkEvents'])
            self.assertTrue(receipt['parameterHash'])
        f=self.runtime.completion(self.sid,self.run)
        a=next(t for t in f['courses'] if t['stageId']=='course');b=next(t for t in f['courses'] if t['stageId']=='course_b')
        self.assertEqual(a['scope']['pageIds'],['p1']);self.assertEqual(b['scope']['pageIds'],['p2'])

    async def test_sdk_natural_question_resume_preserves_request_over_preview(self):
        record=self.store.get('run',self.run);record.update(courseTasks={},sourceMessageId='original');self.store.put('run',self.run,record)
        self.store.put('message',self.sid+':original',{'messageId':'original','text':'给折射课补语音'})
        self.next_tools=[('ask_user',{'kind':'question','question':'昨天两页，还是今天三页？','requestText':'给折射课补语音',
            'candidates':[{'stageId':'course','revision':1,'label':'昨天两页'}]})]
        await self.execute('给折射课补语音')
        question=self.store.get('session',self.sid)['pendingQuestion']
        other=self.stage.model_copy(deep=True);other.id='course_b';other.title='当前预览'
        from test_course_tasks import own
        own(self.store,other);self.store.link_course(self.sid,'course_b',active=True)
        steps=[('read_stage',{'stageId':'course','sceneId':'s1'}),
            ('patch_stage',{'stageId':'course','expectedRevision':1,'operations':[{'op':'replace','target':{'sceneId':'s1','actionId':'a1'},'path':'/text','value':'更新的讲稿'}]})]
        from backend.runtime import Message
        env={'NODE_OPTIONS':'--import='+str(ROOT/'tests/sdk-preload.mjs'),'OPENMAIC_FIXTURE_STEPS':json.dumps(steps),'OPENMAIC_FIXTURE_CONTEXT':str(self.context_file)}
        with patch.dict(os.environ,env):
            accepted=await self.runtime.submit(self.sid,Message(messageId='answer',text='昨天两页那个',questionId=question['id'],stageId='course_b'))
            await asyncio.wait_for(self.runtime.tasks[self.sid],30)
        result=self.store.get('run',accepted['runId'])
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        self.assertEqual(result['previousRequest']['text'],'给折射课补语音')
        target=result['runContext']['courses']['course']
        self.assertEqual(target['targetPageIds'],['p1']);self.assertEqual(result['answerChain'],[question['id']])
        self.assertNotIn('courseTasks',result)
        self.assertEqual(self.c.stage('course_b').revision,1)
        self.assertEqual(self.c.stage('course').scenes[0].actions[0].text,'更新的讲稿')

    async def test_sdk_narration_only_keeps_missing_page_and_old_checks_outside_task(self):
        record=self.store.get('run',self.run);record['courseTasks']={};self.store.put('run',self.run,record)
        stage=self.c.stage('course');stage.scenes=stage.scenes[:1];self.store.put('stage','course',stage.model_dump())
        async def tts(stage_id,text,teacher,signature,**kwargs):
            import io,wave
            data=io.BytesIO()
            with wave.open(data,'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\x00\x00'*8000)
            id='local_'+signature[:16];folder=Path(self.temp.name)/'data/media';folder.mkdir(parents=True,exist_ok=True)
            (folder/(id+'.wav')).write_bytes(data.getvalue())
            media={'id':id,'stageId':stage_id,'file':id+'.wav','mime':'audio/wav','duration':1,'signature':signature}
            self.store.put('media',id,media);return media
        self.p.tts=tts
        record=self.store.get('run',self.run);record.pop('runContext',None);self.store.put('run',self.run,record)
        self.next_tools=[('read_stage',{'stageId':'course','sceneId':'s1'}),
            ('generate_tts',{'stageId':'course','sceneId':'s1'})]
        result=await self.execute('只给这门课补语音')
        self.assertEqual(result['state'],'completed',result.get('error'))
        feedback=self.runtime.completion(self.sid,self.run)['courses'][0]
        self.assertTrue(feedback['ready']);self.assertFalse(feedback['courseReady'])
        self.assertEqual(len(self.c.stage('course').scenes),1)
        self.assertNotIn('unfinishedTasks',self.store.get('session',self.sid))

    async def test_ask_user_blocks_later_writes_and_waits(self):
        self.next_tools=[('ask_user',{'kind':'question','question':'是否补全整门课？','options':['继续','只改标题']})]
        result=await self.execute('我想调整范围')
        self.assertEqual(result['state'],'waiting_for_user',result.get('error'));self.assertEqual(len(self.requests),1)
        nodes=self.store.timeline(self.sid)['nodes'];self.assertEqual(sum(n['kind']=='question' for n in nodes),1)

class SdkSkills(SdkRuntime):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        import shutil
        shutil.copytree(ROOT/'skills',Path(self.temp.name)/'skills')
        # Inherited write/TTS tests need their parent fixture's registered scope.
        # Tests exercising discovery explicitly clear scopes in their own body.

    def skill_steps(self, identifier, limit=50000):
        resource=self.c.skills.snapshot(refresh=True).read(identifier)
        return [('read_skill',{'skillId':identifier,'offset':offset,'limit':limit})
                for offset in range(0,len(resource['text']),limit)]

    def tool_details(self):
        return [{**self.store.get('pi_tool_detail',self.sid+':'+self.run+':'+n['toolCallId']), 'toolName':n['data']['name']}
                for n in self.store.timeline(self.sid,limit=500)['nodes'] if n['kind']=='tool' and n['runId']==self.run]

    async def test_explicit_pagination_blocks_writes_until_complete(self):
        write=('edit_deck',{'stageId':'course','expectedRevision':1,'operation':'rename','pageId':'p1','title':'完整加载后的标题'})
        reads=self.skill_steps('slide-dsl',500)
        self.assertGreater(len(reads),1)
        self.next_tools=[write,reads[0],write,*reads[1:],write]
        result=await self.execute('/slide-dsl /slide-dsl 修改第一页标题')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        self.assertEqual(self.c.stage('course').scenes[0].title,'完整加载后的标题')
        details=self.tool_details()
        self.assertEqual(sum('SKILL_LOAD_REQUIRED' in json.dumps(d['result']) for d in details),2)
        successful=[d for d in details if d['toolName']=='read_skill']
        self.assertEqual(len(successful),len(reads))
        payloads=[json.loads(d['result']['content'][0]['text']) for d in successful]
        original=self.c.skills.snapshot().read('slide-dsl')['text']
        self.assertEqual(''.join(p['text'] for p in payloads),original)
        self.assertFalse(payloads[-1]['hasMore'])
        self.assertTrue(all(p['snapshotVersion']==payloads[0]['snapshotVersion'] for p in payloads))
        nodes=[n for n in self.store.timeline(self.sid)['nodes'] if n['kind']=='tool']
        self.assertTrue(all(n['source']=='pi' for n in nodes))
        self.assertEqual(sum(n['kind']=='user' for n in self.store.timeline(self.sid)['nodes']),1)

    async def test_unknown_and_overbudget_require_real_clarification(self):
        for text,marker in [('/missing-skill 改标题','missing-skill'),
                            ('/workshop-style /lecture-style /feynman-learning /slide-dsl 改标题','slide-dsl')]:
            with self.subTest(text=text):
                self.next_tools=[('edit_deck',{'stageId':'course','expectedRevision':1,'operation':'rename','pageId':'p1','title':'不应保存'}),
                                 ('ask_user',{'kind':'question','question':'请缩小或修正 Skill 选择','options':['只选工作坊']})]
                result=await self.execute(text)
                self.assertEqual(result['state'],'waiting_for_user',result.get('error'))
                self.assertEqual(self.c.stage('course').revision,1)
                self.assertIn(marker,self.requests[0]['systemPrompt'])
                self.assertIn('SKILL_SELECTION_REQUIRED',json.dumps(self.tool_details()[0]['result']))
                self.store.patch_session(self.sid,state='running',pendingQuestion=None)
                self.run='selection_budget'
                self.store.patch_session(self.sid,runId=self.run)
                self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})

    async def test_actual_sdk_compaction_requires_fresh_reads(self):
        self.next_tools=self.skill_steps('workshop-style')
        first=await self.execute('/workshop-style 读取方法')
        self.assertNotEqual(first['state'],'failed',first.get('error'))
        session_file=self.store.get('session',self.sid)['piSessionFile']
        self.run='after_compaction'
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})
        self.store.patch_session(self.sid,state='running',runId=self.run)
        self.context_file.unlink()
        self.next_tools=[('rename_stage',{'stageId':'course','expectedRevision':1,'title':'不应保存'}),*self.skill_steps('workshop-style')]
        with patch.dict(os.environ,{'OPENMAIC_FIXTURE_COMPACT':'1'}):
            result=await self.execute('/workshop-style 再次读取方法')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        self.assertIn('SKILL_LOAD_REQUIRED',json.dumps(self.tool_details()[0]['result']))
        self.assertEqual(self.c.stage('course').revision,1)
        self.assertTrue(any(json.loads(line).get('type')=='compaction' for line in Path(session_file).read_text().splitlines()))
        self.assertFalse(any(m['role']=='toolResult' and m.get('toolName')=='read_skill' for m in self.requests[1]['messages']))
        self.assertTrue(any(d['toolName']=='read_skill' for d in self.tool_details()))

    async def test_all_resources_aliases_and_denied_paths_via_sdk(self):
        snapshot=self.c.skills.snapshot(refresh=True)
        targets=[(name,path) for name,files in snapshot.payload['resources'].items() for path in files]
        from backend.skills import LEGACY_PATHS,LEGACY_ALIASES
        targets+=list(LEGACY_PATHS)+[(name,'SKILL.md') for name in LEGACY_ALIASES]
        denied=['../secret.md','/etc/passwd','references/missing.md','references/../SKILL.md']
        self.next_tools=[('read_skill',{'skillId':name,'path':path,'limit':50000}) for name,path in targets]
        self.next_tools += [('read_skill',{'skillId':'stage-design','path':path}) for path in denied]
        result=await self.execute('读取可用资源及兼容路径，验证权限边界，不修改课程')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        details=self.tool_details()
        self.assertEqual(len(details),len(targets)+len(denied))
        for detail,(name,path) in zip(details,targets):
            expected=snapshot.read(name,path)
            data=detail['result']['details']['data']
            self.assertEqual(data['text'],expected['text'])
            self.assertEqual(data['bodyHash'],expected['bodyHash'])
            self.assertEqual(json.loads(detail['result']['content'][0]['text'])['text'],data['text'])
        self.assertTrue(all('SKILL_SCOPE' in json.dumps(d['result']) for d in details[-4:]))
        self.assertEqual(len(snapshot.public()['skills']),16)
        self.assertTrue(all('text' not in item for item in snapshot.public()['skills']))

    async def test_run_snapshot_survives_reload_via_sdk(self):
        original=self.c.skills.snapshot(refresh=True).read('workshop-style')['text']
        execute=self.tools.execute
        changed=False
        async def reload_after_read(*args,**kwargs):
            nonlocal changed
            result=await execute(*args,**kwargs)
            if args[3]=='read_skill' and not changed:
                file=Path(self.temp.name)/'skills/agent-runtime/workshop-style/SKILL.md'
                file.write_text(original+'\n验收新增说明。\n')
                self.c.reload_skills();changed=True
            return result
        self.tools.execute=reload_after_read
        self.next_tools=[('read_skill',{'skillId':'workshop-style'})]*2
        result=await self.execute('/workshop-style 读取同一冻结版本')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        data=[d['result']['details']['data'] for d in self.tool_details()]
        self.assertEqual(data[0],data[1])
        self.assertEqual(data[0]['text'],original)
        self.assertNotEqual(self.c.skills.snapshot().read('workshop-style')['bodyHash'],data[0]['bodyHash'])

    async def test_body_byte_budget_requires_clarification_via_sdk(self):
        file=Path(self.temp.name)/'skills/agent-runtime/large-fixture'
        file.mkdir()
        (file/'SKILL.md').write_text('---\nname: large-fixture\ndescription: 体积预算验收\n---\n'+'甲'*40001)
        self.next_tools=[('rename_stage',{'stageId':'course','expectedRevision':1,'title':'不应保存'}),
                         ('ask_user',{'kind':'question','question':'正文超过120000字节，请缩小选择'})]
        result=await self.execute('/large-fixture 修改课程名')
        self.assertEqual(result['state'],'waiting_for_user',result.get('error'))
        self.assertIn('large-fixture',self.requests[0]['systemPrompt'])
        self.assertIn('SKILL_SELECTION_REQUIRED',json.dumps(self.tool_details()[0]['result']))
        self.assertEqual(self.c.stage('course').revision,1)

    async def test_legacy_session_resumes_with_standard_skill_and_durable_diagnostics(self):
        self.next_tools=[('read_skill',{'skill':'slides'})]
        first=await self.execute('读取普通页面制作规范')
        self.assertNotEqual(first['state'],'failed',first.get('error'))
        old_session=self.store.get('session',self.sid)['piSessionFile']
        snapshot=self.store.get('skill_diagnostics',self.run)
        self.assertEqual(len(snapshot['skills']),16)
        self.assertEqual(snapshot['diagnostics'],[])
        tool=next(n for n in self.store.timeline(self.sid)['nodes'] if n['kind']=='tool')
        detail=self.store.get('pi_tool_detail',self.sid+':'+self.run+':'+tool['toolCallId'])
        self.assertEqual(detail['result']['details']['data']['skillId'],'slide-craft')
        self.assertEqual(detail['result']['details']['data']['requestedId'],'slides')
        self.assertEqual(detail['result']['details']['data']['snapshotVersion'],snapshot['version'])
        self.assertTrue(all('bash' not in r['tools'] and 'read' not in r['tools'] for r in self.requests))
        self.context_file.unlink()
        self.run='run_resumed_skills'
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})
        self.store.patch_session(self.sid,state='running',runId=self.run)
        self.next_tools=[('read_skill',{'skillId':'slide-design'})]
        resumed=await self.execute('再次读取页面规范')
        self.assertNotEqual(resumed['state'],'failed',resumed.get('error'))
        self.assertEqual(self.store.get('session',self.sid)['piSessionFile'],old_session)
        results=[m for m in self.requests[-1]['messages'] if m['role']=='toolResult' and m['toolName']=='read_skill']
        self.assertEqual(len(results),2)
        before=json.loads(results[0]['content'][0]['text']);after=json.loads(results[1]['content'][0]['text'])
        self.assertEqual(before['text'],after['text'])
        self.assertEqual(before['bodyHash'],after['bodyHash'])
        self.assertEqual(after['requestedId'],'slide-design')
        self.assertFalse(any(n['kind']=='assistant' and '画布为 1280x720' in n['data'].get('text','') for n in self.store.timeline(self.sid)['nodes']))

    async def test_resource_failure_uses_minimal_prompt_and_reports_error(self):
        import shutil
        shutil.rmtree(Path(self.temp.name)/'skills')
        result=await self.execute('你好')
        self.assertNotEqual(result['state'],'failed',result.get('error'))
        diagnostic=self.store.get('skill_diagnostics',self.run)
        self.assertEqual(diagnostic['skills'],[])
        self.assertTrue(diagnostic['loadError'])
        self.assertNotIn('<available_course_skills>',str(self.requests[0]['systemPrompt']))
        self.assertIn('禁止通用文件读写',str(self.requests[0]['systemPrompt']))

if __name__=='__main__':unittest.main()
