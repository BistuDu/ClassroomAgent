"""Checkpointed director/actor graph. Browser effects never count as success on send."""
import asyncio
import json
import re
import time
from contextlib import suppress
from contextvars import ContextVar
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import START, END, StateGraph
from langgraph.types import Command, interrupt

from .classroom_model import ClassroomModel
from .classroom_prompts import actor_prompt, director_prompt
from .classroom_tools import capability_instructions, tool_schemas
from .courses import DomainError, fail
from .models import Teacher, digest, uid
from .classroom_models import PlaybackCursor
from .store import now


event_identity = ContextVar('classroom_event_identity', default=None)


class RoundState(TypedDict, total=False):
    classroomId: str
    dialogueId: str
    sceneId: str
    endReason: str
    waitReason: str
    roundId: str
    generation: int
    question: str
    initiator: str
    actor: str
    count: int
    toolCount: int
    modelCount: int
    spent: float
    messages: list
    result: dict
    callIndex: int
    chunks: list[str]
    chunkIndex: int
    pendingId: str
    messageId: str
    history: list


def sentences(text):
    parts = re.split(r'(?<=[。！？!?\n])', text)
    chunks, current = [], ''
    for part in parts:
        while len(part) > 350:
            if current.strip():
                chunks.append(current.strip())
                current = ''
            chunks.append(part[:350])
            part = part[350:]
        if len(current) + len(part) > 350 and current.strip():
            chunks.append(current.strip())
            current = ''
        current += part
    if current.strip():
        chunks.append(current.strip())
    return chunks


class ClassroomRuntime:
    def __init__(self, rooms, model=None):
        self.rooms, self.store, self.config = rooms, rooms.store, rooms.config
        rooms.runtime = self
        self.model = model or ClassroomModel(self.config)
        self.graph = None
        self.checkpoints = None
        self.tasks, self.locks, self.watchers = {}, {}, {}

    async def initialize(self):
        if self.graph is not None:
            return
        self.checkpoints = AsyncSqliteSaver.from_conn_string(str(self.config.data_dir / 'classroom-checkpoints.sqlite3'))
        saver = await self.checkpoints.__aenter__()
        builder = StateGraph(RoundState)
        for name in ('director', 'actor', 'prepare_tool', 'wait_tool', 'prepare_audio', 'wait_audio', 'wait_user', 'end_dialogue'):
            builder.add_node(name, getattr(self, name))
        builder.add_edge(START, 'director')
        builder.add_conditional_edges('director', lambda s: 'end_dialogue' if s['actor']=='end' else 'wait_user' if s['actor']=='wait' else 'actor')
        builder.add_conditional_edges('actor', lambda s: 'wait_user' if s['actor'] == 'wait' else 'prepare_audio' if s['chunks'] else 'prepare_tool' if s['result']['calls'] else 'director')
        builder.add_conditional_edges('prepare_tool', lambda s: 'wait_tool' if s.get('pendingId') else 'prepare_tool' if s['callIndex'] < len(s['result']['calls']) else 'actor')
        builder.add_conditional_edges('wait_tool', lambda s: 'prepare_tool' if s['callIndex'] < len(s['result']['calls']) else 'actor')
        builder.add_edge('prepare_audio', 'wait_audio')
        builder.add_conditional_edges('wait_audio', lambda s: 'prepare_audio' if s['chunkIndex'] < len(s['chunks']) else 'prepare_tool' if s['result']['calls'] else 'director')
        builder.add_edge('wait_user', 'director')
        builder.add_edge('end_dialogue', END)
        self.graph = builder.compile(checkpointer=saver)
        # No external calls during recovery; preserve checkpoints and saved media.
        for op in self.store.list('learning_op'):
            if op['state'] == 'running':
                self.rooms.finish_op(op, 'unknown', {'error': '服务重启，操作结果待核实'})
        for session in self.store.list('learning'):
            if session['ownerId'] != self.store.owner_id:
                continue
            if session['state'] not in ('paused', 'version_conflict', 'waiting_lesson', 'waiting_user'):
                self.rooms.update(session['id'], state='interrupted', error='课堂已恢复，请选择继续互动或继续讲课；不会自动播放')
                self.rooms.set_dialogue_status(session['id'], 'interrupted', 'service_restart')
                self.rooms.emit(session['id'], 'interrupted', {'message': '服务重启，已保存课堂保留'})
        self.store.db.execute("DELETE FROM records WHERE kind='learning_control'")

    def graph_config(self, cid):
        return {'configurable': {'thread_id': cid}, 'recursion_limit': 250}

    def active(self, state):
        session = self.rooms.get(state['classroomId'], live=True)
        if session['generation'] != state['generation'] or session['roundId'] != state['roundId']:
            fail('CLASSROOM_STALE', '旧课堂轮次已撤销')
        did = state.get('dialogueId') or session.get('activeDialogueId')
        if did != session.get('activeDialogueId'):
            fail('CLASSROOM_STALE', '旧互动会话已结束')
        state['dialogueId'] = did
        if not state.get('sceneId'):state['sceneId'] = session['cursor']['sceneId']
        if state['sceneId'] != session['cursor']['sceneId']:
            fail('CLASSROOM_STALE', '旧页面已撤销')
        event_identity.set({'classroomId':session['id'], 'dialogueId':did,
                            'roundId':state['roundId'], 'generation':state['generation'], 'sceneId':state['sceneId']})
        return session

    async def paid(self, state, key, kind, arguments, callback):
        self.active(state)
        op = self.rooms.operation(state['classroomId'], state['roundId'] + ':' + key, kind, arguments)
        if op['state'] == 'completed':
            return op['result'], 0
        if op['state'] != 'pending':
            fail('CLASSROOM_UNCERTAIN', '该操作中断或结果未知，不能自动重复请求；请停止后明确重试')
        self.rooms.finish_op(op, 'running')
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.config.classroom_provider_timeout_seconds):
                result = await callback()
            self.active(state)
            self.rooms.finish_op(op, 'completed', result)
            return result, time.monotonic() - started
        except BaseException as exc:
            uncertain = isinstance(exc, (asyncio.CancelledError, TimeoutError)) or (
                isinstance(exc, DomainError) and exc.code in ('MEDIA_UNCERTAIN', 'PROVIDER_NETWORK', 'CLASSROOM_MODEL_NETWORK'))
            self.rooms.finish_op(op, 'unknown' if uncertain else 'failed',
                                 {'error': self.config.redact(str(exc)) or type(exc).__name__})
            raise

    def write(self, kind, data=None, **identity):
        frozen = event_identity.get() or {}
        get_stream_writer()({'kind': kind, 'data': data or {}, **frozen, **identity})

    def bounded_history(self, cid):
        room = self.rooms.get(cid)
        did = room.get('activeDialogueId')
        if not did:return []
        dialogue = self.rooms.dialogue(did)
        messages = []
        # Filter final messages BEFORE pagination; token deltas cannot evict speech.
        rows = self.store.db.execute("SELECT body FROM learning_events WHERE dialogue=? AND classroom=? AND json_extract(body,'$.kind') IN ('user_message','message_end') ORDER BY seq DESC", (did,cid))
        budget = self.config.classroom_context_tokens // 3
        recent, size, older = [], 0, []
        for row in rows:
            event = json.loads(row['body'])
            text = event['data'].get('text')
            if not text:continue
            content = f"[{event.get('speakerId') or '用户'}] {text}"
            length = len(content.encode('utf-8')) // 2 + 1
            if size + length <= budget // 2 and not older:
                recent.insert(0, {'role':'user','content':content});size += length
            else:
                # Bounded extractive evidence; full original remains in event log.
                older.insert(0,content[:180])
                if sum(map(len,older)) >= 2000:break
        summary = '\n'.join(older)[-2000:]
        if summary != dialogue['summary']:
            dialogue.update(summary=summary)
            self.store.put('learning_dialogue',did,dialogue)
        return ([{'role':'user','content':'当前话题较早发言摘录（按上下文预算省略，事实以当前证据为准）：\n'+summary}] if summary else []) + recent

    async def director(self, state):
        session = self.active(state)
        if state['count'] == 0 and state['initiator']:
            actor = state['initiator']
            return {'actor': actor, 'toolCount': 0, 'messages': []}
        if state['spent'] >= self.config.classroom_generation_timeout_seconds:
            self.write('budget_reached', {'message': '本轮生成时间预算已达到，等待你追问或继续讲课'})
            return {'actor': 'wait', 'waitReason':'budget_reached'}
        # Recent labelled excerpts and participant previews mirror the original.
        # Metadata, not text prefixes, identifies human and AI speakers.
        rows = self.store.db.execute(
            "SELECT body FROM learning_events WHERE dialogue=? AND classroom=? AND json_extract(body,'$.kind') IN ('user_message','message_end') ORDER BY seq DESC LIMIT 10",
            (state['dialogueId'], state['classroomId']))
        history = []
        for row in rows:
            event = json.loads(row['body'])
            text = event['data'].get('text') or ''
            if text:
                history.insert(0, {'kind': event['kind'], 'speakerId': event.get('speakerId') or 'user',
                                   'text': text[:200], 'truncated': len(text) > 200})
        evidence = json.dumps({'question': state['question'], 'context': self.rooms.context(state['classroomId']),
                               'history': history, 'turnCount': state['count'],
                               'responded': [{'speakerId': item['speakerId'], 'text': item['text'][:200],
                                              'truncated': len(item['text']) > 200} for item in state['history'][-10:]],
                               'spokenRoleIds': sorted({item['speakerId'] for item in state['history']}),
                               'currentRound':state['history'][-8:]}, ensure_ascii=False)
        prompt = director_prompt(state['count'], state['initiator'], history, state['history'],
                                 session['roles'], state['question'])
        saved = self.store.find('learning_op', state['classroomId'] + ':' + state['roundId'] + ':director:' + str(state['count']))
        if saved:
            prompt = saved['arguments']['system']
            evidence = saved['arguments']['messages'][0]['content']
        result, elapsed = await self.paid(state, 'director:' + str(state['count']), 'model',
            {'system': prompt, 'messages': [{'role': 'user', 'content': evidence}]},
            lambda: self.model.generate(prompt, [{'role': 'user', 'content': evidence}], [], lambda _: None))
        try:
            decision = json.loads(result['text'].strip().removeprefix('```json').removesuffix('```').strip())
            selected = decision.get('next_agent', decision.get('next'))
            actor = {'USER': 'wait', 'END': 'end'}.get(selected, selected)
        except (ValueError, KeyError, TypeError):
            fail('CLASSROOM_DIRECTOR', '调度器没有返回有效下一角色')
        if actor not in ('teacher', 'curious', 'notetaker', 'thinker', 'wait', 'end'):
            fail('CLASSROOM_DIRECTOR', '调度器返回未知角色')
        if actor=='end' and 'next_agent' not in decision and decision.get('reason')!='topic_complete':
            fail('CLASSROOM_DIRECTOR', '调度器结束原因无效')
        if len(state['history']) >= 2 and state['history'][-1] == state['history'][-2]:
            actor = 'wait'
            self.write('budget_reached', {'message':'检测到重复无进展，等待你继续'})
        return {'waitReason':'no_progress' if len(state['history'])>=2 and state['history'][-1]==state['history'][-2] else '', 'endReason':'topic_complete' if actor == 'end' else '', 'actor': actor, 'spent': state['spent'] + elapsed, 'toolCount': 0, 'messages': []}

    async def actor(self, state):
        session = self.active(state)
        role = next((r for r in session['roles'] if r['id'] == state['actor']), None)
        if role is None or role['id'] not in ('teacher', 'curious', 'notetaker', 'thinker'):
            fail('CLASSROOM_TOOL_ROLE', '无法识别当前课堂角色，不能请求模型')
        prompt = actor_prompt(role, session['roles'], state['history'],
                              state['initiator'], state['question'])
        context = self.rooms.context(state['classroomId'])
        tools = tool_schemas(role['id'], context['type'])
        prompt += capability_instructions(tools)
        prompt += '\n\n# Automatically supplied classroom evidence\n' + json.dumps(context, ensure_ascii=False)
        messages = state['messages'] or [
            *self.bounded_history(state['classroomId']),
            {'role': 'user', 'content': '本轮问题/讨论：' + state['question']}]
        # Old checkpoints may carry a standalone evidence message. New intent
        # uses one refreshed system section; saved intent below stays frozen.
        messages = [m for m in messages if not (m.get('role') == 'user'
                    and str(m.get('content', '')).startswith('当前页真实证据：'))]
        if state['toolCount'] >= self.config.classroom_max_tool_calls or state['spent'] >= self.config.classroom_generation_timeout_seconds:
            self.write('budget_reached', {'message': '老师演示工具达到预算，等待用户'})
            return {'actor': 'wait', 'chunks': [], 'result': {'calls': [], 'text': ''}, 'waitReason':'budget_reached'}
        message_id = state['roundId'] + ':message:' + str(state['modelCount'])
        saved = self.store.find('learning_op', state['classroomId'] + ':' + state['roundId'] + ':actor:' + str(state['modelCount']))
        policy = {'version': 2, 'sceneId': context['sceneId'], 'tools': tools,
                  'roundId': state['roundId'], 'generation': state['generation'],
                  'instanceId': session['cursor']['instanceId']}
        arguments = {'system': prompt, 'messages': messages, 'actor': role['id'], 'toolPolicy': policy}
        if saved:
            if saved['arguments']['actor'] != role['id']:
                fail('REQUEST_CONFLICT', '恢复角色与原模型操作不一致')
            # Frozen intent and hash must survive upgrade/replay. Completed
            # operations never call the provider again; effects are reauthorized.
            arguments = saved['arguments']
            if saved['state'] == 'pending' and arguments.get('toolPolicy') != policy:
                fail('CLASSROOM_TOOL_POLICY', '旧模型操作缺少当前工具权限或页面已变化，已保留记录；请重新提问')
            prompt, messages = arguments['system'], arguments['messages']
        self.write('message_start', {}, speakerId=role['id'], messageId=message_id)
        result, elapsed = await self.paid(state, 'actor:' + str(state['modelCount']), 'model',
            arguments,
            lambda: self.model.generate(prompt, messages, tools,
                lambda delta: self.write('text_delta', {'text': delta}, speakerId=role['id'], messageId=message_id)))
        # Reject explicit forged dialogue instead of voicing it as one actor.
        # Merely addressing a classmate by name remains allowed.
        labels = {'teacher':'老师', 'curious':'好奇宝宝', 'notetaker':'笔记员', 'thinker':'思考者'}
        others = '|'.join(re.escape(name) for rid,name in labels.items() if rid != role['id'])
        if re.search(r'(?:^|[\n：:；;])\s*(?:' + others + r')\s*(?:[:：]|——)', result['text']):
            self.write('message_end', {'text': result['text'], 'finishReason':'role_conflict', 'usage':result['usage']},
                       speakerId=role['id'],messageId=message_id)
            fail('CLASSROOM_ROLE_REPLY', '角色回复冒充其他同学或老师，已停止配音；请追问或继续讲课')
        self.write('message_end', {'text': result['text'], 'finishReason': result['finishReason'], 'usage': result['usage']},
                   speakerId=role['id'], messageId=message_id)
        calls = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}}
                 for c in result['calls']]
        assistant = {'role': 'assistant', 'content': result['text'] or None}
        if calls:
            assistant['tool_calls'] = calls
        history = state['history'] + ([{'speakerId': role['id'], 'text': result['text']}] if result['text'] else [])
        # Calls are processed after any preceding speech, then the actor sees actual receipts.
        return {'result': result, 'messages': [*messages, assistant], 'callIndex': 0,
                'chunks': sentences(result['text']), 'chunkIndex': 0, 'messageId': message_id,
                'history': history, 'spent': state['spent'] + elapsed, 'modelCount': state['modelCount'] + 1,
                'count': state['count'] + (0 if calls else 1), 'pendingId': ''}

    def authorize_effect(self, state, call, previous=None):
        """Authorize against the saved model intent, never a newly selected page."""
        session = self.active(state)
        model_op = self.store.find('learning_op', state['classroomId'] + ':' +
            state['roundId'] + ':actor:' + str(state['modelCount'] - 1))
        if not model_op or model_op['generation'] != state['generation'] or model_op['roundId'] != state['roundId']:
            fail('CLASSROOM_TOOL_POLICY', '缺少工具调用的原模型意图，不能安全续接')
        binding = model_op['arguments'].get('toolPolicy') or {}
        original_calls = (model_op.get('result') or {}).get('calls', [])
        if model_op['state'] != 'completed' or not any(
                c.get('id') == call['id'] and c.get('name') == call['name']
                and c.get('parameters') == call['parameters'] for c in original_calls):
            fail('CLASSROOM_TOOL_POLICY', '工具调用与已保存模型结果不一致')
        if model_op['arguments'].get('actor') != state['actor'] or binding.get('sceneId') != state['sceneId']:
            fail('CLASSROOM_TOOL_POLICY', '原角色或页面绑定无效，不能安全续接')
        version = binding.get('version')
        if version not in (1, 2) or call['name'] not in {t['name'] for t in binding.get('tools', [])}:
            fail('CLASSROOM_TOOL_POLICY', '工具不在原请求权限内')
        if version == 2 and (binding.get('roundId') != state['roundId'] or
                            binding.get('generation') != state['generation'] or 'instanceId' not in binding):
            fail('CLASSROOM_TOOL_POLICY', '原执行身份不完整')
        if previous and (previous['generation'] != state['generation'] or
                         previous['roundId'] != state['roundId'] or
                         previous['arguments'].get('sceneId') != binding['sceneId'] or
                         previous['arguments'].get('name') != call['name'] or
                         (version == 2 and previous['arguments'].get('instanceId') != binding['instanceId']) or
                         previous['arguments'].get('parameters') != call['parameters']):
            fail('CLASSROOM_STALE', '保存的演示身份与原请求不一致')
        self.rooms.validate_tool(state['classroomId'], state['actor'], call['name'],
            call['parameters'], bound_scene_id=binding['sceneId'], legacy=version == 1)
        return binding

    async def prepare_tool(self, state):
        session = self.active(state)
        call = state['result']['calls'][state['callIndex']]
        identity = {'speakerId': state['actor'], 'toolCallId': call['id'], 'messageId': state['messageId']}
        self.write('tool_start', {'name': call['name'], 'parameters': call['parameters']}, **identity)
        key = state['roundId'] + ':tool:' + call['id']
        previous = self.store.find('learning_op', state['classroomId'] + ':' + key)
        # A settled effect is a recorded fact, not a request for re-execution.
        if previous and previous['state'] in ('completed', 'failed'):
            old = previous['arguments']
            if (previous['generation'] != state['generation'] or previous['roundId'] != state['roundId']
                    or old.get('sceneId') != state['sceneId'] or old.get('name') != call['name']
                    or old.get('parameters') != call['parameters']):
                fail('CLASSROOM_STALE', '保存的已完成演示与原请求不一致')
            result = previous['result']
            self.write('tool_end', {'name': call['name'], 'result': result}, **identity)
            brief = {'ok': previous['state'] == 'completed', 'observation': result.get('result'), 'status': result['status']}
            self.rooms.update(state['classroomId'], state='running', pending=None)
            return {'messages': [*state['messages'], {'role': 'tool', 'tool_call_id': call['id'],
                    'content': json.dumps(brief, ensure_ascii=False)[:12000]}],
                    'callIndex': state['callIndex'] + 1, 'pendingId': '', 'toolCount': state['toolCount'] + 1}
        try:
            if state['toolCount'] >= self.config.classroom_max_tool_calls:
                fail('CLASSROOM_TOOL_BUDGET', '本轮角色工具达到上限')
            binding = self.authorize_effect(state, call, previous)
            value = None
        except (DomainError, ValueError) as exc:
            value = {'ok': False, 'error': self.config.redact(str(exc))}
        if value is not None:
            self.write('tool_end', {'name': call['name'], 'result': value}, **identity)
            return {'messages': [*state['messages'], {'role': 'tool', 'tool_call_id': call['id'],
                    'content': json.dumps(value, ensure_ascii=False)}], 'callIndex': state['callIndex'] + 1,
                    'pendingId': '', 'toolCount': state['toolCount'] + 1}
        arguments = {'name': call['name'], 'parameters': call['parameters'],
                     'sceneId': binding['sceneId'],
                     'instanceId': binding.get('instanceId', session['cursor']['instanceId']), **identity}
        if previous:
            # Browser delivery identity changes on refresh; journal intent does
            # not. This also reconciles a crash between intent and checkpoint.
            arguments = previous['arguments']
        op = self.rooms.operation(state['classroomId'], key, 'tool', arguments)
        if op['state'] in ('completed', 'failed'):
            result = op['result']
            self.write('tool_end', {'name': call['name'], 'result': result}, **identity)
            brief = {'ok': op['state'] == 'completed', 'observation': result.get('result'), 'status': result['status']}
            self.rooms.update(state['classroomId'], state='running', pending=None)
            return {'messages': [*state['messages'], {'role':'tool', 'tool_call_id':call['id'],
                'content':json.dumps(brief, ensure_ascii=False)[:12000]}],
                'callIndex':state['callIndex'] + 1, 'pendingId':'', 'toolCount':state['toolCount'] + 1}
        if op['state'] != 'pending':
            fail('CLASSROOM_UNCERTAIN', '演示结果未知或已撤销，不能自动重复执行')
        delivery = {**arguments, 'instanceId': session['cursor']['instanceId']}
        delivery['parameters'] = {**call['parameters'], 'sceneId': binding['sceneId']}
        op['deliveryInstanceId'] = delivery['instanceId']
        self.store.put('learning_op', op['id'], op)
        self.rooms.update(state['classroomId'], state='waiting_tool', pending={'kind': 'tool', 'operationId': op['id'], **delivery})
        self.write('execution_pending', {'operationId': op['id'], 'kind': 'tool', **delivery}, **identity)
        return {'pendingId': op['id']}

    async def wait_tool(self, state):
        answer = interrupt({'kind': 'tool', 'operationId': state['pendingId']})
        self.active(state)
        op = self.store.get('learning_op', state['pendingId'])
        if answer.get('operationId') != op['id'] or op['state'] not in ('completed', 'failed'):
            fail('CLASSROOM_ACK', '演示尚无真实回执')
        result = op['result']
        call = state['result']['calls'][state['callIndex']]
        self.write('tool_end', {'name': call['name'], 'result': result},
                   speakerId=state['actor'], toolCallId=call['id'], messageId=state['messageId'])
        if op['state'] == 'completed':
            receipt = result.get('result') or {}
            changes = {'lastObservation': receipt}
            if isinstance(receipt.get('state'), dict):
                current = self.rooms.get(state['classroomId'])['cursor']
                changes['cursor'] = {**current, 'experimentState': receipt['state']}
            self.rooms.update(state['classroomId'], **changes)
        self.rooms.update(state['classroomId'], state='running', pending=None)
        brief = {'ok': op['state'] == 'completed', 'observation': result.get('result'), 'status': result['status']}
        return {'messages': [*state['messages'], {'role': 'tool', 'tool_call_id': call['id'],
                 'content': json.dumps(brief, ensure_ascii=False)[:12000]}],
                'callIndex': state['callIndex'] + 1, 'pendingId': '', 'toolCount': state['toolCount'] + 1}

    async def prepare_audio(self, state):
        session = self.active(state)
        text = state['chunks'][state['chunkIndex']]
        role = next(r for r in session['roles'] if r['id'] == state['actor'])
        teacher = Teacher(model=role['model'], voice=role['voice'],
                          speed=(session['stage'].get('teacher') or {}).get('speed', 1))
        signature = digest([session['id'], state['roundId'], state['messageId'], state['chunkIndex'],
                            role['id'], teacher.model_dump(), text])
        key = 'tts:' + state['messageId'] + ':' + str(state['chunkIndex'])
        arguments = {'text': text, 'speakerId': role['id'], 'voice': role['voice'], 'model': role['model'],
                     'signature': signature, 'sceneId': session['cursor']['sceneId']}
        try:
            media, elapsed = await self.paid(state, key, 'tts', arguments,
                lambda: self.rooms.providers.tts(session['stageId'], text, teacher, signature))
            self.rooms.reference_media(session['id'], media['id'])
            audio_args = {**arguments, 'audioId': media['id'], 'duration': media['duration']}
            op = self.rooms.operation(session['id'], state['roundId'] + ':audio:' + signature, 'audio', audio_args)
            self.rooms.update(session['id'], state='waiting_audio', pending={'kind': 'audio', 'operationId': op['id'], **audio_args})
            self.write('audio_ready', {'kind': 'audio', 'operationId': op['id'], **audio_args},
                       speakerId=role['id'], messageId=state['messageId'])
            return {'pendingId': op['id'], 'spent': state['spent'] + elapsed}
        except (DomainError, TimeoutError) as exc:
            # Persist the failed segment, still wait for an explicit text-only/retry choice.
            op = self.rooms.operation(session['id'], state['roundId'] + ':audio:' + signature, 'audio', arguments)
            self.rooms.update(session['id'], state='audio_error', error=str(exc),
                pending={'kind': 'audio', 'operationId': op['id'], **arguments, 'error': str(exc), 'ttsKey': key})
            self.write('audio_error', {'operationId': op['id'], 'error': str(exc), **arguments},
                       speakerId=role['id'], messageId=state['messageId'])
            return {'pendingId': op['id']}

    async def wait_audio(self, state):
        answer = interrupt({'kind': 'audio', 'operationId': state['pendingId']})
        self.active(state)
        op = self.store.get('learning_op', state['pendingId'])
        if answer.get('operationId') != op['id'] or op['state'] != 'completed':
            fail('CLASSROOM_AUDIO', '语音未播放完成或尚未明确仅文字继续')
        self.write('audio_end', {'operationId': op['id'], 'status': op['result']['status']},
                   speakerId=state['actor'], messageId=state['messageId'])
        self.rooms.update(state['classroomId'], state='running', pending=None, error=None)
        return {'chunkIndex': state['chunkIndex'] + 1, 'pendingId': ''}

    async def end_dialogue(self, state):
        self.active(state)
        cid=state['classroomId']
        with self.store.transaction():
            self.rooms.set_dialogue_status(cid,'completed',state['endReason'],source='classroom_graph')
            self.rooms.update(cid,state='waiting_lesson',pending=None,error=None)
        return {'pendingId':''}

    async def wait_user(self, state):
        room=self.rooms.get(state['classroomId'])
        # LangGraph re-enters this node on resume with the PREVIOUS round state.
        # Its pending interrupt receives the new state before the next director.
        if room['generation']==state['generation'] and room['roundId']==state['roundId']:
            self.active(state)
            with self.store.transaction():
                self.rooms.update(state['classroomId'], state='waiting_user', pending=None)
                self.rooms.set_dialogue_status(state['classroomId'],'waiting_user',state.get('waitReason') or None,source='classroom_graph')
            self.write('waiting_user', {'message':'可继续追问，或由你明确继续讲课'})
        answer=interrupt({'kind':'user'})
        if answer.get('kind')!='question':
            fail('CLASSROOM_INPUT','等待用户节点仅接受新一轮问题')
        return answer['state']

    async def cancel(self, cid, *, preserve_pending=False):
        task = self.tasks.pop(cid, None)
        if preserve_pending and task and not task.done() and self.rooms.get(cid).get('pending'):
            # A prepared browser effect is not checkpointed until the following
            # interrupt node settles. Give that local write time to finish.
            with suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 2)
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        watcher = self.watchers.pop(cid, None)
        if watcher and not watcher.done():
            watcher.cancel()
        session = self.rooms.get(cid)
        for op in self.store.list('learning_op'):
            if not preserve_pending and op['classroomId'] == cid and op['generation'] == session['generation'] and op['state'] == 'pending':
                self.rooms.finish_op(op, 'cancelled', {'error': '用户中断旧执行'})

    async def drive(self, cid, value):
        started = self.rooms.get(cid)
        try:
            async for mode, event in self.graph.astream(value, config=self.graph_config(cid), stream_mode=['custom', 'updates']):
                if mode == 'custom':
                    event = dict(event)
                    event.pop('classroomId', None)
                    room = self.rooms.get(cid)
                    if (event.get('generation')!=room['generation'] or event.get('roundId')!=room['roundId'] or event.get('dialogueId')!=room.get('activeDialogueId')):
                        continue
                    self.rooms.emit(cid, event.pop('kind'), event.pop('data', {}), source='classroom_graph', **event)
            pending = self.rooms.get(cid).get('pending')
            if pending and pending.get('operationId'):
                self.watchers[cid] = asyncio.create_task(self.timeout_receipt(cid, pending))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.rooms.get(cid)['generation'] != started['generation']:return
            self.rooms.set_dialogue_status(cid,'interrupted','execution_error')
            self.rooms.update(cid, state='interrupted', error=self.config.redact(str(exc)))
            self.rooms.emit(cid, 'interrupted', {'error': self.config.redact(str(exc))})

    async def timeout_receipt(self, cid, pending):
        seconds = max(self.config.classroom_ack_timeout_seconds, pending.get('duration', 0) + 30)
        await asyncio.sleep(seconds)
        session = self.rooms.get(cid)
        if (session.get('pending') or {}).get('operationId') == pending['operationId']:
            self.rooms.set_dialogue_status(cid,'interrupted','receipt_timeout')
            self.rooms.update(cid, state='interrupted', error='客户端回执超时；请恢复互动或继续讲课')
            self.rooms.emit(cid, 'receipt_timeout', {'operationId': pending['operationId']})

    async def receipt(self, cid, operation_id):
        session = self.rooms.get(cid)
        if not session.get('pending') or session['pending'].get('operationId') != operation_id:
            return session
        if session['pending']['kind'] == 'restore':
            op = self.store.get('learning_op', operation_id)
            if op['state'] == 'completed':
                return self.rooms.update(cid, state='lecture', cursor=session['returnCursor'],
                                         returnCursor=None, pending=None, error=None)
            return self.rooms.update(cid, state='interrupted', error='恢复演示失败，讲课保持暂停')
        op = self.store.get('learning_op', operation_id)
        if op['kind'] == 'audio' and op['state'] == 'failed':
            return self.rooms.update(cid, state='audio_error', error='语音播放失败，请重试或仅文字继续')
        prior = self.tasks.get(cid)
        async def resume():
            if prior and not prior.done():
                await prior
            watcher = self.watchers.pop(cid, None)
            if watcher:
                watcher.cancel()
            await self.drive(cid, Command(resume={'operationId': operation_id}))
        self.tasks[cid] = asyncio.create_task(resume())
        return self.rooms.get(cid)

    async def command(self, cid, args):
        await self.initialize()
        async with self.locks.setdefault(cid, asyncio.Lock()):
            session = self.rooms.get(cid, live=args.kind not in ('stop', 'pause'))
            if args.kind == 'navigate' or (args.kind=='stop' and args.confirmEnd):
                self.rooms.require_exit_confirmation(session,args)
            if args.cursor is not None and args.kind in ('continue', 'start', 'resume_interaction'):
                cursor = self.rooms.cursor(session, args.cursor)
                if cursor['sceneId'] != session['cursor']['sceneId']:
                    fail('CLASSROOM_PAGE', '恢复前不能改变当前页面')
                session = self.rooms.update(cid, cursor=cursor)
            if args.kind in ('question', 'join'):
                text, initiator = args.text.strip(), ''
                if args.kind == 'join':
                    marker = (session.get('pending') or {}).get('marker')
                    if not marker or marker['id'] != args.markerId or args.markerId in session['consumedDiscussions']:
                        fail('CLASSROOM_MARKER', '讨论点已处理或不在当前页')
                    text = marker['topic'] + '\n' + marker['prompt']
                    initiator = marker['initiatorId']
                if not text:
                    fail('CLASSROOM_INPUT', '请输入问题')
                if args.cursor is None:
                    fail('CLASSROOM_CURSOR', '提问前须确认暂停播放现场')
                cursor = self.rooms.cursor(session, args.cursor)
                if cursor['playing']:
                    fail('CLASSROOM_CURSOR', '讲课尚未暂停')
                if cursor['sceneId'] != session['cursor']['sceneId']:
                    fail('CLASSROOM_PAGE', '提问或参与讨论不能改变当前页面，请先切页')
                if args.kind == 'question' and re.fullmatch(r'(明白了[，, ]*)?(继续讲课|继续上课|回到讲课)[。！! ]*', text):
                    session = self.rooms.update(cid,cursor=cursor)
                    return await self.continue_lecture(cid, session)
                await self.cancel(cid)
                round_id, generation = uid('round'), session['generation'] + 1
                self.rooms.update(cid,roundId=round_id,generation=generation)
                did=session.get('activeDialogueId')
                if args.kind=='join' and did:
                    self.rooms.set_dialogue_status(cid,'completed','new_discussion',source='classroom_player');did=None
                if not did:
                    did=self.rooms.begin_dialogue(cid,text,'discussion' if args.kind=='join' else 'qa')['id']
                else:
                    self.rooms.set_dialogue_status(cid,'active',source='classroom_player')
                changes = {'generation': generation, 'roundId': round_id, 'state': 'running',
                           'cursor': cursor, 'pending': None, 'error': None,
                           'lastObservation': None,
                           'returnCursor': session['returnCursor'] or cursor}
                if args.kind == 'join':
                    changes['consumedDiscussions'] = {**session['consumedDiscussions'], args.markerId: 'joined'}
                self.rooms.update(cid, **changes)
                self.rooms.emit(cid, 'user_message', {'text': text}, source='classroom_player', messageId=args.requestId)
                state = RoundState(classroomId=cid, dialogueId=did, sceneId=cursor['sceneId'], roundId=round_id, generation=generation,
                    question=text, initiator=initiator, actor='', count=0, toolCount=0, modelCount=0,
                    spent=0, messages=[], result={}, callIndex=0, chunks=[], chunkIndex=0,
                    pendingId='', messageId='', history=[], waitReason='', endReason='')
                snapshot = await self.graph.aget_state(self.graph_config(cid))
                if snapshot.next == ('wait_user',) and snapshot.values.get('dialogueId',did)==did:
                    value = Command(resume={'kind': 'question', 'state': state})
                elif snapshot.next:
                    await self.graph.aupdate_state(self.graph_config(cid),state,as_node='wait_user')
                    value=None
                else:
                    # New input state restarts START without rewriting old paid intent.
                    value = state
                self.tasks[cid] = asyncio.create_task(self.drive(cid, value))
            elif args.kind == 'continue':
                return await self.continue_lecture(cid, session)
            elif args.kind == 'skip':
                marker = (session.get('pending') or {}).get('marker')
                if not marker or marker['id'] != args.markerId:
                    fail('CLASSROOM_MARKER', '没有对应待参与讨论')
                cursor = dict(session['cursor'], phase='after', playing=False)
                self.rooms.update(cid, state='lecture', generation=session['generation'] + 1, pending=None, cursor=cursor,
                    consumedDiscussions={**session['consumedDiscussions'], args.markerId: 'skipped'})
            elif args.kind in ('pause', 'stop', 'navigate'):
                # Validate before cancelling; malformed navigation has no side effects.
                cursor = self.rooms.cursor(session, args.cursor) if args.cursor else session['cursor']
                if args.kind == 'navigate' and not args.cursor:
                    fail('CLASSROOM_CURSOR', '切页必须提交新页稳定位置')
                await self.cancel(cid)
                if args.kind == 'navigate' or (args.kind=='stop' and args.confirmEnd):
                    self.rooms.set_dialogue_status(cid,'completed','user_'+args.kind,source='classroom_player')
                elif session.get('activeDialogueId'):
                    self.rooms.set_dialogue_status(cid,'interrupted','user_'+args.kind,source='classroom_player')
                self.rooms.update(cid, generation=session['generation'] + 1, state='paused', cursor=cursor,
                    returnCursor=None if args.kind == 'navigate' else session['returnCursor'], pending=None,
                    lastObservation=None if args.kind == 'navigate' else session.get('lastObservation'))
                if args.kind == 'stop':
                    self.store.db.execute("DELETE FROM records WHERE kind='learning_control' AND id=?", (cid,))
            elif args.kind == 'start':
                if session['returnCursor'] or session.get('pending'):
                    fail('CLASSROOM_WAITING', '请先恢复互动或继续讲课')
                self.rooms.update(cid, state='lecture', error=None)
            elif args.kind == 'resume_interaction':
                if self.tasks.get(cid) and not self.tasks[cid].done():
                    fail('RUN_ACTIVE', '课堂正在生成')
                pending = session.get('pending')
                if pending and pending.get('operationId'):
                    op = self.store.get('learning_op', pending['operationId'])
                    if op['state'] == 'pending':
                        if op['kind'] == 'tool':
                            snapshot = await self.graph.aget_state(self.graph_config(cid))
                            frozen = dict(snapshot.values)
                            try:
                                if not frozen.get('result') or frozen.get('callIndex', -1) not in range(len(frozen['result'].get('calls', []))):
                                    fail('CLASSROOM_TOOL_POLICY', '缺少原工具检查点，不能安全续接')
                                call = frozen['result']['calls'][frozen['callIndex']]
                                binding = self.authorize_effect(frozen, call, op)
                            except (DomainError, ValueError) as exc:
                                self.rooms.update(cid, state='interrupted', error=self.config.redact(str(exc)))
                                self.rooms.set_dialogue_status(cid, 'interrupted', 'execution_error')
                                raise
                            pending = {**pending, 'parameters': {**call['parameters'], 'sceneId': binding['sceneId']}}
                        if op['kind'] in ('tool', 'restore'):
                            op['deliveryInstanceId'] = session['cursor']['instanceId']
                            self.store.put('learning_op', op['id'], op)
                            pending = {**pending, 'instanceId': op['deliveryInstanceId']}
                        snapshot = await self.graph.aget_state(self.graph_config(cid))
                        if op['kind'] != 'restore' and snapshot.next not in (('wait_tool',), ('wait_audio',)):
                            self.rooms.update(cid, state='running', error=None, pending=pending)
                            self.tasks[cid] = asyncio.create_task(self.drive(cid, None))
                        else:
                            self.rooms.update(cid, state='waiting_audio' if op['kind'] == 'audio' else 'waiting_tool', error=None, pending=pending)
                    elif op['state'] == 'completed':
                        snapshot = await self.graph.aget_state(self.graph_config(cid))
                        if op['kind'] != 'restore' and snapshot.next not in (('wait_tool',), ('wait_audio',)):
                            self.rooms.update(cid, state='running', error=None)
                            self.tasks[cid] = asyncio.create_task(self.drive(cid, None))
                        else:
                            return await self.receipt(cid, op['id'])
                    else:
                        fail('CLASSROOM_UNCERTAIN', '操作失败或结果未知，请明确重试语音、追问或继续讲课')
                else:
                    snapshot = await self.graph.aget_state(self.graph_config(cid))
                    if snapshot.next and snapshot.next != ('wait_user',):
                        self.rooms.update(cid, state='running', error=None)
                        self.tasks[cid] = asyncio.create_task(self.drive(cid, None))
                    else:
                        self.rooms.update(cid, state='waiting_user', error=None)
            elif args.kind in ('text_only', 'retry_audio'):
                return await self.audio_choice(cid, session, args.kind)
            else:
                fail('CLASSROOM_INPUT', '未知课堂命令')
            self.rooms.emit(cid, 'state', {'state': self.rooms.get(cid)['state']}, source='classroom_player')
            return self.rooms.get(cid)

    async def continue_lecture(self, cid, session):
        if not session['returnCursor']:
            fail('CLASSROOM_CURSOR', '没有待恢复的讲课位置')
        await self.cancel(cid)
        self.rooms.set_dialogue_status(cid,'completed','user_continue',source='classroom_player')
        generation = session['generation'] + 1
        self.rooms.update(cid, generation=generation)
        cursor = session['returnCursor']
        op = self.rooms.operation(cid, 'restore:' + str(generation), 'restore',
            {'sceneId': cursor['sceneId'], 'instanceId': session['cursor']['instanceId'], 'cursor': cursor})
        return self.rooms.update(cid, state='waiting_tool', pending={'kind': 'restore', 'operationId': op['id'], **op['arguments']})

    async def audio_choice(self, cid, session, kind):
        pending = session.get('pending')
        if not pending or pending.get('kind') != 'audio':
            fail('CLASSROOM_AUDIO', '当前没有待处理语音')
        op = self.store.get('learning_op', pending['operationId'])
        if kind == 'text_only':
            self.rooms.finish_op(op, 'completed', {'status': 'text_only', 'result': {}})
            self.rooms.emit(cid, 'text_only', {'operationId': op['id']}, source='classroom_player')
            return await self.receipt(cid, op['id'])
        if pending.get('audioId'):
            self.rooms.finish_op(op, 'pending')
            return self.rooms.update(cid, state='waiting_audio', error=None)
        # Retry runs outside the command lock so stop/new question can cancel it.
        self.rooms.update(cid, state='waiting_audio', error=None)
        self.tasks[cid] = asyncio.create_task(self.retry_audio(cid, session, pending, op))
        return self.rooms.get(cid)

    async def retry_audio(self, cid, session, pending, op):
        # Explicit user retry: a new operation and force flag, never automatic paid replay.
        role = next(r for r in session['roles'] if r['id'] == pending['speakerId'])
        retry = self.rooms.operation(cid, uid('retry'), 'tts', pending)
        self.rooms.finish_op(retry, 'running')
        try:
            async with asyncio.timeout(self.config.classroom_provider_timeout_seconds):
                media = await self.rooms.providers.tts(session['stageId'], pending['text'],
                    Teacher(model=role['model'], voice=role['voice']), pending['signature'], force=True)
            self.rooms.finish_op(retry, 'completed', media)
            self.rooms.reference_media(cid, media['id'])
        except BaseException as exc:
            self.rooms.finish_op(retry, 'unknown', {'error': self.config.redact(str(exc))})
            if isinstance(exc, asyncio.CancelledError):
                raise
            if self.rooms.get(cid)['generation'] == session['generation']:
                self.rooms.update(cid, state='audio_error', error=self.config.redact(str(exc)))
            return
        if self.rooms.get(cid)['generation'] != session['generation']:
            return
        self.rooms.finish_op(op, 'pending')
        self.rooms.update(cid, state='waiting_audio', error=None,
                                 pending={**pending, 'audioId': media['id'], 'duration': media['duration']})

    async def close(self):
        for cid in list(self.tasks):
            await self.cancel(cid, preserve_pending=True)
        if self.checkpoints:
            await self.checkpoints.__aexit__(None, None, None)
        await self.model.close()
