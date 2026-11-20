"""PC-only, evidence-based setup checks. No AI billing, credentials or global CLI edits."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from core import staffing,web_workspace as web,hermes_agent,employee_tools
from core.subprocess_options import hidden_console

LOCK=threading.RLock()
PROCESS=None
CACHE=None
CACHED_AT=0
ROOT=Path(__file__).resolve().parents[1]
MIN_NODE=(22,19,0)

def path():return staffing.settings_path().parent/'setup_assistant.json'
def saved():return json.loads(path().read_text(encoding='utf-8')) if path().exists() else {}
def env():
    result={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('SECRET','PASSWORD','TOKEN','API_KEY','CREDENTIAL'))}
    result['PYTHONIOENCODING']='utf-8'
    return result

def version(command):
    if not command:return {'installed':False,'version':None}
    try:
        r=subprocess.run([command,'--version'],capture_output=True,timeout=5,env=env(),**hidden_console())
        match=re.search(r'(\d+)\.(\d+)\.(\d+)',r.stdout.decode('utf-8','replace'))
        if r.returncode or not match:raise ValueError()
        return {'installed':True,'version':match.group(0),'parts':tuple(map(int,match.groups()))}
    except (OSError,ValueError,subprocess.SubprocessError):return {'installed':False,'version':None}

def dependencies():
    result={}
    expected=json.loads((ROOT/'tools/web/package.json').read_text(encoding='utf-8'))['dependencies']
    for name,want in expected.items():
        file=ROOT/'tools/web/node_modules'/name/'package.json'
        try:actual=json.loads(file.read_text(encoding='utf-8'))['version']
        except (OSError,ValueError,KeyError):actual=None
        result[name]={'expected':want,'installed':actual,'matches':actual==want}
    return result

def runtime_checks():
    global CACHE,CACHED_AT
    with LOCK:
        if CACHE is not None and time.monotonic()-CACHED_AT<3:return dict(CACHE)
    node=shutil.which('node');npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    check=version(node);node_ok=check.get('parts',(0,0,0))>=MIN_NODE
    deps=dependencies();browser=False
    if node_ok and deps['playwright']['matches']:
        code="const fs=require('fs'),p=require('./tools/web/node_modules/playwright');console.log(JSON.stringify({exists:fs.existsSync(p.chromium.executablePath())}));"
        try:
            r=subprocess.run([node,'-e',code],cwd=ROOT,capture_output=True,timeout=8,env=env(),**hidden_console())
            browser=r.returncode==0 and json.loads(r.stdout).get('exists') is True
        except (OSError,ValueError,subprocess.SubprocessError):pass
    result={'node':{k:v for k,v in check.items() if k!='parts'},'node_compatible':node_ok,'minimum_node':'22.19.0','npm_installed':bool(npm),'dependencies':deps,'chromium_installed':browser,'bundled_editor':(ROOT/'console/vendor/monaco/vs/loader.js').is_file(),'ready':node_ok and bool(npm) and browser and all(d['matches'] for d in deps.values())}
    with LOCK:CACHE=result;CACHED_AT=time.monotonic()
    return dict(result)

def public():
    cfg=saved();runtime=runtime_checks();job=dict(cfg.get('installation') or {'status':'NOT_STARTED','log':[]})
    with LOCK:
        if job.get('status')=='RUNNING' and (PROCESS is None or PROCESS.poll() is not None):job['status']='INTERRUPTED' if PROCESS is None else 'FINISHING'
    h=hermes_agent.public();probe=h.get('probe') or {};hermes_ready=bool(h['settings']['enabled'] and h['settings']['python_path'] and probe.get('ok') and h['key_present'] and h['settings']['model'])
    mcp=cfg.get('mcp_check');valid=False
    if mcp:
        try:valid=mcp['team_revision']==staffing.current()['revision'] and mcp['tools_revision']==employee_tools.current()['revision'] and Path(mcp['project_path']).is_dir()
        except (KeyError,OSError):pass
    from desktop_launcher import SETUP_FLOW_VERSION
    intro_path=staffing.settings_path().parent/'desktop_setup.json'
    try:intro=json.loads(intro_path.read_text(encoding='utf-8'))
    except (OSError,ValueError):intro={'version':SETUP_FLOW_VERSION,'pending':False}
    return {'onboarding':intro,'runtime':runtime,'installation':job,'mcp_check':mcp if valid else None,
        'hermes':{'enabled':h['settings']['enabled'],'sdk_checked':bool(probe.get('ok')),'key_present':h['key_present'],'model_configured':bool(h['settings']['model']),'configuration_ready':hermes_ready,'authentication_verified':False},
        'steps':[{'id':'node','title':'1. Node.js·npm 확인','status':'READY' if runtime['node_compatible'] and runtime['npm_installed'] else 'ACTION_REQUIRED'},
                 {'id':'tools','title':'2. 웹 도구·브라우저 설치','status':'READY' if runtime['ready'] else 'ACTION_REQUIRED'},
                 {'id':'mcp','title':'3. MCP 연결 준비·검사','status':'BRIDGE_CHECKED' if valid else 'ACTION_REQUIRED'},
                 {'id':'hermes','title':'4. Hermes 선택 설정','status':'CONFIGURED_NOT_AUTHENTICATED' if hermes_ready else 'OPTIONAL'}],
        'notice':'이 화면은 현재 프로그램이 실행 중인 PC를 점검합니다. 다른 PC의 설치 완료를 뜻하지 않습니다. MCP 브리지 검사와 AI 클라이언트 등록·로그인, Hermes 설정과 유료 API 인증은 구분합니다.'}

def update(key,value):
    with LOCK:
        cfg=saved();cfg[key]=value;web.atomic(path(),cfg)

def install():
    global PROCESS,CACHE
    from core.ai_connections import assert_idle
    assert_idle()
    with LOCK:
        if PROCESS is not None and (PROCESS.poll() is None or saved().get('installation',{}).get('status')=='RUNNING'):raise ValueError('웹 도구 설치가 이미 진행 중입니다.')
        checks=runtime_checks()
        if not checks['node_compatible'] or not checks['npm_installed']:raise ValueError('Node.js 22.19 이상과 npm을 먼저 설치한 뒤 프로그램을 다시 실행하세요.')
        job={'id':'SETUP-'+uuid.uuid4().hex[:16],'status':'RUNNING','started_at':web.stamp(),'log':['고정 버전 npm 도구와 Chromium을 준비합니다. AI 호출이나 프로젝트 의존성 설치는 하지 않습니다.']}
        profile=path().parent/'setup_runtime';profile.mkdir(parents=True,exist_ok=True)
        empty=profile/'empty.npmrc';empty.write_text('',encoding='utf-8')
        safe=env();safe.update(npm_config_cache=str(profile/'npm-cache'),npm_config_userconfig=str(empty),npm_config_update_notifier='false')
        try:process=subprocess.Popen([sys.executable,str(ROOT/'scripts/setup_web_tools.py')],cwd=ROOT,env=safe,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',**hidden_console())
        except OSError as exc:raise ValueError('도구 설치를 시작하지 못했습니다.') from exc
        PROCESS=process;update('installation',job)
    def run():
        global CACHE
        expired=threading.Event()
        def timeout():expired.set();web.stop_owned(process)
        timer=threading.Timer(1200,timeout);timer.daemon=True;timer.start()
        try:
            for line in process.stdout:
                with LOCK:
                    clean=re.sub(r'\x1b\[[0-9;]*m','',line.strip());clean=re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@',r'\1[인증정보 숨김]@',clean);clean=re.sub(r'(?i)(token|api_key|password)=([^&\s]+)',r'\1=[숨김]',clean)
                    job['log'].append(clean[:500]);job['log']=job['log'][-60:];update('installation',job)
            code=process.wait();job['status']='CANCELLED' if getattr(process,'director_cancelled',False) else 'TIMED_OUT' if expired.is_set() else 'DONE' if code==0 else 'FAILED'
            # Never equate an exit code alone with verified readiness.
            CACHE=None
            if job['status']=='DONE' and not runtime_checks()['ready']:job['status']='NEEDS_CHECK'
        except Exception:job['status']='FAILED';job['log'].append('설치 진행을 확인하지 못했습니다. 다시 점검하세요.')
        finally:timer.cancel();job['finished_at']=web.stamp();update('installation',job)
    threading.Thread(target=run,name='director-tool-setup',daemon=True).start()
    return {'installation':job}

def cancel():
    with LOCK:process=PROCESS
    if process is not None and process.poll() is None:
        process.director_cancelled=True;web.stop_owned(process)
    return public()

def check_mcp(value):
    project=web.project(value.get('project_path'));ident=value.get('staff_id');employee_tools.member(ident)
    messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'director-setup','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'}]
    result=subprocess.run([sys.executable,str(ROOT/'scripts/director_mcp.py'),'--project',str(project),'--staff',ident],cwd=ROOT,env=env(),input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,encoding='utf-8',capture_output=True,timeout=20,**hidden_console())
    try:
        replies=[json.loads(line) for line in result.stdout.splitlines()]
        if result.returncode or len(replies)!=2 or replies[0]['result']['serverInfo']['name']!='ai-dev-director-readonly':raise ValueError()
        tools=[x['name'] for x in replies[1]['result']['tools']]
        if set(tools)!=set(employee_tools.allowed(ident)):raise ValueError()
    except (KeyError,TypeError,ValueError):raise ValueError('MCP 브리지 점검에 실패했습니다. 선택한 프로젝트·직원과 Python 환경을 확인하세요.') from None
    check={'status':'BRIDGE_CHECKED','project_path':str(project),'staff_id':ident,'tools':tools,'checked_at':web.stamp(),'team_revision':staffing.current()['revision'],'tools_revision':employee_tools.current()['revision'],'client_registered':False,'ai_login_verified':False}
    update('mcp_check',check);return check


def registration(value):
    p=web.project(value.get('project_path'));ident=value.get('staff_id');employee_tools.member(ident)
    args=[str(ROOT/'scripts/director_mcp.py'),'--project',str(p),'--staff',ident]
    # Codex uses TOML; Claude Code and Gemini CLI accept mcpServers JSON, with
    # different destinations. No file in the user's account is read or overwritten.
    entry={'command':sys.executable,'args':args}
    toml='[mcp_servers.director]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps(args,ensure_ascii=False)+'\n'
    return {'codex_toml':toml,'claude_json':json.dumps({'mcpServers':{'director':entry}},ensure_ascii=False,indent=2),'gemini_json':json.dumps({'mcpServers':{'director':entry}},ensure_ascii=False,indent=2),'notice':'사용하는 AI 클라이언트의 MCP 설정에 병합하세요. 기존 설정을 통째로 덮어쓰지 마세요. 이 정보 생성은 등록·계정 로그인을 실행하지 않습니다.'}


def shutdown():
    with LOCK:process=PROCESS
    if process is not None and process.poll() is None:
        process.director_cancelled=True;web.stop_owned(process)

import atexit
atexit.register(shutdown)


def finish_intro():
    from desktop_launcher import SETUP_FLOW_VERSION
    web.atomic(staffing.settings_path().parent/'desktop_setup.json',{'version':SETUP_FLOW_VERSION,'pending':False,'acknowledged_at':web.stamp()})
    return {'acknowledged':True,'href':'/office','notice':'안내 확인만 기록했습니다. 설치·인증 준비 상태는 변경하지 않았습니다.'}
