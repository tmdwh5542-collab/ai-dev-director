"""Owned development processes, bounded source checkpoints and evidence-only audits.
No shell command strings, dependency installation, deployment or unowned PID termination.
"""
import atexit
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import tempfile
import time
import uuid
from urllib.parse import urlsplit
from core import staffing
from core.subprocess_options import hidden_console

LOCK=threading.RLock()
SERVERS={}
JOBS={}
AUDIT_PROCESSES={}
ROOT=Path(__file__).resolve().parents[1]
EXT={'.js','.jsx','.ts','.tsx','.mjs','.cjs','.css','.scss','.sass','.html','.htm','.json','.md','.txt','.vue','.svelte','.py','.gd','.cs','.shader','.svg','.yaml','.yml','.toml'}
DENY={'node_modules','.git','.venv','venv','dist','build','coverage','.next','.cache','vendor'}
MAX_FILE=1024*1024
MAX_TOTAL=16*1024*1024

def root():return staffing.settings_path().parent/'web_workspace'
def digest(data):return hashlib.sha256(data).hexdigest()
def stamp():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)
def write_source(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.director-',suffix='.tmp',dir=path.parent,delete=False) as stream:
        temp=Path(stream.name);stream.write(data)
    try:temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def project(value):
    import dashboard_server as d
    if not isinstance(value,str):raise ValueError('프로젝트를 선택하세요.')
    ok,p=d.validate_project_path(value)
    if not ok:raise ValueError(str(p))
    return Path(p)
def folder(p):return root()/digest(str(p).encode())[:24]
def git(p,*args):
    r=subprocess.run(['git','-C',str(p),*args],capture_output=True,timeout=15,**hidden_console())
    if r.returncode:raise ValueError('Git 조회 실패: '+r.stderr.decode('utf-8','replace')[:300])
    return r.stdout

def source(p,name):
    if not isinstance(name,str) or not name or len(name)>512 or '\\' in name or '\x00' in name:raise ValueError('소스 파일 경로를 확인하세요.')
    parts=Path(name).parts
    if Path(name).is_absolute() or any(x in {'.','..',*DENY} or x.startswith('.') or any(t in x.lower() for t in ('secret','credential','token','private-key')) for x in parts) or Path(name).suffix.lower() not in EXT:raise ValueError('편집 가능한 일반 소스 파일만 지원합니다. 숨김·비밀 파일은 제외합니다.')
    candidate=p.joinpath(*parts)
    if any(p.joinpath(*parts[:i]).is_symlink() for i in range(1,len(parts)+1)) or not candidate.resolve().is_relative_to(p.resolve()):raise ValueError('심볼릭 링크나 프로젝트 밖 경로는 지원하지 않습니다.')
    return candidate

def names(p):
    data=git(p,'ls-files','-z','--cached','--others','--exclude-standard');result=[]
    for raw in data.split(b'\x00'):
        if not raw:continue
        name=raw.decode('utf-8','strict')
        try:
            path=source(p,name)
            if path.is_file():result.append(name)
        except ValueError:continue
    result=sorted(set(result))
    if len(result)>600:raise ValueError('소스 파일이 600개를 초과합니다. 프로젝트 범위를 나누세요.')
    return result

def read(p,name):
    path=source(p,name)
    if not path.is_file():raise ValueError('소스 파일을 찾을 수 없습니다.')
    if path.stat().st_size>MAX_FILE:raise ValueError('파일은 1MB 이하여야 합니다.')
    raw=path.read_bytes()
    try:content=raw.decode('utf-8')
    except UnicodeDecodeError:raise ValueError('UTF-8 텍스트 파일만 지원합니다.')
    return {'path':name,'content':content,'sha256':digest(raw)}

def snapshot(p,label='수정 전 체크포인트'):
    files={};total=0
    for name in names(p):
        path=source(p,name)
        if path.stat().st_size>MAX_FILE:raise ValueError('체크포인트 파일 한도는 1MB입니다.')
        data=path.read_bytes();total+=len(data)
        if len(data)>MAX_FILE or total>MAX_TOTAL:raise ValueError('체크포인트 한도: 파일 1MB, 전체 16MB입니다.')
        files[name]=base64.b64encode(data).decode()
    if names(p)!=list(files):raise staffing.TeamConflict('소스 목록이 변경됐습니다. 체크포인트를 다시 저장하세요.')
    for name,encoded in files.items():
        path=source(p,name)
        if not path.is_file() or digest(path.read_bytes())!=digest(base64.b64decode(encoded)):raise staffing.TeamConflict('보관 중 소스가 변경됐습니다. 다시 저장하세요.')
    ident='CP-'+uuid.uuid4().hex[:20]
    value={'id':ident,'created_at':stamp(),'label':str(label)[:100],'project_path':str(p),'files':files}
    out=folder(p)/'checkpoints'
    if len(list(out.glob('CP-*.json')))>=30:raise ValueError('체크포인트 보관 한도 30개에 도달했습니다.')
    atomic(out/(ident+'.json'),value);return {'id':ident,'label':value['label'],'created_at':value['created_at'],'files':len(files)}

def checkpoint(p,ident):
    if not isinstance(ident,str) or not re.fullmatch(r'CP-[a-f0-9]{20}',ident):raise ValueError('체크포인트 ID가 필요합니다.')
    file=folder(p)/'checkpoints'/(ident+'.json')
    if not file.exists():raise ValueError('체크포인트를 찾을 수 없습니다.')
    return json.loads(file.read_text(encoding='utf-8'))

def comparison(p,ident):
    old=checkpoint(p,ident);files=[]
    for name in sorted(set(old['files'])|set(names(p))):
        path=source(p,name);before=base64.b64decode(old['files'][name]) if name in old['files'] else None
        after=path.read_bytes() if path.is_file() else None
        if before==after:continue
        if after is not None and len(after)>MAX_FILE:raise ValueError('변경 파일이 1MB를 초과합니다.')
        try:diff=''.join(difflib.unified_diff((before or b'').decode('utf-8').splitlines(True),(after or b'').decode('utf-8').splitlines(True),fromfile='checkpoint/'+name,tofile='current/'+name))[:32000]
        except UnicodeDecodeError:diff='바이너리 변경 (편집 미지원)'
        files.append({'path':name,'before_sha256':digest(before) if before is not None else None,'current_sha256':digest(after) if after is not None else None,'diff':diff})
    rev=digest(json.dumps(files,sort_keys=True).encode())
    return {'checkpoint':ident,'revision':rev,'files':files,'notice':'복구는 이 비교 시점 이후 파일이 바뀌면 거부합니다. 생성된 소스 파일은 복구 시 제거될 수 있습니다.'}

def restore(p,ident,expected):
    with LOCK:
        diff=comparison(p,ident)
        if expected!=diff['revision']:raise staffing.TeamConflict('비교 이후 파일이 변경됐습니다. 다시 비교하세요.')
        baseline=checkpoint(p,ident);undo=snapshot(p,'복구 직전 자동 보관')
        originals={};written=[]
        try:
            for change in diff['files']:
                path=source(p,change['path']);raw=path.read_bytes() if path.is_file() else None
                if (digest(raw) if raw is not None else None)!=change['current_sha256']:raise staffing.TeamConflict('파일이 변경되어 복구를 중지했습니다.')
                originals[path]=raw
            for change in diff['files']:
                name=change['path'];path=source(p,name);written.append(path)
                if name in baseline['files']:
                    write_source(path,base64.b64decode(baseline['files'][name]))
                elif path.exists():path.unlink()
        except Exception:
            for path in written:
                if originals[path] is None:path.unlink(missing_ok=True)
                else:write_source(path,originals[path])
            raise
        return {'restored':len(diff['files']),'undo_checkpoint':undo['id']}

def save_file(p,value):
    with LOCK:
        current=read(p,value.get('path'))
        if value.get('expected_sha256')!=current['sha256']:raise staffing.TeamConflict('파일이 변경됐습니다. 다시 읽고 비교하세요.')
        content=value.get('content')
        if not isinstance(content,str) or len(content.encode())>MAX_FILE:raise ValueError('1MB 이하 UTF-8 소스가 필요합니다.')
        backup=snapshot(p,'편집 전 자동 보관');path=source(p,current['path'])
        if read(p,current['path'])['sha256']!=current['sha256']:raise staffing.TeamConflict('보관 중 파일이 변경됐습니다. 다시 읽으세요.')
        write_source(path,content.encode('utf-8'))
        return {**read(p,current['path']),'checkpoint':backup['id']}

def config(p):
    path=folder(p)/'server.json'
    return json.loads(path.read_text()) if path.exists() else {'script':'dev','port':3000}

def package(p):
    file=p/'package.json'
    if file.is_symlink() or not file.is_file() or file.stat().st_size>128000:return {}
    value=json.loads(file.read_text(encoding='utf-8'));return value.get('scripts',{})

def server_status(p):
    entry=SERVERS.get(str(p));cfg=config(p)
    alive=bool(entry and entry['process'].poll() is None)
    ready=False
    if alive:
        try:
            with socket.create_connection(('127.0.0.1',entry['port']),timeout=.2):ready=True
        except OSError:pass
    log=entry['lines'][-100:] if entry else []
    return {'running':alive,'ready':ready,'owned':bool(entry),'url':f"http://127.0.0.1:{entry['port']}" if ready else None,'pid':entry['process'].pid if alive else None,'script':cfg['script'],'port':cfg['port'],'log':log}

def stop_owned(process):
    if process.poll() is not None:return
    import psutil
    try:
        proc=psutil.Process(process.pid);children=proc.children(recursive=True)
        for child in reversed(children):
            try:child.terminate()
            except psutil.NoSuchProcess:pass
        proc.terminate();_,alive=psutil.wait_procs(children+[proc],timeout=3)
        for child in alive:
            try:child.kill()
            except psutil.NoSuchProcess:pass
    except psutil.NoSuchProcess:pass
    process.wait(timeout=5)

def stop_server(p):
    entry=SERVERS.get(str(p))
    if entry:stop_owned(entry['process'])
    return server_status(p)

def start_server(p,value):
    with LOCK:
        if server_status(p)['running']:return server_status(p)
        script=value.get('script','dev');port=value.get('port',3000)
        if script not in {'dev','start','serve','preview'} or script not in package(p):raise ValueError('package.json의 dev/start/serve/preview 스크립트를 선택하세요.')
        if type(port) is not int or not 1024<=port<=65535:raise ValueError('1024~65535 포트를 선택하세요.')
        try:
            with socket.socket() as sock:sock.bind(('127.0.0.1',port))
        except OSError:raise ValueError('이 포트는 다른 프로그램이 사용 중입니다. 기존 프로세스는 종료하지 않습니다.')
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:raise ValueError('Node.js/npm을 먼저 설치하세요.')
        # Scripts are from the explicitly selected user project, run only by this button.
        argv=[npm,'run',script,'--','--port',str(port),'--host','127.0.0.1']
        text=str(package(p).get(script,''))
        if re.search(r'\bnext\b',text):argv=[npm,'run',script,'--','--port',str(port),'--hostname','127.0.0.1']
        env={**os.environ,'PORT':str(port),'HOST':'127.0.0.1','BROWSER':'none','FORCE_COLOR':'0','npm_config_cache':str(folder(p)/'npm-cache')}
        snapshot(p,'개발 서버 시작 전')
        process=subprocess.Popen(argv,cwd=p,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',**hidden_console())
        entry={'process':process,'port':port,'lines':[]};SERVERS[str(p)]=entry;atomic(folder(p)/'server.json',{'script':script,'port':port})
        def drain():
            for line in process.stdout:
                with LOCK:
                    entry['lines'].append(re.sub(r'\x1b\[[0-9;]*m','',line.rstrip())[:1500]);entry['lines'][:]=entry['lines'][-100:]
        threading.Thread(target=drain,daemon=True).start()
    return server_status(p)

def tools_status():
    return {'node':bool(shutil.which('node')),'playwright':(ROOT/'tools/web/node_modules/playwright/package.json').exists(),'lighthouse':(ROOT/'tools/web/node_modules/lighthouse/package.json').exists(),'monaco':(ROOT/'console/vendor/monaco/vs/loader.js').exists(),'setup':'PC에서 scripts/setup_web_tools.py를 실행하면 고정 버전 도구를 설치합니다.'}

def reports(p):
    out=folder(p)/'reports';result=[]
    for path in sorted(out.glob('AUD-*.json'),key=lambda f:f.stat().st_mtime,reverse=True)[:20]:
        value=json.loads(path.read_text(encoding='utf-8'));result.append({k:v for k,v in value.items() if k not in {'details'}})
    for job in JOBS.values():
        if job['project_path']==str(p) and job['status']=='RUNNING':result.insert(0,dict(job))
    return result

def audit(p,value):
    kind=value.get('kind','browser');url=value.get('url');steps=value.get('steps',[])
    if not isinstance(steps,list) or len(steps)>8:raise ValueError('화면 검수 단계는 최대 8개입니다.')
    for step in steps:
        if not isinstance(step,dict) or step.get('action') not in {'click','fill'} or not isinstance(step.get('selector'),str) or not 1<=len(step['selector'])<=200 or not isinstance(step.get('value',''),str) or len(step.get('value',''))>2000:raise ValueError('검수 단계 형식을 확인하세요.')
    try:u=urlsplit(url)
    except (ValueError,TypeError):raise ValueError('검수 주소를 확인하세요.')
    # Browser automation never receives local operational/admin URLs or private credentials.
    entry=server_status(p)
    if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost'} or u.username or u.password or not entry['running'] or u.port!=config(p)['port']:raise ValueError('자동 검수는 이 작업실에서 실행한 개발 서버 주소만 지원합니다.')
    if kind not in {'browser','lighthouse'}:raise ValueError('검수 종류를 확인하세요.')
    if not tools_status()[kind if kind=='lighthouse' else 'playwright']:raise ValueError('웹 검수 도구 설치가 필요합니다.')
    with LOCK:
        if len(list((folder(p)/'reports').glob('AUD-*.json')))>=100:raise ValueError('검수 보고서 보관 한도 100개에 도달했습니다.')
        if any(j['status']=='RUNNING' for j in JOBS.values()):raise ValueError('이전 검수가 끝난 뒤 실행하세요.')
        ident='AUD-'+uuid.uuid4().hex[:20];job={'id':ident,'kind':kind,'url':url,'project_path':str(p),'status':'RUNNING','created_at':stamp()};JOBS[ident]=job
    def run():
        directory=folder(p)/'reports'/ident;directory.mkdir(parents=True,exist_ok=True)
        try:
            argv=[shutil.which('node'),str(ROOT/'scripts/web_audit.mjs'),kind,url,str(directory)]
            process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**hidden_console());AUDIT_PROCESSES[ident]=process
            try:stdout,stderr=process.communicate(json.dumps({'steps':steps}).encode(),timeout=150)
            except subprocess.TimeoutExpired:
                stop_owned(process);raise ValueError('검수 제한 시간 150초를 초과했습니다.')
            if process.returncode:raise ValueError(stderr.decode('utf-8','replace')[-1500:] or '검수 실행 실패')
            details=json.loads(stdout.decode('utf-8'));job.update(status='DONE',summary=details.get('summary','검수 완료'),details=details,finished_at=stamp())
        except Exception as exc:job.update(status='FAILED',summary=str(exc)[:1500],finished_at=stamp())
        with LOCK:
            atomic(folder(p)/'reports'/(ident+'.json'),job);AUDIT_PROCESSES.pop(ident,None)
    threading.Thread(target=run,daemon=True).start();return dict(job)

def listing(p):
    cps=[]
    for file in (folder(p)/'checkpoints').glob('CP-*.json'):
        cp=json.loads(file.read_text(encoding='utf-8'));cps.append({k:v for k,v in cp.items() if k!='files'})
    return {'project_path':str(p),'server':server_status(p),'scripts':list(k for k in package(p) if k in {'dev','start','preview','serve'}),'files':names(p),'checkpoints':sorted(cps,key=lambda c:c['created_at'],reverse=True),'reports':reports(p),'tools':tools_status()}

def action(value):
    p=project(value.get('project_path'));act=value.get('action')
    if act=='start':return start_server(p,value)
    if act=='stop':return stop_server(p)
    if act=='delete-checkpoint':
        ident=value.get('checkpoint');checkpoint(p,ident);(folder(p)/'checkpoints'/(ident+'.json')).unlink();return {'deleted':ident}
    if act=='checkpoint':return snapshot(p,value.get('label','수동 체크포인트'))
    if act=='compare':return comparison(p,value.get('checkpoint'))
    if act=='read':
        if value.get('checkpoint'):
            cp=checkpoint(p,value['checkpoint']);name=value.get('path');source(p,name)
            raw=base64.b64decode(cp['files'].get(name,''))
            return {'path':name,'content':raw.decode('utf-8'),'sha256':digest(raw)}
        return read(p,value.get('path'))
    if act=='save':return save_file(p,value)
    if act=='restore':return restore(p,value.get('checkpoint'),value.get('expected_revision'))
    if act=='audit':return audit(p,value)
    if act=='report':
        ident=value.get('id','')
        if not re.fullmatch('AUD-[a-f0-9]{20}',ident):raise ValueError('보고서 ID를 확인하세요.')
        path=folder(p)/'reports'/(ident+'.json')
        if not path.exists():raise ValueError('보고서가 준비되지 않았습니다.')
        return json.loads(path.read_text())
    raise ValueError('지원하지 않는 웹 작업입니다.')

@atexit.register
def shutdown():
    for process in list(AUDIT_PROCESSES.values()):
        try:stop_owned(process)
        except Exception:pass
    for p in list(SERVERS):
        try:stop_server(Path(p))
        except Exception:pass
