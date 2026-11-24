"""Opt-in HTTPS LAN companion gateway. The execution server remains loopback-only.
Each paired device has a revocable, hashed session; the internal bridge token never leaves the PC.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit, parse_qs

MESH_NETWORK=ipaddress.ip_network('100.64.0.0/10')
PRIVATE_NETWORKS=[ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
COOKIE='director_device'
SESSION_SECONDS=30*86400
PAIR_SECONDS=180
MAX_BODY=64000
MANAGER_LOCK=threading.Lock()


def data_root():
    from core.db_path import get_db_path
    return get_db_path().parent


def private_address(value):
    try:
        address=ipaddress.ip_address(value)
        return address.version==4 and (any(address in n for n in PRIVATE_NETWORKS) or address in MESH_NETWORK or
               (os.environ.get('DIRECTOR_TESTING')=='1' and address.is_loopback))
    except ValueError:
        return False


def interfaces():
    import psutil
    rows=[];stats=psutil.net_if_stats()
    for name,addresses in psutil.net_if_addrs().items():
        if name in stats and not stats[name].isup:continue
        for a in addresses:
            if a.family==socket.AF_INET and private_address(a.address):
                mesh=ipaddress.ip_address(a.address) in MESH_NETWORK
                if mesh and 'tailscale' not in name.lower():continue
                rows.append({'name':name,'address':a.address,'mode':'tailscale' if mesh else 'lan'})
    return rows


def _atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    try:temp.chmod(0o600)
    except OSError:pass
    temp.replace(path)


def certificates(address):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    directory=data_root()/'device-link';cert=directory/'server.crt';key=directory/'server.key'
    directory.mkdir(parents=True,exist_ok=True)
    valid=False
    if cert.exists() and key.exists():
        try:
            parsed=x509.load_pem_x509_certificate(cert.read_bytes())
            valid=(ipaddress.ip_address(address) in parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
                   and parsed.not_valid_after_utc>datetime.now(timezone.utc)+timedelta(days=1))
        except (ValueError,x509.ExtensionNotFound):pass
    if not valid:
        private=ec.generate_private_key(ec.SECP256R1())
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'AI DEV DIRECTOR local PC')])
        current=datetime.now(timezone.utc)
        parsed=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(current-timedelta(minutes=5)).not_valid_after(current+timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]),critical=False)
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).sign(private,hashes.SHA256()))
        key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        cert.write_bytes(parsed.public_bytes(serialization.Encoding.PEM))
        try:key.chmod(0o600);cert.chmod(0o600)
        except OSError:pass
    fingerprint=x509.load_pem_x509_certificate(cert.read_bytes()).fingerprint(hashes.SHA256()).hex()
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert),str(key))
    return context,fingerprint


class LinkManager:
    def __init__(self,backend,root):
        self.backend=backend;self.root=Path(root);self.lock=threading.RLock();self.server=None;self.thread=None
        self.error=None;self.pair_hash=None;self.pair_until=0;self.attempts=[];self.fingerprint=None
        self.settings_path=data_root()/'device_link.json';self.sessions_path=data_root()/'paired_devices.json'
        self.settings=json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {'enabled':False,'address':None,'port':8443}
        self.sessions=json.loads(self.sessions_path.read_text()) if self.sessions_path.exists() else []

    def status(self):
        with self.lock:
            return {'enabled':bool(self.server),'address':self.settings.get('address'),'port':self.settings.get('port'),
                    'url':self.origin+'/pair' if self.server else None,'interfaces':interfaces(),'error':self.error,
                    'certificate_sha256':self.fingerprint,'pair_expires_at':self.pair_until if self.pair_until>time.time() else None,
                    'devices':[{k:s.get(k) for k in ('id','name','created_at','last_seen','expires_at','revoked')} for s in self.sessions],
                    'mode':'pc-hosted-private-network','pc_required':True}

    @property
    def origin(self):return 'https://'+str(self.settings['address'])+':'+str(self.settings['port'])

    def start(self,address,port=8443,persist=True):
        if not isinstance(address,str) or not private_address(address) or address not in {i['address'] for i in interfaces()}:
            raise ValueError('이 PC의 사설 Wi-Fi/LAN 주소를 선택하세요.')
        if type(port) is not int or not 1024<=port<=65535 or port==self.backend.server_address[1]:raise ValueError('연결 포트는 PC 실행 서버와 다른 1024~65535 값이어야 합니다.')
        with self.lock:
            if self.server:raise ValueError('이미 기기 연결이 켜져 있습니다. 먼저 끈 뒤 변경하세요.')
            context,fingerprint=certificates(address)
            server=GatewayServer((address,port),GatewayHandler);server.manager=self
            server.tls=context
            self.settings={'enabled':True,'address':address,'port':server.server_address[1]};self.fingerprint=fingerprint;self.server=server;self.error=None
            self.thread=threading.Thread(target=server.serve_forever,name='director-device-gateway',daemon=True);self.thread.start()
            if persist:_atomic(self.settings_path,self.settings)
        return self.status()

    def restore(self):
        if self.settings.get('enabled'):
            try:self.start(self.settings.get('address'),self.settings.get('port',8443))
            except Exception as exc:self.error='기기 연결을 복구하지 못했습니다. PC에서 연결 설정을 확인하세요: '+str(exc)

    def close(self,revoke=True,persist=True):
        with self.lock:
            server=self.server;self.server=None;self.pair_hash=None;self.pair_until=0
            if revoke:
                for s in self.sessions:s['revoked']=True
                _atomic(self.sessions_path,self.sessions)
            if persist:self.settings['enabled']=False;_atomic(self.settings_path,self.settings)
        if server:server.shutdown();server.server_close()
        return self.status()

    def issue_code(self):
        with self.lock:
            if not self.server:raise ValueError('먼저 기기 연결을 켜세요.')
            code=''.join(secrets.choice('0123456789') for _ in range(8));self.pair_hash=hashlib.sha256(code.encode()).hexdigest();self.pair_until=time.time()+PAIR_SECONDS
            return {'code':code,'expires_at':self.pair_until,'url':self.origin+'/pair'}

    def pair(self,code,name):
        with self.lock:
            now=time.time();self.attempts=[t for t in self.attempts if now-t<60]
            if len(self.attempts)>=10:raise ValueError('연결 시도가 많습니다. 1분 뒤 PC에서 코드를 새로 발급하세요.')
            self.attempts.append(now)
            if not isinstance(code,str) or len(code)!=8 or not code.isascii() or not code.isdigit() or not self.pair_hash or self.pair_until<now or not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(),self.pair_hash):raise ValueError('연결 코드가 틀리거나 만료됐습니다. PC에서 새 코드를 발급하세요.')
            if not isinstance(name,str) or not name.strip() or len(name)>40 or any(ord(c)<32 for c in name):raise ValueError('기기 이름을 1~40자로 입력하세요.')
            live=[s for s in self.sessions if not s.get('revoked') and s['expires_at']>now]
            if len(live)>=10:raise ValueError('연결된 기기는 최대 10대입니다. PC에서 사용하지 않는 기기를 해제하세요.')
            secret=secrets.token_urlsafe(32);ident=secrets.token_hex(12)
            record={'id':ident,'name':name.strip(),'token_hash':hashlib.sha256(secret.encode()).hexdigest(),'csrf':secrets.token_urlsafe(32),
                    'created_at':now,'last_seen':now,'expires_at':now+SESSION_SECONDS,'revoked':False}
            # Keep at most 50 expired/revoked history entries, while preserving every live device.
            history=[s for s in self.sessions if s not in live][-50:];self.sessions=history+live+[record]
            _atomic(self.sessions_path,self.sessions);self.pair_hash=None;self.pair_until=0
            return ident+'.'+secret,dict(record)

    def authenticate(self,cookie):
        try:
            parsed=SimpleCookie();parsed.load(cookie or '');value=parsed[COOKIE].value;ident,secret=value.split('.',1)
        except (KeyError,ValueError,CookieError):return None
        with self.lock:
            now=time.time();record=next((s for s in self.sessions if s['id']==ident),None)
            if not record or record.get('revoked') or record['expires_at']<=now or not hmac.compare_digest(record['token_hash'],hashlib.sha256(secret.encode()).hexdigest()):return None
            if now-record['last_seen']>60:record['last_seen']=now;_atomic(self.sessions_path,self.sessions)
            return dict(record)

    def revoke(self,ident):
        with self.lock:
            record=next((s for s in self.sessions if s['id']==ident),None)
            if record is None:raise ValueError('등록된 기기가 아닙니다.')
            record['revoked']=True;_atomic(self.sessions_path,self.sessions)
        return self.status()


def manager(backend,root):
    with MANAGER_LOCK:
        if not hasattr(backend,'device_link'):backend.device_link=LinkManager(backend,root)
        return backend.device_link


class GatewayServer(ThreadingHTTPServer):
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(24)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()
    daemon_threads=True
    allow_reuse_address=os.name!='nt'
    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()
    def finish_request(self,request,client_address):
        try:
            with self.tls.wrap_socket(request,server_side=True) as secured:
                self.RequestHandlerClass(secured,client_address,self)
        except (ssl.SSLError,TimeoutError,ConnectionError):pass
    def get_request(self):
        sock,address=super().get_request();sock.settimeout(20);return sock,address


READ_API={'/ops/web-workspace','/ops/web-artifact','/ops/employee-tools','/ops/automation','/ops/office-layout','/ops/secretary','/ops/knowledge','/ops/hermes/tasks','/ops/office','/ops/briefings','/status','/ops/activity','/ops/missions','/ops/digest','/ops/replay','/ops/projects','/ops/team','/ops/company','/ops/meetings',
          '/ops/workflows','/ops/project-memory','/ops/mission-launch','/ops/mission-step','/ops/roles','/chat/messages','/result','/run/approval','/run/inspect'}
WRITE_API={'/ops/team/game-ready','/ops/team/recommendations','/ops/automation','/ops/office-layout','/ops/knowledge','/ops/hermes/tasks','/ops/hermes/decide','/ops/hermes/stop','/ops/briefings','/ops/team','/ops/company','/ops/meetings','/ops/meetings/decide','/ops/mission-launch','/ops/mission-control','/ops/missions/stop',
           '/project','/chat','/chat/new','/run/approve','/run/reject','/ops/mission/decide','/result/apply','/result/discard'}
PAGES={'/web-workspace','/automation','/operations','/office','/missions','/classic'}
ASSETS={'/crew-portraits-cozy-hd.png','/vendor/pixi/csp-support.js','/office-gpu.js','/vendor/pixi/pixi.min.js','/web-tools.js','/web-workspace.js','/web-workspace.css','/furniture-art.js','/furniture-desk-hd.png','/furniture-table-hd.png','/furniture-chair-hd.png','/furniture-partition-hd.png','/furniture-plant-hd.png','/crew-portraits-hd.png','/cozy-office.js','/cozy-office.css','/game-style.js','/game-style.css','/crew-illustrated.png','/office-corporate-hd.png','/office-creative-hd.png','/office-garden-hd.png','/automation.js','/automation.css','/office-decor.js','/office-view.js','/office-decor.css','/operations.css','/operations.js','/hermes.js','/executive.js','/crew-portraits.png','/pixel-theme.css','/character-art.js','/remote.css','/office.js','/office.css','/company.js','/team-editor.js','/meetings.js','/missions.js','/missions.css'}


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args):pass  # Never log pair codes, session cookies, or request bodies.
    def response(self,value,code=200,kind='application/json; charset=utf-8',cookie=None):
        body=json.dumps(value,ensure_ascii=False).encode() if isinstance(value,dict) else value.encode() if isinstance(value,str) else value
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','private, max-age=86400' if code==200 and urlsplit(self.path).path=='/crew-portraits.png' else 'no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        policy="default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if urlsplit(self.path).path=='/web-workspace':policy+="; frame-src http: https:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'"
        if urlsplit(self.path).path=='/classic':policy+="; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        self.send_header('Content-Security-Policy',policy)
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(body)
    def error(self,text,code=400):return self.response({'error':text},code)
    def valid_origin(self,post=False):
        m=self.server.manager
        return self.headers.get('Host')==urlsplit(m.origin).netloc and (self.headers.get('Origin')==m.origin if post else self.headers.get('Origin') in (None,m.origin))
    def do_GET(self):self.handle_request(False)
    def do_POST(self):self.handle_request(True)
    def handle_request(self,post):
        if not self.valid_origin(post):
            try:
                unread=int(self.headers.get('Content-Length') or 0)
                if 0<unread<=MAX_BODY:self.rfile.read(unread)
            except (ValueError,OSError):pass
            return self.error('이 PC 연결 주소에서만 요청할 수 있습니다.',403)
        parsed=urlsplit(self.path);route=parsed.path;m=self.server.manager
        if parsed.scheme or parsed.netloc or (post and parsed.query):return self.error('요청 경로가 올바르지 않습니다.')
        try:
            body=b''
            if post:
                if self.headers.get('Transfer-Encoding'):raise ValueError('요청 형식이 올바르지 않습니다.')
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<=size<=MAX_BODY:return self.error('요청 크기가 너무 큽니다.',413)
                body=self.rfile.read(size)
            if route=='/pair' and not post:return self.response((m.root/'console/device-pair.html').read_bytes(),kind='text/html; charset=utf-8')
            if route in {'/device-pair.js','/devices.css','/pixel-theme.css'} and not post:return self.response((m.root/'console'/route[1:]).read_bytes(),kind='text/javascript; charset=utf-8' if route.endswith('.js') else 'text/css; charset=utf-8')
            if route=='/remote.webmanifest' and not post:return self.response({'name':'AI DEV DIRECTOR · PC 연결','short_name':'AI DEV','start_url':'/office','scope':'/','display':'standalone','background_color':'#ede7d7','theme_color':'#f3e9d3','icons':[{'src':'/device-icon.svg','sizes':'any','type':'image/svg+xml','purpose':'any'}]},kind='application/manifest+json')
            if route=='/device-icon.svg' and not post:return self.response((m.root/'assets/director.svg').read_bytes(),kind='image/svg+xml')
            if route=='/remote/pair' and post:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json' or len(body)>2048:raise ValueError('올바른 연결 요청이 필요합니다.')
                value=json.loads(body)
                if not isinstance(value,dict):raise ValueError('기기 이름과 연결 코드를 입력하세요.')
                token,session=m.pair(value.get('code'),value.get('name'))
                return self.response({'paired':True,'name':session['name'],'expires_at':session['expires_at']},cookie=f'{COOKIE}={token}; Path=/; Max-Age={SESSION_SECONDS}; Secure; HttpOnly; SameSite=Strict')
            session=m.authenticate(self.headers.get('Cookie'))
            if not session:
                if not post and (route in PAGES or route=='/'):
                    self.send_response(303);self.send_header('Location','/pair');self.end_headers();return
                return self.error('PC에서 연결 코드를 발급해 기기를 다시 연결하세요.',401)
            if route=='/remote/session' and not post:return self.response({'name':session['name'],'csrf':session['csrf'],'expires_at':session['expires_at'],'pc_required':True})
            if route=='/remote-client.js' and not post:return self.response((m.root/'console/remote-client.js').read_bytes(),kind='text/javascript; charset=utf-8')
            if post:
                csrf=self.headers.get('X-Director-Remote-CSRF') or self.headers.get('X-Solomon-Bridge') or ''
                if not hmac.compare_digest(csrf.encode('utf-8'),session['csrf'].encode('utf-8')):return self.error('기기 요청 인증이 필요합니다.',403)
                if route=='/remote/logout':
                    m.revoke(session['id']);return self.response({'logged_out':True},cookie=f'{COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict')
                if route not in WRITE_API:return self.error('이 기능은 PC에서 사용하세요.',403)
                if route=='/ops/automation':
                    value=json.loads(body)
                    if not isinstance(value,dict) or value.get('action') not in {'preview','prepare','approve','cancel','pause'}:return self.error('예약 계획 설정은 PC에서 사용하세요.',403)
            elif route=='/':route='/office'
            elif route not in READ_API|PAGES|ASSETS and not route.startswith('/vendor/monaco/'):return self.error('기기 연결에서 제공하지 않는 경로입니다.',403)
            # Remote clients can select/launch only projects already registered on the PC.
            project=None
            if post and route in {'/project','/ops/mission-launch','/ops/meetings','/ops/briefings','/ops/hermes/tasks','/ops/knowledge'}:
                if route=='/project':project=parse_qs(body.decode('utf-8')).get('path',[''])[0]
                else:
                    value=json.loads(body)
                    if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                    project=value.get('project_path')
            elif route in {'/ops/project-memory','/ops/web-workspace','/ops/web-artifact'}:project=parse_qs(parsed.query).get('path',[''])[0]
            if project is not None:
                import dashboard_server as d
                registered={os.path.normcase(os.path.abspath(p['path'])) for p in d.build_project_choices()['projects']}
                if not isinstance(project,str) or not os.path.isabs(project) or os.path.normcase(os.path.abspath(project)) not in registered:return self.error('먼저 PC에서 이 프로젝트를 등록하거나 선택하세요.',403)
            path=route+('?' + parsed.query if parsed.query else '')
            headers={'Accept':self.headers.get('Accept','application/json'),'Origin':f'http://127.0.0.1:{m.backend.server_address[1]}','X-Requested-With':'fetch'}
            if post:headers.update({'Content-Type':self.headers.get('Content-Type','application/json'),'X-Solomon-Bridge':m.backend.bridge_token})
            connection=http.client.HTTPConnection('127.0.0.1',m.backend.server_address[1],timeout=600 if post and route=='/chat' else 30)
            try:
                connection.request('POST' if post else 'GET',path,body=body if post else None,headers=headers)
                response=connection.getresponse();content=response.read();status=response.status;kind=response.getheader('Content-Type','application/json')
            finally:connection.close()
            if route=='/ops/roles' and not post:
                value=json.loads(content);content=json.dumps({'roles':value['roles'],'csrf':session['csrf']}).encode()
            if route in PAGES and not post:
                content=content.replace(b'</head>',b'<meta name="apple-mobile-web-app-capable" content="yes"><link rel="manifest" href="/remote.webmanifest" crossorigin="use-credentials"><link rel="stylesheet" href="/remote.css"><script src="/remote-client.js"></script></head>',1)
            return self.response(content,status,kind)
        except (ValueError,UnicodeError) as exc:return self.error(str(exc))
        except (OSError,http.client.HTTPException) as exc:return self.error('PC 서버 연결을 확인하세요. '+str(exc)[:160],502)
