import asyncio
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from backend.config import settings, ROOT
from backend.courses import Courses, DomainError
from backend.document_tools import read, grep
from backend.inspection import Inspection
from backend.models import Stage, Scene, Plan, PlanPage, Teacher, Action, Source, digest, render_fingerprint, visual_fingerprint, program_fingerprint, audio_signature
from backend.narration import Narration
from backend.providers import Providers
from backend.runtime import Runtime
from backend.store import Store
from backend.tools import Tools
from backend.tool_args import TOOLS, Patch, Read, Grep, Check, Image
from backend.tool_result import success
from backend.export_contracts import tool_parameters


def classroom():
    pages=[PlanPage(id='p'+str(i),title='页面'+str(i),type='slide',brief='解释光的折射') for i in range(1,3)]
    plan=Plan(title='折射',audience='初中生',objectives=['解释折射'],pages=pages)
    scenes=[Scene(id='s'+str(i),planPageId='p'+str(i),title='页面'+str(i),brief='观察折射',type='slide',content={'type':'slide','elements':[
        {'id':'title','type':'text','x':20,'y':20,'width':800,'height':60,'text':'折射 折射'},
        {'id':'note','type':'text','x':20,'y':120,'width':800,'height':60,'text':'角度比较'}]},actions=[Action(id='a'+str(j),type='speech',text='观察光线'+str(j)) for j in range(1,4)]) for i in range(1,3)]
    return Stage(id='course',title='折射',approvedPlan=plan,teacher=Teacher(model='qwen3-tts-flash',voice='Cherry'),scenes=scenes)

class Contracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch('backend.config.ROOT',Path(self.temp.name));self.patch.start()
        shutil.copytree(ROOT/'skills',Path(self.temp.name)/'skills')
        self.store=Store(Path(self.temp.name)/'test.sqlite3');self.c=Courses(self.store);self.p=Providers(self.store)
        self.stage=classroom();self.store.put('stage',self.stage.id,self.stage.model_dump())
        self.store.put('course_owner',self.stage.id,{'ownerId':'local'})
        self.store.put('course_approval',self.stage.id,{'planHash':digest(self.stage.approvedPlan.model_dump())})
        self.sid=self.store.session(self.stage.id)['id'];self.run='run_test'
        self.store.patch_session(self.sid,state='running',runId=self.run,approvedPlan=self.stage.approvedPlan.model_dump(),planHash=digest(self.stage.approvedPlan.model_dump()))
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})
        self.n=Narration(self.c,self.p);self.i=Inspection(self.c,self.p);self.t=Tools(self.c,self.p,self.i,self.n)
        await self.t.call(self.sid,self.run,'read-fixture','read_stage',{'stageId':self.stage.id})
    async def asyncTearDown(self):
        await self.n.close();await self.p.close();self.store.close();self.patch.stop();self.temp.cleanup()
    async def call(self,name,args,id=None):return await self.t.call(self.sid,self.run,id or name,name,args)

    def test_schema_rejects_ambiguous_and_fabricated_inputs(self):
        invalid={
          'ask_user':{'kind':'question','question':'确认？','plan':self.stage.approvedPlan.model_dump()},
          'read_skill':{'skill':'../../secret'},
          'fetch_url':{'url':'https://example.org','sourceId':'x'},
          'rename_stage':{'stageId':'course','expectedRevision':1,'title':'   '},
          'edit_deck':{'stageId':'course','expectedRevision':1,'operation':'rename','pageId':'p1'},
          'patch_stage':{'stageId':'course','expectedRevision':1,'operations':[{'op':'replace_text','path':'/title','old':'折射'}]},
          'check_scene':{'stageId':'course','sceneId':'s1','mode':'program','passed':True},
          'set_teacher_voice':{'stageId':'course','expectedRevision':1,'voiceId':'Cherry','teacher':self.stage.teacher.model_dump()}}
        for name,args in invalid.items():
            with self.subTest(name=name),self.assertRaises(ValidationError):TOOLS[name][0].model_validate(args)
        for args in ({'stageId':'course','expectedRevision':1},{'stageId':'course','title':'新名称'}):
            with self.subTest(rename_args=args),self.assertRaises(ValidationError):TOOLS['rename_stage'][0].model_validate(args)
        self.assertEqual(len(TOOLS),20)

    def test_provider_tool_schemas_have_object_roots_without_losing_unions(self):
        for name,(model,_) in TOOLS.items():
            with self.subTest(tool=name):
                schema=tool_parameters(model)
                self.assertEqual(schema['type'],'object')
                self.assertIsInstance(schema['properties'],dict)
                original=model.model_json_schema()
                if 'oneOf' in original:
                    self.assertEqual(schema['oneOf'],original['oneOf'])
                    self.assertEqual(schema['$defs'],original['$defs'])
        ask=tool_parameters(TOOLS['ask_user'][0])
        self.assertEqual(set(ask['required']),{'kind','question'})
        self.assertIn('plan',ask['properties'])

    async def test_stable_patch_after_reorder_and_atomic_failure(self):
        self.c.edit(self.sid,TOOLS['edit_deck'][0].model_validate({'stageId':'course','expectedRevision':1,'operation':'reorder','order':['p2','p1']}).root)
        await self.call('read_stage',{'stageId':'course'},'reread-after-external-edit')
        result=await self.call('patch_stage',{'stageId':'course','expectedRevision':2,'operations':[
            {'op':'replace_text','target':{'sceneId':'s1','elementId':'note'},'path':'/text','old':'角度','new':'入射角度'}]})
        self.assertEqual(self.c.stage('course').scenes[1].content.elements[1].text,'入射角度比较')
        content=json.loads(result['content'][0]['text']);self.assertNotIn('data',content);self.assertNotIn('scenes',content)
        with self.assertRaises(DomainError):
            await self.call('patch_stage',{'stageId':'course','expectedRevision':3,'operations':[
                {'op':'replace_text','target':{'sceneId':'s1','elementId':'note'},'path':'/text','old':'入射角','new':'新标题'},
                {'op':'replace_text','target':{'sceneId':'s2','elementId':'note'},'path':'/text','old':'角度','new':'新内容'}]},'failure')
        self.assertEqual(self.c.stage('course').revision,3);self.assertEqual(self.c.stage('course').scenes[1].title,'页面1')

    async def test_rename_stage_revision_compatibility_and_idempotency(self):
        legacy=self.store.get('stage','course');legacy.pop('description',None);self.store.put('stage','course',legacy)
        args={'stageId':'course','expectedRevision':1,'title':'  光的折射  ','description':'  面向初中生  '}
        result=await self.call('rename_stage',args,'rename-once')
        self.assertTrue(result['ok']);self.assertEqual(result['data']['title'],'光的折射')
        self.assertEqual(result['data']['description'],'面向初中生');self.assertEqual(result['data']['revision'],2)
        saved=self.c.stage('course');self.assertEqual(saved.approvedPlan.title,'光的折射')
        self.assertEqual(saved.description,'面向初中生')
        checkpoint=next(event for event in self.store.events(self.sid) if event['kind']=='course_updated' and event['data']['revision']==2)
        self.assertEqual(checkpoint['data']['title'],'光的折射');self.assertEqual(checkpoint['data']['description'],'面向初中生')
        content=json.loads(result['content'][0]['text'])
        self.assertEqual(content['title'],'光的折射');self.assertNotIn('scenes',content)
        self.assertNotIn('sources',result['details']['data'])
        replay=await self.call('rename_stage',args,'rename-once')
        self.assertEqual(replay,result);self.assertEqual(self.c.stage('course').revision,2)
        omitted=await self.call('rename_stage',{'stageId':'course','expectedRevision':2,'title':'新课名'},'rename-title')
        self.assertEqual(omitted['data']['description'],'面向初中生')
        self.assertEqual(self.c.stage('course').approvedPlan.title,'新课名')
        with self.assertRaises(DomainError) as stale:
            await self.call('rename_stage',{'stageId':'course','expectedRevision':2,'title':'覆盖旧版'},'rename-stale')
        self.assertEqual(stale.exception.code,'REVISION_CONFLICT')
        self.assertEqual(self.c.stage('course').title,'新课名')
        cleared=await self.call('rename_stage',{'stageId':'course','expectedRevision':3,'title':'新课名','description':''},'rename-clear-description')
        self.assertEqual(cleared['data']['description'],'')
        foreign=self.stage.model_copy(deep=True);foreign.id='foreign-course'
        self.store.put('stage',foreign.id,foreign.model_dump());self.store.put('course_owner',foreign.id,{'ownerId':'another-user'})
        with self.assertRaises(DomainError) as denied:
            await self.call('rename_stage',{'stageId':foreign.id,'expectedRevision':1,'title':'不应修改'},'rename-foreign')
        self.assertEqual(denied.exception.code,'ACCESS_OWNER')

    async def test_edit_deck_renames_ungenerated_approved_slot(self):
        stage=self.c.stage('course');stage.scenes=stage.scenes[:1];self.store.put('stage','course',stage.model_dump())
        result=await self.call('edit_deck',{'stageId':'course','expectedRevision':1,
            'operation':'rename','pageId':'p2','title':'尚未生成的页面'})
        saved=self.c.stage('course')
        self.assertEqual(saved.approvedPlan.pages[1].title,'尚未生成的页面')
        self.assertIsNone(result['data']['sceneId']);self.assertEqual(result['data']['affectedPage']['title'],'尚未生成的页面')
        self.assertEqual([s.planPageId for s in saved.scenes],['p1'])

    async def test_edit_deck_brief_and_source_operations_are_scoped(self):
        original_content=self.c.stage('course').scenes[0].content.model_dump()
        brief=await self.call('edit_deck',{'stageId':'course','expectedRevision':1,
            'operation':'set_brief','pageId':'p1','brief':'说明实验中变量与结果之间的关系'})
        self.assertEqual(brief['data']['affectedPage']['brief'],'说明实验中变量与结果之间的关系')
        self.assertTrue(brief['data']['generatedContentStale'])
        self.assertEqual(self.c.stage('course').scenes[0].brief,'说明实验中变量与结果之间的关系')
        self.assertEqual(self.c.stage('course').approvedPlan.pages[0].brief,'说明实验中变量与结果之间的关系')
        self.assertEqual(self.c.stage('course').scenes[0].content.model_dump(),original_content)
        self.assertNotIn('scenes',json.loads(brief['content'][0]['text']))
        source={'id':'src1','title':'实验资料','url':'https://example.org/source','excerpt':'折射数据','sourceVersion':'v1'}
        stage=self.c.stage('course');stage.sources.append(Source.model_validate(source));self.store.put('stage','course',stage.model_dump())
        with self.assertRaises(DomainError) as foreign_source:
            await self.call('edit_deck',{'stageId':'course','expectedRevision':2,
                'operation':'set_sources','pageId':'p1','sourceIds':['not-in-course']},'sources-foreign')
        self.assertEqual(foreign_source.exception.code,'SOURCE_MISSING')
        with self.assertRaises(DomainError) as unread:
            await self.call('edit_deck',{'stageId':'course','expectedRevision':2,
                'operation':'set_sources','pageId':'p1','sourceIds':['src1']},'sources-unread')
        self.assertEqual(unread.exception.code,'SOURCE_NOT_READ');self.assertEqual(self.c.stage('course').revision,2)
        self.store.put('source_access',self.sid+':course:src1',{'sourceVersion':'v1'})
        linked=await self.call('edit_deck',{'stageId':'course','expectedRevision':2,
            'operation':'set_sources','pageId':'p1','sourceIds':['src1']},'sources-read')
        self.assertEqual(linked['data']['affectedPage']['sourceIds'],['src1'])
        self.assertTrue(linked['data']['generatedContentStale'])
        self.assertEqual(self.c.stage('course').scenes[0].sourceIds,['src1'])
        self.assertEqual(self.c.stage('course').scenes[0].content.model_dump(),original_content)
        self.assertTrue(any(item['sceneId']=='s1' for item in linked['data']['changes']['checksInvalidated']))

    async def test_patch_stage_migration_theme_and_single_page_boundary(self):
        for path,code in (('/title','COURSE_METADATA_USE_RENAME_STAGE'),
                          ('/scenes/0/title','PAGE_METADATA_USE_EDIT_DECK'),
                          ('/scenes/0/brief','PAGE_METADATA_USE_EDIT_DECK'),
                          ('/scenes/0/sourceIds','PAGE_METADATA_USE_EDIT_DECK')):
            with self.subTest(path=path),self.assertRaises(DomainError) as rejected:
                await self.call('patch_stage',{'stageId':'course','expectedRevision':1,
                    'operations':[{'op':'replace','path':path,'value':'禁止的元数据修改'}]},'reject-'+path)
            self.assertEqual(rejected.exception.code,code)
        with self.assertRaises(DomainError) as cross_page:
            await self.call('patch_stage',{'stageId':'course','expectedRevision':1,'operations':[
                {'op':'replace_text','target':{'sceneId':'s1','elementId':'note'},'path':'/text','old':'角度比较','new':'甲'},
                {'op':'replace_text','target':{'sceneId':'s2','elementId':'note'},'path':'/text','old':'角度比较','new':'乙'}]},'cross-page')
        self.assertEqual(cross_page.exception.code,'PATCH_SCOPE');self.assertEqual(self.c.stage('course').revision,1)
        themed=await self.call('patch_stage',{'stageId':'course','expectedRevision':1,
            'operations':[{'op':'replace','path':'/theme/accent','value':'#c34f36'}]},'theme-alone')
        self.assertEqual(self.c.stage('course').theme.accent,'#c34f36');self.assertEqual(themed['data']['revision'],2)
        with self.assertRaises(DomainError):
            await self.call('patch_stage',{'stageId':'course','expectedRevision':2,'operations':[
                {'op':'replace','path':'/theme/accent','value':'#2c7a5b'},
                {'op':'replace_text','target':{'sceneId':'s1','elementId':'note'},'path':'/text','old':'角度比较','new':'新文字'}]},'mixed-theme-page')
        self.assertEqual(self.c.stage('course').revision,2);self.assertEqual(self.c.stage('course').theme.accent,'#c34f36')
        with self.assertRaises(DomainError) as stale:
            await self.call('patch_stage',{'stageId':'course','expectedRevision':1,'operations':[
                {'op':'replace_text','target':{'sceneId':'s1','elementId':'note'},'path':'/text','old':'角度比较','new':'过期'}]},'patch-stale')
        self.assertEqual(stale.exception.code,'REVISION_CONFLICT');self.assertEqual(self.c.stage('course').revision,2)

    async def test_page_patch_reference_failure_and_speech_audio_invalidation(self):
        stage=self.c.stage('course');scene=stage.scenes[0]
        scene.actions.append(Action(id='spotlight_title',type='spotlight',elementId='title'))
        speech=scene.actions[0];speech.audioId='voice_fixture';speech.audioStatus='ready'
        speech.audioSignature=audio_signature(speech,stage.teacher);speech.duration=1
        media_root=Path(self.temp.name)/'data/media';media_root.mkdir(parents=True,exist_ok=True)
        (media_root/'voice_fixture.wav').write_bytes(b'RIFFfixture')
        self.store.put('media','voice_fixture',{'id':'voice_fixture','stageId':'course','file':'voice_fixture.wav','mime':'audio/wav'})
        self.store.put('stage','course',stage.model_dump())
        with self.assertRaises((DomainError,ValidationError)):
            await self.call('patch_stage',{'stageId':'course','expectedRevision':1,'operations':[
                {'op':'remove','target':{'sceneId':'s1','elementId':'title'},'path':''}]},'dangling-spotlight')
        self.assertEqual(self.c.stage('course').revision,1)
        updated=await self.call('patch_stage',{'stageId':'course','expectedRevision':1,'operations':[
            {'op':'replace','target':{'sceneId':'s1','actionId':speech.id},'path':'/text','value':'新的讲解内容'}]},'speech-edit')
        saved=self.c.stage('course');new_speech=saved.scenes[0].actions[0]
        self.assertEqual(saved.scenes[0].id,'s1');self.assertEqual(new_speech.audioStatus,'stale')
        self.assertIsNone(new_speech.audioId);self.assertEqual(updated['data']['changes']['audioInvalidated'],[speech.id])
        self.assertTrue(any(item['sceneId']=='s1' for item in updated['data']['changes']['checksInvalidated']))

    async def test_stable_targets_resolved_between_operations(self):
        result=await self.call('patch_stage',{'stageId':'course','expectedRevision':1,'operations':[
            {'op':'remove','target':{'sceneId':'s1','elementId':'title'},'path':''},
            {'op':'replace_text','target':{'sceneId':'s1','elementId':'note'},'path':'/text','old':'角度','new':'入射角'}]})
        self.assertTrue(result['ok']);self.assertEqual(self.c.stage('course').scenes[0].content.elements[0].text,'入射角比较')

    def test_pagination_and_all_occurrences(self):
        a=Read(stageId='course',sceneId='s1',detail='source',limit=100)
        first=read(self.stage,a);second=read(self.stage,a.model_copy(update={'offset':first['nextOffset'],'revision':1}))
        self.assertTrue(first['hasMore']);self.assertEqual(first['nextOffset'],second['offset'])
        with self.assertRaises(DomainError):read(self.stage,a.model_copy(update={'offset':100,'revision':2}))
        g=Grep(stageId='course',query='折射',limit=1);one=grep(self.stage,g);two=grep(self.stage,g.model_copy(update={'cursor':one['nextCursor']}))
        self.assertNotEqual(one['matches'][0],two['matches'][0]);self.assertGreater(one['total'],2)
        with self.assertRaises(DomainError):grep(self.stage,g.model_copy(update={'query':'比较','cursor':one['nextCursor']}))
        tree=read(self.stage,Read(stageId='course'));self.assertNotIn('fontSize',tree['text'])

    async def test_sources_batch_version_and_stored_continuation(self):
        sources=[{'id':'source1','title':'资料','url':'https://example.org/1','text':'长资料 '*6000,'completeness':'full'},
                 {'id':'source2','title':'资料2','url':'https://example.org/2','excerpt':'摘要'}]
        saved=self.c.sources_batch(self.sid,sources);self.assertIsNone(saved['revision'])
        same=self.c.sources_batch(self.sid,sources);self.assertIsNone(same['revision'])
        self.assertEqual(self.c.stage('course').revision,1)
        self.p.fetch=AsyncMock(side_effect=AssertionError('续读不得联网'))
        result=await self.call('fetch_url',{'sourceId':'source1','sourceVersion':saved['sources'][0]['sourceVersion'],'offset':12000,'limit':100})
        self.assertTrue(result['data']['hasMore']);self.p.fetch.assert_not_called()
        self.assertEqual(result['data']['completeness'],'full')

    async def test_tts_isolated_failure_and_unknown_stop(self):
        attempts=[]
        async def fake(sid,stage,scene,action,signature,**kwargs):
            attempts.append(action)
            if action=='a2':raise DomainError('TTS_FORMAT','损坏的语音')
            return {'actionId':action,'mediaId':'m'+action,'status':'ready','duration':1}
        self.n.segment=fake;progress=[]
        result=await self.call('generate_tts',{'stageId':'course','sceneId':'s1'})
        self.assertEqual([s['status'] for s in result['data']['segments']],['ready','failed','ready']);self.assertEqual(result['details']['status'],'partial')
        self.assertFalse(result['isError']);self.assertEqual(attempts,['a1','a2','a3'])
        async def unknown(*args,**kwargs):raise DomainError('MEDIA_UNCERTAIN','结果未知')
        self.n.segment=unknown
        result=await self.call('generate_tts',{'stageId':'course','sceneId':'s1'},'unknown')
        self.assertEqual([s['status'] for s in result['data']['segments']],['uncertain','not_run','not_run']);self.assertTrue(result['isError'])
        self.assertTrue(self.store.get('run',self.run)['haltFeedback'])

    async def test_all_tool_output_routes_and_compact_generation(self):
        # Actual entrypoints, local controlled services, no paid provider calls.
        self.p.search=AsyncMock(return_value=[{'id':'ref','title':'资料','url':'https://example.org','excerpt':'参考'}])
        self.p.fetch=AsyncMock(return_value={'id':'fetched','title':'全文','url':'https://example.org/full','text':'正文'*200,'completeness':'full'})
        approval='fixture_approval'
        self.store.put('plan_approval',approval,{'approvalId':approval,'kind':'create','state':'created','sessionId':self.sid,'stageId':None,'plan':self.stage.approvedPlan.model_dump(),'planHash':digest(self.stage.approvedPlan.model_dump()),'createdStageId':'course'})
        for name,args in [('read_skill',{'skill':'slides'}),('web_search',{'query':'光'}),('fetch_url',{'url':'https://example.org/full'}),('create_stage',{'approvalId':approval}),('list_stages',{}),('list_voices',{}),('read_stage',{'stageId':'course'}),('grep_stage',{'stageId':'course','query':'折射'}),('list_scenes',{'stageId':'course'})]:
            result=await self.call(name,args)
            self.assertEqual(result['details']['schemaVersion'],2);json.loads(result['content'][0]['text'])
        rev=self.c.stage('course').revision
        edited=await self.call('edit_deck',{'stageId':'course','expectedRevision':rev,'operation':'rename','pageId':'p1','title':'新标题'})
        self.assertNotIn('scenes',json.loads(edited['content'][0]['text']))
        renamed=self.c.stage('course')
        self.assertEqual(renamed.approvedPlan.pages[0].title,'新标题');self.assertEqual(renamed.scenes[0].title,'新标题')
        rev=edited['data']['revision']
        voice=await self.call('set_teacher_voice',{'stageId':'course','expectedRevision':rev,'voiceId':'Ethan'})
        self.assertEqual(voice['data']['teacher']['voice'],'Ethan');rev=voice['data']['revision']
        self.p.generate=AsyncMock(return_value=self.stage.scenes[0].model_dump())
        gen=await self.call('generate_scene',{'stageId':'course','expectedRevision':rev,'pageId':'p1','brief':'解释光线'})
        self.assertIn('a1',gen['data']['displacedActionIds']);self.assertNotIn('fontSize',gen['content'][0]['text']);rev=gen['data']['revision']
        self.p.generate=AsyncMock(return_value={'actions':[Action(id='new_speech',type='speech',text='请观察').model_dump()]})
        actions=await self.call('generate_actions',{'stageId':'course','expectedRevision':rev,'sceneId':'s1'})
        self.assertEqual(actions['details']['data']['actions'][0]['textChars'],3);self.assertIn('textChars',actions['content'][0]['text'])
        self.p.image=AsyncMock(return_value={'id':'img','stageId':'course','width':1024,'height':1024,'mime':'image/png'})
        image=await self.call('generate_image',{'stageId':'course','prompt':'水中的铅笔'});self.assertEqual(image['data']['id'],'img')
        self.i.preview=AsyncMock(return_value={'id':'snap','snapshotId':'snap','stageId':'course','sceneId':'s1','mediaId':'snap_media','image':{'data':'AA==','mimeType':'image/png'}})
        preview=await self.call('render_scene_preview',{'stageId':'course','sceneId':'s1'})
        self.assertEqual(preview['content'][1]['type'],'image');self.assertNotIn('image',preview['details']['data'])
        self.i.check=AsyncMock(return_value={'id':'report','stageId':'course','sceneId':'s1','passed':False,'executed':True,'issues':[{'code':'OVERFLOW'}]})
        check=await self.call('check_scene',{'stageId':'course','sceneId':'s1'});self.assertFalse(check['isError'])
        self.store.patch_session(self.sid,approvedPlan=None)
        ask=await self.call('ask_user',{'kind':'question','question':'需要继续吗？'})
        self.assertTrue(ask['waiting']);self.assertEqual(ask['details']['data']['question'],'需要继续吗？')
        with self.assertRaises(DomainError):await self.call('read_stage',{'stageId':'course'},'after-ask')

    def test_fingerprint_dependencies_and_scoped_completion(self):
        before=copy.deepcopy(self.stage);after=copy.deepcopy(before);after.teacher.voice='Ethan'
        self.assertEqual(render_fingerprint(before,before.scenes[0]),render_fingerprint(after,after.scenes[0]))
        self.assertEqual(visual_fingerprint(before,before.scenes[0]),visual_fingerprint(after,after.scenes[0]))
        self.assertNotEqual(program_fingerprint(before,before.scenes[0]),program_fingerprint(after,after.scenes[0]))
        after.scenes[0].actions[0].text='科学结论改变'
        self.assertEqual(render_fingerprint(before,before.scenes[0]),render_fingerprint(after,after.scenes[0]))
        self.assertNotEqual(visual_fingerprint(before,before.scenes[0]),visual_fingerprint(after,after.scenes[0]))
        runtime=Runtime(self.store,self.c,self.t)
        self.store.patch_session(self.sid,state='running')
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})
        runtime.context.verified(self.sid,self.run,self.stage,{'p1'})
        ctx=runtime.context.ensure(self.sid,self.run);entry=ctx['courses']['course'];entry.update(operated=True,targetPageIds=['p1'],baselineIssueKeys=[]);runtime.context.save(ctx)
        self.assertEqual({i['sceneId'] for i in runtime.completion(self.sid,self.run)['issues']},{'s1'})
        self.store.put('run',self.run,{'id':self.run,'sessionId':self.sid,'state':'running','metadataVersion':3,'courseTasks':{}})
        self.assertEqual(runtime.completion(self.sid,self.run)['issues'],[])

    async def test_voice_selection_preserves_language(self):
        self.stage.teacher.language='English'
        self.store.put('stage',self.stage.id,self.stage.model_dump())
        result=await self.call('set_teacher_voice',{'stageId':'course','expectedRevision':1,'voiceId':'Ethan'})
        self.assertEqual(result['data']['teacher']['language'],'English')

    async def test_gateway_size_error_before_paid_call(self):
        with patch.object(settings,'image_provider','gateway'),patch.object(settings,'image_api_key','test'),patch.object(settings,'image_model','test'),patch.object(settings,'image_base_url','https://example.org'),patch.object(settings,'image_output_size','1024x1024'):
            self.p.request=AsyncMock(side_effect=AssertionError('不支持的尺寸不得付费试探'))
            with self.assertRaises(DomainError) as error:await self.p.image('course','铅笔','1280*720','req')
            self.assertEqual(error.exception.code,'UNSUPPORTED_IMAGE_SIZE');self.p.request.assert_not_called()

    async def test_legacy_unknown_image_does_not_repeat_paid_request(self):
        with patch.object(settings,'image_provider','gateway'),patch.object(settings,'image_api_key','test'),patch.object(settings,'image_model','test'),patch.object(settings,'image_base_url','https://example.org'),patch.object(settings,'image_output_size','auto'):
            params={'model':'test','prompt':'铅笔','n':1,'size':'auto'}
            legacy_id='image_'+digest({'stageId':'course','provider':'gateway','baseUrl':'https://example.org','params':params})
            self.store.put('media_task',legacy_id,{'id':legacy_id,'status':'requesting','logicalSize':'1280*720'})
            self.p.request=AsyncMock(side_effect=AssertionError('旧缓存未知结果不得重新付费'))
            with self.assertRaises(DomainError) as error:await self.p.image('course','铅笔',None,'new')
            self.assertEqual(error.exception.code,'MEDIA_UNCERTAIN');self.p.request.assert_not_called()

    async def test_visual_report_survives_audio_only_change_but_not_semantic_edit(self):
        from backend.models import report_matches
        scene=self.stage.scenes[0]
        report={'stageId':'course','sceneId':scene.id,'mode':'visual','fingerprintVersion':2,'fingerprint':visual_fingerprint(self.stage,scene,self.store),'passed':True}
        newer=copy.deepcopy(self.stage);newer.teacher.voice='Ethan'
        self.assertTrue(report_matches(report,newer,newer.scenes[0],self.store))
        newer.scenes[0].actions[0].text='改变科学结论'
        self.assertFalse(report_matches(report,newer,newer.scenes[0],self.store))
        new_source=Source(id='unrelated',title='无关',url='https://example.org',excerpt='无关')
        old=copy.deepcopy(self.stage);old.sources.append(new_source)
        self.assertTrue(report_matches(report,old,old.scenes[0],self.store))

    async def test_program_execution_failure_is_error_not_content_verdict(self):
        self.i._check=AsyncMock(side_effect=DomainError('BROWSER_MISSING','没有浏览器'))
        report=await self.i.check(self.stage,self.stage.scenes[0],Check.model_validate({'stageId':'course','sceneId':'s1'}).root)
        result=success('check_scene',report)
        self.assertTrue(result['isError']);self.assertFalse(result['details']['data']['executed']);self.assertTrue(report['uncovered'])

if __name__=='__main__':unittest.main()
