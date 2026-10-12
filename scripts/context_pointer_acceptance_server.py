"""Isolated deterministic UI acceptance: real LangGraph, browser effects and ACK."""
import json
import shutil
import sys
import tempfile
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import config
PROJECT = config.ROOT
FIXTURE = Path(tempfile.mkdtemp(prefix='context-pointer-', dir=PROJECT/'data'))
for name in ('frontend','generators'):
    (FIXTURE/name).symlink_to(PROJECT/name, target_is_directory=True)
shutil.copytree(PROJECT/'skills', FIXTURE/'skills')
config.ROOT = FIXTURE
config.settings.openmaic_port = 8010
config.settings.openmaic_origin = 'http://127.0.0.1:8010'
from backend import app as service
from backend.models import Stage, Scene, Plan, PlanPage, Teacher

class ControlledModel:
    async def generate(self, system, messages, tools, on_delta):
        record = {'system':system,'messages':messages,'tools':tools}
        with (FIXTURE/'requests.jsonl').open('a') as log:
            log.write(json.dumps(record, ensure_ascii=False)+'\n')
        if system.startswith('You are the Director of a multi-agent classroom.'):
            evidence=json.loads(messages[0]['content'])
            text=json.dumps({'next':'teacher' if not evidence['spokenRoleIds'] else 'wait'})
            return {'text':text,'calls':[],'usage':{},'finishReason':'stop'}
        context=json.loads(system.split('# Automatically supplied classroom evidence\n')[1])
        question=messages[-1].get('content','') or ''
        tool=next((name for name,word in (('spotlight','聚光'),('laser','激光')) if word in question), None)
        if tool and not any(m['role']=='tool' for m in messages):
            return {'text':'','calls':[{'id':'pointer-'+tool,'name':tool,'parameters':{'elementId':'title'},'arguments':'{"elementId":"title"}'}], 'usage':{},'finishReason':'tool_calls'}
        text='请理解题目描述，再根据课堂所学判断；尚未提交时我不会直接给出正确选项。' if context['type']=='quiz' else '标题已在当前页显示，操作结果来自浏览器的真实回执。'
        on_delta(text)
        return {'text':text,'calls':[],'usage':{},'finishReason':'stop'}
    async def close(self):
        pass

class ControlledTTS:
    async def tts(self, stage_id, text, teacher, signature, **kwargs):
        media={'id':'fixture-audio','stageId':stage_id,'ownerId':'local','mime':'audio/wav','duration':0.3,'file':'fixture.wav'}
        service.store.put('media',media['id'],media)
        return media

media_dir=config.settings.data_dir/'media';media_dir.mkdir(parents=True)
with wave.open(str(media_dir/'fixture.wav'),'wb') as f:
    f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*4800)
pages=[PlanPage(id='slot-slide',title='聚光和激光验收',type='slide',brief='当前页指示'),PlanPage(id='slot-quiz',title='无工具测验问答',type='quiz',brief='答案保护')]
scenes=[Scene(id='slide1',planPageId=pages[0].id,title=pages[0].title,brief=pages[0].brief,type='slide',content={'type':'slide','elements':[{'id':'title','type':'text','x':100,'y':140,'width':700,'height':100,'text':'聚光与激光：当前页绑定'},{'id':'body','type':'text','x':100,'y':320,'width':700,'height':100,'text':'模型仅传 elementId，运行层绑定页面'}]},actions=[{'id':'speech-slide','type':'speech','text':'验收讲解'}]),Scene(id='quiz1',planPageId=pages[1].id,title=pages[1].title,brief=pages[1].brief,type='quiz',content={'type':'quiz','questions':[{'id':'q1','text':'光由空气进入水时，可能发生什么？','options':[{'id':'A','text':'传播方向改变'},{'id':'B','text':'始终保持方向不变'}],'answer':'A','explanation':'折射可能改变方向'}]},actions=[{'id':'speech-quiz','type':'speech','text':'请理解题意'}])]
stage=Stage(id='pointer-acceptance',title='当前页工具验收（隔离数据）',description='固定模型，真实浏览器执行',approvedPlan=Plan(title='当前页工具验收',audience='验收',objectives=['验证真实回执'],pages=pages),teacher=Teacher(model='qwen3-tts-flash',voice='Cherry'),scenes=scenes)
service.store.put('stage',stage.id,stage.model_dump());service.store.put('course_owner',stage.id,{'ownerId':'local'})
service.store.session(stage.id)
service.classroom_runtime.model=ControlledModel()
service.classrooms.providers=ControlledTTS()
print('FIXTURE='+str(FIXTURE), flush=True)
if __name__=='__main__':
    import uvicorn
    uvicorn.run(service.app, host='127.0.0.1', port=8010, access_log=False)
