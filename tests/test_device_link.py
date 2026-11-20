import http.client
import json
from pathlib import Path
import socket
import ssl
import time
from types import SimpleNamespace
import pytest
from core import device_link as link,staffing
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server,request  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]

def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


@pytest.fixture
def gateway(env,http_server):
    manager=link.manager(http_server,ROOT);manager.start('127.0.0.1',free_port())
    yield manager
    manager.close(revoke=False,persist=False)


def remote(manager,method='GET',path='/ops/team',body=None,headers=None,cookie=None,origin=True):
    connection=http.client.HTTPSConnection(manager.settings['address'],manager.settings['port'],context=ssl._create_unverified_context(),timeout=5)
    outgoing={}
    if method=='POST' and origin:outgoing['Origin']=manager.origin
    if cookie:outgoing['Cookie']=cookie
    if isinstance(body,dict):body=json.dumps(body);outgoing['Content-Type']='application/json'
    outgoing.update(headers or {})
    connection.request(method,path,body=body,headers=outgoing)
    response=connection.getresponse();result=(response.status,response.read(),dict(response.getheaders()));connection.close();return result


def pair(manager,name='우리집 아이패드'):
    code=manager.issue_code()['code']
    status,body,headers=remote(manager,'POST','/remote/pair',{'name':name,'code':code})
    assert status==200,body
    return headers['Set-Cookie'].split(';',1)[0]


def test_default_disabled_and_local_api_boundary(env,http_server):
    value=json.loads(request(http_server,'GET','/ops/devices')[1]);assert value['enabled'] is False and value['url'] is None
    assert request(http_server,'GET','/ops/devices',headers={'Origin':'https://evil.example'})[0]==403
    assert request(http_server,'POST','/ops/devices',json.dumps({'action':'code'}))[0]==403
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    for body in ['[]','{}',' '*2049]:assert request(http_server,'POST','/ops/devices',body,headers=headers)[0]==400
    for address in ['0.0.0.0','8.8.8.8','192.168.99.99']:
        assert request(http_server,'POST','/ops/devices',json.dumps({'action':'enable','address':address}),headers=headers)[0]==400


def test_https_pairing_cookie_and_internal_token_never_exposed(gateway):
    assert remote(gateway)[0]==401
    assert remote(gateway,path='/office')[0]==303
    assert remote(gateway,path='/pair')[0]==200
    cookie=pair(gateway)
    guest_art=remote(gateway,path='/crew-portraits.png');assert guest_art[0]==401 and guest_art[2]['Cache-Control']=='no-store'
    art_status,art,art_headers=remote(gateway,path='/crew-portraits.png',cookie=cookie)
    assert art_status==200 and art[:8]==b'\x89PNG\r\n\x1a\n' and art_headers['Content-Type']=='image/png'
    status,body,_=remote(gateway,path='/ops/roles',cookie=cookie);value=json.loads(body)
    assert status==200 and value['csrf']!=gateway.backend.bridge_token
    assert gateway.backend.bridge_token.encode() not in body
    stored=gateway.sessions_path.read_text();assert cookie.split('.',1)[1] not in stored
    assert gateway.status()['devices'][0]['name']=='우리집 아이패드'
    assert 'token_hash' not in gateway.status()['devices'][0]
    assert json.loads(remote(gateway,path='/remote/session',cookie=cookie)[1])['pc_required'] is True
    assert remote(gateway,path='/office',cookie=cookie)[1].count(b'/remote-client.js')==1


def test_secure_cookie_single_use_code_and_rate_limit(gateway):
    code=gateway.issue_code()['code']
    status,_,headers=remote(gateway,'POST','/remote/pair',{'code':code,'name':'휴대폰'})
    assert status==200
    assert all(x in headers['Set-Cookie'] for x in ['Secure','HttpOnly','SameSite=Strict','Max-Age=2592000'])
    assert remote(gateway,'POST','/remote/pair',{'code':code,'name':'재사용'})[0]==400
    for _ in range(10):remote(gateway,'POST','/remote/pair',{'code':'00000000','name':'시도'})
    code=gateway.issue_code()['code']
    status,body,_=remote(gateway,'POST','/remote/pair',{'code':code,'name':'제한'})
    assert status==400 and '1분'.encode() in body


def test_pair_expiration_origin_and_host_checks(gateway):
    code=gateway.issue_code()['code'];gateway.pair_until=time.time()-1
    assert remote(gateway,'POST','/remote/pair',{'code':code,'name':'만료'})[0]==400
    assert remote(gateway,'POST','/remote/pair',{'code':'00000000','name':'기기'},origin=False)[0]==403
    assert remote(gateway,path='/pair',headers={'Host':'evil.example'})[0]==403
    assert remote(gateway,path='/pair',headers={'Origin':'https://evil.example'})[0]==403


def test_remote_team_edits_sync_back_to_pc_and_csrf_required(gateway,http_server):
    cookie=pair(gateway);team=json.loads(remote(gateway,cookie=cookie)[1])['team'];revision=team['revision'];team['members'][0]['name']='태블릿 기획자'
    body={'team':team,'expected_revision':revision}
    assert remote(gateway,'POST','/ops/team',body,cookie=cookie)[0]==403
    assert remote(gateway,'POST','/ops/team',body,headers={'X-Solomon-Bridge':'test-token'},cookie=cookie)[0]==403
    token=json.loads(remote(gateway,path='/remote/session',cookie=cookie)[1])['csrf']
    assert remote(gateway,'POST','/ops/team',body,headers={'X-Director-Remote-CSRF':token},cookie=cookie)[0]==200
    assert json.loads(request(http_server,'GET','/ops/team')[1])['team']['members'][0]['name']=='태블릿 기획자'
    assert remote(gateway,'POST','/ops/team',body,headers={'X-Director-Remote-CSRF':token},cookie=cookie)[0]==409


@pytest.mark.parametrize('path',['/ops/devices','/ops/devices/qr','/ops/state','/bridge/status','/ops/desktop-health','/config.yaml','/data/device-link/server.key','/office/../../config.yaml'])
def test_internal_paths_not_available_remotely(gateway,path):
    assert remote(gateway,path=path,cookie=pair(gateway))[0]==403


def test_pc_only_operations_and_registered_project_boundary(gateway,tmp_path,monkeypatch):
    cookie=pair(gateway);csrf=json.loads(remote(gateway,path='/remote/session',cookie=cookie)[1])['csrf'];headers={'X-Director-Remote-CSRF':csrf}
    for route in ['/ops/pick-folder','/ops/shutdown','/ops/devices','/ops/roles','/result/open_worktree']:
        assert remote(gateway,'POST',route,{},headers=headers,cookie=cookie)[0]==403
    registered=str(tmp_path/'known');unknown=str(tmp_path/'unknown')
    monkeypatch.setattr('dashboard_server.build_project_choices',lambda:{'projects':[{'path':registered,'name':'known'}],'current':registered})
    launched=[]
    monkeypatch.setattr('dashboard_server.submit_mission_launch',lambda payload:(launched.append(payload) or {'state':'queued'},202))
    payload={'request_id':'launch-from-phone','project_path':unknown,'goal':'HUD'}
    assert remote(gateway,'POST','/ops/mission-launch',payload,headers=headers,cookie=cookie)[0]==403
    payload['project_path']=registered
    assert remote(gateway,'POST','/ops/mission-launch',payload,headers=headers,cookie=cookie)[0]==202
    assert launched==[payload]
    assert remote(gateway,path='/ops/project-memory?path='+unknown,cookie=cookie)[0]==403


def test_device_revocation_logout_expiry_and_disable(gateway):
    cookie=pair(gateway);csrf=json.loads(remote(gateway,path='/remote/session',cookie=cookie)[1])['csrf'];ident=gateway.status()['devices'][0]['id']
    gateway.revoke(ident);assert remote(gateway,cookie=cookie)[0]==401
    cookie=pair(gateway,'휴대폰');csrf=json.loads(remote(gateway,path='/remote/session',cookie=cookie)[1])['csrf']
    assert remote(gateway,'POST','/remote/logout',headers={'X-Director-Remote-CSRF':csrf},cookie=cookie)[0]==200
    assert remote(gateway,cookie=cookie)[0]==401
    cookie=pair(gateway,'만료 기기');gateway.sessions[-1]['expires_at']=0
    assert remote(gateway,cookie=cookie)[0]==401
    cookie=pair(gateway,'해제 기기');gateway.close()
    assert all(s['revoked'] for s in gateway.sessions)
    assert json.loads(gateway.settings_path.read_text())['enabled'] is False


def test_sessions_survive_pc_restart_without_raw_tokens(gateway):
    cookie=pair(gateway);other=link.LinkManager(gateway.backend,ROOT)
    assert other.authenticate(cookie)['name']=='우리집 아이패드'
    assert other.authenticate('director_device=bogus') is None
    assert other.authenticate('director_device=x.unknown') is None


def test_slow_tls_client_does_not_block_other_devices(gateway):
    raw=socket.create_connection((gateway.settings['address'],gateway.settings['port']))
    try:assert remote(gateway,path='/pair')[0]==200
    finally:raw.close()


def test_tailscale_and_lan_interfaces_are_explicit(monkeypatch):
    monkeypatch.setattr('psutil.net_if_stats',lambda:{})
    monkeypatch.setattr('psutil.net_if_addrs',lambda:{'Tailscale':[SimpleNamespace(family=socket.AF_INET,address='100.101.102.103')],
        'Wi-Fi':[SimpleNamespace(family=socket.AF_INET,address='192.168.1.12')],
        'Other':[SimpleNamespace(family=socket.AF_INET,address='100.99.88.77')],
        'Public':[SimpleNamespace(family=socket.AF_INET,address='8.8.8.8')]})
    assert link.interfaces()==[{'name':'Tailscale','address':'100.101.102.103','mode':'tailscale'},{'name':'Wi-Fi','address':'192.168.1.12','mode':'lan'}]


def test_pc_enable_code_qr_and_revoke_endpoint(env,http_server):
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    def post(value):return request(http_server,'POST','/ops/devices',json.dumps(value),headers=headers)
    code,body=post({'action':'enable','address':'127.0.0.1','port':free_port()});assert code==200
    assert json.loads(body)['enabled']
    assert request(http_server,'GET','/ops/devices/qr')[0]==200
    code,body=post({'action':'code'});assert code==200 and len(json.loads(body)['code'])==8
    assert post({'action':'disable'})[0]==200
