"""Local sync-folder operational snapshots; no cloud credentials, no source/build backup.
Restoration is staged and applied before database users start on next launch.
"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from core.db_path import get_db_path

LOCK=threading.RLock()
FILES={'development_rules.json','employee_tools.json','automation_plans.json','automation_jobs.json','office_layouts.json','director.db','team_settings.json','company_meetings.json','executive_briefings.json','skill_library.json','company_knowledge.json','ai_connections.json','hermes_settings.json','hermes_jobs.json','engine-projects.json','role_settings.json'}
MAX_BYTES=128*1024*1024

def root(): return get_db_path().parent
def atomic(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)
def settings():
    p=root()/'backup_settings.json'
    return {'enabled':False,'folder':'','interval_minutes':60,'keep':10,**(json.loads(p.read_text(encoding='utf-8')) if p.exists() else {})}
def allowed(name): return name in FILES or bool(re.fullmatch(r'missions/MSN-[A-Za-z0-9_-]+\.json',name))
def digest(data): return hashlib.sha256(data).hexdigest()
def candidates():
    return list(dict.fromkeys(str(Path(os.environ[k]).resolve()) for k in ('OneDrive','OneDriveConsumer','OneDriveCommercial') if os.environ.get(k)))
def destination():
    cfg=settings();p=Path(cfg['folder'])
    if not cfg['folder'] or not p.is_absolute() or not p.is_dir(): raise ValueError('존재하는 OneDrive 또는 백업 폴더의 절대 경로를 지정하세요.')
    p=p.resolve(); r=root().resolve()
    if p==r or r in p.parents or p in r.parents: raise ValueError('프로그램 데이터와 분리된 백업 폴더를 선택하세요.')
    out=p/'AI-DEV-DIRECTOR-Backups'
    if out.is_symlink(): raise ValueError('백업 하위 폴더의 바로가기는 허용하지 않습니다.')
    out.mkdir(exist_ok=True)
    return out

def save_settings(value):
    if not isinstance(value.get('enabled'),bool) or type(value.get('interval_minutes')) is not int or not 15<=value['interval_minutes']<=1440 or type(value.get('keep')) is not int or not 2<=value['keep']<=50 or not isinstance(value.get('folder'),str): raise ValueError('백업 주기(15~1440분)·보관 수(2~50개)·폴더를 확인하세요.')
    cfg={k:value[k] for k in ('enabled','folder','interval_minutes','keep')}
    if len(cfg['folder'])>2048: raise ValueError('폴더 경로가 너무 깁니다.')
    if cfg['folder'] and (not Path(cfg['folder']).is_absolute() or not Path(cfg['folder']).is_dir()): raise ValueError('존재하는 절대 경로를 입력하세요.')
    if cfg['enabled'] and not cfg['folder']: raise ValueError('자동 백업 폴더를 먼저 지정하세요.')
    with LOCK: atomic(root()/'backup_settings.json',cfg)
    return status()

def archives():
    if not settings()['folder']: return []
    p=destination()
    return [{'id':x.name,'bytes':x.stat().st_size,'modified':x.stat().st_mtime} for x in sorted(p.glob('backup-*.zip'),reverse=True) if not x.is_symlink()][:50]
def status():
    state=root()/'backup_state.json'
    try: items=archives();error=''
    except (ValueError,OSError) as exc: items=[];error=str(exc)
    return {'settings':settings(),'candidates':candidates(),'archives':items,'state':json.loads(state.read_text(encoding='utf-8')) if state.exists() else {},'pending_restore':(root()/'restore_pending').is_dir(),'error':error,'coverage':'회사 설정·회의·지식·미션·SQLite 운영 기록. 게임 소스·작업트리·빌드·인증키 파일·기기 인증 제외. OneDrive 업로드 완료 여부는 앱이 확인하지 않습니다.'}

def assert_idle():
    from core.ai_connections import assert_idle as idle
    idle()
    from core.scheduled_work import ACTIVE
    if ACTIVE: raise ValueError('유튜브 업로드를 완료 또는 중지한 뒤 백업·복구하세요.')
    from core import hermes_agent, company_meetings
    if any(j.get('status') in {'QUEUED','RUNNING','STOPPING'} for j in hermes_agent.telemetry()['jobs']): raise ValueError('Hermes 업무를 완료 또는 중지한 뒤 백업·복구하세요.')
    if any(m.get('status') in company_meetings.ACTIVE for m in company_meetings.snapshot()['meetings']): raise ValueError('회의를 먼저 완료하세요.')

def create():
    with LOCK:
        if (root()/'update_exit.json').exists():raise ValueError('앱 업데이트 중에는 운영 백업을 시작하지 않습니다.')
        assert_idle();out=destination(); cfg=settings()
        ident='backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+uuid.uuid4().hex[:8]+'.zip'
        final=out/ident;tmp=out/(ident+'.partial')
        try:
            with tempfile.TemporaryDirectory() as temp:
                data={}
                db=get_db_path()
                if db.exists():
                    snapshot=Path(temp)/'director.db'
                    with closing(sqlite3.connect(str(db))) as source,closing(sqlite3.connect(str(snapshot))) as target: source.backup(target)
                    data['director.db']=snapshot.read_bytes()
                files=[root()/n for n in FILES if n!='director.db']+list((root()/'missions').glob('MSN-*.json'))
                for p in files:
                    if p.is_file() and not p.is_symlink() and not p.parent.is_symlink():
                        raw=p.read_bytes();json.loads(raw);data[p.relative_to(root()).as_posix()]=raw
                if sum(map(len,data.values()))>MAX_BYTES: raise ValueError('운영 기록이 백업 한도 128MB를 초과했습니다.')
                manifest={'format':1,'app':'ai-dev-director-operations','created_at':datetime.now(timezone.utc).isoformat(),'files':{n:digest(v) for n,v in data.items()}}
                with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
                    for n,raw in data.items(): z.writestr(n,raw)
                    z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
                verify(tmp)
                tmp.replace(final)
            # Retention only ever touches this app's matching archive files.
            for entry in sorted(out.glob('backup-*.zip'),reverse=True)[cfg['keep']:]:
                if not entry.is_symlink(): entry.unlink()
            atomic(root()/'backup_state.json',{'last_success':manifest['created_at'],'archive':ident,'message':'로컬 백업 저장 완료 · 클라우드 업로드는 OneDrive에서 확인하세요.'})
        finally:
            if tmp.exists():tmp.unlink()
        return status()

def verify(p):
    try: return _verify(p)
    except (zipfile.BadZipFile, sqlite3.Error, KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError('백업 형식 또는 데이터베이스가 올바르지 않습니다.') from exc

def _verify(p):
    with zipfile.ZipFile(p) as z:
        names=z.namelist()
        if len(names)>10000 or len(set(names))!=len(names) or 'manifest.json' not in names or sum(i.file_size for i in z.infolist())>MAX_BYTES+1024*1024: raise ValueError('백업 크기·구성이 올바르지 않습니다.')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('format')!=1 or manifest.get('app')!='ai-dev-director-operations' or not isinstance(manifest.get('files'),dict) or set(names)!=set(manifest['files'])|{'manifest.json'}: raise ValueError('백업 목록이 일치하지 않습니다.')
        data={}
        if 'director.db' not in manifest['files']: raise ValueError('데이터베이스가 없는 백업은 복구할 수 없습니다.')
        for n,h in manifest['files'].items():
            if not allowed(n): raise ValueError('허용하지 않는 복구 파일입니다.')
            raw=z.read(n)
            if digest(raw)!=h: raise ValueError('백업 해시가 일치하지 않습니다.')
            if n!='director.db': json.loads(raw)
            data[n]=raw
        if 'director.db' in data:
            with tempfile.TemporaryDirectory() as temp:
                db=Path(temp)/'verify.db';db.write_bytes(data['director.db'])
                with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
                    if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('백업 데이터베이스가 손상됐습니다.')
        return data

def stage_restore(ident, confirmation):
    with LOCK:
        assert_idle()
        if confirmation!='운영 기록 복구': raise ValueError('확인 문구: 운영 기록 복구')
        if not isinstance(ident,str) or not re.fullmatch(r'backup-[A-Za-z0-9-]+\.zip',ident): raise ValueError('백업을 선택하세요.')
        p=destination()/ident
        if p.is_symlink(): raise ValueError('백업 바로가기는 복구할 수 없습니다.')
        data=verify(p)
        # Save current state before scheduling replacement. Existing pairing/backup config remains local.
        create()
        stage=root()/'restore_pending'
        if stage.exists(): raise ValueError('이미 예약된 복구가 있습니다. 취소하거나 재시작하세요.')
        temp=root()/('restore-'+uuid.uuid4().hex)
        try:
            temp.mkdir()
            for n,raw in data.items():
                target=temp/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            atomic(temp/'restore.json',{'files':{n:digest(v) for n,v in data.items()},'archive':ident})
            temp.replace(stage)
        finally:
            if temp.exists():shutil.rmtree(temp)
        return status()

def apply_pending():
    """Only at backend startup, before schema opening or any workers. Idempotent after a crash."""
    stage=root()/'restore_pending'
    if not stage.exists(): return
    if stage.is_symlink(): raise ValueError('복구 폴더 바로가기는 허용하지 않습니다.')
    meta=json.loads((stage/'restore.json').read_text(encoding='utf-8'));data={}
    if 'director.db' not in meta['files']: raise ValueError('데이터베이스가 없는 복구 예약입니다.')
    for n,h in meta['files'].items():
        if not allowed(n) or digest((stage/n).read_bytes())!=h: raise ValueError('예약 복구 파일 검증 실패; 데이터를 변경하지 않았습니다.')
        data[n]=(stage/n).read_bytes()
    # Stop captured jobs; a historical PID must never revive work or spend on restart.
    for n,raw in list(data.items()):
        if n.endswith('.json'):
            value=json.loads(raw)
            if n=='automation_plans.json':
                for plan in value.get('plans',[]):plan['enabled']=False
            if n=='automation_jobs.json':
                for job in value.get('jobs',[]):
                    job['restored_unverified']=True
                    if job['status']=='APPROVED':job.update(status='READY_REVIEW',approval=None)
                    if job['status'] in {'UPLOADING','STOPPING'}:job.update(status='NEEDS_REVIEW',remote_attempt=True)
                    job['error']='운영 백업에서 복구됨. 기존 업로드를 Studio에서 확인한 뒤 수동으로 재검토하세요.'
            records=([value] if n.startswith('missions/') else value.get('jobs',[]) if n=='hermes_jobs.json' else value.get('meetings',[]) if n=='company_meetings.json' else [])
            for record in records:
                if record.get('status') in {'RUNNING','QUEUED','STOPPING'}: record.update(status='STOPPED',owner_pid=None,error='운영 백업에서 복구되어 중지됨',blocked_reason='복구된 작업은 자동 재실행하지 않습니다.')
            data[n]=json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')
    existing=[get_db_path() if n=='director.db' else root()/n for n in FILES]+list((root()/'missions').glob('MSN-*.json'))
    for p in existing:
        if p.is_symlink() or p.parent.is_symlink(): raise ValueError('데이터 바로가기는 복구할 수 없습니다.')
    for n,raw in data.items():
        p=get_db_path() if n=='director.db' else root()/n;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.restore-tmp');tmp.write_bytes(raw);tmp.replace(p)
    for p in existing:
        if ('director.db' if p==get_db_path() else p.relative_to(root()).as_posix()) not in data and p.exists():p.unlink()
    for suffix in ('-wal','-shm'):
        p=Path(str(get_db_path())+suffix)
        if p.exists():p.unlink()
    # Nonterminal SQLite runs must require manual attention, not startup automatic retries.
    if get_db_path().exists():
        with closing(sqlite3.connect(str(get_db_path()))) as conn:
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                conn.execute("UPDATE runs SET current_state='HUMAN_REQUIRED' WHERE current_state NOT IN ('PASS','FAIL','HUMAN_REQUIRED','TIMEOUT')")
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_usage'").fetchone():
                conn.execute("UPDATE ai_usage SET status='INTERRUPTED', pid=NULL WHERE status='RUNNING'")
            conn.commit()
    atomic(root()/'backup_state.json',{'last_restore':datetime.now(timezone.utc).isoformat(),'archive':meta['archive'],'message':'복구 완료. 경로·AI 연결을 확인한 뒤 작업을 수동으로 재개하세요.'})
    shutil.rmtree(stage)

def cancel_restore():
    with LOCK:
        p=root()/'restore_pending'
        if p.exists():shutil.rmtree(p)
        return status()

def start_scheduler(stop):
    def worker():
        while not stop.wait(30):
            try:
                cfg=settings();state=status()['state'];stamp=state.get('last_success')
                due=not stamp or time.time()-datetime.fromisoformat(stamp).timestamp()>=cfg['interval_minutes']*60
                if cfg['enabled'] and due and not (root()/'restore_pending').exists():create()
            except Exception as exc:
                # Busy work is retried next interval, never interrupted to make a snapshot.
                atomic(root()/'backup_state.json',{**(status()['state']),'message':'백업 대기/실패: '+str(exc)[:300]})
    thread=threading.Thread(target=worker,name='director-operations-backup',daemon=True);thread.start();return thread
