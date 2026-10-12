"""Real Bailian voice verification and resumable course repair. No keys/URLs logged.

Run from the project root: .venv/bin/python -m scripts.verify_tts
Add --course ID to also complete its existing narration through the public API.
"""
import argparse
import asyncio
import io
import json
import math
import struct
import wave
import httpx
from backend.config import settings
from backend.courses import DomainError
from backend.models import Action, Teacher, audio_signature, digest, uid
from backend.providers import Providers
from backend.store import Store, now


def audio_evidence(body):
    with wave.open(io.BytesIO(body), 'rb') as audio:
        count, rate, channels, width = audio.getnframes(), audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        frames = audio.readframes(count)
    if width != 2 or not count or len(frames) != count * channels * width:
        raise ValueError('Expected complete PCM16 WAV')
    samples = struct.unpack('<' + 'h' * (len(frames) // 2), frames)
    rms = math.sqrt(sum(v * v for v in samples) / len(samples))
    if rms == 0:
        raise ValueError('Audio is silent')
    return {'duration':round(count/rate,3), 'bytes':len(body), 'sampleRate':rate, 'rms':round(rms,2)}


async def verify_voices():
    store = Store(settings.data_dir/'classroom.sqlite3')
    providers = Providers(store)
    try:
        for voice in providers.voices()['voices']:
            teacher = Teacher(model=settings.bailian_tts_model, voice=voice['id'])
            action = Action(type='speech', text='同学们好，欢迎来到小课堂。我们一起观察、思考，探索科学的奥秘。')
            signature = audio_signature(action, teacher)
            try:
                media = await providers.tts('voice_catalog', action.text, teacher, signature)
                evidence = audio_evidence((settings.data_dir/'media'/media['file']).read_bytes())
                async with httpx.AsyncClient(trust_env=False) as client:
                    response = await client.get(settings.openmaic_origin+'/api/media/'+media['id'])
                    response.raise_for_status()
                    if response.content != (settings.data_dir/'media'/media['file']).read_bytes():
                        raise ValueError('Served audio differs from saved audio')
                store.put('voice_sample', digest([settings.bailian_base_url, teacher.model, teacher.voice]),
                          {'mediaId':media['id'], 'verifiedAt':now(), **evidence})
                print(json.dumps({'voice':teacher.voice, 'model':teacher.model, 'mediaId':media['id'], **evidence}), flush=True)
            except DomainError as exc:
                print(json.dumps({'voice':teacher.voice, 'error':exc.code, 'message':exc.message}, ensure_ascii=False), flush=True)
                raise SystemExit(1)
    finally:
        await providers.close()
        store.close()


async def recover_course(stage_id):
    async with httpx.AsyncClient(base_url=settings.openmaic_origin, timeout=30, trust_env=False) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            if response.status_code >= 400:
                print(json.dumps({'apiError':response.status_code, 'detail':response.json()}, ensure_ascii=False), flush=True)
                raise SystemExit(1)
            return response.json()
        sessions = await request('GET', '/api/sessions')
        sid = next(s['id'] for s in sessions if s['stageId'] == stage_id)
        initial = await request('GET', '/api/courses/'+stage_id)
        for scene in initial['scenes']:
            stage = await request('GET', '/api/courses/'+stage_id)
            current = next(s for s in stage['scenes'] if s['id'] == scene['id'])
            ids = [a['id'] for a in current['actions'] if a['type']=='speech' and a['audioStatus']!='ready']
            if not ids:
                continue
            job = await request('POST', f'/api/courses/{stage_id}/scenes/{scene["id"]}/tts',
                                json={'sessionId':sid, 'expectedRevision':stage['revision'], 'requestId':uid('repair_tts'), 'actionIds':ids})
            while job['status']=='running':
                await asyncio.sleep(1)
                job = await request('GET', '/api/narration-jobs/'+job['id'])
            print(json.dumps({'sceneId':scene['id'], 'jobId':job['id'], 'status':job['status'],
                              'segments':[{k:s[k] for k in ('actionId','status','error') if k in s} for s in job['segments']]}, ensure_ascii=False), flush=True)
            if job['status'] != 'completed':
                raise SystemExit(1)
        stage = await request('GET', '/api/courses/'+stage_id)
        evidence = []
        for scene in stage['scenes']:
            for action in scene['actions']:
                if action['type'] != 'speech':
                    continue
                if action['audioStatus'] != 'ready' or action['audioSignature'] != audio_signature(Action.model_validate(action), Teacher.model_validate(stage['teacher'])):
                    raise ValueError('Audio is missing or stale')
                response = await client.get('/api/media/'+action['audioId'])
                response.raise_for_status()
                evidence.append(audio_evidence(response.content))
        print(json.dumps({'courseId':stage_id, 'revision':stage['revision'], 'verifiedSegments':len(evidence),
                          'totalSeconds':round(sum(e['duration'] for e in evidence),2)}), flush=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course')
    args = parser.parse_args()
    await verify_voices()
    if args.course:
        await recover_course(args.course)


if __name__=='__main__':
    asyncio.run(main())
