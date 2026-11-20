import base64,io,json,os,shutil,sqlite3,sys,zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from core import update_protocol as p,app_updates as updates
from scripts import update_worker as worker
from tests.test_v301_companion_http import http_server,request

REPO='example/director'


@pytest.mark.parametrize('name',['data./records.json','data /records.json','console/NUL.txt','console/file?.js','console/file\x01.js'])
def test_windows_alias_and_reserved_paths_are_rejected(name):
    with pytest.raises(ValueError):p.safe_name(name)

@pytest.fixture
def release(tmp_path,monkeypatch):
    root=tmp_path/'한글 설치';root.mkdir();(root/'data').mkdir()
    key=Ed25519PrivateKey.generate();public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
    old={'desktop_launcher.py':b'# stable shell','native_app.py':b'# stable native','requirements.txt':b'psutil','requirements-native.txt':b'PySide6','companion_server.py':b'# old server','release_version.py':b'VERSION="2026.11.20.1"','core/app_updates.py':b'# old updater','core/update_protocol.py':b'# protocol','scripts/update_worker.py':b'# worker','console/view.js':b'old view','config.yaml':b'default: true','companion.json':b'{"port":8091}','data/.gitkeep':b''}
    old_manifest={'app':p.APP,'format':1,'version':'2026.11.20.1','files':{k:p.sha(v) for k,v in old.items()}}
    for name,raw in old.items():file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw)
    (root/'desktop_distribution.json').write_text(json.dumps(old_manifest))
    (root/'config.yaml').write_text('user: preserved');(root/'data/user.json').write_text('user history')
    new={**old,'companion_server.py':b'# new server','release_version.py':b'VERSION="2026.11.20.2"','console/view.js':b'new view','console/new.js':b'new file'}
    new_manifest={'app':p.APP,'format':1,'version':'2026.11.20.2','files':{k:p.sha(v) for k,v in new.items()}}
    archive=tmp_path/'update.zip'
    def build(files=new,manifest=new_manifest,extra=None):
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for name,raw in files.items():z.writestr('AI DEV DIRECTOR/'+name,raw)
            z.writestr('AI DEV DIRECTOR/desktop_distribution.json',json.dumps(manifest))
            if extra:z.writestr(extra,b'unsafe')
        payload={'app':p.APP,'format':1,'repository':REPO,'version':manifest['version'],'min_updater':1,'archive_url':'https://github.com/'+REPO+'/releases/download/v2/update.zip','archive_sha256':p.sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,'release_notes':'실제 서명 테스트 · <img src=x onerror=alert(1)>'}
        return {'payload':payload,'signature':base64.b64encode(key.sign(p.canonical(payload))).decode()}
    envelope=build()
    (root/'data/update_settings.json').write_text(json.dumps({'repository':REPO,'public_key':public,'auto_check':False,'auto_download':False}))
    monkeypatch.setattr(updates,'ROOT',root);monkeypatch.setattr(updates,'BUSY',False);monkeypatch.setattr(updates,'data_root',lambda:root/'data')
    return SimpleNamespace(root=root,archive=archive,key=key,public=public,envelope=envelope,new=new_manifest,old=old_manifest,build=build)


def job(release):
    folder=release.root/'data/app_updates/UPD-01234567890123456789';folder.mkdir(parents=True,exist_ok=True);shutil.copyfile(release.archive,folder/'archive.zip')
    record={'root':str(release.root),'repository':REPO,'public_key':release.public,'envelope':release.envelope,'backend':{'pid':99999999,'created':0},'clients':[],'port':8091}
    (release.root/'data/update_exit.json').write_text(json.dumps({'job_id':folder.name}))
    return folder,record


def test_real_installer_output_can_download_and_stage_an_update(release, tmp_path, monkeypatch):
    from scripts.install_desktop import copy_installation
    source = tmp_path/'old-release-source'
    for name in release.old['files']:
        file = source/name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'default: true' if name == 'config.yaml' else (release.root/name).read_bytes())
    (source/'desktop_distribution.json').write_text(json.dumps(release.old))
    installed = tmp_path/'actually-installed'
    copy_installation(source, installed)
    shutil.rmtree(source)
    monkeypatch.setattr(updates, 'ROOT', installed)
    monkeypatch.setattr(updates, 'data_root', lambda: installed/'data')
    assert updates.current_version() == release.old['version']
    assert updates.public()['installed'] is True
    (installed/'data/update_settings.json').write_text(json.dumps({'repository':REPO,'public_key':release.public,'auto_check':False,'auto_download':False}))
    updates.update_state(status='AVAILABLE', envelope=release.envelope)
    monkeypatch.setattr(updates,'open_download',lambda *a,**kw:io.BytesIO(release.archive.read_bytes()))
    updates.download(background=False)
    assert updates.state()['status'] == 'READY', updates.public()
    assert not updates.state()['plan']['manual_required']


def test_signature_repository_version_hash_and_protocol_are_checked(release):
    payload=p.verify_envelope(release.envelope,release.public,REPO)
    assert p.inspect_archive(release.archive,payload)['version']=='2026.11.20.2'
    bad=json.loads(json.dumps(release.envelope));bad['payload']['version']='2026.11.20.9'
    with pytest.raises(ValueError,match='서명'):p.verify_envelope(bad,release.public,REPO)
    with pytest.raises(ValueError):p.verify_envelope(release.envelope,release.public,'other/repo')
    with pytest.raises(ValueError):p.version('v1.2.3')
    assert p.version('2026.11.20.2')>p.version('2026.11.20.1')
    release.archive.write_bytes(release.archive.read_bytes()+b'corrupt')
    with pytest.raises(ValueError,match='해시'):p.inspect_archive(release.archive,payload)


@pytest.mark.parametrize('name',['../outside.py','data/director.db','.venv/bin/python','node_modules/x.js','a/../../x.js','a\\x.py','C:/evil.py','secrets/token.json'])
def test_archive_paths_cannot_touch_data_credentials_or_runtime(name):
    with pytest.raises(ValueError):p.safe_name(name)


def test_extra_paths_and_local_changes_are_rejected(release):
    bad=release.build(extra='AI DEV DIRECTOR/../outside.py')
    with pytest.raises(ValueError):p.inspect_archive(release.archive,bad['payload'])
    release.build();(release.root/'console/view.js').write_text('user modification')
    with pytest.raises(ValueError,match='직접 수정'):p.plan(release.root,release.old,release.new)
    (release.root/'console/view.js').write_text('old view')
    newer=json.loads(json.dumps(release.new));newer['files']['native_app.py']=p.sha(b'new shell')
    assert p.plan(release.root,release.old,newer)['manual_required']


def test_successful_transaction_preserves_user_settings_and_records(release):
    folder,record=job(release);restarted=[]
    worker.run(release.root,folder,record,health=lambda r,j:True,restart=lambda r:restarted.append(r))
    assert (release.root/'console/view.js').read_text()=='new view'
    assert (release.root/'config.yaml').read_text()=='user: preserved'
    assert (release.root/'data/user.json').read_text()=='user history'
    assert json.loads((folder/'journal.json').read_text())['stage']=='COMMITTED'
    assert json.loads((release.root/'data/update_state.json').read_text())['status']=='INSTALLED'
    assert len(restarted)==1 and not (release.root/'data/update_exit.json').exists()


def test_failed_start_restores_code_and_database_migration(release):
    folder,record=job(release);database=release.root/'data/director.db'
    with sqlite3.connect(database) as conn:conn.execute('create table original(value text)');conn.execute("insert into original values ('preserved')")
    def fail(root,_):
        with sqlite3.connect(database) as conn:conn.execute('drop table original');conn.execute('create table migrated(value text)')
        (root/'data/user.json').write_text('changed by failed startup')
        raise ValueError('startup failed fixture')
    restarted=[]
    with pytest.raises(ValueError):worker.run(release.root,folder,record,health=fail,restart=lambda r:restarted.append(r))
    assert (release.root/'console/view.js').read_text()=='old view' and not (release.root/'console/new.js').exists()
    assert (release.root/'data/user.json').read_text()=='user history'
    with sqlite3.connect(database) as conn:assert conn.execute('select value from original').fetchone()[0]=='preserved'
    assert json.loads((release.root/'data/update_state.json').read_text())['status']=='ROLLED_BACK' and restarted


def test_interrupted_update_recovers_from_verified_backups(release):
    folder,record=job(release);payload=release.envelope['payload']
    journal=worker.prepare(release.root,folder,payload,release.new);worker.apply_files(release.root,folder,release.new,journal)
    worker.run(release.root,folder,record,recover=True,restart=lambda r:None)
    assert (release.root/'console/view.js').read_text()=='old view'
    assert not (release.root/'data/update_exit.json').exists()


def test_check_and_download_use_signed_feed_without_network(release,monkeypatch):
    monkeypatch.setattr(updates,'fetch_json',lambda url,*args:{'assets':[{'name':'director-update.json','browser_download_url':'https://github.com/'+REPO+'/releases/download/v2/director-update.json'}]} if url.startswith('https://api.github.com/') else release.envelope)
    updates.check(background=False);assert updates.state()['status']=='AVAILABLE'
    monkeypatch.setattr(updates,'open_download',lambda *a,**kw:io.BytesIO(release.archive.read_bytes()))
    updates.download(background=False)
    assert updates.state()['status']=='READY' and updates.public()['has_release']
    assert 'envelope' not in updates.public()['state'] and 'archive_path' not in updates.public()['state']


def test_unsafe_asset_origins_and_remote_writes_are_rejected(http_server):
    from core.device_link import PAGES,READ_API,WRITE_API
    assert '/updates' not in PAGES and '/ops/updates' not in READ_API|WRITE_API
    for url in ['http://github.com/example/director/releases/download/v2/x.zip','https://evil.test/x.zip','https://github.com/other/repo/releases/download/v2/x.zip']:
        with pytest.raises(ValueError):p.asset_url(url,REPO)
    assert request(http_server,'POST','/ops/updates','{}',{'Content-Type':'application/json'})[0]==403
    assert request(http_server,'POST','/ops/updates','{}',{'Content-Type':'application/json','X-Solomon-Bridge':'test-token','Origin':'https://evil.test'})[0]==403


def test_conflict_after_backup_does_not_overwrite_new_user_edit(release,monkeypatch):
    folder,record=job(release);original=worker.prepare
    def prepare_and_edit(*args):
        value=original(*args);(release.root/'console/view.js').write_text('new user edit after backup');return value
    monkeypatch.setattr(worker,'prepare',prepare_and_edit)
    with pytest.raises(ValueError,match='직접 수정'):worker.run(release.root,folder,record,restart=lambda r:None)
    assert (release.root/'console/view.js').read_text()=='new user edit after backup'
    assert json.loads((release.root/'data/update_state.json').read_text())['status']=='ERROR'


def test_corrupt_backup_does_not_restart_partial_recovery(release,monkeypatch):
    folder,record=job(release);original=worker.apply_files;restarts=[]
    def corrupt(*args):
        original(*args);(folder/'backup/code/console/view.js').write_text('corrupt backup');raise ValueError('fixture apply error')
    monkeypatch.setattr(worker,'apply_files',corrupt)
    with pytest.raises(ValueError):worker.run(release.root,folder,record,restart=lambda r:restarts.append(r))
    assert not restarts and (release.root/'data/update_exit.json').exists()
    assert json.loads((release.root/'data/update_state.json').read_text())['status']=='RECOVERY_FAILED'


def test_waiting_for_an_open_process_never_kills_it():
    import psutil
    with pytest.raises(ValueError,match='종료되지'):worker.wait_closed([{'pid':os.getpid(),'created':psutil.Process().create_time()}],timeout=.01)
    assert psutil.pid_exists(os.getpid())


def test_launcher_blocks_active_updater_and_accepts_committed_job(release):
    import psutil
    from desktop_launcher import guard_update,DesktopError
    folder,record=job(release)
    record['helper']={'pid':os.getpid(),'created':psutil.Process().create_time()}
    (folder/'job.json').write_text(json.dumps(record))
    with pytest.raises(DesktopError,match='진행 중'):guard_update(release.root)
    record['helper']={'pid':99999999,'created':0}
    (folder/'job.json').write_text(json.dumps(record))
    (folder/'journal.json').write_text(json.dumps({'stage':'COMMITTED'}))
    guard_update(release.root)
    assert not (release.root/'data/update_exit.json').exists()


def test_copied_helper_process_recovers_interrupted_transaction(release):
    import subprocess
    folder,record=job(release)
    (folder/'job.json').write_text(json.dumps(record))
    shutil.copy2(Path(worker.__file__),folder/'worker.py')
    shutil.copy2(Path(p.__file__),folder/'update_protocol.py')
    journal=worker.prepare(release.root,folder,release.envelope['payload'],release.new)
    worker.apply_files(release.root,folder,release.new,journal)
    # An inert shell records restart; no desktop, provider or external site opens.
    (release.root/'native_app.py').write_text("from pathlib import Path\nPath(__file__).with_name('restarted.txt').write_text('restarted')\n")
    completed=subprocess.run([sys.executable,str(folder/'worker.py'),'--recover'],cwd=folder,capture_output=True,text=True,timeout=15)
    assert completed.returncode==0,completed.stderr
    assert (release.root/'console/view.js').read_bytes()==b'old view'
    assert json.loads((release.root/'data/update_state.json').read_text())['status']=='ROLLED_BACK'
    assert not (release.root/'data/update_exit.json').exists()


def test_real_new_backend_probe_uses_expected_installation_and_version(release,monkeypatch):
    import socket
    source=Path(__file__).resolve().parents[1]
    for directory in ('core','agents','schemas'):
        shutil.copytree(source/directory,release.root/directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    for file in source.glob('*.py'):shutil.copy2(file,release.root/file.name)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    (release.root/'companion.json').write_text(json.dumps({'port':port,'allowed_projects':[]}))
    manifest=release.new;(release.root/'desktop_distribution.json').write_text(json.dumps(manifest))
    monkeypatch.setenv('DIRECTOR_TESTING','1');monkeypatch.setenv('TEST_DB_PATH',str(release.root/'data/director.db'))
    record={'port':port,'envelope':release.envelope}
    try:
        assert worker.probe_backend(release.root,record) is True
    except Exception:
        print((release.root/'data/update-probe.log').read_text(encoding='utf-8',errors='replace'));raise
    assert not (release.root/'data/automation_jobs.json').exists()
