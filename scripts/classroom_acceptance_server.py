"""Opt-in real-provider classroom acceptance, isolated from authoring data.

Run from the Python project: .venv/bin/python scripts/classroom_acceptance_server.py
Reads an existing optics course, copies media, and synthesizes five short clips
once in data/classroom-acceptance-env. Never changes the source course/database.
"""
import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import config
from backend.models import Stage, Action, audio_signature, digest
from backend.providers import Providers
from backend.store import Store

PROJECT = config.ROOT
FIXTURE = PROJECT / 'data' / 'classroom-acceptance-env'
FIXTURE.mkdir(parents=True, exist_ok=True)
for target in ('frontend', 'skills', 'generators'):
    link = FIXTURE / target
    if not link.exists():
        link.symlink_to(PROJECT / target, target_is_directory=True)
config.ROOT = FIXTURE
config.settings.openmaic_port = 8002
config.settings.openmaic_origin = 'http://127.0.0.1:8002'


async def seed():
    source = sqlite3.connect(f'file:{PROJECT / "data/classroom.sqlite3"}?mode=ro', uri=True)
    store = Store(config.settings.data_dir / 'classroom.sqlite3')
    providers = Providers(store)
    try:
        row = source.execute("SELECT body FROM records WHERE kind='stage' AND id=?",
            ('stage_64e91b2b42db4adc967a470046b0a575',)).fetchone()
        if not row:
            raise RuntimeError('验收依赖现有五页折射课；未找到，不能伪造真实课件验收')
        stage = Stage.model_validate(json.loads(row[0]))
        existing = store.find('stage','acceptance-optics')
        if existing:
            # Keep enough speech time to test an actual mid-audio interruption.
            saved = Stage.model_validate(existing)
            speech = next(a for a in stage.scenes[2].actions if a.type=='speech')
            if saved.scenes[2].actions[-1].text != speech.text:
                record = json.loads(source.execute("SELECT body FROM records WHERE kind='media' AND id=?",(speech.audioId,)).fetchone()[0])
                shutil.copy2(PROJECT/'data/media'/record['file'],config.settings.data_dir/'media'/record['file'])
                record.update(stageId=saved.id,ownerId='local')
                store.put('media',record['id'],record)
                saved.scenes[2].actions[-1] = speech
                saved.revision += 1
                store.put('stage',saved.id,saved.model_dump())
            return
        stage.id = 'acceptance-optics'
        stage.title = '课堂运行验收：光的折射（隔离数据）'
        stage.approvedPlan.title = stage.title
        stage.revision = 1
        media_dir = config.settings.data_dir / 'media'
        media_dir.mkdir(parents=True, exist_ok=True)
        for i, scene in enumerate(stage.scenes):
            if scene.type == 'slide':
                for element in scene.content.elements:
                    if element.mediaId:
                        record = json.loads(source.execute("SELECT body FROM records WHERE kind='media' AND id=?", (element.mediaId,)).fetchone()[0])
                        shutil.copy2(PROJECT / 'data/media' / record['file'], media_dir / record['file'])
                        record.update(stageId=stage.id, ownerId='local')
                        store.put('media', record['id'], record)
            speech = Action(id=f'acceptance-speech-{i}', type='speech', text=[
                '光在空气和水之间拐弯了，我们一起观察。',
                '角度从法线量起。想一想，水里的角更大还是更小？',
                '先把入射角设为五度，再观察光线。',
                '眼睛沿直线判断，看到的位置可能和实际不同。',
                '请完成这三道题。提交后你可以向老师提问。'][i])
            if i == 2:
                speech.text = next(a.text for a in scene.actions if a.type=='speech')
            signature = audio_signature(speech, stage.teacher)
            media = await providers.tts(stage.id, speech.text, stage.teacher, signature)
            speech.audioId, speech.audioSignature = media['id'], signature
            speech.audioStatus, speech.duration = 'ready', media['duration']
            scene.actions = [speech]
            if scene.type == 'interactive':
                # Same saved experiment and bridge contract as the original course.
                angle = next(v for v in scene.content.variables if v.max >= 45)
                scene.actions.insert(0, Action(id='acceptance-state', type='widget_setState', state={angle.name: 5}))
            if i < 2:
                scene.actions.append(Action(id=f'acceptance-discussion-{i}', type='discussion',
                    topic='光从空气斜着进入水时，两个角有什么不同？',
                    prompt='用一句话说说观察到的现象。', initiatorId='curious' if i == 0 else 'thinker'))
        store.put('stage', stage.id, stage.model_dump())
        store.put('course_owner', stage.id, {'ownerId':'local'})
        store.put('course_approval', stage.id, {'planHash':digest(stage.approvedPlan.model_dump())})
        print('Isolated classroom acceptance fixture ready on port 8002; real TTS saved.', flush=True)
    finally:
        await providers.close()
        store.close()
        source.close()


if __name__ == '__main__':
    asyncio.run(seed())
    import uvicorn
    uvicorn.run('backend.app:app', host='127.0.0.1', port=8002, access_log=False)
