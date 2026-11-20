import json
import sqlite3
import zipfile
from pathlib import Path
import pytest
from core import company_backup as backup, company_knowledge as knowledge
from core.db_path import get_db_path
from core import staffing
from tests.test_v301_companion_http import http_server, request

@pytest.fixture
def backup_folder(tmp_path_factory,monkeypatch):
    folder=tmp_path_factory.mktemp('OneDrive')
    monkeypatch.setattr(backup,'assert_idle',lambda:None)
    backup.save_settings({'enabled':True,'folder':str(folder),'interval_minutes':15,'keep':2})
    with sqlite3.connect(str(get_db_path())) as conn:conn.execute('CREATE TABLE sample(value)');conn.execute("INSERT INTO sample VALUES('original')")
    return folder

def test_backup_restore_sqlite_and_journals_without_credentials(backup_folder):
    root=get_db_path().parent
    (root/'team_settings.json').write_text('{"company":"old"}')
    (root/'device-link.json').write_text('{"secret":"no"}')
    (root/'solomon-bridge.token').write_text('secret')
    (root/'missions').mkdir();(root/'missions/MSN-abc.json').write_text('{"mission_id":"MSN-abc","status":"RUNNING","owner_pid":123}')
    result=backup.create();ident=result['archives'][0]['id'];data=backup.verify(backup.destination()/ident)
    assert 'device-link.json' not in data and 'solomon-bridge.token' not in data
    with sqlite3.connect(str(get_db_path())) as conn:conn.execute("UPDATE sample SET value='changed'")
    (root/'team_settings.json').write_text('{"company":"new"}')
    backup.stage_restore(ident,'운영 기록 복구');assert backup.status()['pending_restore']
    assert json.loads((root/'team_settings.json').read_text())['company']=='new'
    backup.apply_pending()
    with sqlite3.connect(str(get_db_path())) as conn:assert conn.execute('SELECT value FROM sample').fetchone()[0]=='original'
    assert json.loads((root/'team_settings.json').read_text())['company']=='old'
    assert json.loads((root/'missions/MSN-abc.json').read_text())['status']=='STOPPED'
    assert (root/'solomon-bridge.token').read_text()=='secret'
    assert not backup.status()['pending_restore']
    backup.apply_pending() # completed restore is a no-op

def test_backup_retention_and_tamper_checks(backup_folder):
    for _ in range(3):backup.create()
    assert len(backup.archives())==2
    original=backup.destination()/backup.archives()[0]['id']
    with zipfile.ZipFile(original) as z: contents={n:z.read(n) for n in z.namelist()}
    contents['team_settings.json']=b'{}'
    bad=backup_folder/'tampered.zip'
    with zipfile.ZipFile(bad,'w') as z:
        for n,v in contents.items():z.writestr(n,v)
    with pytest.raises(ValueError):backup.verify(bad)
    contents['../escape']=b'bad';manifest=json.loads(contents['manifest.json']);manifest['files']['../escape']=backup.digest(b'bad');contents['manifest.json']=json.dumps(manifest).encode()
    with zipfile.ZipFile(bad,'w') as z:
        for n,v in contents.items():z.writestr(n,v)
    with pytest.raises(ValueError):backup.verify(bad)
    with pytest.raises(ValueError):backup.stage_restore('../escape.zip','운영 기록 복구')
    with pytest.raises(ValueError):backup.stage_restore(original.name,'yes')

def test_pending_restore_tamper_does_not_change_current(backup_folder):
    ident=backup.create()['archives'][0]['id'];backup.stage_restore(ident,'운영 기록 복구')
    (get_db_path().parent/'restore_pending/director.db').write_bytes(b'corrupt')
    with pytest.raises(ValueError):backup.apply_pending()
    with sqlite3.connect(str(get_db_path())) as conn:assert conn.execute('SELECT value FROM sample').fetchone()[0]=='original'
    backup.cancel_restore();assert not backup.status()['pending_restore']

def test_knowledge_scope_review_revision_and_history():
    def submit(**extra):
        value={'expected_revision':knowledge.listing()['revision'],'project_path':'project-A','kind':'engine','department':'development','title':'Godot guideline','content':'Use fixed physics steps','source':'MSN-1','enabled':False,**extra}
        return knowledge.submit(value,lambda p:(True,p))
    state=submit();entry=state['entries'][0]
    assert knowledge.instructions('project-A')==''
    state=submit(id=entry['id'],enabled=True)
    assert 'fixed physics' in knowledge.instructions('project-A','development')
    assert knowledge.instructions('project-B','development')==''
    assert knowledge.instructions('project-A','design')==''
    assert len(state['entries'][0]['history'])==1
    with pytest.raises(staffing.TeamConflict):submit(id=entry['id'],expected_revision='stale')
    from schemas.order import OrderSchema
    order=staffing.bind_order(OrderSchema(goal='game',staff_reference_project='forged'),staffing.default_team(),project='project-A')
    assert 'fixed physics' in staffing.guidance(order,'BUILDER')
    assert order.staff_reference_project=='project-A'
    assert 'fixed physics' in staffing.planning_context({'project_path':'project-A'},staffing.default_team())['company_knowledge']

def test_http_boundaries_and_desktop_page(http_server):
    for url in ('/operations','/operations.js','/ops/backup','/ops/knowledge'):
        assert request(http_server,'GET',url)[0]==200
    for url in ('/ops/backup','/ops/knowledge'):
        assert request(http_server,'POST',url)[0]==403
    code,body=request(http_server,'POST','/ops/knowledge',json.dumps({'expected_revision':'stale'}),{'Content-Type':'application/json','X-Solomon-Bridge':'test-token'})
    assert code==400
    from core.device_link import READ_API,WRITE_API,PAGES
    assert '/operations' in PAGES and '/ops/knowledge' in READ_API&WRITE_API
    assert '/ops/backup' not in READ_API|WRITE_API

def test_scheduler_enabled_due_only_and_pending_skipped(backup_folder,monkeypatch):
    class SingleTick:
        calls=0
        def wait(self,seconds):
            self.calls+=1
            return self.calls>1
    calls=[]
    monkeypatch.setattr(backup,'create',lambda:calls.append('backup'))
    backup.start_scheduler(SingleTick()).join(2);assert calls==['backup']
    backup.atomic(get_db_path().parent/'backup_state.json',{'last_success':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
    backup.start_scheduler(SingleTick()).join(2);assert len(calls)==1
    (get_db_path().parent/'restore_pending').mkdir()
    backup.atomic(get_db_path().parent/'backup_state.json',{})
    backup.start_scheduler(SingleTick()).join(2);assert len(calls)==1

def test_restore_clears_sqlite_running_states(backup_folder):
    with sqlite3.connect(str(get_db_path())) as conn:
        conn.execute('CREATE TABLE runs(current_state TEXT)');conn.execute("INSERT INTO runs VALUES('BUILDING')")
        conn.execute('CREATE TABLE ai_usage(status TEXT,pid INT)');conn.execute("INSERT INTO ai_usage VALUES('RUNNING',123)")
    ident=backup.create()['archives'][0]['id'];backup.stage_restore(ident,'운영 기록 복구');backup.apply_pending()
    with sqlite3.connect(str(get_db_path())) as conn:
        assert conn.execute('SELECT current_state FROM runs').fetchone()[0]=='HUMAN_REQUIRED'
        assert conn.execute('SELECT status,pid FROM ai_usage').fetchone()==('INTERRUPTED',None)

def test_pending_restore_blocks_new_mutations(http_server,backup_folder):
    ident=backup.create()['archives'][0]['id'];backup.stage_restore(ident,'운영 기록 복구')
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    assert request(http_server,'POST','/ops/knowledge','{}',headers)[0]==409
    assert request(http_server,'POST','/ops/backup','{"action":"cancel"}',headers)[0]==200
    assert request(http_server,'POST','/ops/knowledge','{}',headers)[0]==400

def test_invalid_zip_and_data_parent_are_rejected(backup_folder):
    bad=backup_folder/'bad.zip';bad.write_bytes(b'not a zip')
    with pytest.raises(ValueError):backup.verify(bad)
    backup.save_settings({'enabled':False,'folder':str(get_db_path().parent),'interval_minutes':15,'keep':2})
    with pytest.raises(ValueError):backup.destination()

def test_hermes_receives_only_reviewed_project_knowledge(tmp_path,monkeypatch):
    from tests.test_hermes_agent import submitted
    project=str(tmp_path/'game')
    state=knowledge.listing()
    knowledge.submit({'expected_revision':state['revision'],'project_path':project,'kind':'lesson','department':'all','title':'검수 교훈','content':'knowledge-evidence-unique','source':'MSN-1','enabled':True},lambda p:(True,p))
    job=submitted(tmp_path,monkeypatch)
    assert 'knowledge-evidence-unique' in job['prompt']
    assert project==job['project_path']
