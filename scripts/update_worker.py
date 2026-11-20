"""Independent updater copied outside replaced code; no shell strings or unrelated PID kills."""
import hashlib,http.client,json,os,shutil,subprocess,sys,tempfile,time,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE if (HERE/'update_protocol.py').is_file() else HERE.parent/'core'))
import update_protocol as protocol
import psutil

MAX_DATA=512*1024*1024
SKIP_DATA={'app_updates','desktop_clients','update_exit.json'}

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.update-',delete=False) as f:temp=Path(f.name);f.write(json.dumps(value,ensure_ascii=False).encode())
    try:temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def alive(record):
    try:p=psutil.Process(record['pid']);return abs(p.create_time()-record['created'])<.01 and p.status()!=psutil.STATUS_ZOMBIE
    except (psutil.Error,KeyError):return False

def wait_closed(records,timeout=60):
    deadline=time.monotonic()+timeout
    while any(alive(record) for record in records):
        if time.monotonic()>deadline:raise ValueError('앱이 종료되지 않아 업데이트를 취소했습니다. 강제 종료하지 않았습니다.')
        time.sleep(.2)

def backup_data(root,destination):
    root=Path(root);destination=Path(destination);entries=[];total=0
    for item in (root/'data').iterdir():
        if item.name in SKIP_DATA or item.name.endswith('.lock'):continue
        if item.is_symlink():raise ValueError('운영 기록의 링크를 백업할 수 없습니다.')
        for file in ([item] if item.is_file() else item.rglob('*')):
            if file.is_symlink():raise ValueError('운영 기록의 링크를 백업할 수 없습니다.')
            if not file.is_file():continue
            total+=file.stat().st_size
            if total>MAX_DATA or len(entries)>=20000:raise ValueError('적용 전 운영 기록 백업 한도(512MB/20,000파일)를 초과했습니다.')
            entries.append(file)
    hashes={}
    for file in entries:
        relative=file.relative_to(root/'data');out=destination/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,out);hashes[relative.as_posix()]=protocol.sha(out.read_bytes())
    return hashes

def replace_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.update-',delete=False) as f:temp=Path(f.name);f.write(data)
    try:temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def prepare(root,job,payload,manifest):
    old=read(root/'desktop_distribution.json');plan=protocol.plan(root,old,manifest)
    if plan['manual_required']:raise ValueError('실행 파일·의존성 변경은 전체 설치가 필요합니다.')
    names=sorted(set(plan['changed']+plan['removed']+['desktop_distribution.json']))
    backup=job/'backup';backup.mkdir(exist_ok=True);originals={};size=0
    for name in names:
        source=protocol.target(root,name);originals[name]=source.is_file()
        if source.is_file():size+=source.stat().st_size
    if shutil.disk_usage(job).free<size+MAX_DATA+payload['archive_bytes']:raise ValueError('코드·운영 기록 백업 공간이 부족합니다.')
    data_hashes=backup_data(root,backup/'data')
    code_hashes={}
    for name,exists in originals.items():
        if exists:
            source=protocol.target(root,name);out=backup/'code'/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,out);code_hashes[name]=protocol.sha(out.read_bytes())
    journal={'stage':'BACKED_UP','backup_ready':True,'originals':originals,'code_hashes':code_hashes,'data_hashes':data_hashes,'plan':plan,'old_version':old.get('version'),'new_version':payload['version']}
    atomic(job/'journal.json',journal)
    return journal

def restore(root,job):
    journal=read(job/'journal.json')
    if not journal.get('backup_ready'):return
    for name,digest in journal.get('code_hashes',{}).items():
        backup=job/'backup/code'/name
        if backup.is_symlink() or protocol.sha(backup.read_bytes())!=digest:raise ValueError('코드 복구본 검증에 실패했습니다.')
    for name,digest in journal.get('data_hashes',{}).items():
        backup=job/'backup/data'/name
        if backup.is_symlink() or not backup.resolve().is_relative_to((job/'backup/data').resolve()) or protocol.sha(backup.read_bytes())!=digest:raise ValueError('운영 기록 복구본 검증에 실패했습니다.')
    for name,existed in journal['originals'].items():
        file=protocol.target(root,name)
        if existed:replace_bytes(file,(job/'backup/code'/name).read_bytes())
        elif file.exists():file.unlink()
    # Called only before the new normal app is started. Preserve updater/desktop state.
    for item in (root/'data').iterdir():
        if item.name in SKIP_DATA or item.name.endswith('.lock'):continue
        if item.is_symlink():raise ValueError('데이터 복구 대상에 링크가 있습니다.')
        if item.is_dir():shutil.rmtree(item)
        else:item.unlink()
    backup=job/'backup/data'
    if backup.exists():shutil.copytree(backup,root/'data',dirs_exist_ok=True)
    journal['stage']='ROLLED_BACK';atomic(job/'journal.json',journal)

def apply_files(root,job,manifest,journal):
    journal['stage']='APPLYING';atomic(job/'journal.json',journal)
    with zipfile.ZipFile(job/'archive.zip') as archive:
        for name in journal['plan']['changed']:
            replace_bytes(protocol.target(root,name),archive.read('AI DEV DIRECTOR/'+name))
        for name in journal['plan']['removed']:protocol.target(root,name).unlink(missing_ok=True)
        replace_bytes(root/'desktop_distribution.json',archive.read('AI DEV DIRECTOR/desktop_distribution.json'))
    journal['stage']='VERIFYING';atomic(job/'journal.json',journal)

def probe_backend(root,record):
    port=record['port'];existing=http.client.HTTPConnection('127.0.0.1',port,timeout=.5)
    try:
        existing.request('GET','/ops/desktop-health');existing.getresponse().read();raise ValueError('기존 포트가 사용 중입니다. 다른 프로그램은 중지하지 않았습니다.')
    except (OSError,http.client.HTTPException):pass
    finally:existing.close()
    environment={**os.environ,'DIRECTOR_UPDATE_PROBE':'1'}
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    with (root/'data/update-probe.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,str(root/'companion_server.py')],cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,**options)
    expected=hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest();deadline=time.monotonic()+45;healthy=False
    try:
        while time.monotonic()<deadline:
            if process.poll() is not None:break
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
            try:
                connection.request('GET','/ops/desktop-health');response=connection.getresponse();value=json.loads(response.read(4096))
                if response.status==200 and value.get('installation_id')==expected and value.get('version')==record['envelope']['payload']['version']:healthy=True;break
            except (OSError,ValueError,http.client.HTTPException):pass
            finally:connection.close()
            time.sleep(.4)
        if not healthy:raise ValueError('새 버전의 백엔드 시작 검사를 통과하지 못했습니다.')
    finally:
        # Terminate only the exact probe child we started; no auto-resume/scheduler runs in probe mode.
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    return healthy

def launch(root):
    exe=root/'native/AI-DEV-DIRECTOR/AI-DEV-DIRECTOR.exe'
    argv=[str(exe),'--app-root',str(root)] if exe.is_file() else [sys.executable,str(root/'native_app.py'),'--app-root',str(root)]
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
    subprocess.Popen(argv,cwd=root,**options)

def run(root,job,record,health=probe_backend,restart=launch,recover=False):
    root=Path(root).resolve();job=Path(job).resolve();committed=False;backed=False;closed=False;restored=False;recovery_failed=False;mutated=False
    try:
        wait_closed([record['backend'],*record.get('clients',[])]);closed=True
        settings=read(root/'data/update_settings.json')
        if settings['public_key']!=record['public_key'] or settings['repository']!=record['repository']:raise ValueError('등록된 업데이트 신뢰 설정이 변경됐습니다.')
        payload=protocol.verify_envelope(record['envelope'],settings['public_key'],settings['repository'])
        if payload['min_updater']>protocol.PROTOCOL:raise ValueError('전체 설치가 필요한 업데이트입니다.')
        if recover:
            prior=read(job/'journal.json');backed=bool(prior.get('backup_ready'))
            if prior.get('stage') in {'APPLYING','VERIFYING'}:
                mutated=True;restore(root,job);restored=True
                atomic(root/'data/update_state.json',{'status':'ROLLED_BACK','message':'중단된 업데이트를 이전 상태로 복구했습니다.'})
            elif prior.get('stage')=='COMMITTED':
                atomic(root/'data/update_state.json',{'status':'INSTALLED','version':payload['version'],'message':'업데이트 시작 검사가 완료된 버전으로 실행합니다.'})
            else:
                atomic(root/'data/update_state.json',{'status':'ERROR','message':'파일 교체 전 중단된 업데이트를 취소했습니다. 기존 파일을 유지합니다.'})
        else:
            manifest=protocol.inspect_archive(job/'archive.zip',payload)
            if protocol.version(payload['version'])<=protocol.version(read(root/'desktop_distribution.json')['version']):raise ValueError('동일 버전 또는 이전 버전은 적용하지 않습니다.')
            journal=prepare(root,job,payload,manifest);backed=True
            # Recheck archive and local changes after backup, immediately before writes.
            protocol.inspect_archive(job/'archive.zip',payload);protocol.plan(root,read(root/'desktop_distribution.json'),manifest)
            mutated=True
            apply_files(root,job,manifest,journal)
            if health(root,record) is not True:raise ValueError('새 버전 시작 검사 성공 근거가 없습니다.')
            journal['stage']='COMMITTED';atomic(job/'journal.json',journal);committed=True
            atomic(root/'data/update_state.json',{'status':'INSTALLED','version':payload['version'],'message':'업데이트와 시작 검사를 완료했습니다.','job_id':job.name})
    except Exception as exc:
        if mutated:
            try:restore(root,job);restored=True
            except Exception:
                recovery_failed=True;atomic(root/'data/update_state.json',{'status':'RECOVERY_FAILED','message':'자동 복구가 완료되지 않았습니다. 앱 시작을 보류했습니다. 설치 폴더의 업데이트 기록을 확인하세요.'});raise
            atomic(root/'data/update_state.json',{'status':'ROLLED_BACK','message':'새 버전 시작/적용 실패로 이전 코드·데이터를 복구했습니다: '+str(exc)[:700],'job_id':job.name})
        else:atomic(root/'data/update_state.json',{'status':'ERROR','message':'업데이트 적용 전 중단: '+str(exc)[:700]})
        raise
    finally:
        if not recovery_failed and closed:
            (root/'data/update_exit.json').unlink(missing_ok=True)
            restart(root)
        elif not recovery_failed and not backed:
            (root/'data/update_exit.json').unlink(missing_ok=True)


def main():
    job=HERE;root=HERE.parents[2]
    if job.parent.name!='app_updates' or job.parent.parent.name!='data' or not job.name.startswith('UPD-'):raise ValueError('설치 앱이 준비한 업데이트 작업에서만 실행할 수 있습니다.')
    if '--recover' in sys.argv[1:]:
        marker=root/'data/update_exit.json'
        if not marker.is_file() or read(marker).get('job_id')!=job.name:raise ValueError('복구 대기 중인 설치 작업이 아닙니다.')
    record=read(job/'job.json')
    if str(root.resolve())!=record['root'] or job.is_symlink():raise ValueError('설치 식별자가 다릅니다.')
    lock=(job/'worker.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    atomic(job/'worker-process.json',{'pid':os.getpid(),'created':psutil.Process().create_time()})
    run(root,job,record,recover='--recover' in sys.argv[1:])
if __name__=='__main__':main()
