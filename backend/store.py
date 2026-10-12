import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import uid
from .timeline import project


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Local durable records; only validated service methods author course documents."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.transaction_lock = threading.RLock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError("数据库版本不兼容；请按 README 恢复对应备份")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                updated TEXT NOT NULL, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
                kind TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_session ON events(session,seq);
            CREATE TABLE IF NOT EXISTS calls (
                run TEXT NOT NULL, request TEXT NOT NULL, body TEXT,
                PRIMARY KEY(run,request));
            CREATE TABLE IF NOT EXISTS timeline (
                session TEXT NOT NULL, id TEXT NOT NULL, first_seq INTEGER NOT NULL,
                last_seq INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(session,id));
            CREATE INDEX IF NOT EXISTS timeline_order ON timeline(session,first_seq);
            PRAGMA user_version=1;
        """)
        if not self.find('migration','timeline-v1'):
            with self.transaction():
                for row in self.db.execute('SELECT seq,session,kind,body,created FROM events ORDER BY seq').fetchall():
                    project(self, {'seq':row[0],'sessionId':row[1],'kind':row[2],'data':json.loads(row[3]),'createdAt':row[4]})
                # Older chat-only sessions are retained with an explicit legacy marker.
                for chat in self.list('chat'):
                    sid=chat['sessionId']
                    if not self.db.execute('SELECT 1 FROM timeline WHERE session=? AND json_extract(body,"$.kind")=? LIMIT 1',(sid,chat['role'])).fetchone():
                        self.event(sid,'user_message' if chat['role']=='user' else 'text_delta',{'text':chat['text'],'messageId':chat['id'],'segmentId':chat['id'],'legacy':True},source='legacy',version=1)
                self.put('migration','timeline-v1',{'version':2})

        self.migrate_multi_course()
        self.migrate_run_targets()

    owner_id = 'local'

    def remove_media(self, media_id: str, directory: Path):
        """Maintenance deletion refuses pinned classroom and current course media.

        There is no automatic GC. Use this method for future cleanup instead of
        deleting files directly; old classroom references remain pinned.
        """
        from .courses import fail
        with self.transaction():
            record = self.get('media', media_id)
            if record.get('ownerId', self.owner_id) != self.owner_id:
                fail('ACCESS_OWNER', '不能清理其他用户的媒体')
            pinned = any(r['mediaId'] == media_id for r in self.list('learning_media'))
            for stage in self.list('stage'):
                for scene in stage.get('scenes', []):
                    pinned = pinned or any(a.get('audioId') == media_id for a in scene.get('actions', []))
                    pinned = pinned or any(e.get('mediaId') == media_id for e in scene.get('content', {}).get('elements', []))
            if pinned:
                fail('MEDIA_REFERENCED', '媒体仍被课程或保留的课堂引用，不能清理')
            path = (directory / record['file']).resolve()
            if path.parent != directory.resolve():
                fail('MEDIA_PATH', '媒体路径越界')
            path.unlink(missing_ok=True)
            self.db.execute("DELETE FROM records WHERE kind='media' AND id=?", (media_id,))

    def owned(self, kind, id):
        item=self.find(kind,id)
        if not item or item.get('deletedAt'):return False
        owner = self.find('course_owner' if kind == 'stage' else kind + '_owner', id)
        return bool(owner and owner.get('ownerId') == self.owner_id and not owner.get('deletedAt'))

    def migrate_multi_course(self):
        from .models import digest
        with self.transaction():
            if self.find('migration', 'multi-course-v2'):
                return
            self.put('user', self.owner_id, {'id':self.owner_id, 'deployment':'local-single-user'})
            for kind in ('stage', 'session'):
                owner_kind = 'course_owner' if kind == 'stage' else 'session_owner'
                for item in self.list(kind):
                    if not self.find(owner_kind, item['id']):
                        owner = item.get('ownerId', self.owner_id)
                        self.put(owner_kind, item['id'], {'ownerId':owner, 'version':2, 'migrated':True,
                            'deletedAt':item.get('deletedAt')})
            for stage in self.list('stage'):
                if stage.get('approvedPlan'):
                    self.put('course_approval',stage['id'],{'stageId':stage['id'],'planHash':digest(stage['approvedPlan']), 'version':2})
            for session in self.list('session'):
                sid=session['id'];stage_id=session.get('stageId')
                session.update(activeStageId=stage_id, linkedStageIds=[stage_id] if stage_id else [], metadataVersion=2,
                    unfinishedGoals={stage_id:{'goal':'full-course','touchedSceneIds':[],'touchedSlotIds':[]}} if stage_id and session.get('fullCourseGoal') else {})
                session.pop('fullCourseGoal',None)
                question=session.get('pendingQuestion')
                if question:
                    question={**question,'stageId':stage_id,'expectedRevision':(self.find('stage',stage_id) or {}).get('revision') if stage_id else None}
                    session['pendingQuestion']=question
                    self.put('question',question['id'],question)
                    if question['kind']=='plan_approval':
                        self.put('plan_approval',question['id'],{'approvalId':question['id'],'sessionId':sid,'kind':'update' if stage_id else 'create',
                            'stageId':stage_id,'plan':question['plan'],'planHash':digest(question['plan']),'planVersion':question['planVersion'],
                            'expectedRevision':question['expectedRevision'],'state':'pending','createdStageId':None,'version':2})
                if session.get('approvedPlan'):
                    aid='legacy:'+sid
                    self.put('plan_approval',aid,{'approvalId':aid,'sessionId':sid,'kind':'create','stageId':None,
                        'plan':session['approvedPlan'],'planHash':digest(session['approvedPlan']),'planVersion':session.get('planVersion',0),
                        'state':'created' if stage_id else 'approved','createdStageId':stage_id,'version':2,'legacy':True})
                self.put('session',sid,session)
            for run in self.list('run'):
                if 'courseTargets' in run:continue
                session=self.find('session',run['sessionId']) or {}
                stage_id=session.get('stageId')
                run['courseTargets']={stage_id:{'stageId':stage_id,'goal':run.get('goal','local'),'touchedSceneIds':run.get('touchedSceneIds',[]),'touchedSlotIds':run.get('touchedSlotIds',[])}} if stage_id else {}
                run['metadataVersion']=2
                self.put('run',run['id'],run)
            self.put('migration','multi-course-v2',{'version':2,'createdAt':now()})

    def migrate_run_targets(self):
        with self.transaction():
            if self.find('migration','multi-course-run-targets-v2'):return
            for run in self.list('run'):
                if 'courseTargets' in run:continue
                session=self.find('session',run['sessionId']) or {};stage_id=session.get('stageId')
                run['courseTargets']={stage_id:{'stageId':stage_id,'goal':run.get('goal','local'),
                    'touchedSceneIds':run.get('touchedSceneIds',[]),'touchedSlotIds':run.get('touchedSlotIds',[])}} if stage_id else {}
                run['metadataVersion']=2
                self.put('run',run['id'],run)
            self.put('migration','multi-course-run-targets-v2',{'version':2,'createdAt':now()})

    def require_session(self, sid):
        from .courses import fail
        if not self.owned('session',sid): fail('ACCESS_OWNER','对话不存在或不属于当前本地用户')
        return self.get('session',sid)

    def link_course(self, sid, stage_id, active=False):
        if not self.owned('stage',stage_id):
            from .courses import fail
            fail('ACCESS_OWNER','课程不属于当前本地用户')
        session=self.require_session(sid)
        linked=list(session.get('linkedStageIds',[]))
        if stage_id not in linked:linked.append(stage_id)
        changes={'linkedStageIds':linked}
        if active:changes.update(activeStageId=stage_id,stageId=stage_id)
        self.put('course_link',sid+':'+stage_id,{'sessionId':sid,'stageId':stage_id,'updatedAt':now()})
        return self.patch_session(sid,**changes)

    @contextmanager
    def transaction(self):
        with self.transaction_lock:
            if self.db.in_transaction:
                yield
                return
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def get(self, kind: str, id: str) -> dict:
        row = self.db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
        if not row:
            raise KeyError(f"{kind} 不存在")
        return json.loads(row[0])

    def find(self, kind: str, id: str) -> dict | None:
        try:
            return self.get(kind, id)
        except KeyError:
            return None

    def put(self, kind: str, id: str, body: dict) -> dict:
        self.db.execute("INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,updated=excluded.updated",
                        (kind, id, json.dumps(body, ensure_ascii=False, allow_nan=False), now()))
        return copy.deepcopy(body)

    def list(self, kind: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM records WHERE kind=? ORDER BY updated DESC", (kind,))]

    def event(self, session: str, kind: str, body: dict, *, source='workbench', version=2, captured_at=None) -> dict:
        with self.transaction():
            created = now()
            run = body.get('runId') or (self.find('session',session) or {}).get('runId')
            body = {**body, 'runId':run, '_eventVersion':version, '_source':source, '_capturedAt':captured_at or created}
            cur = self.db.execute("INSERT INTO events(session,kind,body,created) VALUES(?,?,?,?)",
                                  (session, kind, json.dumps(body, ensure_ascii=False, allow_nan=False), created))
            event = {'version':version,'source':source,'eventType':kind,'payload':body,'capturedAt':captured_at or created,'sessionId':session,'runId':run,'seq':cur.lastrowid,'kind':kind,'data':body,'createdAt':created}
            event['timeline'] = project(self,event)
            self.put('event_projection',str(event['seq']),{'nodeIds':[n['id'] for n in event['timeline']]})
            return event

    def capture_tool(self, event, parameters=None, result=None):
        body=event['data'];key=event['sessionId']+':'+str(event['runId'])+':'+body['toolCallId']
        prior=self.find('pi_tool_detail',key) or {'parameters':None,'result':None,'parametersComplete':False,'source':'pi','version':2}
        # One frozen SDK final result. Late updates cannot replace the receipt.
        if prior['result'] is not None:return
        if parameters is not None:prior.update(parameters=parameters,parametersComplete=True)
        if result is not None:prior['result']=result
        self.put('pi_tool_detail',key,prior)

    def pi_event(self, session, run, message):
        key=run+':'+str(message['seq'])
        with self.transaction():
            if self.find('pi_receipt',key):return
            payload=message['payload']
            from .tool_result import safe
            # Image input was delivered to the SDK/model. UI reads the durable media attachment.
            if payload.get('result'):
                payload=json.loads(json.dumps(payload))
                details=payload['result'].get('details') or {}
                media_id=(details.get('data') or {}).get('mediaId') if isinstance(details.get('data'),dict) else None
                for block in payload['result'].get('content',[]):
                    if block.get('type')=='image':
                        block.pop('data',None);block['url']='/api/media/'+media_id if media_id else None
            event=self.event(session,payload['eventType'],safe({**payload,'runId':run}),source='pi',captured_at=message['capturedAt'])
            tool_call_id=payload.get('toolCallId')
            if tool_call_id:
                operation=self.find('operation_record',run+':'+tool_call_id)
                if operation:
                    operation.setdefault('sdkEvents',{})[payload['eventType']]=event['seq']
                    self.put('operation_record',operation['id'],operation)
            self.put('pi_receipt',key,{'seq':event['seq']})
            return event

    def timeline(self, session, before=None, limit=50):
        maximum = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE session=?',(session,)).fetchone()[0]
        entries = self.db.execute('SELECT body FROM timeline WHERE session=? AND first_seq<? ORDER BY first_seq DESC LIMIT ?',
                                  (session,before if before is not None else maximum+1,max(1,min(limit,100))+1)).fetchall()
        more = len(entries)>limit
        nodes = [json.loads(row[0]) for row in entries[:limit]][::-1]
        for node in nodes:node.setdefault('source','legacy')
        return {'nodes':nodes,'snapshotSeq':maximum,'before':nodes[0]['firstSeq'] if more and nodes else None,'version':2}

    def events(self, session: str, after: int = 0, limit: int = 500) -> list[dict]:
        entries=[{'version':json.loads(row[2]).get('_eventVersion',1),'source':json.loads(row[2]).get('_source','legacy'),'eventType':row[1],'payload':json.loads(row[2]),'capturedAt':json.loads(row[2]).get('_capturedAt',row[3]),'sessionId':session,'runId':json.loads(row[2]).get('runId'),
                  'seq':row[0],'kind':row[1],'data':json.loads(row[2]),'createdAt':row[3],'timeline':[]}
                 for row in self.db.execute('SELECT seq,kind,body,created FROM events WHERE session=? AND seq>? ORDER BY seq LIMIT ?', (session,after,limit))]
        # Send each current node once per batch. Avoid persisting/retransmitting
        # a full accumulated assistant message for every token event.
        last={}
        for event in entries:
            projection=self.find('event_projection',str(event['seq'])) or {}
            for node_id in projection.get('nodeIds',[]): last[node_id]=event
            if projection.get('timeline'): event['timeline']=projection['timeline']
        for node_id,event in last.items():
            row=self.db.execute('SELECT body FROM timeline WHERE session=? AND id=?',(session,node_id)).fetchone()
            if row:
                node=json.loads(row[0]);node.setdefault('source','legacy');event['timeline'].append(node)
        return entries

    def session(self, stage_id: str | None = None) -> dict:
        if stage_id and not self.owned('stage',stage_id):
            from .courses import fail
            fail('ACCESS_OWNER','不能关联无归属课程')
        body = {"id": uid("session"), "stageId": stage_id, "state": "idle", "runId": None,
                "pendingQuestion": None, "approvedPlan": None, "planVersion": 0,
                "piSessionFile": None, "createdAt": now(), "sources": [], "activeStageId":stage_id,
                "linkedStageIds":[stage_id] if stage_id else [], "metadataVersion":4}
        with self.transaction():
            self.put('session_owner',body['id'],{'ownerId':self.owner_id,'version':2})
            self.put("session", body["id"], body)
            if stage_id:self.link_course(body['id'],stage_id,active=True)
        return body

    def patch_session(self, id: str, **changes: Any) -> dict:
        body = self.get("session", id)
        body.update(changes)
        return self.put("session", id, body)

    def cached_call(self, run: str, request: str) -> dict | None:
        row = self.db.execute("SELECT body FROM calls WHERE run=? AND request=?", (run, request)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def cache_call(self, run: str, request: str, body: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO calls VALUES(?,?,?)", (run, request, json.dumps(body, ensure_ascii=False)))

    def close(self) -> None:
        self.db.close()
