import copy
from datetime import datetime,timedelta,timezone
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import threading
import urllib.parse
import pytest
from core import scheduled_work as work,youtube_channel as channel
from core.db_path import get_db_path
from tests.test_v301_companion_http import http_server,request

FIXED=datetime(2026,11,16,0,0,tzinfo=timezone.utc)

@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(work,'now',lambda:FIXED)
    monkeypatch.setattr(work,'ACTIVE',{})
    monkeypatch.setattr(channel,'public',lambda:{'connected':True,'channel':{'id':'UC-unit-channel','title':'검수 채널'}})
    return FIXED

def plan(enabled=True):
    preview=work.parse_command('매일 오전 10시부터 쇼츠 1개 롱폼 1개 2시간 간격');preview['enabled']=enabled
    return work.save_plan({'plan':preview,'expected_revision':work.digest(work.plans())})['plans'][0]

def prepared(clock):
    p=plan();work.prepare(p['id']);return p,next(j for j in work.jobs()['jobs'] if j['day']=='2026-11-16' and j['kind']=='short')

def media_job(clock,tmp_path,monkeypatch):
    p,j=prepared(clock);f=tmp_path/'영상.mp4';f.write_bytes(b'unit-test-movie')
    monkeypatch.setattr(work,'probe_media',lambda raw,kind:{'path':str(f),'filename':f.name,'size':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'duration':5,'width':64,'height':96,'mime':'video/mp4'})
    work.attach({'id':j['id'],'path':str(f),'title':'게임 개발 소식','description':'검수용 설명','made_for_kids':False,'synthetic_media':True})
    return p,work._job(work.jobs(),j['id']),f

def approve(j,**values):
    return work.action({'action':'approve','id':j['id'],'expected_revision':work.digest(work._job(work.jobs(),j['id'])),'channel_id':'UC-unit-channel','rights_confirmed':True,'quality_confirmed':True,**values})

class Adapter:
    def __init__(self):self.calls=0;self.job=None;self.privacy='private'
    def upload(self,j,m,stopped):self.calls+=1;self.job=copy.deepcopy(j);return 'vid00000001'
    def videos(self,ids):return [{'id':ids[0],'snippet':{'channelId':'UC-unit-channel','title':self.job['media']['title']},'status':{'privacyStatus':self.privacy,'publishAt':self.job['publish_at'],'uploadStatus':'processed'}}]


def test_korean_preview_is_disabled_and_counts_are_precise():
    p=work.parse_command('매일 유튜브 계정에 쇼츠 5개 롱폼 1개 오전 9시부터 예약으로 올려줘')
    assert p['enabled'] is False and p['timezone']=='Asia/Seoul'
    assert [s['time'] for s in p['slots']]==['09:00','11:00','13:00','15:00','17:00','19:00']
    assert [s['kind'] for s in p['slots']]==['short']*5+['long']
    assert work.parse_command('매일 2시간 간격 쇼츠 1개 오전 9시')['slots'][0]['time']=='09:00'
    assert work.parse_command('매일 오후 9시 쇼츠 2개 30분 간격')['slots'][0]['time']=='21:00'

@pytest.mark.parametrize('text',['매주 쇼츠 5개 9시','매일 쇼츠 25개 9시','매일 쇼츠 5개 21시','매일 쇼츠 1개 오후 13시','매일 쇼츠 1개 9시 1분 간격'])
def test_ambiguous_or_overflowing_commands_are_rejected(text):
    with pytest.raises(ValueError):work.parse_command(text)

def test_daily_identity_and_no_catchup(clock,monkeypatch):
    p=plan();work.prepare(p['id']);work.prepare(p['id']);assert len(work.jobs()['jobs'])==4
    work.tick(FIXED+timedelta(hours=8),background=False,adapter=Adapter())
    today=[j for j in work.jobs()['jobs'] if j['day']=='2026-11-16'];assert all(j['status']=='MISSED' for j in today)
    assert work.listing()['today']['target']==2
    work.tick(FIXED+timedelta(days=2),background=False,adapter=Adapter())
    assert not any(j['day']=='2026-11-17' and j['status']=='UPLOADING' for j in work.jobs()['jobs'])


def test_media_approval_channel_and_file_integrity(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch)
    with pytest.raises(ValueError):approve(j,channel_id='other-channel')
    with pytest.raises(ValueError):approve(j,rights_confirmed=False)
    approve(j);f.write_bytes(b'modified');adapter=Adapter();work.tick(background=False,adapter=adapter)
    assert adapter.calls==0 and work._job(work.jobs(),j['id'])['status']=='FAILED'
    public=work.listing();assert str(f) not in json.dumps(public,ensure_ascii=False)


def test_real_queue_receipt_and_actual_publication_status(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j);adapter=Adapter();work.tick(background=False,adapter=adapter)
    stored=work._job(work.jobs(),j['id']);assert adapter.calls==1 and stored['status']=='SCHEDULED' and stored['video_id']=='vid00000001'
    for _ in range(3):work.tick(background=False,adapter=adapter)
    assert adapter.calls==1
    monkeypatch.setattr(work,'now',lambda:FIXED+timedelta(hours=4))
    work.reconcile(j['id'],adapter=adapter);assert work._job(work.jobs(),j['id'])['status']=='NEEDS_REVIEW'
    adapter.privacy='public';work.reconcile(j['id'],adapter=adapter);assert work._job(work.jobs(),j['id'])['status']=='PUBLISHED'


def test_ambiguous_upload_is_never_replayed_and_recovers(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j)
    class Uncertain(Adapter):
        def upload(self,*a):self.calls+=1;raise channel.UploadUncertain('최종 응답 유실')
    adapter=Uncertain();work.tick(background=False,adapter=adapter);assert work._job(work.jobs(),j['id'])['status']=='NEEDS_REVIEW'
    work.tick(background=False,adapter=adapter);assert adapter.calls==1
    work._update(j['id'],status='UPLOADING',remote_attempt=True);work.recover();assert work._job(work.jobs(),j['id'])['status']=='NEEDS_REVIEW'


def test_concurrent_ticks_claim_only_once(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j);entered=threading.Event();release=threading.Event()
    class Slow(Adapter):
        def upload(self,*args):entered.set();release.wait(3);return super().upload(*args)
    adapter=Slow();thread=threading.Thread(target=work.tick,kwargs={'background':False,'adapter':adapter});thread.start()
    try:
        assert entered.wait(2);work.tick(background=False,adapter=adapter)
    finally:release.set();thread.join(4)
    assert adapter.calls==1


def test_pause_and_duplicate_file_protection(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch)
    other=next(o for o in work.jobs()['jobs'] if o['id']!=j['id'])
    with pytest.raises(ValueError):work.attach({'id':other['id'],'path':str(f),'title':'같은 영상','description':'','made_for_kids':False,'synthetic_media':False})
    approve(j);work.pause(p['id']);adapter=Adapter();work.tick(background=False,adapter=adapter);assert adapter.calls==0


def test_restored_approval_requires_studio_confirmation(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);work._update(j['id'],restored_unverified=True)
    with pytest.raises(ValueError):approve(j)
    approve(j,no_existing_upload_confirmed=True)
    assert work._job(work.jobs(),j['id'])['restored_unverified'] is False


def test_plan_edit_preserves_partially_uploaded_day(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j);adapter=Adapter();work.tick(background=False,adapter=adapter)
    edited=work.parse_command('매일 오전 11시부터 쇼츠 2개 롱폼 1개');edited['enabled']=True
    work.save_plan({'id':p['id'],'plan':edited,'expected_revision':work.digest(work.plans())});work.prepare(p['id'])
    today=[o for o in work.jobs()['jobs'] if o['day']=='2026-11-16' and o['status']!='CANCELLED'];tomorrow=[o for o in work.jobs()['jobs'] if o['day']=='2026-11-17' and o['status']!='CANCELLED']
    assert len(today)==2 and len(tomorrow)==3


def test_daily_attempt_cap(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j);state=work.jobs()
    for i in range(24):state['jobs'].append({**copy.deepcopy(j),'id':'prior-'+str(i),'status':'FAILED','attempt_day':'2026-11-16'})
    work.write('automation_jobs.json',state);adapter=Adapter();work.tick(background=False,adapter=adapter);assert adapter.calls==0


def test_scheduler_off_never_calls_google(clock,monkeypatch):
    monkeypatch.setattr(channel,'http',lambda *a,**k:pytest.fail('live request'))
    class Single:
        calls=0
        def wait(self,_):self.calls+=1;return self.calls>1
    thread=work.start_scheduler(Single());thread.join(2);assert not thread.is_alive()


def test_media_probe_actual_video_and_short_eligibility(tmp_path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):pytest.skip('local ffmpeg/ffprobe unavailable')
    video=tmp_path/'sample.mp4';subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=64x96:d=0.2','-c:v','mpeg4','-y',str(video)],check=True,timeout=15)
    result=work.probe_media(str(video),'short');assert result['width']==64 and result['height']==96 and result['sha256']==hashlib.sha256(video.read_bytes()).hexdigest()
    landscape=tmp_path/'wide.mp4';subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=red:s=96x64:d=0.2','-c:v','mpeg4','-y',str(landscape)],check=True,timeout=15)
    with pytest.raises(ValueError):work.probe_media(str(landscape),'short')


def test_google_network_is_blocked_during_unit_tests():
    with pytest.raises(RuntimeError,match='YOUTUBE_NETWORK_BLOCKED'):channel.http('GET','https://www.googleapis.com/youtube/v3/channels')


def test_desktop_oauth_pkce_and_encrypted_vault(tmp_path,monkeypatch):
    monkeypatch.setenv('YT_TEST_SECRET','test-client-secret')
    channel.save_settings({'client_id':'unit.apps.googleusercontent.com','client_secret_env':'YT_TEST_SECRET','ffprobe_path':''})
    seen={}
    def fake_json(method,url,**kwargs):
        seen.update(kwargs.get('form',{}))
        return {'refresh_token':'private-refresh','access_token':'private-access','expires_in':3600,'scope':' '.join(channel.SCOPES)}
    monkeypatch.setattr(channel,'_json',fake_json);monkeypatch.setattr(channel,'channels',lambda token:[{'id':'UC-one','snippet':{'title':'검수 채널'}}])
    flow=channel.start_login();url=urllib.parse.urlsplit(flow['url']);query=urllib.parse.parse_qs(url.query);redirect=urllib.parse.urlsplit(query['redirect_uri'][0]);connection=http.client.HTTPConnection(redirect.hostname,redirect.port,timeout=3)
    try:
        connection.request('GET','/oauth2callback?state=wrong&code=not-real');r=connection.getresponse();r.read();assert r.status==400
        connection.request('GET','/oauth2callback?'+urllib.parse.urlencode({'state':query['state'][0],'code':'test-only-code'}));r=connection.getresponse();r.read();assert r.status==200
        assert query['code_challenge_method']==['S256'];assert channel.vault()['channel_id']=='UC-one'
        import base64
        assert base64.urlsafe_b64encode(hashlib.sha256(seen['code_verifier'].encode()).digest()).rstrip(b'=').decode()==query['code_challenge'][0]
        assert b'private-refresh' not in (get_db_path().parent/'secrets/youtube-vault.bin').read_bytes()
        assert 'private-refresh' not in json.dumps(channel.public())
        from core.company_backup import FILES
        assert 'youtube-vault.bin' not in FILES
    finally:connection.close();channel.cancel_login()


def test_authenticated_http_boundaries(clock,http_server):
    for route in ('/automation','/automation.js','/automation.css','/ops/automation','/ops/youtube'):assert request(http_server,'GET',route)[0]==200
    for route in ('/ops/automation','/ops/automation/asset','/ops/automation/reconcile','/ops/youtube'):assert request(http_server,'POST',route)[0]==403
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    code,body=request(http_server,'POST','/ops/automation',json.dumps({'action':'preview','command':'매일 쇼츠 5개 롱폼 1개 9시'}),headers)
    assert code==200 and len(json.loads(body)['plan']['slots'])==6
    from core.device_link import READ_API,WRITE_API
    assert '/ops/automation' in READ_API&WRITE_API
    assert {'/ops/youtube','/ops/automation/asset','/ops/automation/reconcile'}.isdisjoint(READ_API|WRITE_API)

def test_resumable_upload_contract_and_final_hash(tmp_path,monkeypatch):
    data=b'a'*(8*1024*1024)+b'final-video-bytes';file=tmp_path/'large.mp4';file.write_bytes(data);requests=[]
    monkeypatch.setattr(channel,'_access',lambda:'private-access')
    monkeypatch.setattr(channel,'channels',lambda token:[{'id':'UC-unit-channel'}])
    def transport(method,url,headers=None,data=None):
        requests.append((method,url,headers,data))
        if method=='POST':return 200,{'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private-session'},b''
        if headers['Content-Range'].startswith('bytes 0-'):return 308,{'Range':f'bytes=0-{8*1024*1024-1}'},b''
        return 200,{},b'{"id":"vid00000001"}'
    monkeypatch.setattr(channel,'http',transport)
    job={'id':'auto-upload-contract','publish_at':(FIXED+timedelta(hours=1)).isoformat(),'approval':{'channel_id':'UC-unit-channel'}}
    media={'path':str(file),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'mime':'video/mp4','title':'검수 영상','description':'설명','made_for_kids':False,'synthetic_media':True}
    assert channel.upload(job,media,lambda:False)=='vid00000001'
    body=json.loads(requests[0][3]);assert body['status']['privacyStatus']=='private' and body['status']['publishAt']==job['publish_at']
    assert body['status']['containsSyntheticMedia'] is True and body['status']['selfDeclaredMadeForKids'] is False
    assert len(requests)==3 and requests[-1][3]==b'final-video-bytes'
    assert 'private-session' not in json.dumps(channel.public())
    # A changed source must never send the completing chunk.
    requests.clear();file.write_bytes(data[:-1]+b'x')
    with pytest.raises(channel.UploadUncertain):channel.upload(job,media,lambda:False)
    assert len(requests)==2


def test_resumable_location_does_not_leak_bearer_token_to_external_host(clock,tmp_path,monkeypatch):
    monkeypatch.setattr(channel,'_access',lambda:'private-access');monkeypatch.setattr(channel,'channels',lambda t:[{'id':'UC-unit-channel'}]);calls=[]
    def transport(*args):calls.append(args);return 200,{'Location':'https://evil.example/upload'},b''
    monkeypatch.setattr(channel,'http',transport)
    with pytest.raises(channel.UploadUncertain):channel.upload({'id':'test','approval':{'channel_id':'UC-unit-channel'},'publish_at':stamp_for_test()}, {'size':1,'mime':'video/mp4','title':'a','description':'','made_for_kids':False,'synthetic_media':False},lambda:False)
    assert len(calls)==1

def stamp_for_test():return (FIXED+timedelta(hours=1)).isoformat()


def test_backup_restore_pauses_plans_and_invalidates_publish_grants(clock,tmp_path,tmp_path_factory,monkeypatch):
    from core import company_backup as backup
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j)
    import sqlite3
    with sqlite3.connect(str(get_db_path())) as conn:conn.execute('CREATE TABLE sample_backup(value TEXT)')
    folder=tmp_path_factory.mktemp('schedule-backups');backup.save_settings({'enabled':False,'folder':str(folder),'interval_minutes':60,'keep':10})
    saved=backup.create();ident=saved['archives'][0]['id'];backup.stage_restore(ident,'운영 기록 복구');backup.apply_pending()
    assert all(not p['enabled'] for p in work.plans()['plans'])
    restored=work._job(work.jobs(),j['id']);assert restored['status']=='READY_REVIEW' and restored['approval'] is None and restored['restored_unverified']
    with pytest.raises(ValueError):approve(restored)
    assert 'secrets/youtube-vault.bin' not in backup.verify(backup.destination()/ident)

def test_pre_upload_auth_failure_can_be_reviewed_again(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j)
    class NoAuth(Adapter):
        def upload(self,*a):raise channel.ChannelError('API 인증 전 실패')
    work.tick(background=False,adapter=NoAuth());failed=work._job(work.jobs(),j['id'])
    assert failed['status']=='FAILED' and failed['remote_attempt'] is False
    work.attach({'id':j['id'],'path':str(f),'title':'재검토 영상','description':'','made_for_kids':False,'synthetic_media':False})
    assert work._job(work.jobs(),j['id'])['status']=='READY_REVIEW'


def test_publication_history_keeps_last_week_and_never_assumes_clock_success(clock,tmp_path,monkeypatch):
    p,j,f=media_job(clock,tmp_path,monkeypatch);approve(j);adapter=Adapter();work.tick(background=False,adapter=adapter)
    assert work.listing()['history'][0]['scheduled']==1 and work.listing()['history'][0]['published']==0
    monkeypatch.setattr(work,'now',lambda:FIXED+timedelta(days=1));view=work.listing()
    assert any(o['id']==j['id'] for o in view['jobs'])
    assert view['history'][1]['scheduled']==1 and view['history'][1]['published']==0

def test_company_wide_slot_cap_is_enforced(clock):
    spec=work.parse_command('매일 9시 쇼츠 5개 롱폼 1개')
    for i in range(4):work.save_plan({'plan':{**spec,'name':'plan '+str(i)},'expected_revision':work.digest(work.plans())})
    with pytest.raises(ValueError,match='회사 전체'):work.save_plan({'plan':spec,'expected_revision':work.digest(work.plans())})

def test_oauth_callback_state_is_consumed_once_under_concurrency(monkeypatch):
    monkeypatch.setenv('YT_TEST_SECRET','test-only')
    channel.save_settings({'client_id':'unit.apps.googleusercontent.com','client_secret_env':'YT_TEST_SECRET','ffprobe_path':''})
    entered=threading.Event();release=threading.Event();calls=[]
    def exchange(*a,**kwargs):
        calls.append(1);entered.set();release.wait(3)
        return {'refresh_token':'unit-refresh','access_token':'unit-access','expires_in':3600,'scope':' '.join(channel.SCOPES)}
    monkeypatch.setattr(channel,'_json',exchange);monkeypatch.setattr(channel,'channels',lambda t:[{'id':'UC-one','snippet':{'title':'test'}}])
    flow=channel.start_login();q=urllib.parse.parse_qs(urllib.parse.urlsplit(flow['url']).query);redirect=urllib.parse.urlsplit(q['redirect_uri'][0]);url='/oauth2callback?'+urllib.parse.urlencode({'state':q['state'][0],'code':'unit-code'});results=[]
    def first():
        conn=http.client.HTTPConnection(redirect.hostname,redirect.port,timeout=4)
        try:conn.request('GET',url);r=conn.getresponse();r.read();results.append(r.status)
        finally:conn.close()
    thread=threading.Thread(target=first);thread.start()
    try:
        assert entered.wait(2)
        conn=http.client.HTTPConnection(redirect.hostname,redirect.port,timeout=3);conn.request('GET',url);r=conn.getresponse();r.read();assert r.status==400;conn.close()
    finally:release.set();thread.join(4);channel.cancel_login()
    assert calls==[1] and results==[200]
