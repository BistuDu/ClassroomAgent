"""Opt-in paid acceptance: real Pi Agent -> Skill read -> page -> browser check."""
import asyncio
import json
import shutil
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import uvicorn

from backend import config
from backend.config import ROOT, settings
from backend.models import Plan, PlanPage, Stage, Teacher, digest
from backend.store import now


async def main():
    folder = Path(tempfile.mkdtemp(prefix='skills-live-', dir=ROOT / 'data'))
    (folder / 'data').mkdir()
    shutil.copytree(ROOT / 'skills', folder / 'skills')
    for name in ('agent-runtime', 'node_modules', 'contracts', 'frontend', 'generators'):
        (folder / name).symlink_to(ROOT / name, target_is_directory=True)
    (folder / 'data' / 'browsers').symlink_to(ROOT / 'data' / 'browsers', target_is_directory=True)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    listener.listen()
    listener.setblocking(False)
    with patch.object(config, 'ROOT', folder), patch.object(settings, 'openmaic_origin', f'http://127.0.0.1:{port}'), \
            patch.object(settings, 'run_timeout_seconds', 360), patch.object(settings, 'provider_timeout_seconds', 120), \
            patch.object(settings, 'max_tool_calls', 20):
        from backend.app import app, courses, store, runtime
        plan = Plan(title='Skill 系统验收：光的反射', audience='初中生', objectives=['认识入射角与反射角'],
                    pages=[PlanPage(id='p1', title='入射角等于反射角', type='slide',
                                    brief='用简洁文字和两条光线说明入射角等于反射角')])
        stage = Stage(id='skill_acceptance_course', title=plan.title, approvedPlan=plan,
                      teacher=Teacher(model=settings.bailian_tts_model, voice=settings.bailian_tts_voice), updatedAt=now())
        store.put('stage', stage.id, stage.model_dump())
        store.put('course_owner', stage.id, {'ownerId':store.owner_id})
        store.put('course_approval', stage.id, {'planHash':digest(plan.model_dump()), 'approvalId':'fixture-approved'})
        session = store.session(stage.id)
        run = 'skill_acceptance_run'
        store.patch_session(session['id'], state='running', runId=run)
        store.put('run', run, {'id':run, 'sessionId':session['id'], 'state':'running', 'metadataVersion':3,
                              'courseTasks':{}, 'previewStageId':stage.id, 'haltFeedback':True})
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started:
                if serving.done():
                    await serving
                    raise RuntimeError('验收服务未启动')
                await asyncio.sleep(.05)
            prompt = (
                f'这是 Skill 系统真实验收，目标课程 {stage.id} 已有明确批准的一页方案。'
                '本次只做页面内容和程序检查，不制作讲稿、语音、图片或视觉检查，也不要求整课就绪。'
                '请根据 Skill 索引主动读取普通页面制作 Skill 及质量检查 Skill；'
                '使用 read_stage 或 list_scenes 核实课程、p1 和当前版本，然后直接操作 p1。'
                '然后 generate_scene 创建 p1，内容简洁，使用少量文字和光线图形，不用外部素材。'
                '生成后对真实 sceneId 调用 check_scene(mode=program)，必须实际执行，最后如实说明检查的缺项。'
                '请勿生成音频或为了整课完成度扩大验收范围。')
            await runtime.run(store.get('session',session['id']),prompt,False,'skill_acceptance_message')
            tools = [n for n in store.timeline(session['id'])['nodes'] if n['kind']=='tool']
            names = [n['data']['name'] for n in tools]
            saved = courses.stage(stage.id)
            checks = [c for c in store.list('inspection') if c['stageId']==stage.id]
            diagnostics = store.find('skill_diagnostics',run)
            summary = {'createdAt':now(), 'artifactDirectory':str(folder), 'model':settings.creation['model'],
                       'run':store.get('run',run), 'toolNames':names, 'sceneCount':len(saved.scenes),
                       'skillReads':[store.get('pi_tool_detail',session['id']+':'+run+':'+n['toolCallId'])['result']['details']['data']['skillId']
                                     for n in tools if n['data']['name']=='read_skill' and n['status']=='completed'],
                       'checks':checks, 'skillDiagnostics':diagnostics,
                       'allToolEventsFromSdk':all(n['source']=='pi' for n in tools)}
            summary['accepted'] = bool(summary['skillReads'] and len(saved.scenes)==1
                                       and any(c.get('executed') for c in checks)
                                       and 'generate_scene' in names and 'check_scene' in names
                                       and summary['allToolEventsFromSdk'])
            (folder / 'acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:summary[k] for k in ('accepted','artifactDirectory','model','toolNames','sceneCount','skillReads','allToolEventsFromSdk')},ensure_ascii=False))
            print(json.dumps({'checks':[{'executed':c.get('executed'),'passed':c['passed'],'issues':c.get('issues',[])} for c in checks]},ensure_ascii=False))
            if not summary['accepted']:
                raise SystemExit(1)
        finally:
            server.should_exit = True
            await serving
            listener.close()


if __name__ == '__main__':
    asyncio.run(main())
