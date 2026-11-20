"""Opt-in YouTube desktop OAuth + resumable uploads. No network on status reads.
Tokens and resumable-session URLs live in a local encrypted vault, excluded from backups.
"""
import base64
import hashlib
import http.server as http_server
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from core.db_path import get_db_path

LOCK=threading.RLock()
SCOPES=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.readonly']
DEFAULT={'client_id':'','client_secret_env':'YOUTUBE_CLIENT_SECRET','ffprobe_path':''}
_LOGIN=None
_LOGIN_MESSAGE='아직 연결하지 않았습니다.'

class ChannelError(ValueError):pass
class UploadUncertain(ChannelError):pass

def root():return get_db_path().parent
def _write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def settings():
    p=root()/'youtube_settings.json'
    return {**DEFAULT,**(json.loads(p.read_text(encoding='utf-8')) if p.exists() else {})}


def _protect(data,decode=False):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]
        buf=ctypes.create_string_buffer(data);src=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte)));out=Blob()
        fn=ctypes.windll.crypt32.CryptUnprotectData if decode else ctypes.windll.crypt32.CryptProtectData
        if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out)):raise ChannelError('Windows 사용자 인증 저장소에 접근할 수 없습니다.')
        try:return ctypes.string_at(out.data,out.size)
        finally:ctypes.windll.kernel32.LocalFree(out.data)
    from cryptography.fernet import Fernet
    p=root()/'secrets/youtube-vault.key'
    if not p.exists():
        if decode:raise ChannelError('YouTube 인증 키가 없습니다. 다시 로그인하세요.')
        p.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
    crypt=Fernet(p.read_bytes())
    return crypt.decrypt(data) if decode else crypt.encrypt(data)
def vault():
    p=root()/'secrets/youtube-vault.bin'
    if not p.exists():return {}
    try:return json.loads(_protect(p.read_bytes(),True))
    except Exception as exc:raise ChannelError('YouTube 인증을 읽을 수 없습니다. 이 PC에서 다시 연결하세요.') from exc

def save_vault(value):
    p=root()/'secrets/youtube-vault.bin';p.parent.mkdir(parents=True,exist_ok=True);raw=_protect(json.dumps(value).encode());tmp=p.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw)
    tmp.replace(p)

def public():
    import shutil
    cfg=settings()
    try:v=vault();error=''
    except ChannelError as exc:v={};error=str(exc)
    return {'settings':cfg,'connected':bool(v.get('refresh_token') and v.get('channel_id')),'channel':{'id':v.get('channel_id',''),'title':v.get('channel_title','')},'secret_present':bool(os.environ.get(cfg['client_secret_env'])),'ffprobe_available':bool(shutil.which(cfg['ffprobe_path'] or 'ffprobe')),'login_message':error or _LOGIN_MESSAGE}

def save_settings(value):
    cfg={k:value.get(k,'') for k in DEFAULT}
    if any(not isinstance(v,str) or len(v)>2048 for v in cfg.values()) or (cfg['client_id'] and not re.fullmatch(r'[A-Za-z0-9._-]+\.apps\.googleusercontent\.com',cfg['client_id'])) or not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,79}',cfg['client_secret_env']):raise ChannelError('Google 데스크톱 OAuth 클라이언트 ID와 환경변수 이름을 확인하세요.')
    if cfg['ffprobe_path'] and not Path(cfg['ffprobe_path']).is_absolute():raise ChannelError('ffprobe 실행 파일은 절대 경로로 입력하세요.')
    with LOCK:
        old=settings()
        if _LOGIN:raise ChannelError('로그인 창을 완료하거나 취소한 뒤 설정을 변경하세요.')
        if vault().get('refresh_token') and any(cfg[k]!=old[k] for k in ('client_id','client_secret_env')):raise ChannelError('먼저 연결을 해제한 뒤 OAuth 설정을 변경하세요.')
        _write(root()/'youtube_settings.json',cfg)
    return public()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def http(method,url,headers=None,data=None):
    if os.environ.get('DIRECTOR_TESTING')=='1':raise RuntimeError('YOUTUBE_NETWORK_BLOCKED_IN_TEST')
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in {'www.googleapis.com','oauth2.googleapis.com'} or parsed.username or parsed.password or parsed.port not in (None,443):raise ChannelError('허용되지 않는 YouTube API 주소입니다.')
    request=urllib.request.Request(url,data=data,headers=headers or {},method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=60) as response:return response.status,dict(response.headers),response.read(1024*1024)
    except urllib.error.HTTPError as exc:
        body=exc.read(65536)
        if exc.code==308:return 308,dict(exc.headers),body
        reason=''
        try:reason=json.loads(body).get('error',{}).get('errors',[{}])[0].get('reason','')
        except (ValueError,AttributeError,IndexError,TypeError):pass
        if not isinstance(reason,str) or not re.fullmatch(r'[a-zA-Z0-9_]{0,80}',reason):reason=''
        raise ChannelError(f'Google API 오류 {exc.code}'+(' · '+reason if reason else '')+' · 인증/할당량/YouTube Studio를 확인하세요.') from None
    except (OSError,TimeoutError):raise ChannelError('Google API 연결이 중단됐습니다. 상태를 확인하세요.') from None

def _json(method,url,token=None,body=None,form=None):
    headers={};data=None
    if token:headers['Authorization']='Bearer '+token
    if body is not None:data=json.dumps(body).encode();headers['Content-Type']='application/json'
    if form is not None:data=urllib.parse.urlencode(form).encode();headers['Content-Type']='application/x-www-form-urlencoded'
    raw=http(method,url,headers,data)[2]
    return json.loads(raw) if raw else {}

def _access():
    with LOCK:
        v=vault();cfg=settings()
        if not v.get('refresh_token'):raise ChannelError('먼저 이 PC에서 YouTube 계정에 연결하세요.')
        if v.get('expires_at',0)>time.time()+120:return v['access_token']
        reply=_json('POST','https://oauth2.googleapis.com/token',form={'client_id':cfg['client_id'],'client_secret':os.environ.get(cfg['client_secret_env'],''),'refresh_token':v['refresh_token'],'grant_type':'refresh_token'})
        if not reply.get('access_token'):raise ChannelError('Google 토큰 갱신에 실패했습니다. 다시 로그인하세요.')
        v.update(access_token=reply['access_token'],expires_at=time.time()+int(reply.get('expires_in',3600)));save_vault(v);return v['access_token']

def channels(token):return _json('GET','https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true',token).get('items',[])
def videos(ids):
    if not ids:return []
    return _json('GET','https://www.googleapis.com/youtube/v3/videos?'+urllib.parse.urlencode({'part':'snippet,status,processingDetails','id':','.join(ids[:50])}),_access()).get('items',[])

def cancel_login():
    global _LOGIN
    with LOCK:
        flow=_LOGIN;_LOGIN=None
    if flow:flow['server'].shutdown();flow['server'].server_close()

def start_login():
    global _LOGIN,_LOGIN_MESSAGE
    cfg=settings()
    if not cfg['client_id'] or not os.environ.get(cfg['client_secret_env']):raise ChannelError('데스크톱 OAuth ID와 클라이언트 시크릿 환경변수를 먼저 설정하세요.')
    cancel_login();state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    class Callback(http_server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass  # OAuth codes never enter logs.
        def do_GET(self):
            global _LOGIN_MESSAGE
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            with LOCK:
                flow=_LOGIN
                valid=bool(flow and not flow.get('used') and flow['server'] is self.server and time.time()<flow['expires_at'] and urllib.parse.urlsplit(self.path).path=='/oauth2callback' and secrets.compare_digest(query.get('state',[''])[0],state))
                if valid:flow['used']=True
            if not valid:self.send_error(400,'Invalid or expired login');return
            try:
                if query.get('error'):raise ChannelError('Google 로그인이 취소됐습니다.')
                reply=_json('POST','https://oauth2.googleapis.com/token',form={'client_id':cfg['client_id'],'client_secret':os.environ[cfg['client_secret_env']],'code':query.get('code',[''])[0],'code_verifier':verifier,'redirect_uri':flow['redirect_uri'],'grant_type':'authorization_code'})
                if not reply.get('refresh_token') or not set(SCOPES)<=set(reply.get('scope','').split()):raise ChannelError('YouTube 업로드·채널 확인 권한에 동의한 뒤 다시 연결하세요.')
                found=channels(reply['access_token'])
                if len(found)!=1:raise ChannelError('업로드할 YouTube 채널 하나를 선택하여 다시 로그인하세요.')
                from core.scheduled_work import ACTIVE, LOCK as work_lock
                with work_lock, LOCK:
                    if _LOGIN is not flow or time.time()>=flow['expires_at']:raise ChannelError('로그인이 취소·만료됐습니다. 현재 로그인 창을 사용하세요.')
                    if ACTIVE:raise ChannelError('업로드가 끝난 뒤 다시 로그인하세요. 기존 연결을 유지합니다.')
                    save_vault({'refresh_token':reply['refresh_token'],'access_token':reply['access_token'],'expires_at':time.time()+int(reply.get('expires_in',3600)),'channel_id':found[0]['id'],'channel_title':found[0]['snippet']['title'],'sessions':{}})
                message='YouTube 연결 완료. 앱으로 돌아가 새로고침하세요.'
            except Exception as exc:message=str(exc) if isinstance(exc,ChannelError) else 'YouTube 연결에 실패했습니다. 앱에서 다시 연결하세요.'
            with LOCK:
                if _LOGIN is flow:_LOGIN_MESSAGE=message
            body=message.encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def finish():
                with LOCK:same=bool(_LOGIN and _LOGIN['server'] is self.server)
                if same:cancel_login()
            threading.Thread(target=finish,daemon=True).start()
    server=http_server.ThreadingHTTPServer(('127.0.0.1',0),Callback);redirect=f'http://127.0.0.1:{server.server_address[1]}/oauth2callback'
    with LOCK:_LOGIN={'server':server,'redirect_uri':redirect,'expires_at':time.time()+600}
    threading.Thread(target=server.serve_forever,name='director-youtube-oauth',daemon=True).start()
    def expire():
        with LOCK:same=bool(_LOGIN and _LOGIN['server'] is server)
        if same:cancel_login()
    timer=threading.Timer(600,expire);timer.daemon=True;timer.start()
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode();_LOGIN_MESSAGE='PC의 기본 브라우저에서 Google 로그인을 완료하세요. 10분 후 만료됩니다.'
    return {'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode({'client_id':cfg['client_id'],'redirect_uri':redirect,'response_type':'code','scope':' '.join(SCOPES),'access_type':'offline','prompt':'consent','state':state,'code_challenge':challenge,'code_challenge_method':'S256'}),'expires_in':600}

def disconnect():
    cancel_login()
    with LOCK:
        v=vault()
        if v.get('refresh_token'):_json('POST','https://oauth2.googleapis.com/revoke',form={'token':v['refresh_token']})
        p=root()/'secrets/youtube-vault.bin'
        if p.exists():p.unlink()
    return public()

def upload(job,media,stopped):
    """Upload once. Any failure after session creation is ambiguous; never retry automatically."""
    token=_access();found=channels(token)
    if len(found)!=1 or found[0]['id']!=job['approval']['channel_id']:raise ChannelError('승인한 채널과 현재 로그인 채널이 다릅니다. 다시 검토하세요.')
    metadata={'snippet':{'title':media['title'],'description':media['description'],'categoryId':'22'},'status':{'privacyStatus':'private','publishAt':job['publish_at'],'selfDeclaredMadeForKids':media['made_for_kids'],'containsSyntheticMedia':media['synthetic_media']}}
    try:
        if stopped():raise ChannelError('업로드 시작 전에 중지됐습니다.')
        status,headers,_=http('POST','https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',{'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Upload-Content-Length':str(media['size']),'X-Upload-Content-Type':media['mime']},json.dumps(metadata).encode())
        location=next((v for k,v in headers.items() if k.lower()=='location'),'');u=urllib.parse.urlsplit(location)
        if u.scheme!='https' or u.hostname!='www.googleapis.com' or u.username or u.password or u.port not in (None,443) or not u.path.startswith('/upload/youtube/'):raise ChannelError('Google 업로드 세션 주소를 확인할 수 없습니다.')
        with LOCK:v=vault();v.setdefault('sessions',{})[job['id']]=location;save_vault(v)
        offset=0;sha=hashlib.sha256()
        with open(media['path'],'rb') as f:
            while offset<media['size']:
                if stopped():raise ChannelError('업로드가 중지됐습니다. YouTube 상태를 확인하세요.')
                data=f.read(min(8*1024*1024,media['size']-offset))
                if not data:raise ChannelError('업로드 중 원본 파일이 변경됐습니다.')
                sha.update(data);end=offset+len(data)
                if end==media['size'] and (sha.hexdigest()!=media['sha256'] or f.read(1)):raise ChannelError('승인한 영상과 실제 파일이 달라 업로드를 완료하지 않았습니다.')
                token=_access()
                code,reply_headers,body=http('PUT',location,{'Authorization':'Bearer '+token,'Content-Type':media['mime'],'Content-Length':str(len(data)),'Content-Range':f'bytes {offset}-{end-1}/{media["size"]}'},data)
                if code in (200,201):
                    if end!=media['size']:raise ChannelError('전체 영상을 보내기 전에 완료 응답이 도착했습니다.')
                    result=json.loads(body)
                    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',result.get('id','')):raise ChannelError('YouTube 영상 ID를 확인할 수 없습니다.')
                    return result['id']
                if code!=308 or end==media['size']:raise ChannelError('업로드 결과를 확인할 수 없습니다.')
                confirmed=next((v for k,v in reply_headers.items() if k.lower()=='range'),'')
                if confirmed!=f'bytes=0-{end-1}':raise ChannelError('YouTube 업로드 수신 위치가 일치하지 않습니다.')
                offset=end
        raise ChannelError('업로드 결과가 없습니다.')
    except Exception as exc:
        raise UploadUncertain('업로드 결과 확인이 필요합니다. 자동 재업로드하지 않습니다. '+(str(exc) if isinstance(exc,ChannelError) else '통신 또는 파일 오류')) from None
