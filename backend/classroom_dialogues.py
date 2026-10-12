"""Course history and topic identity, independent of playback and paid operations."""
import json

from .classroom_models import ClassroomDialogue
from .courses import fail
from .models import uid
from .store import now


class DialogueRecords:
    def migrate_dialogues(self):
        with self.store.transaction():
            columns = {r['name'] for r in self.store.db.execute('PRAGMA table_info(learning_events)')}
            if 'dialogue' not in columns:
                self.store.db.execute('ALTER TABLE learning_events ADD COLUMN dialogue TEXT')
            self.store.db.execute('CREATE INDEX IF NOT EXISTS learning_dialogue_order ON learning_events(dialogue,seq)')
            # Only old rooms are mapped. New rooms always persist the optional field.
            for room in self.store.list('learning'):
                if 'activeDialogueId' in room:
                    continue
                rows = self.store.db.execute('SELECT seq,body FROM learning_events WHERE classroom=? ORDER BY seq', (room['id'],)).fetchall()
                interactive = any(json.loads(r['body'])['kind'] in ('user_message', 'message_end', 'tool_start') for r in rows)
                did = 'legacy:' + room['id']
                room['activeDialogueId'] = None
                if interactive:
                    active = bool(room.get('returnCursor'))
                    scene = next((s for s in room['stage']['scenes'] if s['id'] == room['cursor']['sceneId']), None)
                    record = ClassroomDialogue(id=did, ownerId=room['ownerId'], stageId=room['stageId'],
                        sourceClassroomId=room['id'], sceneId=room['cursor']['sceneId'],
                        planPageId=scene.get('planPageId') if scene else None,
                        type='legacy', title='旧版课堂互动（话题边界未记录）',
                        status='interrupted', createdAt=room['createdAt'], updatedAt=room['updatedAt']).model_dump()
                    self.store.put('learning_dialogue', did, record)
                    # Never change the original event body, event_id or seq.
                    self.store.db.execute('UPDATE learning_events SET dialogue=? WHERE classroom=? AND dialogue IS NULL', (did, room['id']))
                    if active:room['activeDialogueId'] = did
                self.store.put('learning', room['id'], room)
            if not self.store.find('migration','classroom-dialogues-v1'):
                self.store.put('migration', 'classroom-dialogues-v1', {'version':1, 'createdAt':now()})

    def dialogue(self, did):
        record = self.store.find('learning_dialogue', did)
        if not record or record['ownerId'] != self.store.owner_id:
            fail('ACCESS_OWNER', '互动会话不存在或不属于当前用户')
        room = self.get(record['sourceClassroomId'])
        self.courses.stage(record['stageId'])
        if room['stageId'] != record['stageId'] or room['ownerId'] != record['ownerId']:
            fail('ACCESS_OWNER', '互动会话的课程归属不一致')
        return record

    def list_dialogues(self, stage_id, cursor=None, limit=50):
        self.courses.stage(stage_id)
        limit = max(1, min(limit, 100))
        params = [self.store.owner_id, stage_id]
        where = "kind='learning_dialogue' AND json_extract(body,'$.ownerId')=? AND json_extract(body,'$.stageId')=?"
        if cursor:
            record = self.dialogue(cursor)
            if record['stageId'] != stage_id:fail('ACCESS_OWNER', '会话分页游标不属于该课程')
            where += " AND (json_extract(body,'$.createdAt'),id)>(?,?)"
            params.extend([record['createdAt'], cursor])
        rows = self.store.db.execute('SELECT body FROM records WHERE '+where+" ORDER BY json_extract(body,'$.createdAt'),id LIMIT ?", (*params, limit+1)).fetchall()
        items = [{k:v for k,v in json.loads(r['body']).items() if k!='summary'} for r in rows[:limit]]
        return {'items':items, 'nextCursor':items[-1]['id'] if len(rows)>limit else None}

    def dialogue_events(self, did, after=0, limit=200):
        record = self.dialogue(did)
        return [{**json.loads(r['body']), 'dialogueId':did, 'seq':r['seq']} for r in self.store.db.execute(
            'SELECT seq,body FROM learning_events WHERE dialogue=? AND classroom=? AND seq>? ORDER BY seq LIMIT ?',
            (did, record['sourceClassroomId'], max(0,after), max(1,min(limit,500))))]

    def dialogue_tool_details(self, did, round_id, call_id):
        record = self.dialogue(did)
        result = {}
        for r in self.store.db.execute("SELECT body FROM learning_events WHERE dialogue=? AND classroom=? AND json_extract(body,'$.roundId')=? AND json_extract(body,'$.toolCallId')=? ORDER BY seq", (did,record['sourceClassroomId'],round_id,call_id)):
            event = json.loads(r['body'])
            if event['kind']=='tool_start':result['parameters']=event['data'].get('parameters')
            if event['kind']=='tool_end':result['result']=event['data'].get('result')
        return result

    def begin_dialogue(self, cid, text, kind='qa'):
        room = self.get(cid)
        scene = next(s for s in room['stage']['scenes'] if s['id']==room['cursor']['sceneId'])
        pages = room['stage']['approvedPlan']['pages']
        page_number = next((i+1 for i,p in enumerate(pages) if p['id']==scene['planPageId']), None)
        record = ClassroomDialogue(id=uid('dialogue'), ownerId=room['ownerId'],stageId=room['stageId'],
            sourceClassroomId=cid,sceneId=scene['id'],planPageId=scene['planPageId'],startingPageNumber=page_number,
            type=kind,title=text.split('\n')[0][:100],status='active',createdAt=now(),updatedAt=now()).model_dump()
        with self.store.transaction():
            self.store.put('learning_dialogue',record['id'],record)
            self.update(cid,activeDialogueId=record['id'])
            self.emit(cid,'dialogue_started',{'dialogue':{k:v for k,v in record.items() if k!='summary'}})
        return record

    def set_dialogue_status(self, cid, status, reason=None, *, source='classroom_service'):
        with self.store.transaction():
            room=self.get(cid); did=room.get('activeDialogueId')
            if not did:return room
            record=self.dialogue(did)
            record.update(status=status,endReason=reason,updatedAt=now())
            self.store.put('learning_dialogue',did,record)
            self.emit(cid,'dialogue_'+status,{'status':status,'reason':reason},source=source,dialogueId=did)
            if status=='completed':room=self.update(cid,activeDialogueId=None)
            return room

    def require_exit_confirmation(self, room, args):
        conflict=bool(room.get('activeDialogueId')) or room['state']=='discussion_prompt'
        if not conflict:return
        if not args.confirmEnd:fail('CLASSROOM_CONFIRMATION','请先确认结束当前互动再执行此操作')
        if args.expectedDialogueId!=room.get('activeDialogueId') or args.expectedGeneration!=room['generation']:
            fail('CLASSROOM_STALE','互动已变化，请重新确认')
