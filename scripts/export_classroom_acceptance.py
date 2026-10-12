"""Export local, non-secret acceptance facts from actual persisted receipts."""
import argparse
import json
import math
import sqlite3
import struct
import sys
import wave
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--classroom-id',required=True)
    args=parser.parse_args()
    data=ROOT/'data/classroom-acceptance-env/data'
    db=sqlite3.connect(f'file:{data / "classroom.sqlite3"}?mode=ro',uri=True)
    def records(kind):
        return [json.loads(r[0]) for r in db.execute('SELECT body FROM records WHERE kind=?',(kind,))]
    room=next(r for r in records('learning') if r['id']==args.classroom_id)
    events=[json.loads(r[0]) for r in db.execute('SELECT body FROM learning_events WHERE classroom=? ORDER BY seq',(room['id'],))]
    ops=[r for r in records('learning_op') if r['classroomId']==room['id']]
    media={r['id']:r for r in records('media')}
    audio=[]
    for op in ops:
        if op['kind']!='audio' or not op['arguments'].get('audioId'):
            continue
        item=media[op['arguments']['audioId']]
        with wave.open(str(data/'media'/item['file']),'rb') as wav:
            width,rate,channels,n=wav.getsampwidth(),wav.getframerate(),wav.getnchannels(),wav.getnframes()
            raw=wav.readframes(n)
            samples=struct.unpack('<'+'h'*(len(raw)//2),raw) if width==2 else []
            rms=math.sqrt(sum(x*x for x in samples)/max(1,len(samples)))
        audio.append({'speakerId':op['arguments']['speakerId'],'voice':op['arguments']['voice'],
            'model':op['arguments']['model'],'mediaId':item['id'],'duration':n/rate,'channels':channels,
            'rms16':round(rms,1),'status':op['state'],'actualEnded':(op.get('result') or {}).get('result',{}).get('ended') is True})
    delays=[]
    for user in [e for e in events if e['kind']=='user_message']:
        first=next((e for e in events if e['roundId']==user['roundId'] and e['kind']=='text_delta'),None)
        sound=next((e for e in events if e['roundId']==user['roundId'] and e['kind']=='audio_ready'),None)
        start=datetime.fromisoformat(user['createdAt'])
        delays.append({'roundId':user['roundId'],'firstTextSeconds':round((datetime.fromisoformat(first['createdAt'])-start).total_seconds(),3) if first else None,
                       'firstAudioReadySeconds':round((datetime.fromisoformat(sound['createdAt'])-start).total_seconds(),3) if sound else None})
    result={'capturedAt':datetime.now().astimezone().isoformat(),'classroomId':room['id'],
        'testedPython':sys.version.split()[0],'dependencies':{n:version(n) for n in ['langgraph','langgraph-checkpoint-sqlite']},
        'state':room['state'],'audio':audio,'latencies':delays,
        'rolesWithActualEnded':sorted({a['speakerId'] for a in audio if a['actualEnded'] and a['rms16']>0}),
        'teacherToolResults':[{'name':o['arguments']['name'],'state':o['state'],'result':o['result']} for o in ops if o['kind']=='tool'],
        'restoreResults':[{'savedCursor':o['arguments']['cursor'],'state':o['state'],'result':o['result']} for o in ops if o['kind']=='restore'],
        'quizAttempts':[{k:r.get(k) for k in ['id','sceneId','status','answers','results']} for r in records('attempt') if r.get('classroomId')==room['id']],
        'modelOperations':{state:sum(o['kind']=='model' and o['state']==state for o in ops) for state in ['completed','failed','unknown','cancelled']}}
    out=ROOT/'data/classroom-evidence/provider-results.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'output':str(out),'rolesWithActualEnded':result['rolesWithActualEnded'],'latencies':delays},ensure_ascii=False))
    db.close()

if __name__=='__main__':
    main()
