"""Durable learning records, ownership, fences and browser execution receipts."""
import asyncio
import json
import time

from .classroom_models import (ClassroomSession, ClassroomRole, PlaybackCursor, NewClassroom,
                               ClassroomCommand, ClassroomProgress, ClassroomAck)
from .classroom_dialogues import DialogueRecords
from .config import settings
from .classroom_tools import available_tool_names
from .courses import fail
from .models import Stage, Teacher, digest, uid, Action
from .providers import VOICE_MODELS, validate_teacher
from .store import now


def fingerprint(stage):
    return digest({'plan': stage.approvedPlan.model_dump(), 'theme': stage.theme.model_dump(),
                   'teacher': stage.teacher.model_dump() if stage.teacher else None,
                   'scenes': [s.model_dump() for s in stage.scenes]})


class Classrooms(DialogueRecords):
    def __init__(self, store, courses, providers, config=settings):
        self.store, self.courses, self.providers, self.config = store, courses, providers, config
        self.runtime = None
        self.store.db.executescript('''
            CREATE TABLE IF NOT EXISTS learning_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, classroom TEXT NOT NULL,
                event_id TEXT NOT NULL UNIQUE, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS learning_order ON learning_events(classroom,seq);
        ''')
        self.migrate_dialogues()

    def get(self, cid, *, live=False):
        session = self.store.find('learning', cid)
        if not session or session['ownerId'] != self.store.owner_id:
            fail('ACCESS_OWNER', '课堂不存在或不属于当前用户')
        if live:
            stage = self.courses.stage(session['stageId'])
            if fingerprint(stage) != session['fingerprint']:
                self.set_dialogue_status(cid,'interrupted','course_changed')
                self.update(cid, state='version_conflict', error='课件已更新，请从当前版本重新开始课堂；旧历史仍保留')
                fail('REVISION_CONFLICT', '课堂绑定的课件内容已变化，不能继续旧动作')
        session.setdefault('activeDialogueId', None)
        return session

    def update(self, cid, **changes):
        with self.store.transaction():
            session = self.get(cid)
            session.update(changes, updatedAt=now())
            self.store.put('learning', cid, session)
        return session

    def create(self, args: NewClassroom):
        stage = self.courses.stage(args.stageId)
        if stage.revision != args.expectedRevision:
            fail('REVISION_CONFLICT', '课程已更新，请刷新后开始学习')
        if not stage.scenes:
            fail('CLASSROOM_EMPTY', '尚无已保存页面')
        request = self.store.owner_id + ':' + args.requestId
        with self.store.transaction():
            prior = self.store.find('learning_create', request)
            if prior:
                # Existing resume receipts were hashed with the removed selector.
                if prior['hash'] not in (digest(args.model_dump()), digest({**args.model_dump(), 'intent': 'resume'})):
                    fail('REQUEST_CONFLICT', '相同课堂创建标识不能使用不同参数')
                return self.get(prior['classroomId'])
            recent = next((s for s in self.store.list('learning')
                           if s['ownerId'] == self.store.owner_id and s['stageId'] == stage.id), None)
            if recent and recent['fingerprint'] == fingerprint(stage):
                session = recent
            else:
                teacher = stage.teacher or Teacher(model=self.config.bailian_tts_model,
                                                    voice=self.config.bailian_tts_voice)
                validate_teacher(teacher)
                voices = [v for v in VOICE_MODELS if teacher.model in VOICE_MODELS[v]]
                roles = [ClassroomRole(id='teacher', name='老师', description='讲解、演示和纠错',
                                       voice=teacher.voice, model=teacher.model)]
                for i, (role, name, description) in enumerate([
                    ('curious', '好奇宝宝', '提出相关追问，不打断讲课'),
                    ('notetaker', '笔记员', '整理关键知识，简短归纳'),
                    ('thinker', '思考者', '提出不同角度，主动验证猜想')]):
                    roles.append(ClassroomRole(id=role, name=name, description=description,
                                               voice=voices[i % len(voices)], model=teacher.model))
                session = ClassroomSession(id=uid('classroom'), stageId=stage.id,
                    ownerId=self.store.owner_id, revision=stage.revision, fingerprint=fingerprint(stage),
                    stage=stage, roles=roles, state='paused', cursor=PlaybackCursor(sceneId=stage.scenes[0].id),
                    createdAt=now(), updatedAt=now()).model_dump()
                self.store.put('learning', session['id'], session)
                for scene in stage.scenes:
                    ids = [a.audioId for a in scene.actions if a.audioId]
                    if scene.type == 'slide':
                        ids += [e.mediaId for e in scene.content.elements if e.mediaId]
                    for media_id in ids:
                        self.reference_media(session['id'], media_id)
            self.store.put('learning_create', request, {'hash': digest(args.model_dump()),
                                                       'classroomId': session['id']})
        return session

    def reference_media(self, cid, media_id):
        session = self.get(cid)
        media = self.store.get('media', media_id)
        if media.get('stageId') != session['stageId'] or media.get('ownerId', self.store.owner_id) != session['ownerId']:
            fail('ACCESS_OWNER', '课堂媒体归属不一致')
        self.store.put('learning_media', cid + ':' + media_id,
                       {'classroomId': cid, 'mediaId': media_id, 'ownerId': session['ownerId']})

    def lease(self, cid, controller_id, *, acquire=True):
        self.get(cid)
        with self.store.transaction():
            prior = self.store.find('learning_control', cid)
            if prior and prior['expires'] > time.time() and prior['controllerId'] != controller_id:
                fail('CLASSROOM_CONTROL', '此课堂正在另一个浏览器窗口中学习')
            if not acquire and (not prior or prior['controllerId'] != controller_id):
                fail('CLASSROOM_CONTROL', '课堂控制权限已失效，请重新开始控制')
            self.store.put('learning_control', cid, {'controllerId': controller_id, 'expires': time.time() + 60})

    def cursor(self, session, cursor: PlaybackCursor):
        stage = Stage.model_validate(session['stage'])
        scene = next((s for s in stage.scenes if s.id == cursor.sceneId), None)
        if not scene:
            fail('CLASSROOM_PAGE', '播放位置不属于当前课程')
        if cursor.actionId:
            action = next((a for a in scene.actions if a.id == cursor.actionId), None)
            if not action:
                fail('CLASSROOM_ACTION', '播放动作不存在，不能使用数组下标恢复')
            if cursor.audioId or cursor.audioSignature:
                if action.type != 'speech' or cursor.audioId != action.audioId or cursor.audioSignature != action.audioSignature:
                    fail('CLASSROOM_AUDIO', '播放语音与当前动作不一致')
                if action.duration and cursor.audioTime > action.duration + 1:
                    fail('CLASSROOM_AUDIO', '音频位置超出当前片段')
        elif cursor.audioId or cursor.audioSignature or cursor.audioTime:
            fail('CLASSROOM_AUDIO', '音频位置必须关联稳定动作')
        if cursor.experimentState is not None:
            if scene.type != 'interactive':
                fail('CLASSROOM_STATE', '非实验页不能提交实验状态')
            scene.content.validate_state(cursor.experimentState)
        if len(json.dumps(cursor.model_dump())) > 100000:
            fail('CLASSROOM_STATE', '播放现场过大')
        return cursor.model_dump()

    def progress(self, cid, args: ClassroomProgress):
        session = self.get(cid, live=True)
        self.lease(cid, args.controllerId, acquire=False)
        if args.generation != session['generation']:
            fail('CLASSROOM_STALE', '旧轮次播放进度已失效')
        cursor = self.cursor(session, args.cursor)
        if session['state'] not in ('paused', 'lecture', 'discussion_prompt'):
            if cursor['sceneId'] != session['cursor']['sceneId'] or args.markerId:
                fail('CLASSROOM_STALE', '互动期间不能由播放进度切页或触发新讨论，请使用课堂命令')
        changes = {'cursor': cursor}
        if args.markerId:
            scene = next(s for s in session['stage']['scenes'] if s['id'] == cursor['sceneId'])
            marker = next((a for a in scene['actions'] if a['id'] == args.markerId and a['type'] == 'discussion'), None)
            if not marker:
                fail('CLASSROOM_MARKER', '当前页没有该讨论点')
            if args.markerId not in session['consumedDiscussions']:
                changes.update(state='discussion_prompt', pending={'kind': 'discussion', 'marker': marker})
        elif session['state'] in ('paused', 'lecture'):
            changes['state'] = 'lecture' if args.cursor.playing else 'paused'
        return self.update(cid, **changes)

    def emit(self, cid, kind, data=None, *, source='classroom_service', **identity):
        session = self.get(cid)
        with self.store.transaction():
            event = {'eventId': uid('event'), 'classroomId': cid, 'roundId': session['roundId'],
                     'dialogueId': session.get('activeDialogueId'),
                     'generation': session['generation'], 'source': source, 'kind': kind,
                     'speakerId': None, 'messageId': None, 'toolCallId': None,
                     'sceneId': session['cursor']['sceneId'], 'data': data or {},
                     'createdAt': now(), **identity}
            # Redact before saving so credentials never enter history/details.
            event = json.loads(self.config.redact(json.dumps(event, ensure_ascii=False)))
            row = self.store.db.execute('INSERT INTO learning_events(classroom,event_id,body,dialogue) VALUES(?,?,?,?)',
                (cid, event['eventId'], json.dumps(event, ensure_ascii=False), event.get('dialogueId')))
            event['seq'] = row.lastrowid
        return event

    def events(self, cid, after=0, limit=200):
        self.get(cid)
        return [{**json.loads(r['body']), 'dialogueId': r['dialogue'], 'seq': r['seq']} for r in self.store.db.execute(
            'SELECT seq,body,dialogue FROM learning_events WHERE classroom=? AND seq>? ORDER BY seq LIMIT ?',
            (cid, after, min(max(limit, 1), 500)))]

    def operation(self, cid, key, kind, arguments):
        session = self.get(cid)
        operation_id = cid + ':' + key
        with self.store.transaction():
            operation = self.store.find('learning_op', operation_id)
            if operation:
                if operation['requestHash'] != digest(arguments):
                    fail('REQUEST_CONFLICT', '同一课堂操作的参数已变化')
                return operation
            operation = {'id': operation_id, 'classroomId': cid, 'roundId': session['roundId'],
                'generation': session['generation'], 'kind': kind, 'requestHash': digest(arguments),
                'arguments': arguments, 'state': 'pending', 'result': None,
                'createdAt': now(), 'updatedAt': now()}
            return self.store.put('learning_op', operation_id, operation)

    def finish_op(self, operation, state, result=None):
        operation = {**operation, 'state': state, 'result': result, 'updatedAt': now()}
        self.store.put('learning_op', operation['id'], operation)
        return operation

    def context(self, cid):
        session = self.get(cid, live=True)
        scene = next(s for s in session['stage']['scenes'] if s['id'] == session['cursor']['sceneId'])
        context = {'stageId': session['stageId'], 'sceneId': scene['id'], 'title': scene['title'],
                   'brief': scene['brief'], 'type': scene['type'],
                   'objectives': session['stage']['approvedPlan']['objectives']}
        scenes = session['stage']['scenes']
        context.update(course={'title': session['stage']['title'],
                               'description': session['stage'].get('description', '')},
                       totalScenes=len(scenes),
                       sceneDirectory=[{k: s[k] for k in ('id', 'title', 'type')} for s in scenes[:5]],
                       remainingScenes=max(0, len(scenes) - 5))
        if scene['type'] == 'slide':
            context['elements'] = [{k: e.get(k) for k in ('id', 'type', 'text', 'alt', 'rows', 'points')}
                                   for e in scene['content']['elements']]
        elif scene['type'] == 'interactive':
            context['experiment'] = {k: scene['content'][k] for k in ('variables', 'controls', 'presets', 'initialState')}
            context['observed'] = session.get('lastObservation') or session['cursor'].get('experimentState')
        else:
            context['questions'] = [{k: q[k] for k in ('id', 'text', 'options')}
                                    for q in scene['content']['questions']]
            record = self.store.find('attempt', session['attempts'].get(scene['id'], ''))
            if record and record.get('classroomId') == cid and record.get('contentHash') == digest(scene['content']):
                context['attempt'] = {k: record[k] for k in ('status', 'results')}
            else:
                context['attempt'] = {'status': 'not_submitted'}
        # Semantic evidence only. Keep identity/grades; shorten display text and
        # long tabular/point lists before they enter any role's model context.
        def excerpt(value):
            if isinstance(value, str):
                return value if len(value) <= 1200 else value[:1200] + '…（证据摘录）'
            if isinstance(value, list):
                return [excerpt(v) for v in value[:80]]
            if isinstance(value, dict):
                return {k: excerpt(v) for k, v in value.items()}
            return value
        limited = excerpt(context)
        limit = self.config.classroom_context_tokens * 2 // 3
        if len(json.dumps(limited, ensure_ascii=False).encode('utf-8')) > limit:
            for field in ('elements', 'questions'):
                while len(limited.get(field, [])) > 1 and len(json.dumps(limited, ensure_ascii=False).encode('utf-8')) > limit:
                    limited[field].pop()
        if limited != context:
            limited['evidenceOmitted'] = True
        return limited

    def validate_tool(self, cid, speaker, name, parameters, *, bound_scene_id=None, legacy=False):
        if speaker != 'teacher':
            fail('CLASSROOM_TOOL_ROLE', '同学只能发言，不得操作课件')
        context = self.context(cid)
        if name not in available_tool_names(speaker, context['type']):
            fail('CLASSROOM_TOOL_PAGE', f'当前角色和页面（{context["type"]}）不支持工具 {name}')
        if not isinstance(parameters, dict):
            fail('CLASSROOM_TOOL_ARGS', '课堂工具参数必须为对象')
        pointer = name in ('spotlight', 'laser')
        if pointer and bound_scene_id != context['sceneId']:
            fail('CLASSROOM_PAGE', '指示请求缺少有效的原页面绑定或页面已切换')
        if (not pointer or legacy) and parameters.get('sceneId') != context['sceneId']:
            fail('CLASSROOM_PAGE', '演示工具只能作用于当前页')
        fields = {'spotlight': {'elementId'}, 'laser': {'elementId'},
                  'widget_setState': {'state'}, 'widget_highlight': {'target'},
                  'widget_annotation': {'target', 'content'}, 'widget_reveal': {'target'}}
        expected = fields[name] | ({'sceneId'} if not pointer or legacy else set())
        if set(parameters) != expected:
            fail('CLASSROOM_TOOL_ARGS', '课堂工具或参数不合法')
        session = self.get(cid, live=True)
        scene = next(s for s in Stage.model_validate(session['stage']).scenes if s.id == context['sceneId'])
        action = Action(type=name, **{k: v for k, v in parameters.items() if k != 'sceneId'})
        if name in ('spotlight', 'laser'):
            if scene.type != 'slide' or action.elementId not in {e.id for e in scene.content.elements}:
                fail('CLASSROOM_ELEMENT', '指示元素不存在')
        else:
            if scene.type != 'interactive':
                fail('CLASSROOM_PAGE', '当前页面不是实验')
            if name == 'widget_setState':
                scene.content.validate_state(action.state)
            elif action.target not in scene.content.controls:
                fail('CLASSROOM_TARGET', '实验目标不在声明控件中')
            if len(action.content) > 500:
                fail('CLASSROOM_TOOL_ARGS', '实验注释过长')
        return None

    async def command(self, cid, args: ClassroomCommand):
        session = self.get(cid, live=args.kind not in ('stop', 'pause'))
        self.lease(cid, args.controllerId)
        key = cid + ':' + args.requestId
        with self.store.transaction():
            prior = self.store.find('learning_request', key)
            if prior:
                if prior['hash'] != digest(args.model_dump()):
                    legacy=args.model_dump(exclude={'confirmEnd','expectedDialogueId','expectedGeneration'})
                    if args.confirmEnd or args.expectedDialogueId is not None or args.expectedGeneration is not None or prior['hash']!=digest(legacy):
                        fail('REQUEST_CONFLICT', '相同课堂请求不能更换参数')
                return self.get(cid)
            self.store.put('learning_request', key, {'hash': digest(args.model_dump()), 'state': 'accepted'})
        try:
            result = await self.runtime.command(cid, args)
        except BaseException:
            self.store.db.execute("DELETE FROM records WHERE kind='learning_request' AND id=?", (key,))
            raise
        self.store.put('learning_request', key, {'hash': digest(args.model_dump()), 'state': 'completed'})
        return result

    async def ack(self, cid, args: ClassroomAck):
        session = self.get(cid, live=True)
        self.lease(cid, args.controllerId, acquire=False)
        op = self.store.get('learning_op', args.operationId)
        if args.status == 'text_only':
            fail('CLASSROOM_ACK', '仅文字继续须由用户明确选择，不能作为播放完成回执')
        if op['classroomId'] != cid or op['generation'] != args.generation or args.generation != session['generation']:
            fail('CLASSROOM_STALE', '旧操作回执已失效')
        if op['kind'] not in ('tool', 'audio', 'restore') or op['arguments'].get('sceneId') != args.sceneId:
            fail('CLASSROOM_ACK', '回执与执行命令不匹配')
        if op['kind'] in ('tool', 'restore') and op.get('deliveryInstanceId', op['arguments'].get('instanceId')) != args.instanceId:
            fail('CLASSROOM_STALE', '实验实例已切换')
        if args.status == 'completed':
            if op['kind'] == 'audio' and args.result.get('ended') is not True:
                fail('CLASSROOM_ACK', '语音完成必须提供真实 ended 回执')
            if op['kind'] == 'restore' and args.result.get('restored') is not True:
                fail('CLASSROOM_ACK', '播放恢复必须有实际恢复回执')
        result = args.model_dump(exclude={'controllerId'})
        if op['state'] in ('completed', 'failed'):
            if op['result'] != result:
                fail('REQUEST_CONFLICT', '同一执行不能提交不同回执')
            return self.get(cid)
        self.finish_op(op, 'failed' if args.status == 'failed' else 'completed', result)
        self.emit(cid, 'execution_receipt', result, source='classroom_player')
        return await self.runtime.receipt(cid, op['id'])

    def associate_attempt(self, cid, stage_id, scene, record):
        session = self.get(cid, live=True)
        if session['stageId'] != stage_id or session['cursor']['sceneId'] != scene.id:
            fail('CLASSROOM_QUIZ', '提交不属于当前课堂测验页')
        record.update(classroomId=cid, contentHash=digest(scene.content.model_dump()))
        self.update(cid, attempts={**session['attempts'], scene.id: record['id']})

    async def close(self):
        if self.runtime:
            await self.runtime.close()
