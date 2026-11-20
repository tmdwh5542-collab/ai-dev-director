"""PC-only signed updates. Network checks are optional; application is always user initiated."""
import hashlib,json,os,re,shutil,subprocess,sys,threading,time,urllib.error,urllib.request,uuid
from pathlib import Path
from urllib.parse import urlsplit
from core import update_protocol as protocol
from core import staffing
from core.web_workspace import atomic
from core.subprocess_options import hidden_console
from release_version import VERSION

ROOT=Path(__file__).resolve().parents[1]
LOCK=threading.RLock()
BUSY=False
MAX_FEED=100000
DEFAULT={'repository':'','public_key':'','auto_check':True,'auto_download':False}

def data_root():return staffing.settings_path().parent
def settings_path():return data_root()/'update_settings.json'
def state_path():return data_root()/'update_state.json'
def jobs_root():return data_root()/'app_updates'
def read(path,default):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
def settings():return {**DEFAULT,**read(settings_path(),{})}
def state():return read(state_path(),{'status':'UNCONFIGURED','message':'업데이트 배포 저장소와 공개키를 등록하세요.'})
def current_version():return read(ROOT/'desktop_distribution.json',{}).get('version',VERSION)
def configured():return bool(settings()['repository'] and settings()['public_key'])
def now():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def update_state(**value):
    with LOCK:
        current=state();current.update(value);atomic(state_path(),current);return current

def public():
    with LOCK:
        value=state();clean={k:v for k,v in value.items() if k not in {'envelope','archive_path'}}
        if value.get('status')=='INSTALLER_REQUIRED':
            try:clean['installer_url']=protocol.verify_envelope(value['envelope'],settings()['public_key'],settings()['repository'])['archive_url']
            except (ValueError,KeyError):pass
        return {'current_version':current_version(),'installed':(ROOT/'desktop_distribution.json').is_file(),'settings':settings(),'configured':configured(),'busy':BUSY,'has_release':bool(value.get('envelope')),'state':clean,
                'notice':'서명된 GitHub Release만 지원합니다. 적용은 PC에서 사용자가 선택하며 작업 중에는 보류합니다. 배포 저장소·실제 배포본은 아직 연결하지 않은 상태일 수 있습니다.'}

def save(value):
    from core.ai_connections import assert_idle
    assert_idle();cfg=value.get('settings')
    if not isinstance(cfg,dict) or set(cfg)!=set(DEFAULT) or any(type(cfg[k]) is not bool for k in ('auto_check','auto_download')):raise ValueError('업데이트 설정을 확인하세요.')
    if cfg['repository'] or cfg['public_key']:
        protocol.repo(cfg['repository']);protocol.public_key(cfg['public_key'])
    with LOCK:
        if BUSY:raise ValueError('확인·다운로드가 끝난 뒤 설정을 변경하세요.')
        atomic(settings_path(),cfg);atomic(state_path(),{'status':'IDLE' if cfg['repository'] else 'UNCONFIGURED','message':'업데이트 연결 설정을 저장했습니다. 새 버전 확인을 실행하세요.'})
    return public()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def open_download(url,allow_cdn=False):
    opener=urllib.request.build_opener(NoRedirect())
    for _ in range(5):
        u=urlsplit(url)
        if u.scheme!='https' or u.username or u.password or u.port or (u.hostname not in {'github.com','api.github.com'} and not (allow_cdn and u.hostname in {'release-assets.githubusercontent.com','objects.githubusercontent.com'})):raise ValueError('허용되지 않은 업데이트 서버 또는 리디렉션입니다.')
        try:return opener.open(urllib.request.Request(url,headers={'User-Agent':'AI-DEV-DIRECTOR-Update','Accept':'application/vnd.github+json' if u.hostname=='api.github.com' else 'application/octet-stream'}),timeout=25)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301,302,303,307,308} or not exc.headers.get('Location'):raise ValueError('업데이트 서버 요청 실패: '+str(exc.code)) from None
            url=exc.headers['Location']
    raise ValueError('업데이트 리디렉션 한도를 초과했습니다.')

def fetch_json(url,limit,cdn=False):
    with open_download(url,cdn) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('업데이트 정보가 너무 큽니다.')
    return json.loads(data)

def check(background=True):
    global BUSY
    with LOCK:
        if BUSY:raise ValueError('업데이트 확인·다운로드가 이미 진행 중입니다.')
        cfg=settings()
        if not configured():raise ValueError('관리하는 GitHub 저장소와 배포 공개키를 먼저 등록하세요.')
        BUSY=True
    def run():
        global BUSY
        try:
            update_state(status='CHECKING',message='서명된 최신 배포 정보를 확인합니다.')
            release=fetch_json('https://api.github.com/repos/'+protocol.repo(cfg['repository'])+'/releases/latest',512000)
            asset=next((a for a in release.get('assets',[]) if a.get('name')=='director-update.json'),None)
            if not asset:raise ValueError('최신 Release에 director-update.json이 없습니다.')
            url=protocol.asset_url(asset.get('browser_download_url'),cfg['repository']);envelope=fetch_json(url,MAX_FEED,True)
            payload=protocol.verify_envelope(envelope,cfg['public_key'],cfg['repository'])
            available=protocol.version(payload['version'])>protocol.version(current_version())
            update_state(status='AVAILABLE' if available else 'UP_TO_DATE',checked_at=now(),message='새 버전이 있습니다.' if available else '현재 버전이 최신입니다.',version=payload['version'],release_notes=payload['release_notes'],envelope=envelope,archive_path=None,plan=None)
        except Exception as exc:update_state(status='ERROR',message=str(exc)[:1000])
        finally:
            with LOCK:BUSY=False
        if cfg['auto_download'] and state().get('status')=='AVAILABLE':
            try:download()
            except Exception as exc:update_state(status='ERROR',message=str(exc)[:1000])
    if background:threading.Thread(target=run,daemon=True,name='director-update-check').start()
    else:run()
    return public()

def download(background=True):
    global BUSY
    with LOCK:
        if BUSY:raise ValueError('업데이트 확인·다운로드가 진행 중입니다.')
        cfg=settings();envelope=state().get('envelope');payload=protocol.verify_envelope(envelope,cfg['public_key'],cfg['repository'])
        if protocol.version(payload['version'])<=protocol.version(current_version()):raise ValueError('현재 버전보다 새로운 배포본만 받습니다.')
        BUSY=True
    def run():
        global BUSY
        job=jobs_root()/('UPD-'+uuid.uuid4().hex[:20]);part=job/'archive.part';archive=job/'archive.zip'
        try:
            job.mkdir(parents=True,exist_ok=True)
            update_state(status='DOWNLOADING',message='배포 파일을 내려받아 검증합니다.',received_bytes=0)
            if shutil.disk_usage(job).free<payload['archive_bytes']*3+64*1024*1024:raise ValueError('업데이트 다운로드·백업 공간이 부족합니다.')
            size=0
            with open_download(payload['archive_url'],True) as response,part.open('xb') as output:
                while True:
                    chunk=response.read(512*1024)
                    if not chunk:break
                    size+=len(chunk)
                    if size>payload['archive_bytes']:raise ValueError('서명된 배포 크기를 초과했습니다.')
                    output.write(chunk)
                    update_state(received_bytes=size)
            part.replace(archive);manifest=protocol.inspect_archive(archive,payload)
            old=read(ROOT/'desktop_distribution.json',{})
            plan=protocol.plan(ROOT,old,manifest) if old else {'manual_required':True,'manual_files':['최초 전체 설치 필요'],'changed':[],'removed':[]}
            manual=plan['manual_required'] or payload['min_updater']>protocol.PROTOCOL
            update_state(status='INSTALLER_REQUIRED' if manual else 'READY',message='실행 파일·의존성 변경 또는 최초 설치: 전체 설치가 필요합니다.' if manual else '서명·파일 검증 완료. 작업을 마친 뒤 적용하세요.',archive_path=str(archive),plan=plan)
        except Exception as exc:
            part.unlink(missing_ok=True);update_state(status='ERROR',message=str(exc)[:1000],archive_path=None)
        finally:
            with LOCK:BUSY=False
    if background:threading.Thread(target=run,daemon=True,name='director-update-download').start()
    else:run()
    return public()

def assert_idle():
    from core.company_backup import assert_idle as operations_idle
    operations_idle()
    from core import web_workspace,setup_assistant
    if any(p['process'].poll() is None for p in web_workspace.SERVERS.values()) or any(j['status']=='RUNNING' for j in web_workspace.JOBS.values()):raise ValueError('개발 서버와 웹 검수를 먼저 종료하세요.')
    if setup_assistant.PROCESS is not None and setup_assistant.PROCESS.poll() is None:raise ValueError('도구 설치가 끝난 뒤 업데이트하세요.')
    if (data_root()/'restore_pending').exists():raise ValueError('예약된 데이터 복구를 먼저 처리하세요.')
    import dashboard_server as d
    if d._ACTIVE_PROJECTS:raise ValueError('프로젝트 실행 준비가 끝난 뒤 업데이트하세요.')

def apply(server):
    global BUSY
    with LOCK:
        if BUSY:raise ValueError('다운로드·확인이 끝난 뒤 적용하세요.')
        assert_idle();s=state();cfg=settings()
        if s.get('status')!='READY' or not s.get('archive_path'):raise ValueError('검증된 업데이트를 먼저 다운로드하세요.')
        payload=protocol.verify_envelope(s['envelope'],cfg['public_key'],cfg['repository']);archive=Path(s['archive_path'])
        if not archive.resolve().is_relative_to(jobs_root().resolve()) or archive.is_symlink():raise ValueError('업데이트 캐시 경로가 올바르지 않습니다.')
        old=read(ROOT/'desktop_distribution.json',{});new=protocol.inspect_archive(archive,payload);plan=protocol.plan(ROOT,old,new)
        if not old or protocol.version(payload['version'])<=protocol.version(current_version()) or plan['manual_required'] or payload['min_updater']>protocol.PROTOCOL:raise ValueError('전체 설치가 필요하거나 적용할 새 버전이 없습니다.')
        if data_root().resolve()!=ROOT/'data':raise ValueError('설치된 PC 앱에서만 업데이트를 적용하세요.')
        import psutil
        clients=[]
        for file in (ROOT/'data/desktop_clients').glob('*.json'):
            try:
                record=json.loads(file.read_text(encoding='utf-8'));process=psutil.Process(record['pid'])
                if record['installation_id']==hashlib.sha256(os.path.normcase(str(ROOT.resolve())).encode()).hexdigest() and abs(process.create_time()-record['created'])<.01:clients.append(record)
            except (OSError,ValueError,KeyError,psutil.Error):pass
        if not clients:raise ValueError('데스크톱 앱에서 업데이트를 적용하세요. 브라우저·태블릿 적용은 지원하지 않습니다.')
        job=archive.parent
        shutil.copy2(ROOT/'scripts/update_worker.py',job/'worker.py');shutil.copy2(ROOT/'core/update_protocol.py',job/'update_protocol.py')
        record={'id':job.name,'root':str(ROOT.resolve()),'envelope':s['envelope'],'public_key':cfg['public_key'],'repository':cfg['repository'],'backend':{'pid':os.getpid(),'created':psutil.Process().create_time()},'clients':clients,'port':server.server_address[1]}
        atomic(job/'job.json',record)
        with (job/'helper.log').open('ab') as log:
            worker=subprocess.Popen([sys.executable,str(job/'worker.py')],cwd=job,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,**hidden_console())
        record['helper']={'pid':worker.pid,'created':psutil.Process(worker.pid).create_time()};atomic(job/'job.json',record)
        server.maintenance=True
        if hasattr(server,'background_stop'):server.background_stop.set()
        atomic(ROOT/'data/update_exit.json',{'job_id':job.name})
        update_state(status='APPLYING',message='앱을 닫고 백업 후 업데이트합니다. 잠시 후 다시 실행됩니다.',job_id=job.name)
        BUSY=True
        def stop():time.sleep(.8);server.shutdown()
        threading.Thread(target=stop,daemon=True).start()
        return {'status':'APPLYING','job_id':job.name,'helper_pid':worker.pid}

def start_scheduler(stop):
    def run():
        if stop.wait(8):return
        while not stop.is_set():
            if configured() and settings()['auto_check'] and not BUSY:
                try:check()
                except Exception:pass
            if stop.wait(6*60*60):return
    thread=threading.Thread(target=run,daemon=True,name='director-update-scheduler');thread.start();return thread
