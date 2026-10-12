"""Read a backup, migrate an isolated copy, and prove preservation. No live writes."""
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.store import Store
from backend.config import ROOT

KINDS=('stage','media','inspection','pi_receipt','pi_tool_detail','message','question','plan_approval','course_approval')
def fingerprint(db):
    records={kind:[tuple(row) for row in db.execute('select id,body from records where kind=? order by id',(kind,))] for kind in KINDS}
    records['events']=[tuple(row) for row in db.execute('select * from events order by seq')]
    records['timeline']=[tuple(row) for row in db.execute('select * from timeline order by session,id')]
    return {k:hashlib.sha256(json.dumps(v,ensure_ascii=False).encode()).hexdigest() for k,v in records.items()}

def main():
    backup=ROOT/'data/backups/natural-targeting-20261006-180035'
    source=sqlite3.connect('file:'+str(backup/'classroom.sqlite3')+'?mode=ro',uri=True)
    before=fingerprint(source)
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'migrated.sqlite3';dest=sqlite3.connect(path);source.backup(dest);dest.close()
        store=Store(path)
        first=[(r['id'],r) for r in store.list('run')];sessions=store.list('session')
        assert fingerprint(store.db)==before
        store.close();store=Store(path)
        assert first==[(r['id'],r) for r in store.list('run')]
        assert sessions==store.list('session')
        # Compatibility rollback uses legacy alias READS; never run old first-write routing.
        aliases=[(s['id'],s.get('stageId'),s.get('activeStageId'),s.get('piSessionFile')) for s in sessions]
        for _,stage_id,active,_ in aliases:
            assert stage_id==active
            if stage_id:assert store.find('stage',stage_id)
        from backend.models import uid
        original=store.list('stage')[0];new={**original,'id':uid('rollback_probe')};store.put('stage',new['id'],new)
        store.close();again=Store(path)
        assert again.get('stage',new['id'])==new
        assert all(again.get('session',sid).get('piSessionFile')==pi for sid,_,_,pi in aliases)
        again.close()
    watermark=source.execute('select coalesce(max(seq),0) from events').fetchone()[0]
    source.close()
    output={'source':str(backup),'watermark':watermark,'runs':len(first),'sessions':len(sessions),'preservedHashes':before,
        'repeatMigration':'passed','legacyAliasRead':'passed','newArtifactsSurviveReopen':'passed',
        'rollbackLimit':'legacy writer must stay disabled; original v3 tasks are retained'}
    destination=Path(tempfile.mkdtemp(prefix='openmaic-taskfree-migration-'))/'acceptance.json'
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    output['evidenceFile']=str(destination)
    print(json.dumps({k:v for k,v in output.items() if k!='preservedHashes'},ensure_ascii=False))
if __name__=='__main__':main()
