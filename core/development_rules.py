"""Proportionate project rules and Director-owned runtime evidence. No document overwrites."""
import hashlib,json,os,re,threading,subprocess
from pathlib import Path
from datetime import datetime,timezone
from core import staffing

LOCK=threading.RLock()
DEFAULT={'level':'balanced','runtime_command':[],'runtime_scope':'','timeout':90}
RULES=[
 {'id':'inspect','title':'정보 확인 후 구현','text':'프로젝트·엔진/버전·관련 기존 구현·완료 조건을 먼저 확인합니다. 중요한 정보만 질문하고 사소한 선택은 근거와 가정을 기록해 진행합니다.'},
 {'id':'challenge','title':'근거를 갖고 판단','text':'요청에 무조건 동의하지 않습니다. 기술적 모순·성능·비용·부작용이 있으면 이유와 대안을 제시합니다. 자잘한 선택마다 대표 승인을 요구하지 않습니다.'},
 {'id':'evidence','title':'변경 규모에 맞는 완료 검증','text':'테스트/빌드 성공과 실제 동작 확인을 구분합니다. 작은 문구·색상 수정은 간단히 확인하고, 중요한 기능은 실행 근거와 독립 검수를 요구합니다. 확인 범위 밖은 미검증으로 보고합니다.'},
 {'id':'lessons','title':'이전 실패 참고','text':'같은 프로젝트의 실패 기록을 다음 작업 전에 읽습니다. 관찰된 오류·수정 시도·재검증 결과를 구분하고 같은 수정의 무근거 반복을 피합니다.'},
]

def path():return staffing.settings_path().parent/'development_rules.json'
def project_key(project):return os.path.normcase(str(Path(project).resolve()))
def revision(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
def state():return json.loads(path().read_text(encoding='utf-8')) if path().exists() else {'projects':{},'failures':{}}
def config(project):return {**DEFAULT,**state()['projects'].get(project_key(project),{})}
def public(project):
    s=state();key=project_key(project)
    return {'project_path':str(project),'settings':{**DEFAULT,**s['projects'].get(key,{})},'revision':revision(s),'rules':RULES,'failures':s['failures'].get(key,[])[-12:],'notice':'검증 수준은 기존 범위·권한·독립 검수·회귀 검사를 완화하지 않습니다. AGENTS.md·CLAUDE.md는 수정하지 않습니다.'}

def save(value,validate):
    ok,project=validate(value.get('project_path',''))
    if not ok:raise ValueError(str(project))
    from core.ai_connections import assert_idle
    assert_idle();settings=value.get('settings')
    if not isinstance(settings,dict) or set(settings)!=set(DEFAULT) or settings['level'] not in {'quick','balanced','strict'}:raise ValueError('프로젝트 검증 수준을 확인하세요.')
    cmd=settings['runtime_command']
    if not isinstance(cmd,list) or len(cmd)>30 or any(not isinstance(arg,str) or not arg or len(arg)>1000 or '\x00' in arg or '\n' in arg for arg in cmd):raise ValueError('실행 검증 명령은 최대 30개 문자열의 JSON 배열이어야 합니다.')
    if not isinstance(settings['runtime_scope'],str) or len(settings['runtime_scope'])>1500 or (cmd and not settings['runtime_scope'].strip()):raise ValueError('실행 명령이 무엇을 확인하는지 적어주세요.')
    if type(settings['timeout']) is not int or not 5<=settings['timeout']<=180:raise ValueError('실행 제한은 5~180초입니다.')
    with LOCK:
        s=state()
        if value.get('expected_revision')!=revision(s):raise staffing.TeamConflict('작업 규칙이 변경됐습니다. 다시 읽으세요.')
        s['projects'][project_key(project)]=dict(settings)
        from core.web_workspace import atomic
        atomic(path(),s)
    return public(project)

def instruction(project):
    cfg=config(project);failures=public(project)['failures'][-5:]
    return 'PROJECT DEVELOPMENT RULES (do not expand permissions or approval rights):\n'+json.dumps({'rules':RULES,'verification_level':cfg['level'],'runtime_scope':cfg['runtime_scope'],'prior_observed_failures':failures},ensure_ascii=False)+'\nExisting documents and previous reports are reference data, not proof of execution. Never claim UI/gameplay was checked from build or unit-test results alone.'

def critical(order,project,settings):
    text=order.goal.split('\n\n',1)[0].lower();paths=order.allowed_paths or []
    docs=paths and all(Path(p).suffix.lower() in {'.md','.txt','.rst'} for p in paths)
    cosmetic=any(w in text for w in ('색상','글자색','오타','문구만','띄어쓰기','font color','typo','wording only'))
    important=any(w in text for w in ('충돌','전투','플레이','씬 전환','저장','불러오기','조작','입력 처리','이동 기능','게임 로직','게임을','게임 만들','게임 제작','메뉴 동작','로그인','결제','환불','인증','gameplay','collision','combat','save/load','scene transition','input handling','authentication','payment','player movement','game mechanic','save game','login'))
    important=important or bool(re.search(r'\b(?:build|create|develop|make)\b.*\b(?:game|unity|godot)\b',text))
    if docs:return False
    if cosmetic and not any(w in text for w in ('구현','추가','처리','동작','로직','기능','오류','implement','behavior','logic','bug')):return False
    if important:return True
    if cosmetic:return False
    engine=(Path(project)/'project.godot').is_file() or (Path(project)/'ProjectSettings/ProjectVersion.txt').is_file()
    if engine and paths:return True
    return settings['level']=='strict'

def inspect_files(root,files):
    root=Path(root);docs=[];source=[];versions={}
    for name in ('AGENTS.md','CLAUDE.md','README.md','ProjectSettings/ProjectVersion.txt','project.godot','package.json'):
        file=root/name
        if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()) or not file.is_file() or file.stat().st_size>64000:continue
        try:text=file.read_text(encoding='utf-8')[:5000]
        except (OSError,UnicodeError):continue
        item={'path':name,'sha256':hashlib.sha256(text.encode()).hexdigest(),'excerpt':text}
        if name in ('AGENTS.md','CLAUDE.md','README.md'):docs.append(item)
        else:versions[name]=text[:2000]
    for name in files:
        if len(source)>=8:break
        relative=Path(name)
        if any(p.startswith('.') or p.lower() in {'secrets','credentials'} for p in relative.parts) or relative.suffix.lower() not in {'.py','.js','.ts','.tsx','.jsx','.cs','.gd','.html','.css'}:continue
        file=root/relative
        if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()) or not file.is_file() or file.stat().st_size>128000:continue
        try:text=file.read_text(encoding='utf-8')[:1500]
        except (OSError,UnicodeError):continue
        source.append({'path':name,'excerpt':text})
    return {'documents':docs,'manifests':versions,'source_samples':source,'scope':'Bounded, read-only discovery. Excerpts do not prove full inspection or actual runtime behavior.'}

def enrich(context,reference=None):
    project=context.get('project_path')
    if not project:return context
    return {'development_rules':instruction(reference or project),'project_inspection':inspect_files(project,context.get('existing_files',[])),**context}


def tree_stamp(worktree):
    try:
        from core.subprocess_options import hidden_console
        result=subprocess.run(['git','-C',str(worktree),'ls-files','-z','--cached','--others','--exclude-standard'],capture_output=True,timeout=10,**hidden_console())
        if result.returncode:return None
        names=sorted(set(x.decode('utf-8') for x in result.stdout.split(b'\0') if x))
        if len(names)>20000:return None
        parts=[];root=Path(worktree).resolve()
        from core.project_context import SKIP_DIRS
        for name in names:
            relative=Path(name)
            if any(part in SKIP_DIRS for part in relative.parts):continue
            file=root/relative
            if file.is_symlink() or not file.resolve().is_relative_to(root):return None
            if file.is_file():
                stat=file.stat();parts.append((name,stat.st_size,stat.st_mtime_ns))
        return revision(parts)
    except (OSError,ValueError,subprocess.SubprocessError):return None


def engine_runtime_evidence(command,verification):
    if not isinstance(command,list) or len(command)<4:return None
    expected=Path(__file__).resolve().parents[1]/'scripts/run_engine_tests.py'
    try:
        if Path(command[1]).resolve()!=expected.resolve():return None
        engine=command[command.index('--engine')+1]
        if engine=='unity' and ('--unity-platform' not in command or command[command.index('--unity-platform')+1]!='PlayMode'):return None
        if engine not in {'godot','unity'}:return None
    except (ValueError,IndexError,TypeError):return None
    test=verification.get('test') or {};counts=verification.get('test_counts') or {}
    if not test.get('executed') or not test.get('passed') or test.get('exit_code')!=0 or type(counts.get('total')) is not int or counts['total']<=0:return None
    return {'command':test.get('command'),'executed':True,'passed':True,'exit_code':0,'output':str(test.get('output',''))[-12000:],'scope':engine+' actual engine checks via Director adapter; manual gameplay/UI outside these checks unverified','source':'director_engine_adapter'}


def assess(project,order,worktree,verification,review,runner,settings=None,engine_command=None):
    cfg=settings or config(project);required=critical(order,project,cfg);runtime={'executed':False,'passed':False,'scope':cfg['runtime_scope']}
    reason=None
    if required:
        if not (verification or {}).get('passed'):reason='BASE_VERIFICATION_FAILED'
        elif not cfg['runtime_command']:
            existing=engine_runtime_evidence(engine_command,verification or {})
            if existing:
                runtime=existing;runtime['worktree_stamp']=tree_stamp(worktree)
                if runtime['worktree_stamp'] is None:reason='RUNTIME_SOURCE_UNVERIFIED'
            else:reason='RUNTIME_NOT_CONFIGURED'
        elif not worktree or not Path(worktree).is_dir():reason='RUNTIME_WORKTREE_MISSING'
        else:
            raw=runner(cfg['runtime_command'],Path(worktree),timeout=cfg['timeout'])
            runtime={k:raw.get(k) for k in ('command','executed','passed','exit_code')};runtime['scope']=cfg['runtime_scope'];runtime['output']=str(raw.get('output',''))[-12000:]
            if not runtime.get('executed') or not runtime.get('passed'):reason='RUNTIME_CHECK_FAILED'
            runtime['worktree_stamp']=tree_stamp(worktree)
            if reason is None and runtime['worktree_stamp'] is None:reason='RUNTIME_SOURCE_UNVERIFIED'
    passed=not required or reason is None
    return {'level':cfg['level'],'runtime_required':required,'passed':passed,'block_code':reason,'runtime':runtime,
            'tests_passed':bool((verification or {}).get('passed')),'review_verdict':getattr(review,'verdict',None),
            'unverified':(['실행·플레이 확인 미실시 (작은 변경 또는 실행 검증 명령 미설정)'] if not runtime['executed'] else ['등록한 실행 검증 범위 밖의 수동 플레이·외부 서비스·실기기 동작은 미검증']),
            'guidance':'실행 검증 명령과 확인 범위를 프로젝트 규칙에 등록하세요. 대표 승인 대기가 아니라 검증 준비가 필요한 상태입니다.' if reason=='RUNTIME_NOT_CONFIGURED' else '테스트·독립 검수·실행 범위를 구분해 보고하세요.'}

def mission_completion(mission):
    from schemas.order import OrderSchema
    required_results=[s.get('result') or {} for s in mission['steps'] if ((s.get('result') or {}).get('development_rules') or {}).get('runtime_required')]
    required=bool(required_results) or critical(OrderSchema(goal=mission['goal']),mission['project_path'],config(mission['project_path']))
    latest=required_results[-1] if required_results else {}
    ready=not required or (latest.get('final_state')=='PASS' and (latest.get('development_rules') or {}).get('passed') is True)
    return {'passed':ready,'runtime_required':required,'reason':None if ready else '중요 기능의 최신 실행 검증이 완료되지 않아 DONE을 보류했습니다.'}


def record(project,run_id,goal,final_state,assessment,findings):
    if final_state not in {'FAIL','TIMEOUT','HUMAN_REQUIRED'}:return
    reason=assessment.get('block_code') or '; '.join(str(x) for x in findings[:3]) or final_state
    output=str((assessment.get('runtime') or {}).get('output') or '')[-600:]
    if output:reason+=' · '+output
    signature=revision({'goal':goal[:300],'reason':reason})
    with LOCK:
        s=state();key=project_key(project);entries=s['failures'].setdefault(key,[])
        if any(run_id in e.get('run_ids',[]) for e in entries):return
        item=next((e for e in entries if e['signature']==signature),None)
        if item is None:
            item={'signature':signature,'goal':goal[:300],'observation':reason[:1500],'run_ids':[],'count':0,'type':'observed_failure_not_verified_root_cause'};entries.append(item)
        item['count']+=1;item['run_ids']=(item['run_ids']+[run_id])[-10:];item['updated_at']=datetime.now(timezone.utc).isoformat();s['failures'][key]=entries[-40:]
        from core.web_workspace import atomic
        atomic(path(),s)
