import io
import socket
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
from backend.config import settings
from backend.courses import Courses, DomainError
from backend.models import Action, Plan, PlanPage, Scene, Stage, Teacher, audio_signature, digest
from backend.narration import Narration, NarrationRequest, TeacherVoiceEdit
from backend.providers import Providers, bailian_media_url, validate_teacher
from backend.store import Store

HOST = 'dashscope-result-bj.oss-cn-beijing.aliyuncs.com'
URL = f'http://{HOST}/sample.wav?Expires=4102444800&Signature=a%2Bb%3D'


def wav():
    result = io.BytesIO()
    with wave.open(result, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
        audio.writeframes(b'\x01\x00' * 2400)
    return result.getvalue()


class TtsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = patch('backend.config.ROOT', Path(self.directory.name))
        self.config.start()
        self.key = patch.object(settings, 'bailian_api_key', 'test-key'); self.key.start()
        self.model = patch.object(settings, 'bailian_tts_model', 'qwen3-tts-flash'); self.model.start()
        self.store = Store(Path(self.directory.name)/'test.sqlite3')
        self.providers = Providers(self.store)
        await self.providers.client.aclose()
        self.requests = []

        def handle(request):
            self.requests.append(request)
            return httpx.Response(200, content=wav(), headers={'Content-Type':'audio/wav'})

        self.providers.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.dns = patch('backend.providers.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('198.18.0.1',443))])
        self.dns.start()

    async def asyncTearDown(self):
        await self.providers.close()
        self.store.close()
        self.dns.stop(); self.model.stop(); self.key.stop(); self.config.stop()
        self.directory.cleanup()

    async def test_official_http_download_upgrades_to_tls_preserving_signature(self):
        body, mime, _ = await self.providers.bailian_media_bytes(URL)
        request = self.requests[0]
        self.assertEqual(request.url.scheme, 'https')
        self.assertEqual(request.url.query, httpx.URL(URL).query)
        self.assertNotIn('authorization', request.headers)
        self.assertEqual(body, wav())
        self.assertEqual(mime, 'audio/wav')

    async def test_rejects_untrusted_hosts_credentials_ports_and_internal_oss(self):
        for url in ('http://localhost/x', f'https://{HOST}.evil.test/x', f'https://user:pass@{HOST}/x',
                    f'http://{HOST}:443/x', f'https://{HOST}:80/x', f'http://{HOST}:8080/x',
                    'https://dashscope-result-bj.oss-cn-beijing-internal.aliyuncs.com/x'):
            with self.subTest(url=url), self.assertRaises(DomainError) as error:
                bailian_media_url(url)
            self.assertEqual(error.exception.code, 'MEDIA_URL_RESTRICTED')

    async def test_redirect_is_validated_before_request(self):
        self.providers.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request:httpx.Response(302, headers={'Location':'http://127.0.0.1/private'})))
        with self.assertRaises(DomainError) as error:
            await self.providers.bailian_media_bytes(URL)
        self.assertEqual(error.exception.code, 'MEDIA_URL_RESTRICTED')

    async def test_private_dns_rejected(self):
        with patch('backend.providers.socket.getaddrinfo', return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))]):
            with self.assertRaises(DomainError) as error:
                await self.providers.bailian_media_bytes(URL)
        self.assertEqual(error.exception.code, 'MEDIA_URL_RESTRICTED')
        self.assertEqual(self.requests, [])

    async def test_expired_link_reports_actionable_error_without_request(self):
        with self.assertRaises(DomainError) as error:
            await self.providers.bailian_media_bytes(URL.replace('4102444800','1'))
        self.assertEqual(error.exception.code, 'MEDIA_URL_EXPIRED')
        self.assertEqual(self.requests, [])

    async def test_resume_saved_result_without_new_paid_post(self):
        teacher = Teacher(model='qwen3-tts-flash', voice='Cherry')
        action = Action(type='speech', text='你好')
        signature = audio_signature(action, teacher)
        self.store.put('media_task','tts_course_'+signature, {'url':URL,'status':'downloading'})
        self.providers.request = AsyncMock(side_effect=AssertionError('Must not repeat synthesis'))
        media = await self.providers.tts('course', action.text, teacher, signature)
        self.assertEqual(media['duration'], .1)
        self.assertEqual(media['signature'], signature)
        self.assertTrue((settings.data_dir/'media'/media['file']).is_file())
        self.assertEqual(self.store.get('media_task','tts_course_'+signature)['status'], 'ready')
        self.assertNotIn('url', self.store.get('media_task','tts_course_'+signature))
        self.providers.request.assert_not_called()

    async def test_malformed_audio_is_not_saved(self):
        teacher = Teacher(model='qwen3-tts-flash', voice='Cherry')
        self.store.put('media_task','tts_course_sig', {'url':URL,'status':'downloading'})
        self.providers.bailian_media_bytes = AsyncMock(return_value=(b'<html>error</html>','text/html',URL))
        with self.assertRaises(DomainError) as error:
            await self.providers.tts('course','你好',teacher,'sig')
        self.assertEqual(error.exception.code, 'TTS_FORMAT')
        self.assertEqual(self.store.list('media'), [])

    async def test_streaming_wav_header_uses_actual_duration(self):
        teacher = Teacher(model='qwen3-tts-flash', voice='Cherry')
        self.store.put('media_task','tts_course_sig', {'url':URL,'status':'downloading'})
        body = bytearray(wav())
        struct.pack_into('<I',body,4,0x7FFFFFBF)
        struct.pack_into('<I',body,40,0x7FFFFF9B)
        self.providers.bailian_media_bytes = AsyncMock(return_value=(bytes(body),'audio/x-wav',URL))
        media = await self.providers.tts('course','你好',teacher,'sig')
        self.assertEqual(media['duration'], .1)
        with wave.open(str(settings.data_dir/'media'/media['file'])) as audio:
            self.assertEqual(audio.getnframes(),2400)

    async def test_regular_wav_truncation_is_rejected(self):
        teacher = Teacher(model='qwen3-tts-flash', voice='Cherry')
        self.store.put('media_task','tts_course_sig', {'url':URL,'status':'downloading'})
        self.providers.bailian_media_bytes = AsyncMock(return_value=(wav()[:-200],'audio/wav',URL))
        with self.assertRaises(DomainError) as error:
            await self.providers.tts('course','你好',teacher,'sig')
        self.assertEqual(error.exception.code,'TTS_FORMAT')
        self.assertEqual(self.store.list('media'), [])

    async def test_unknown_result_is_not_replayed_but_explicit_force_synthesizes(self):
        teacher = Teacher(model='qwen3-tts-flash', voice='Cherry')
        self.store.put('media_task','tts_course_sig', {'status':'requesting'})
        self.providers.request = AsyncMock(return_value={'output':{'audio':{'url':URL}}})
        with self.assertRaises(DomainError) as error:
            await self.providers.tts('course','你好',teacher,'sig')
        self.assertEqual(error.exception.code, 'MEDIA_UNCERTAIN')
        self.providers.request.assert_not_called()
        media = await self.providers.tts('course','你好',teacher,'sig',force=True)
        self.assertEqual(media['voice'], 'Cherry')
        self.providers.request.assert_awaited_once()

    async def test_voice_catalog_filters_older_model(self):
        with patch.object(settings,'bailian_tts_model','qwen3-tts-flash-2025-09-18'):
            self.assertEqual({v['id'] for v in self.providers.voices()['voices']},{'Cherry','Ethan'})
            with self.assertRaises(DomainError):
                validate_teacher(Teacher(model=settings.bailian_tts_model,voice='Serena'))

    def classroom(self):
        page = PlanPage(id='p1', title='测试', type='quiz', brief='测试')
        plan = Plan(title='测试课', audience='学生', objectives=['观察'], pages=[page])
        teacher = Teacher(model='qwen3-tts-flash', voice='Cherry')
        action = Action(id='a1', type='speech', text='请观察光线', audioStatus='ready', audioId='old_audio', audioSignature='placeholder', duration=1)
        action.audioSignature = audio_signature(action,teacher)
        scene = Scene(id='s1', planPageId='p1', title='测试', brief='测试', type='quiz', actions=[action],
                      content={'type':'quiz','questions':[{'id':'q1','text':'光会折射吗？','options':[{'id':'a','text':'会'},{'id':'b','text':'不会'}],'answer':'a','explanation':'会'}]})
        stage = Stage(id='course', title='测试课', approvedPlan=plan, teacher=teacher, scenes=[scene])
        self.store.put('stage',stage.id,stage.model_dump())
        self.store.put('course_owner',stage.id,{'ownerId':'local'})
        self.store.put('course_approval',stage.id,{'planHash':digest(plan.model_dump())})
        session = self.store.session(stage.id)
        self.store.patch_session(session['id'],approvedPlan=plan.model_dump(),planHash=digest(plan.model_dump()))
        return Courses(self.store), stage, session['id']

    async def test_voice_change_invalidates_audio_and_is_idempotent(self):
        courses, stage, sid = self.classroom()
        service = Narration(courses,self.providers)
        args = TeacherVoiceEdit(sessionId=sid, expectedRevision=1, requestId='voice1', voice='Ethan')
        result = service.set_voice(stage.id,args)
        action = result['scenes'][0]['actions'][0]
        self.assertEqual(result['teacher']['voice'],'Ethan')
        self.assertEqual(action['audioStatus'],'stale')
        self.assertIsNone(action['audioId'])
        self.assertEqual(service.set_voice(stage.id,args)['revision'],2)
        self.assertIsNone(self.store.get('session',sid)['operation'])
        with self.assertRaises(DomainError):
            service.set_voice(stage.id,args.model_copy(update={'voice':'Cherry'}))
        with self.assertRaises(DomainError):
            service.set_voice(stage.id,args.model_copy(update={'requestId':'voice2'}))
        self.assertIsNone(self.store.get('session',sid)['operation'])

    async def test_narration_force_is_forwarded_and_retry_reuses_job(self):
        courses, stage, sid = self.classroom()
        service = Narration(courses,self.providers)
        service.segment = AsyncMock(return_value={'mediaId':'new_audio','duration':1})
        args = NarrationRequest(sessionId=sid, expectedRevision=1, requestId='tts1', force=True)
        job = service.start(stage.id,'s1',args)
        self.assertEqual(service.start(stage.id,'s1',args)['id'],job['id'])
        await service.tasks[job['id']]
        service.segment.assert_awaited_once()
        self.assertTrue(service.segment.call_args.kwargs['force'])
        self.assertEqual(self.store.get('narration_job',job['id'])['status'],'completed')
        await service.close()


if __name__=='__main__':
    unittest.main()
