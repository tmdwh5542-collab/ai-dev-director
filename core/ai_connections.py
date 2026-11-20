"""Explicit provider routing and opt-in APIs. Stores environment-variable names, never secrets."""
import json
import os
import re
import shutil
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from types import SimpleNamespace
from core import staffing

DOMAINS={'openai':'OPENAI','claude':'ANTHROPIC','antigravity':'GOOGLE'}
CLI={'OPENAI':'codex','ANTHROPIC':'claude','GOOGLE':'agy'}
DEFAULT_ENV={'OPENAI':'OPENAI_API_KEY','ANTHROPIC':'ANTHROPIC_API_KEY','GOOGLE':'GEMINI_API_KEY'}


def path(): return staffing.settings_path().parent/'ai_connections.json'
def load(): return json.loads(path().read_text(encoding='utf-8')) if path().exists() else None


def validate(value):
    if not isinstance(value,dict) or set(value)!={'roles','connections','allow_same_provider'}: raise ValueError('AI 연결 설정을 확인하세요.')
    roles=value['roles']; connections=value['connections']
    if not isinstance(roles,dict) or set(roles)!={'head','builder','reviewer'} or any(v not in DOMAINS for v in roles.values()): raise ValueError('세 역할의 AI를 선택하세요.')
    if type(value['allow_same_provider']) is not bool or (len(set(roles.values()))<3 and not value['allow_same_provider']): raise ValueError('같은 AI 사용과 검수 독립성 감소에 동의해주세요.')
    if not isinstance(connections,dict) or set(connections)!=set(DOMAINS.values()): raise ValueError('세 AI의 연결 방식을 설정하세요.')
    clean={}
    for domain,c in connections.items():
        if not isinstance(c,dict) or set(c)!={'mode','model','key_env'} or c['mode'] not in {'cli','api'}: raise ValueError('CLI 또는 API 연결을 선택하세요.')
        if not isinstance(c['model'],str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{0,120}',c['model']) or (c['mode']=='api' and not c['model']): raise ValueError('API 연결에는 사용할 모델 ID를 입력하세요.')
        if not isinstance(c['key_env'],str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}',c['key_env']): raise ValueError('API 키를 보관한 환경변수 이름을 입력하세요.')
        clean[domain]=dict(c)
    return {'roles':dict(roles),'connections':clean,'allow_same_provider':value['allow_same_provider']}


def save(value):
    value=validate(value)
    previous=load()
    with staffing.LOCK:
        p=path();p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
    from core.provider_manager import ProviderManager, ProviderStatus
    manager=ProviderManager()
    for domain in CLI:
        if previous and previous['connections'][domain]==value['connections'][domain]: continue
        manager.set_status(domain,ProviderStatus.RECOVERING,'AI connection registration changed; inference unverified')
        with manager._get_conn() as conn:
            conn.execute('UPDATE provider_health SET next_trial_at=NULL, trial_started_at=NULL, reset_at=NULL WHERE provider=?',(domain,))
    return public()


def public():
    cfg=load() or {'roles':{'head':'claude','builder':'antigravity','reviewer':'openai'},'allow_same_provider':False,'connections':{d:{'mode':'cli','model':'','key_env':DEFAULT_ENV[d]} for d in CLI}}
    return {'settings':cfg,'registered':path().exists(),'availability':{d:{'cli_installed':bool(shutil.which(CLI[d])), 'key_present':bool(os.environ.get(c['key_env'])), 'authentication':'로그인·할당량은 실제 호출 전 미확인'} for d,c in cfg['connections'].items()},
        'login_commands':{'OPENAI':'codex login','ANTHROPIC':'claude auth login','GOOGLE':'agy'},
        'notes':'CLI는 PC의 공식 로그인 세션을 사용합니다. API는 별도 과금이며 PC 환경변수로 키를 등록한 뒤 앱을 다시 실행하세요. GOOGLE CLI는 Antigravity, GOOGLE API는 Gemini입니다.'}


def apply(config):
    cfg=load()
    if cfg:
        for role,provider in cfg['roles'].items(): config.setdefault(role,{}).update(provider=provider,executable=None,model=cfg['connections'][DOMAINS[provider]]['model'] or 'cli-default')
        config.setdefault('builder',{})['mode']='proposal';config['manual_roles']=True;config['ai_connections']=cfg
    return config


def api_route(domain):
    cfg=load()
    return cfg['connections'].get(domain) if cfg and cfg['connections'].get(domain,{}).get('mode')=='api' else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('API 연결의 리디렉션을 허용하지 않습니다.')


def invoke_api(domain,prompt,timeout=300,opener=None):
    route=api_route(domain)
    if not route: raise ValueError('API 연결이 설정되지 않았습니다.')
    secret=os.environ.get(route['key_env'])
    if not secret: raise ValueError('CONFIG_ERROR: API 키 환경변수가 없습니다: '+route['key_env'])
    if os.environ.get('DIRECTOR_TESTING')=='1' and opener is None: raise RuntimeError('테스트 중 실제 유료 API 호출은 차단됩니다.')
    headers={'Content-Type':'application/json'};model=route['model']
    if domain=='OPENAI':
        url='https://api.openai.com/v1/responses';headers['Authorization']='Bearer '+secret
        payload={'model':model,'input':prompt,'max_output_tokens':12000,'store':False}
    elif domain=='ANTHROPIC':
        url='https://api.anthropic.com/v1/messages';headers.update({'x-api-key':secret,'anthropic-version':'2023-06-01'})
        payload={'model':model,'max_tokens':12000,'messages':[{'role':'user','content':prompt}]}
    else:
        from urllib.parse import quote
        url='https://generativelanguage.googleapis.com/v1beta/models/'+quote(model,safe='')+':generateContent';headers['x-goog-api-key']=secret
        payload={'contents':[{'role':'user','parts':[{'text':prompt}]}],'generationConfig':{'maxOutputTokens':12000}}
    from core import usage
    argv=[CLI[domain], 'official-https-api',model];row=usage.call_started(argv,prompt);started=time.monotonic();at=datetime.now(timezone.utc).isoformat()
    try:
        request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers=headers,method='POST')
        with (opener or urllib.request.build_opener(NoRedirect()).open)(request,timeout=timeout) as response:
            http_status=getattr(response,'status',200)
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024: raise ValueError('API 응답 크기 제한을 초과했습니다.')
        body=json.loads(raw)
        if domain=='OPENAI': output='\n'.join(c['text'] for o in body.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
        elif domain=='ANTHROPIC': output='\n'.join(c['text'] for c in body.get('content',[]) if c.get('type')=='text')
        else: output='\n'.join(p.get('text','') for c in body.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if not p.get('thought'))
        if not output.strip(): raise ValueError('API가 비어 있는 응답을 반환했습니다.')
        duration=time.monotonic()-started
        usage.call_finished(row,argv,prompt,SimpleNamespace(stdout=output,stderr='',exit_code=0,duration_sec=duration,timed_out=False))
        return {'output':output,'executable':url,'version':'official-https-api','invocation':'POST '+url+' model='+model,'started_at':at,'ended_at':datetime.now(timezone.utc).isoformat(),'duration_sec':duration,'exit_code':None,'http_status':http_status,'token_usage':'ESTIMATED_IN_LEDGER','failover':False,'observed_fields':['executable','invocation','duration_sec','http_status'],'declared_fields':['authentication_mode','api_key_used'],'authentication_mode':'api_key','api_key_used':True}
    except Exception as exc:
        # Never echo response bodies, headers, or credentials in exceptions/ledger.
        message=({401:'unauthorized: API HTTP 401',403:'unauthorized: API HTTP 403',429:'quota exhausted: API HTTP 429'}.get(exc.code,'service unavailable: API HTTP '+str(exc.code))) if isinstance(exc,urllib.error.HTTPError) else 'API 연결 실패 ('+type(exc).__name__+')'
        error=RuntimeError(message);usage.call_failed(row,error);raise error from None


def login(domain):
    """Launch only a fixed official command in a user-visible terminal; never capture credentials."""
    import subprocess
    import sys
    argv={'OPENAI':['codex','login'],'ANTHROPIC':['claude','auth','login'],'GOOGLE':['agy']}.get(domain)
    if not argv: raise ValueError('로그인할 AI를 선택하세요.')
    executable=shutil.which(argv[0])
    if not executable: return {'opened':False,'command':' '.join(argv),'message':'공식 CLI를 먼저 설치한 뒤 이 명령을 실행하세요.'}
    argv[0]=executable
    if os.environ.get('DIRECTOR_TESTING')=='1': return {'opened':False,'command':' '.join(argv),'message':'테스트 모드에서는 로그인 창을 열지 않습니다.'}
    if sys.platform=='win32':
        env=os.environ.copy();env['DIRECTOR_LOGIN_ARGV']=json.dumps(argv)
        script='$a=ConvertFrom-Json $env:DIRECTOR_LOGIN_ARGV; $exe=$a[0]; $rest=@($a | Select-Object -Skip 1); & $exe @rest'
        subprocess.Popen(['powershell.exe','-NoExit','-NoProfile','-Command',script],env=env,creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif shutil.which('x-terminal-emulator'):
        subprocess.Popen(['x-terminal-emulator','-e',*argv])
    else: return {'opened':False,'command':' '.join(argv),'message':'터미널에서 이 명령으로 로그인하세요.'}
    return {'opened':True,'command':' '.join(argv),'message':'공식 로그인 창에서 직접 인증하세요. 로그인 성공 여부는 실제 호출 시 확인됩니다.'}


def assert_idle():
    from core import usage, company_meetings
    from core.mission import MissionStore, _pid_alive
    import dashboard_server
    if dashboard_server.chat_in_flight() or usage.running_now() or any(m.get('status')=='RUNNING' and _pid_alive(m.get('owner_pid')) for m in MissionStore().all()) or any(m['status'] in company_meetings.ACTIVE for m in company_meetings.snapshot()['meetings']):
        raise staffing.TeamConflict('현재 작업·회의가 진행 중입니다. 완료 또는 중지한 뒤 AI·스킬 설정을 변경하세요.')
