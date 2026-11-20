"""Shared, strict signed-release/archive contract. Safe to copy beside the updater helper."""
import base64,hashlib,json,re,stat,zipfile
from pathlib import Path,PurePosixPath
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APP='ai-dev-director'
PROTOCOL=1
MAX_ARCHIVE=160*1024*1024
MAX_UNPACKED=256*1024*1024
MAX_FILES=10000
PRESERVE={'data/.gitkeep','config.yaml','companion.json','desktop_distribution.json'}
BLOCKED={'data','runs','research','.venv','.git','node_modules','native','build','dist','artifacts','__pycache__','.director_worktrees','secrets','credentials'}
MANUAL_FILES={'native_app.py','desktop_launcher.py','requirements.txt','requirements-native.txt','scripts/build_native_app.py'}

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()
def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9]\d{0,7})(?:\.(?:0|[1-9]\d{0,7})){2,3}',value):raise ValueError('올바른 숫자 버전이 필요합니다.')
    parts=tuple(map(int,value.split('.')));return parts+(0,)*(4-len(parts))

def repo(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}',value):raise ValueError('GitHub owner/repository 형식이 필요합니다.')
    return value

def public_key(value):
    try:
        raw=base64.b64decode(value,validate=True)
        if len(raw)!=32:raise ValueError()
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:raise ValueError('32바이트 Ed25519 공개키(Base64)를 확인하세요.') from None

def asset_url(value,repository):
    try:u=urlsplit(value)
    except (TypeError,ValueError):raise ValueError('배포 파일 URL이 올바르지 않습니다.')
    if u.scheme!='https' or u.hostname!='github.com' or u.username or u.password or u.port or u.query or u.fragment or not u.path.startswith('/'+repo(repository)+'/releases/download/') or any(x in {'.','..'} for x in u.path.split('/')):raise ValueError('설정한 GitHub 저장소의 HTTPS Release 파일만 지원합니다.')
    return value

def verify_envelope(envelope,key,repository):
    if not isinstance(envelope,dict) or set(envelope)!={'payload','signature'} or not isinstance(envelope['payload'],dict):raise ValueError('서명 배포 정보 형식이 올바르지 않습니다.')
    payload=envelope['payload']
    try:public_key(key).verify(base64.b64decode(envelope['signature'],validate=True),canonical(payload))
    except Exception:raise ValueError('업데이트 서명을 확인하지 못했습니다. 적용하지 않습니다.') from None
    required={'app','format','repository','version','min_updater','archive_url','archive_sha256','archive_bytes','release_notes'}
    if set(payload)!=required or payload['app']!=APP or type(payload['format']) is not int or payload['format']!=1 or payload['repository']!=repository:raise ValueError('앱 또는 저장소가 일치하지 않습니다.')
    version(payload['version']);asset_url(payload['archive_url'],repository)
    if type(payload['min_updater']) is not int or payload['min_updater']<1:raise ValueError('업데이트 프로토콜이 올바르지 않습니다.')
    if not isinstance(payload['archive_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',payload['archive_sha256']):raise ValueError('배포 파일 SHA-256을 확인하세요.')
    if type(payload['archive_bytes']) is not int or not 0<payload['archive_bytes']<=MAX_ARCHIVE:raise ValueError('배포 크기 제한을 초과했습니다.')
    if not isinstance(payload['release_notes'],str) or len(payload['release_notes'])>12000:raise ValueError('변경 내용이 너무 큽니다.')
    return payload

def safe_name(name):
    if name=='data/.gitkeep':return name
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or '\x00' in name:raise ValueError('안전하지 않은 업데이트 경로입니다.')
    p=PurePosixPath(name)
    for part in p.parts:
        if part.endswith((' ','.')) or any(ord(c)<32 or c in '<>"|?*' for c in part) or re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part):raise ValueError('Windows에서 안전하지 않은 업데이트 경로입니다.')
    if p.is_absolute() or any(x in {'.','..'} or x.lower() in BLOCKED or x.lower().startswith('.env') for x in p.parts) or str(p)!=name or p.suffix.lower() in {'.key','.pem','.pfx','.token','.db','.sqlite3'}:raise ValueError('업데이트가 실행 환경·데이터·인증 파일을 변경할 수 없습니다: '+name)
    return name

def target(root,name):
    safe_name(name);root=Path(root).resolve();out=root.joinpath(*PurePosixPath(name).parts)
    if not out.resolve().is_relative_to(root) or any(root.joinpath(*PurePosixPath(name).parts[:i]).is_symlink() for i in range(1,len(PurePosixPath(name).parts)+1)):raise ValueError('설치 경로의 바로가기 또는 심볼릭 링크를 지원하지 않습니다.')
    return out

def inspect_archive(path,payload):
    path=Path(path)
    if path.stat().st_size!=payload['archive_bytes'] or sha(path.read_bytes())!=payload['archive_sha256']:raise ValueError('업데이트 다운로드의 크기 또는 해시가 다릅니다.')
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist();seen=set();total=0;files={};prefix='AI DEV DIRECTOR/'
        if len(entries)>MAX_FILES:raise ValueError('업데이트 파일 수 제한을 초과했습니다.')
        for info in entries:
            if info.is_dir():continue
            if not info.filename.startswith(prefix):raise ValueError('업데이트 ZIP 루트가 올바르지 않습니다.')
            name=safe_name(info.filename[len(prefix):]);fold=name.casefold()
            if fold in seen or stat.S_ISLNK(info.external_attr>>16):raise ValueError('중복 경로나 링크가 포함된 ZIP입니다.')
            seen.add(fold);total+=info.file_size
            if total>MAX_UNPACKED or info.file_size>64*1024*1024 or info.file_size>max(1,info.compress_size)*1000:raise ValueError('압축 해제 크기 제한을 초과했습니다.')
            files[name]=info
        if 'desktop_distribution.json' not in files:raise ValueError('설치 목록이 없습니다.')
        info=files['desktop_distribution.json']
        if info.file_size>2*1024*1024:raise ValueError('설치 목록이 너무 큽니다.')
        manifest=json.loads(archive.read(info));managed=manifest.get('files')
        if manifest.get('app')!=APP or manifest.get('format')!=1 or manifest.get('version')!=payload['version'] or not isinstance(managed,dict):raise ValueError('설치 목록의 앱·버전이 다릅니다.')
        essential={'desktop_launcher.py','companion_server.py','release_version.py','core/app_updates.py','core/update_protocol.py','scripts/update_worker.py'}
        if not essential<=set(managed):raise ValueError('업데이트 실행·복구 필수 파일이 없습니다.')
        if set(files)!={*managed,'desktop_distribution.json'}:raise ValueError('서명 ZIP과 설치 목록 파일이 다릅니다.')
        for name,digest in managed.items():
            safe_name(name)
            if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or sha(archive.read(files[name]))!=digest:raise ValueError('설치 파일 해시가 다릅니다: '+name)
    return manifest

def plan(root,old,new):
    old_files=old.get('files',{});new_files=new['files'];changes=[];deletes=[];manual=[]
    for name,digest in new_files.items():
        if name in PRESERVE:continue
        file=target(root,name)
        if old_files.get(name)==digest:continue
        if file.exists() and (name not in old_files or sha(file.read_bytes())!=old_files[name]):raise ValueError('직접 수정된 설치 파일이 있어 업데이트를 보류합니다: '+name)
        if not file.exists() and name in old_files:raise ValueError('기존 설치 파일이 없습니다. 전체 설치로 복구하세요: '+name)
        changes.append(name)
        if name in MANUAL_FILES:manual.append(name)
    for name,digest in old_files.items():
        if name in new_files or name in PRESERVE:continue
        file=target(root,name)
        if file.exists():
            if sha(file.read_bytes())!=digest:raise ValueError('삭제 예정 파일에 사용자 변경이 있습니다: '+name)
            deletes.append(name)
            if name in MANUAL_FILES:manual.append(name)
    return {'changed':changes,'removed':deletes,'manual_required':bool(manual),'manual_files':sorted(set(manual))}
