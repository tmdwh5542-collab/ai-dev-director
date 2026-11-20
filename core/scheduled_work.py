"""Daily durable YouTube work queue. Files + owner approval, never an inferred publish grant.
KST daily identities survive restarts; ambiguous uploads are never replayed.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import uuid
from core import staffing, youtube_channel as channel
from core.db_path import get_db_path
from core.subprocess_options import hidden_console

LOCK=threading.RLock()
ACTIVE={}
KST=timezone(timedelta(hours=9))
MARGIN=timedelta(minutes=10)
WAITING={'WAITING_MEDIA','READY_REVIEW','APPROVED'}
EXTERNAL={'UPLOADING','STOPPING','VERIFYING','SCHEDULED','PUBLISHED','NEEDS_REVIEW'}
MAX_JOBS=5000

class DeferredUpload(ValueError):pass


def now():return datetime.now(timezone.utc)
def stamp(value=None):return (value or now()).isoformat()
def path(name):return get_db_path().parent/name
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
def read(name,default):
    p=path(name);return json.loads(p.read_text(encoding='utf-8')) if p.exists() else copy.deepcopy(default)
def write(name,value):
    p=path(name);p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)
def plans():return read('automation_plans.json',{'plans':[]})
def jobs():return read('automation_jobs.json',{'jobs':[]})
def _job(state,ident):
    found=next((j for j in state['jobs'] if j['id']==ident),None)
    if not found:raise ValueError('예약 업무를 찾을 수 없습니다.')
    return found

def parse_command(text):
    if not isinstance(text,str) or len(text)>1000 or '매일' not in text:raise ValueError('예: 매일 오전 9시부터 쇼츠 5개 롱폼 1개, 2시간 간격')
    shorts=re.search(r'(?:쇼츠|숏츠)\s*(\d+)\s*개',text);longs=re.search(r'롱폼\s*(\d+)\s*개',text)
    clock=re.search(r'(오전|오후)?\s*(\d{1,2})\s*시(?!간)(?:\s*(\d{1,2})\s*분)?',text)
    if not clock or not (shorts or longs):raise ValueError('매일 수행할 영상 개수와 시작 시간을 입력하세요.')
    h=int(clock[2]);minute=int(clock[3] or 0)
    if clock[1]:
        if not 1<=h<=12:raise ValueError('오전/오후 시간은 1~12시로 입력하세요.')
        h=h%12+(12 if clock[1]=='오후' else 0)
    if not 0<=h<=23 or not 0<=minute<=59:raise ValueError('시작 시간을 확인하세요.')
    counts=[int(shorts[1]) if shorts else 0,int(longs[1]) if longs else 0]
    if sum(counts)<1 or sum(counts)>24 or any(c>12 for c in counts):raise ValueError('종류별 최대 12개, 하루 총 24개까지 설정할 수 있습니다.')
    gap=re.search(r'(\d+)\s*(시간|분)\s*간격',text);interval=int(gap[1])*(60 if gap[2]=='시간' else 1) if gap else 120
    if not 15<=interval<=720:raise ValueError('간격은 15분~12시간으로 설정하세요.')
    slots=[]
    for kind,count in zip(('short','long'),counts):
        for _ in range(count):
            at=h*60+minute+len(slots)*interval
            if at>=1440:raise ValueError('일정이 자정을 넘습니다. 시작 시간을 앞당기거나 간격을 줄이세요.')
            slots.append({'id':'slot-'+str(len(slots)+1),'kind':kind,'time':f'{at//60:02d}:{at%60:02d}'})
    return {'name':'매일 유튜브 영상 예약','enabled':False,'slots':slots,'timezone':'Asia/Seoul'}

def validate_plan(value):
    if not isinstance(value,dict) or not isinstance(value.get('name'),str) or not 1<=len(value['name'].strip())<=80 or type(value.get('enabled')) is not bool or value.get('timezone')!='Asia/Seoul' or not isinstance(value.get('slots'),list) or not 1<=len(value['slots'])<=24:raise ValueError('계획 이름·활성화·한국 시간·하루 1~24개 공개 시간을 확인하세요.')
    ids=set();times=set();slots=[]
    for s in value['slots']:
        if not isinstance(s,dict) or set(s)!={'id','kind','time'} or not isinstance(s['id'],str) or not re.fullmatch(r'slot-[A-Za-z0-9_-]{1,30}',s['id']) or s['id'] in ids or s['kind'] not in {'short','long'} or not isinstance(s['time'],str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',s['time']) or s['time'] in times:raise ValueError('중복 없는 영상 종류와 공개 시간(HH:MM)을 설정하세요.')
        ids.add(s['id']);times.add(s['time']);slots.append(dict(s))
    if any(sum(s['kind']==kind for s in slots)>12 for kind in ('short','long')):raise ValueError('종류별 하루 최대 12개입니다.')
    return {'name':value['name'].strip(),'enabled':value['enabled'],'timezone':'Asia/Seoul','slots':slots}

def save_plan(payload):
    value=validate_plan(payload.get('plan'));ident=payload.get('id')
    with LOCK:
        state=plans()
        if payload.get('expected_revision')!=digest(state):raise staffing.TeamConflict('예약 계획이 변경됐습니다. 새로고침 후 다시 저장하세요.')
        old=next((p for p in state['plans'] if p['id']==ident),None)
        if ident and not old:raise ValueError('예약 계획을 찾을 수 없습니다.')
        if not old and len(state['plans'])>=5:raise ValueError('예약 계획은 최대 5개입니다.')
        if sum(len(p['slots']) for p in state['plans'] if p['id']!=ident)+len(value['slots'])>24:raise ValueError('회사 전체 예약 계획을 합쳐 하루 최대 24개입니다.')
        record={**value,'id':ident or 'plan-'+uuid.uuid4().hex[:12],'updated_at':stamp(),'spec':digest(value['slots'])}
        if old:state['plans'][state['plans'].index(old)]=record
        else:state['plans'].append(record)
        write('automation_plans.json',state)
    return listing()


def _materialize(instant,force_plan=None):
    state=jobs();changed=False;local=instant.astimezone(KST)
    for plan in plans()['plans']:
        if not plan['enabled'] and plan['id']!=force_plan:continue
        for offset in (0,1):
            day=(local+timedelta(days=offset)).date().isoformat()
            existing=[j for j in state['jobs'] if j['plan_id']==plan['id'] and j['day']==day]
            # A partially uploaded day keeps its captured schedule; edits apply to the next unuploaded day.
            captured=next((j['plan_spec'] for j in existing if j['status'] in EXTERNAL or j.get('remote_attempt')),None)
            if captured and captured!=plan['spec']:continue
            for old in existing:
                if old['plan_spec']!=plan['spec'] and old['status'] in WAITING|{'MISSED'}:
                    old.update(status='CANCELLED',cancel_source='plan_change',error='공개 시간 변경으로 취소됨. 새 계획에서 영상을 다시 등록·승인하세요.',updated_at=stamp(instant));changed=True
            for slot in plan['slots']:
                ident='auto-'+digest([plan['id'],plan['spec'],day,slot['id']])
                if any(j['id']==ident for j in state['jobs']):continue
                if len(state['jobs'])>=MAX_JOBS:raise ValueError('예약 기록 보관 한도 5,000건에 도달했습니다.')
                publish=datetime.fromisoformat(day+'T'+slot['time']+':00+09:00')
                state['jobs'].append({'id':ident,'plan_id':plan['id'],'plan_name':plan['name'],'plan_spec':plan['spec'],'day':day,'slot_id':slot['id'],'kind':slot['kind'],'publish_at':publish.isoformat(),'status':'MISSED' if publish<=instant+MARGIN else 'WAITING_MEDIA','media':None,'approval':None,'video_id':None,'remote_attempt':False,'error':'','updated_at':stamp(instant),'created_at':stamp(instant)});changed=True
    for j in state['jobs']:
        if j['status'] in WAITING and datetime.fromisoformat(j['publish_at'])<=instant+MARGIN:
            j.update(status='MISSED',approval=None,error='공개 시각까지 10분 미만이거나 이미 지난 일정입니다. 자동으로 몰아서 올리지 않습니다.',updated_at=stamp(instant));changed=True
    if changed:write('automation_jobs.json',state)
    return state

def prepare(ident):
    with LOCK:
        if not any(p['id']==ident for p in plans()['plans']):raise ValueError('예약 계획을 선택하세요.')
        _materialize(now(),ident)
    return listing()

def probe_media(raw,kind):
    if not isinstance(raw,str) or len(raw)>2048 or not Path(raw).is_absolute():raise ValueError('PC 영상 파일의 절대 경로를 입력하세요.')
    p=Path(raw).resolve()
    if not p.is_file() or p.suffix.lower() not in {'.mp4','.mov','.m4v','.webm','.mkv'} or not 0<p.stat().st_size<=4*1024**3:raise ValueError('존재하는 4GB 이하 MP4·MOV·M4V·WebM·MKV 영상이 필요합니다.')
    executable=shutil.which(channel.settings()['ffprobe_path'] or 'ffprobe')
    if not executable:raise ValueError('영상 길이·해상도 검증에 ffprobe가 필요합니다. PC의 YouTube 설정에서 실행 파일을 지정하세요.')
    try:
        result=subprocess.run([executable,'-v','error','-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(p)],capture_output=True,timeout=20,stdin=subprocess.DEVNULL,**hidden_console())
        parsed=json.loads(result.stdout) if result.returncode==0 and len(result.stdout)<=65536 else {}
        duration=float(parsed['format']['duration']);video=next(s for s in parsed['streams'] if s.get('codec_type')=='video');w,h=int(video['width']),int(video['height'])
        if not 0<duration<=43200 or min(w,h)<=0:raise ValueError()
    except (OSError,ValueError,KeyError,StopIteration,subprocess.TimeoutExpired):raise ValueError('영상의 길이·해상도를 확인하지 못했습니다. 실제 영상 파일을 선택하세요.') from None
    if kind=='short' and (duration>180 or w>h):raise ValueError('쇼츠 후보는 3분 이하의 세로 또는 정사각형 영상이어야 합니다. 최종 쇼츠 분류는 YouTube가 결정합니다.')
    sha=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):sha.update(block)
    return {'path':str(p),'filename':p.name,'size':p.stat().st_size,'sha256':sha.hexdigest(),'duration':round(duration,3),'width':w,'height':h,'mime':mimetypes.guess_type(p.name)[0] or 'video/mp4'}

def _fingerprint(job):return digest({'media':job['media'],'publish_at':job['publish_at'],'kind':job['kind']})

def attach(payload):
    for key,maximum in [('title',100),('description',5000)]:
        value=payload.get(key)
        if not isinstance(value,str) or (len(value) if key=='title' else len(value.encode()))>maximum or (key=='title' and not value.strip()) or '<' in value or '>' in value:raise ValueError('제목(100자)·설명(5,000바이트)을 확인하고 < > 문자는 제외하세요.')
    if any(type(payload.get(k)) is not bool for k in ('made_for_kids','synthetic_media')):raise ValueError('아동용 여부와 합성·변형 콘텐츠 표시를 선택하세요.')
    with LOCK:
        state=jobs();j=_job(state,payload.get('id'))
        if j['status'] not in WAITING|{'FAILED'} or j.get('remote_attempt'):raise ValueError('업로드 전 대기·검토 업무에만 영상을 등록할 수 있습니다.')
        media=probe_media(payload.get('path'),j['kind'])
        if any(o['id']!=j['id'] and o.get('media',{} ) and o['media']['sha256']==media['sha256'] and o['status']!='CANCELLED' for o in state['jobs']):raise ValueError('같은 영상이 이미 다른 업무에 등록됐습니다. 중복 업로드를 막기 위해 별도 영상을 선택하세요.')
        media.update({k:payload[k] for k in ('title','description','made_for_kids','synthetic_media')});j.update(media=media,approval=None,status='READY_REVIEW',error='',updated_at=stamp());write('automation_jobs.json',state)
    return listing()

def action(payload):
    with LOCK:
        state=jobs();j=_job(state,payload.get('id'));act=payload.get('action')
        if payload.get('expected_revision')!=digest(j):raise staffing.TeamConflict('업무 상태가 변경됐습니다. 새로고침 후 확인하세요.')
        if act=='approve':
            if j['status']!='READY_REVIEW' or datetime.fromisoformat(j['publish_at'])<=now()+MARGIN:raise ValueError('영상 검토를 마치고 10분 이상 남은 일정만 승인할 수 있습니다.')
            if j.get('restored_unverified') and payload.get('no_existing_upload_confirmed') is not True:raise ValueError('복구된 기록입니다. YouTube Studio에서 기존 업로드가 없음을 먼저 확인하세요.')
            if payload.get('rights_confirmed') is not True or payload.get('quality_confirmed') is not True:raise ValueError('저작권·사용 권리 및 영상·제목·표시 항목 검토를 확인하세요.')
            connected=channel.public()
            if payload.get('channel_id')!=connected['channel']['id']:raise ValueError('승인 화면의 채널이 변경됐습니다. 새로고침 후 다시 확인하세요.')
            if not connected['connected']:raise ValueError('먼저 PC에서 YouTube 채널을 연결하세요.')
            j.update(status='APPROVED',restored_unverified=False,approval={'fingerprint':_fingerprint(j),'channel_id':connected['channel']['id'],'channel_title':connected['channel']['title'],'approved_at':stamp(),'rights_confirmed':True,'quality_confirmed':True},error='',updated_at=stamp())
        elif act=='cancel':
            if j['status'] in {'UPLOADING','STOPPING'}:
                if j['id'] in ACTIVE:ACTIVE[j['id']].set()
                j.update(status='STOPPING',error='진행 중 업로드 중지 요청. 이미 YouTube에 전달된 결과는 확인이 필요합니다.',updated_at=stamp())
            elif j['status'] in WAITING|{'FAILED','MISSED'} and not j.get('remote_attempt'):j.update(status='CANCELLED',cancel_source='operator',approval=None,updated_at=stamp())
            else:raise ValueError('이미 전달했거나 결과가 불명확한 영상은 YouTube Studio에서 확인하세요. 로컬 취소로 공개 예약이 해제되지 않습니다.')
        else:raise ValueError('승인 또는 로컬 업무 취소를 선택하세요.')
        write('automation_jobs.json',state)
    return listing()

def _update(ident,**values):
    with LOCK:
        state=jobs();j=_job(state,ident);j.update(values,updated_at=stamp());write('automation_jobs.json',state);return copy.deepcopy(j)

def _verify(job,video):
    snippet=video.get('snippet',{});status=video.get('status',{});processing=video.get('processingDetails',{})
    if snippet.get('channelId')!=job['approval']['channel_id'] or snippet.get('title')!=job['media']['title']:raise ValueError('승인한 채널·제목과 영상이 다릅니다. YouTube Studio에서 직접 확인하세요.')
    if status.get('uploadStatus') in {'failed','rejected','deleted'} or processing.get('processingStatus') in {'failed','terminated'}:return 'FAILED','YouTube 처리 실패·거부 상태입니다. Studio에서 사유를 확인하세요.'
    if status.get('privacyStatus')=='public':return 'PUBLISHED',('예정 시각보다 일찍 공개됐습니다. Studio를 확인하세요.' if datetime.fromisoformat(job['publish_at'])>now() else '')
    if status.get('privacyStatus')!='private':return 'NEEDS_REVIEW','비공개 공개 예약 상태가 아닙니다. YouTube Studio에서 확인하세요.'
    scheduled=status.get('publishAt')
    if scheduled:
        try:matches=datetime.fromisoformat(scheduled.replace('Z','+00:00'))==datetime.fromisoformat(job['publish_at'])
        except (ValueError,TypeError):matches=False
        if not matches:raise ValueError('YouTube의 공개 예약 시간이 승인한 시간과 다릅니다.')
        if datetime.fromisoformat(job['publish_at'])>now():return 'SCHEDULED',''
        if now()<datetime.fromisoformat(job['publish_at'])+timedelta(minutes=15):return 'VERIFYING','공개 시각이 지났으며 YouTube 공개 상태를 확인 중입니다.'
    return 'NEEDS_REVIEW','비공개 또는 예약 미확인 상태입니다. 프로젝트 정책·업로드 처리·YouTube Studio를 확인하세요.'

def reconcile(ident,video_id=None,confirmed=False,adapter=channel):
    with LOCK:
        j=copy.deepcopy(_job(jobs(),ident));target=video_id or j.get('video_id')
        if not isinstance(target,str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}',target):raise ValueError('YouTube 영상 ID(11자)를 입력하세요.')
        if video_id and (confirmed is not True or j['status'] not in {'NEEDS_REVIEW','VERIFYING','FAILED'} or not j.get('remote_attempt')):raise ValueError('Studio에서 직접 확인한 불명확 업로드 결과에만 영상 ID를 연결하세요.')
        if not j.get('approval') or not j.get('media'):raise ValueError('승인 기록과 영상 자료가 없습니다.')
        if any(o['id']!=ident and o.get('video_id')==target for o in jobs()['jobs']):raise ValueError('이 영상 ID는 다른 업무에 연결돼 있습니다.')
    found=adapter.videos([target])
    if len(found)!=1 or found[0].get('id')!=target:raise ValueError('이 채널에서 영상을 확인하지 못했습니다.')
    status,error=_verify(j,found[0]);_update(ident,video_id=target,status=status,error=error,last_checked_at=stamp(),manual_reconciled=bool(video_id))
    return listing()

def _run(ident,adapter):
    from core.company_backup import LOCK as operation_lock
    try:
        with LOCK:j=copy.deepcopy(_job(jobs(),ident));event=ACTIVE[ident]
        if j['approval']['fingerprint']!=_fingerprint(j):raise ValueError('승인한 자료가 변경됐습니다. 다시 검토하세요.')
        media=j['media'];p=Path(media['path']);sha=hashlib.sha256()
        if p.stat().st_size!=media['size']:raise ValueError('승인 후 파일 크기가 변경됐습니다.')
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(4*1024*1024),b''):sha.update(chunk)
        if sha.hexdigest()!=media['sha256'] or p.stat().st_size!=media['size']:raise ValueError('승인 후 영상 파일이 변경됐습니다. 영상을 다시 등록하세요.')
        with operation_lock,LOCK:
            current=_job(jobs(),ident);plan=next((p for p in plans()['plans'] if p['id']==current['plan_id']),None)
            if event.is_set():raise ValueError('업로드 시작 전에 취소됐습니다.')
            if not plan or not plan['enabled'] or (path('restore_pending')).exists():raise DeferredUpload('계획 일시정지로 대기합니다. 아직 YouTube로 전송하지 않았습니다.')
            if datetime.fromisoformat(current['publish_at'])<=now()+MARGIN:raise ValueError('공개 시간까지 10분 미만이라 업로드를 시작하지 않았습니다.')
            _update(ident,remote_attempt=True)
        video_id=adapter.upload(j,media,lambda:event.is_set() or datetime.fromisoformat(j['publish_at'])<=now()+timedelta(minutes=2))
        _update(ident,video_id=video_id,status='VERIFYING',error='업로드 수신 완료. 실제 공개 예약 상태를 확인합니다.')
        try:reconcile(ident,adapter=adapter)
        except Exception as exc:_update(ident,error='YouTube 예약 상태 재확인이 필요합니다. '+(str(exc) if isinstance(exc,ValueError) else '조회 연결 오류'))
        if event.is_set():_update(ident,error='중지 요청과 업로드 완료가 겹쳤습니다. 이미 전달된 영상의 공개 예약은 YouTube Studio에서 확인·취소하세요.')
    except Exception as exc:
        with LOCK:j=_job(jobs(),ident)
        known_pre_upload=isinstance(exc,channel.ChannelError) and not isinstance(exc,channel.UploadUncertain)
        uncertain=bool(j.get('video_id')) or bool(j.get('remote_attempt') and not known_pre_upload)
        if known_pre_upload:_update(ident,remote_attempt=False)
        status='APPROVED' if isinstance(exc,DeferredUpload) else 'NEEDS_REVIEW' if uncertain else 'CANCELLED' if ACTIVE.get(ident) and ACTIVE[ident].is_set() and not j.get('remote_attempt') else 'FAILED'
        _update(ident,status=status,error=str(exc) if isinstance(exc,(ValueError,OSError)) else '예약 작업 실행 오류. 자동 재업로드하지 않습니다.')
    finally:
        with LOCK:ACTIVE.pop(ident,None)


def tick(instant=None,background=True,adapter=channel):
    from core.company_backup import LOCK as operation_lock
    instant=instant or now()
    with operation_lock,LOCK:
        if path('restore_pending').exists() or path('update_exit.json').exists():return
        state=_materialize(instant)
        if ACTIVE:return
        enabled={p['id'] for p in plans()['plans'] if p['enabled']}
        day=instant.astimezone(KST).date().isoformat()
        attempts=sum(j.get('attempt_day')==day for j in state['jobs'])
        ready=sorted([j for j in state['jobs'] if j['plan_id'] in enabled and j['status']=='APPROVED' and instant+MARGIN<datetime.fromisoformat(j['publish_at'])<=instant+timedelta(hours=24)],key=lambda j:j['publish_at'])
        if not ready or attempts>=24 or not channel.public()['connected']:return
        job=ready[0];job.update(status='UPLOADING',owner_pid=os.getpid(),attempt_day=day,attempt_id=uuid.uuid4().hex,started_at=stamp(instant),updated_at=stamp(instant));ACTIVE[job['id']]=threading.Event();write('automation_jobs.json',state);ident=job['id']
    if background:
        try:threading.Thread(target=_run,args=(ident,adapter),name='director-youtube-upload',daemon=True).start()
        except Exception:
            ACTIVE.pop(ident,None);_update(ident,status='FAILED',error='업로드 스레드를 시작하지 못했습니다.')
    else:_run(ident,adapter)

def recover():
    with LOCK:
        state=jobs();changed=False
        for j in state['jobs']:
            if j['status'] in {'UPLOADING','STOPPING'}:
                j.update(status='NEEDS_REVIEW' if j.get('remote_attempt') else 'READY_REVIEW',approval=j.get('approval') if j.get('remote_attempt') else None,error='프로그램 종료로 중단됐습니다. 자동 재업로드하지 않습니다.',updated_at=stamp());changed=True
        if changed:write('automation_jobs.json',state)

def listing():
    with LOCK:
        cfg=plans();state=jobs();local_day=now().astimezone(KST).date().isoformat();cutoff=(now().astimezone(KST)-timedelta(days=6)).date().isoformat();day_jobs=[j for j in state['jobs'] if j['day']==local_day and (j['status']!='CANCELLED' or j.get('cancel_source')=='operator')];counts={}
        for j in day_jobs:counts[j['status']]=counts.get(j['status'],0)+1
        public=[]
        for j in sorted(state['jobs'],key=lambda j:(j['publish_at'],j['id']),reverse=True):
            if j['day']<cutoff and j['status'] not in {'NEEDS_REVIEW','VERIFYING','FAILED','SCHEDULED'}:continue
            value={k:v for k,v in j.items() if k not in {'media','owner_pid','attempt_id'}}
            value['media']={k:v for k,v in (j.get('media') or {}).items() if k!='path'} if j.get('media') else None;value['revision']=digest(j);public.append(value)
            if len(public)>=250:break
        history=[]
        for offset in range(7):
            day=(now().astimezone(KST)-timedelta(days=offset)).date().isoformat()
            records=[j for j in state['jobs'] if j['day']==day and (j['status']!='CANCELLED' or j.get('cancel_source')=='operator')]
            history.append({'day':day,'target':len(records),'scheduled':sum(j['status']=='SCHEDULED' for j in records),'published':sum(j['status']=='PUBLISHED' for j in records),'attention':sum(j['status'] in {'FAILED','MISSED','NEEDS_REVIEW'} for j in records)})
        health=read('automation_health.json',{})
        channel_info=channel.public()
        return {'history':history,'channel':channel_info['channel'],'channel_connected':channel_info['connected'],'plans':cfg['plans'],'plans_revision':digest(cfg),'jobs':public,'today':{'day':local_day,'target':len(day_jobs),'shorts':sum(j['kind']=='short' for j in day_jobs),'longs':sum(j['kind']=='long' for j in day_jobs),'counts':counts},'health':health,'revision':digest([cfg,state,health]),'runtime_active':bool(ACTIVE),'timezone':'Asia/Seoul'}

def start_scheduler(stop):
    recover()
    def worker():
        last_check=0
        while not stop.wait(30):
            try:
                tick()
                if (now().timestamp()-last_check)>1800 and not path('restore_pending').exists():
                    last_check=now().timestamp()
                    with LOCK:
                        enabled={p['id'] for p in plans()['plans'] if p['enabled']}
                        pending=[j['id'] for j in jobs()['jobs'] if j['plan_id'] in enabled and j['status'] in {'SCHEDULED','VERIFYING'} and j.get('video_id')][:24]
                    for ident in pending:
                        if stop.is_set():break
                        try:reconcile(ident)
                        except Exception:_update(ident,error='YouTube 상태 조회 실패. 자동 재업로드하지 않으며 다음 조회에서 다시 확인합니다.')
                write('automation_health.json',{'last_tick':stamp(),'message':'예약 업무 확인 중 · 실행 장비가 켜져 있을 때 동작합니다.'})
            except Exception as exc:write('automation_health.json',{'last_tick':stamp(),'message':str(exc)[:300] if isinstance(exc,ValueError) else '예약 확인 오류. 비서실에서 기록을 확인하세요.'})
    thread=threading.Thread(target=worker,name='director-scheduled-work',daemon=True);thread.start();return thread

def stop_active():
    with LOCK:
        for event in ACTIVE.values():event.set()
        return len(ACTIVE)


def pause(ident=None):
    with LOCK:
        state=plans()
        if ident and not any(p['id']==ident for p in state['plans']):raise ValueError('예약 계획을 찾을 수 없습니다.')
        for plan in state['plans']:
            if ident is None or plan['id']==ident:plan.update(enabled=False,updated_at=stamp())
        write('automation_plans.json',state)
        if ident is None:stop_active()
    return listing()
