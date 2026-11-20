'use strict';
(function(){
const $=id=>document.getElementById(id);
const STATUS={RUNNING:'진행 중',DONE:'완료',INCOMPLETE:'예산 소진',BLOCKED:'확인 필요',FAILED:'실패',STOPPED:'정지',PASS:'통과',FAIL:'실패',TIMEOUT:'시간 초과',HUMAN_REQUIRED:'확인 필요',RECOVERED:'복구 완료'};
const PROVIDERS={ANTHROPIC:{name:'Claude',icon:'✳'},OPENAI:{name:'Codex',icon:'◈'},GOOGLE:{name:'Antigravity',icon:'△'}};
const HEALTH={HEALTHY:'정상 기록',UNKNOWN:'미확인',QUOTA_LOW:'한도 부족',QUOTA_EXHAUSTED:'한도 소진',AUTH_FAILED:'로그인 필요',UNAVAILABLE:'사용 불가',DEGRADED:'성능 저하',RECOVERING:'복구 확인 중',TIMEOUT:'시간 초과',CONFIG_ERROR:'설정 오류'};
const ROLE={HEAD:'계획 · 지휘',BUILDER:'코드 구현',REVIEWER:'독립 검수'};
const APPLY={applied:'원본에 적용됨',pending:'적용 대기',blocked:'적용 보류',discarded:'폐기됨',rolled_back:'복구됨',busy:'적용 중',error:'적용 오류'};
const BRIEF_KEY='director.mission.brief.v1',DRAFT_KEY='director.chat.draft.v1';
let page=1,pages=1,filter='',query='',listSeq=0,detailSeq=0,currentDetail=null,listController=null,statusBusy=false;
let searchTimer,toastTimer,briefAvailable=true;
const LAUNCH_KEY='director.mission.launch.v1';
let currentProject='',launchRecord=null,launchActive=false,launchTimer=null,launchPolling=false,launchPosting=false,controlBusy=false;
let workflowCatalog=[],preferredWorkflow='auto',memoryProject='',memorySeq=0;
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;}
function storageRead(key){try{return JSON.parse(localStorage.getItem(key)||'null');}catch(e){return null;}}
function storageWrite(key,value){try{localStorage.setItem(key,JSON.stringify(value));return true;}catch(e){return false;}}
function toast(message){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
function error(message){$('page-error').textContent=message;$('page-error').hidden=!message;}
function number(value){return Number.isFinite(Number(value))?Number(value).toLocaleString('ko-KR'):'—';}
function date(value){if(!value)return '기록 없음';const d=new Date(value+(/Z|[+-]\d\d:\d\d$/.test(value)?'':'Z'));return Number.isNaN(d.getTime())?'기록 없음':new Intl.DateTimeFormat('ko-KR',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(d);}
function pill(state,live){const n=el('span',state==='RUNNING'&&live===false?'재개 대기':STATUS[state]||state||'미기록','status-pill');n.dataset.state=state||'UNKNOWN';return n;}
async function json(url,options){const r=await fetch(url,{cache:'no-store',...options});let data;try{data=await r.json();}catch(e){throw Error('서버 응답을 읽을 수 없습니다.');}if(!r.ok||data.error){const e=Error(data.error||'조회 실패 ('+r.status+')');e.status=r.status;throw e;}return data;}
async function post(url,payload){const roles=await json('/ops/roles');return json(url,{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify(payload)});}
function showDialog(id){const dialog=$(id);if(!dialog.open)dialog.showModal();}

function renderList(data){
  page=data.page;pages=data.pages;
  for(const [id,key] of [['stat-all','all'],['stat-running','RUNNING'],['stat-done','DONE']])$(id).textContent=number(data.counts[key]||0);
  $('stat-attention').textContent=number((data.counts.BLOCKED||0)+(data.counts.FAILED||0)+(data.counts.INCOMPLETE||0));
  $('result-count').textContent=number(data.total);
  const frag=document.createDocumentFragment();
  for(const m of data.missions){
    const tr=el('tr'),goal=el('td'),open=el('button',m.goal||'목표 미기록','mission-open');open.type='button';open.title=m.goal||m.mission_id;open.setAttribute('aria-label',(m.goal||m.mission_id)+' 상세 보기');open.onclick=()=>openDetail(m.mission_id);
    goal.append(open,el('span',(m.project||'프로젝트 없음')+'  /  '+m.mission_id,'project-meta'));
    const state=el('td');state.append(pill(m.status,m.live));
    const progress=el('td'),bar=el('div','','step-progress');bar.setAttribute('aria-hidden','true');
    for(let i=0;i<Math.min(m.max_steps||m.steps.length,12);i++)bar.append(el('i','',i<m.passed_steps?'passed':''));
    progress.append(bar,el('small',m.passed_steps+'개 통과 · '+m.steps.length+'/'+(m.max_steps||m.steps.length)+'단계'));
    const result=el('td',m.apply_state?(APPLY[m.apply_state]||m.apply_state):m.deliverable?'작업본 있음':'—',m.apply_state==='applied'?'deliverable-ready':'');
    const arrow=el('td'),button=el('button','↗','icon-button');button.type='button';button.setAttribute('aria-label',m.mission_id+' 상세 보기');button.onclick=()=>openDetail(m.mission_id);arrow.append(button);
    tr.append(goal,state,progress,result,el('td',date(m.updated_at)),arrow);frag.append(tr);
  }
  $('mission-list').replaceChildren(frag);
  const empty=!data.missions.length,hasFilters=!!(query||filter);
  $('empty-state').hidden=!empty;document.querySelector('.table-wrap').hidden=empty;
  $('empty-title').textContent=hasFilters?'조건에 맞는 미션이 없습니다':'첫 번째 미션을 준비해 보세요';
  $('empty-copy').textContent=hasFilters?'다른 검색어나 상태로 다시 찾아보세요.':'목표와 완료 조건을 정리하면 AI가 더 정확하게 작업할 수 있습니다.';
  $('empty-action').textContent=hasFilters?'검색 조건 초기화':'새 미션 준비';
  $('empty-action').onclick=hasFilters?resetSearch:openBrief;
  $('previous').disabled=page<=1;$('next').disabled=page>=pages;
  $('page-number').textContent=page+' / '+pages;
  $('page-description').textContent=data.total?number(data.total)+'개 중 '+number((page-1)*data.limit+1)+'–'+number(Math.min(page*data.limit,data.total))+'개 표시':'미션 0개';
  $('updated-at').textContent='마지막 갱신 '+new Intl.DateTimeFormat('ko-KR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date());
}
async function loadList(){
  const seq=++listSeq;if(listController)listController.abort();listController=new AbortController();
  const params=new URLSearchParams({page:String(page),limit:'10',status:filter,q:query});
  $('mission-list').setAttribute('aria-busy','true');
  try{const data=await json('/ops/missions?'+params,{signal:listController.signal});if(seq!==listSeq)return;renderList(data);error('');}
  catch(e){if(seq===listSeq&&e.name!=='AbortError'){error('미션 기록을 불러오지 못했습니다. '+e.message+' 새로고침으로 다시 시도할 수 있습니다.');$('page-description').textContent='조회 실패 · 마지막 표시 내용이 남아 있습니다.';}}
  finally{if(seq===listSeq)$('mission-list').removeAttribute('aria-busy');}
}
function resetSearch(){clearTimeout(searchTimer);query='';filter='';page=1;$('search').value='';updateFilters();loadList();}
function updateFilters(){for(const b of document.querySelectorAll('[data-status]')){const active=b.dataset.status===filter;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));}}

async function loadStatus(){
  if(statusBusy)return;statusBusy=true;
  try{
    const s=await json('/status');
    currentProject=s.project_path||'';paintProject();
    const frag=document.createDocumentFragment();
    for(const [id,p] of Object.entries(PROVIDERS)){
      const info=s.providers[id]||{},card=el('div','','team-card');card.dataset.provider=id;
      const icon=el('span',p.icon,'provider-icon');icon.setAttribute('aria-hidden','true');
      const name=el('div','','team-info');name.append(el('b',p.name),el('small',info.role&&ROLE[info.role]?info.role+' · '+ROLE[info.role]:'역할 미확인'));
      const health=el('span',HEALTH[info.status]||info.status||'미확인','provider-status'+(info.status==='HEALTHY'?' healthy':''));health.title=info.error&&info.error!=='NONE'?info.error:'마지막 기록 상태입니다. 현재 로그인이나 잔여 한도를 보장하지 않습니다.';
      card.append(icon,name,health);frag.append(card);
    }
    $('team').replaceChildren(frag);
    $('project-title').textContent=s.project_name?'현재 프로젝트 · '+s.project_name:'먼저 작업할 프로젝트를 선택하세요';
    $('project-hint').textContent=!s.project_path?'프로젝트 선택에서 작업할 폴더를 지정한 뒤, 새 미션을 준비하세요.':s.head_busy?'HEAD가 요청을 처리하고 있습니다. 시작 요청의 상태나 스테이지를 확인하세요.':s.todo||s.system_mode_hint||'새 미션을 준비하거나, 기록에서 이전 결과를 확인할 수 있습니다.';
    $('connection').textContent='로컬 서버 연결됨';$('connection').dataset.state='ok';
  }catch(e){$('connection').textContent='연결 확인 필요';$('connection').dataset.state='error';$('project-hint').textContent='서버 상태 조회 실패 · '+e.message;}
  finally{statusBusy=false;}
}

function section(title,text){const box=el('section','','detail-section');box.append(el('h3',title));if(text)box.append(el('p',text));return box;}
function renderDetail(data){
  const m=data.mission,body=$('detail-content');body.replaceChildren();
  body.append(el('p',m.goal||'목표 미기록','detail-goal'));
  const meta=el('div','','detail-meta');meta.append(pill(m.status,m.live),el('span',m.project||'프로젝트 없음'),el('span',m.mission_id),el('span',date(m.updated_at)));body.append(meta);
  if(m.workflow_id){const entry=workflowCatalog.find(w=>w.id===m.workflow_id),box=section('요청한 개발 방식 · '+(entry?.title||m.workflow_id));box.classList.add('workflow-summary');if(entry){box.append(el('p',entry.description));const list=el('ul');for(const item of entry.checklist)list.append(el('li',item));box.append(list);}box.append(el('small','작업 지침입니다. 실제 완료 여부는 단계별 검증 기록으로 확인하세요.'));if(m.memory_sources?.length)box.append(el('p','참고한 검증 기록: '+m.memory_sources.join(', ')));else box.append(el('p',m.use_project_memory===false?'프로젝트 기록 참고를 사용하지 않았습니다.':'참고한 검증 완료 기록이 없습니다.'));body.append(box);}
  if(m.staff_team?.members){const team=section('이 미션의 팀 · '+m.staff_team.members.length+'명','미션을 시작할 때의 직원과 직무입니다. 이후 팀 설정 변경과 구분해 보관합니다.');for(const member of m.staff_team.members)team.append(el('p',member.name+' · '+member.duties));body.append(team);}
  paintControls(m,body);
  if(m.blocked_reason)body.append(section('멈춘 이유',m.blocked_reason));
  if(m.summary)body.append(section('HEAD 요약',m.summary));
  const delivery=section('결과물과 원본 적용 상태');
  delivery.append(el('p',m.apply_state?(APPLY[m.apply_state]||m.apply_state):'적용 기록 없음'));
  if(m.deliverable)delivery.append(el('div',m.deliverable,'detail-path'));
  else delivery.append(el('p','기록된 결과물 경로가 없습니다.'));
  if(m.applied&&m.applied.blocks)delivery.append(el('p','보류 사유: '+m.applied.blocks.join(' · ')));
  if(m.applied&&m.applied.files&&m.applied.files.length)delivery.append(el('div','적용 파일\n'+m.applied.files.join('\n'),'detail-path'));
  body.append(delivery);
  const steps=section('단계별 검증 · '+m.passed_steps+'개 통과 / '+m.steps.length+'개 시도');
  if(!m.steps.length)steps.append(el('p','아직 실행된 단계가 없습니다.'));
  for(const s of m.steps){
    const row=el('article','','evidence-step'),heading=el('div','','evidence-heading');heading.append(el('b',s.index+'단계'),pill(s.state));row.append(heading,el('p',s.goal||'단계 목표 미기록'));
    const metrics=el('div','','evidence-metrics');
    if(s.tests)metrics.append(el('span','테스트 '+number(s.tests.passed||0)+'/'+number(s.tests.total||0)+' 통과 · 실패 '+number(s.tests.failed||0)));
    else metrics.append(el('span','테스트 기록 없음'));
    if(s.assigned_staff_id){const member=m.staff_team?.members?.find(member=>member.id===s.assigned_staff_id);metrics.append(el('span','구현 담당: '+(member?.name||s.assigned_staff_id)));}
    metrics.append(el('span','검수: '+(s.review||'기록 없음')));
    if(s.repairs)metrics.append(el('span','자동 수정 '+s.repairs+'회'));
    if(s.run_id)metrics.append(el('span',s.run_id));
    if(s.development_rules){const r=s.development_rules;metrics.append(el('span','실행 확인: '+(r.runtime?.executed?(r.passed&&r.runtime.passed?'등록 범위 통과':'재검증 필요'):'미실시')));}
    row.append(metrics);if(s.development_rules?.unverified?.length)row.append(el('p','미검증: '+s.development_rules.unverified.join(' · ')));if(s.note)row.append(el('p',s.note));
    if(s.run_id){const button=el('button','실행 로그 · 검수 지적 · 변경 내용 보기','evidence-toggle'),evidence=el('div','','step-evidence');button.type='button';button.setAttribute('aria-expanded','false');evidence.hidden=true;button.onclick=()=>loadStep(m.mission_id,s.index,evidence,button);row.append(button,evidence);}
    steps.append(row);
  }
  body.append(steps);
  const calls=section('AI 호출 기록 · '+data.calls.length+'건 표시');
  calls.append(el('p','완료된 호출을 시간순으로 최대 400건 표시합니다.'));
  if(!data.calls.length)calls.append(el('p','완료된 AI 호출 기록이 없습니다.'));
  const list=el('ol','','call-list');
  for(const c of data.calls){const li=el('li');li.append(el('span',((PROVIDERS[c.provider]||{}).name||c.provider)+' · '+(c.staff_name||c.role||'역할 미기록')+' · '+(c.stage||'')),el('small',Math.round(c.seconds||0)+'초 · '+(c.tokens==null?'토큰 기록 없음':(c.exact?'':'~')+number(c.tokens)+' 토큰')+' · '+c.status));list.append(li);}
  calls.append(list);body.append(calls);
  $('export-report').disabled=false;
}
async function openDetail(id,background=false){
  if(background&&(!$('detail-dialog').open||currentDetail?.mission.mission_id!==id))return;
  const seq=++detailSeq;
  if(!background){currentDetail=null;$('export-report').disabled=true;$('detail-title').textContent='미션 상세';$('detail-content').replaceChildren(el('p','검증 기록을 읽고 있습니다…','muted'));showDialog('detail-dialog');}
  try{const data=await json('/ops/missions?'+new URLSearchParams({mission_id:id}));if(seq!==detailSeq||!$('detail-dialog').open)return;currentDetail=data;renderDetail(data);}
  catch(e){if(seq!==detailSeq)return;if(!background)$('detail-content').replaceChildren(el('p','미션을 불러오지 못했습니다. '+e.message,'form-error'));else toast('상세 기록 갱신 실패 · 마지막 조회 내용입니다.');}
}
function reportText(data){
  const m=data.mission,lines=['# 미션 보고서','',m.goal,'','- 미션 ID: '+m.mission_id,'- 프로젝트: '+m.project_path,'- 상태: '+(STATUS[m.status]||m.status),'- 갱신: '+m.updated_at,'- 원본 적용: '+(APPLY[m.apply_state]||m.apply_state||'기록 없음'),'- 작업본: '+(m.deliverable||'없음'),''];
  if(m.workflow_id)lines.push('- 요청한 개발 방식: '+(workflowCatalog.find(w=>w.id===m.workflow_id)?.title||m.workflow_id),'- 참고한 검증 기록: '+((m.memory_sources||[]).join(', ')||'없음'),'');
  if(m.staff_team?.members)lines.push('## 이 미션의 팀','',...m.staff_team.members.map(member=>'- '+member.name+' ['+member.id+'] · '+member.duties),'');
  if(m.summary)lines.push('## HEAD 요약','',m.summary,'');
  if(m.blocked_reason)lines.push('## 멈춘 이유','',m.blocked_reason,'');
  if(m.applied?.blocks?.length)lines.push('## 적용 보류 사유','',...m.applied.blocks.map(x=>'- '+x),'');
  if(m.applied?.files?.length)lines.push('## 적용 파일','',...m.applied.files.map(x=>'- '+x),'');
  lines.push('## 단계별 검증','');
  for(const s of m.steps)lines.push('### '+s.index+'단계 · '+(STATUS[s.state]||s.state||'미기록'),'',s.goal,'','- 테스트: '+(s.tests?s.tests.passed+'/'+s.tests.total+' 통과, '+s.tests.failed+' 실패':'기록 없음'),'- 검수: '+(s.review||'기록 없음'),'- 자동 수정: '+(s.repairs||0)+'회','- 구현 담당: '+(m.staff_team?.members?.find(member=>member.id===s.assigned_staff_id)?.name||s.assigned_staff_id||'직원 미기록'),'- 실행 ID: '+(s.run_id||'없음'),s.note||'','');
  for(const s of m.steps)if(s.development_rules){const r=s.development_rules;lines.push('실행 검증 ('+s.index+'단계): '+(r.runtime?.executed?(r.passed&&r.runtime.passed?'등록 범위 통과':'재검증 필요'):'미실시'),'미검증: '+(r.unverified||[]).join(' · '),'');}
  lines.push('## AI 호출 기록 (완료된 호출 중 시간순으로 최대 400건)','');for(const c of data.calls)lines.push('- '+(c.staff_name||c.role)+' / '+c.provider+' / '+c.stage+' · '+Math.round(c.seconds||0)+'초 · '+(c.tokens==null?'토큰 기록 없음':(c.exact?'':'~')+c.tokens+' 토큰')+' · '+c.status);
  return lines.join('\n');
}
function downloadReport(){if(!currentDetail)return;const url=URL.createObjectURL(new Blob(['\ufeff'+reportText(currentDetail)],{type:'text/markdown;charset=utf-8'})),a=el('a');a.href=url;a.download=currentDetail.mission.mission_id.replace(/[^a-z0-9_-]/gi,'_')+'-report.md';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('미션 보고서를 저장했습니다.');}

const TEMPLATES={
  feature:{goal:'할 일 목록에 마감일과 완료 상태별 필터를 추가해줘.',criteria:'정상 동작과 예외 상황을 테스트하고, 기존 기능이 유지되어야 합니다.',scope:'관련 파일을 먼저 살펴보고, 필요한 범위에서 구현해 주세요.'},
  bug:{goal:'로그인 실패 시 사용자에게 오류 안내가 표시되지 않는 문제를 수정해줘.',criteria:'문제 재현 테스트를 추가하고, 수정 후 해당 테스트와 기존 테스트가 통과해야 합니다.',scope:'원인을 확인하고 수정해 주세요. 관련 없는 기능 변경은 피해주세요.'},
  quality:{goal:'모바일에서 작업 목록이 화면 밖으로 넘치는 문제를 개선해줘.',criteria:'기존 동작을 유지하고, 개선 전후 차이와 검증 결과를 정리해 주세요.',scope:'기존 구조를 먼저 분석하고, 작은 단계로 개선해 주세요.'}
};
function saveBrief(){briefAvailable=storageWrite(BRIEF_KEY,{goal:$('brief-goal').value,criteria:$('brief-criteria').value,scope:$('brief-scope').value,profile:$('brief-profile').value,workflow_id:workflowCatalog.length?($('brief-workflow').value||'auto'):preferredWorkflow,use_project_memory:$('brief-use-memory').checked});}
function openBrief(){
  $('brief-error').hidden=true;const d=storageRead(BRIEF_KEY)||{};
  for(const k of ['goal','criteria','scope'])$('brief-'+k).value=typeof d[k]==='string'?d[k].slice(0,$('brief-'+k).maxLength):'';
  $('brief-profile').value=['quick','standard','deep'].includes(d.profile)?d.profile:'standard';paintProject();
  preferredWorkflow=typeof d.workflow_id==='string'?d.workflow_id:'auto';$('brief-workflow').value=workflowCatalog.some(w=>w.id===preferredWorkflow)?preferredWorkflow:'auto';$('brief-use-memory').checked=d.use_project_memory!==false;paintWorkflow();
  showDialog('brief-dialog');$('brief-goal').focus();
}
function prepareDraft(e){
  e.preventDefault();const goal=$('brief-goal').value.trim(),criteria=$('brief-criteria').value.trim(),scope=$('brief-scope').value.trim();if(!goal){$('brief-goal').focus();return;}
  const text=briefText(true);
  const existing=storageRead(DRAFT_KEY);
  if(existing?.text&&existing.text!==text&&!confirm('스테이지에 작성 중인 초안이 있습니다. 새 요청으로 바꿀까요?'))return;
  if(!storageWrite(DRAFT_KEY,{text,requestId:null})){$('brief-error').hidden=false;$('brief-error').textContent='브라우저 저장소를 사용할 수 없습니다. 작성한 내용을 복사한 뒤 스테이지에 붙여 넣어 주세요.';return;}
  saveBrief();location.assign('/');
}

function briefText(withWorkflow=false){const goal=$('brief-goal').value.trim(),criteria=$('brief-criteria').value.trim(),scope=$('brief-scope').value.trim(),profile=$('brief-profile').value;let prefix=profile==='quick'?'[빠르게] ':profile==='deep'?'[깊게] ':'';if(withWorkflow)prefix+=(workflowCatalog.find(w=>w.id===$('brief-workflow').value)?.tag||'[자동 절차]')+' '+($('brief-use-memory').checked?'':'[기록 제외] ');return prefix+[goal,criteria?'완료 조건:\n'+criteria:'',scope?'작업 범위와 주의사항:\n'+scope:''].filter(Boolean).join('\n\n');}
function paintProject(){
  $('brief-project').textContent=currentProject||'프로젝트를 선택하세요';
  $('launch-mission').disabled=launchActive;
  $('choose-project').disabled=launchActive;$('brief-choose-project').disabled=launchActive;
  if(memoryProject!==currentProject){memoryProject=currentProject;memorySeq++;$('memory-content').replaceChildren(el('p',currentProject?'펼쳐서 기록을 확인할 수 있습니다.':'프로젝트를 선택하면 기록을 확인할 수 있습니다.'));if($('memory-preview').open)loadProjectMemory();}
}
async function openProjects(){
  if(launchActive){toast('요청 처리 중에는 프로젝트를 바꿀 수 없습니다.');return;}
  $('project-error').hidden=true;$('project-path').value=currentProject;showDialog('project-dialog');
  const list=$('recent-projects');list.replaceChildren(el('p','최근 프로젝트를 읽고 있습니다…','muted'));
  try{const data=await json('/ops/projects');list.replaceChildren();for(const p of data.projects){const b=el('button',p.name);b.type='button';b.append(el('small',p.path));b.onclick=()=>{$('project-path').value=p.path;$('project-path').focus();};list.append(b);}if(!list.children.length)list.append(el('p','아래에 폴더 경로를 입력하거나 찾아보기를 사용하세요.','muted'));}
  catch(e){list.replaceChildren(el('p','최근 목록을 읽지 못했습니다. 경로를 직접 입력할 수 있습니다.','muted'));}
}
async function selectProject(e){
  e.preventDefault();if(launchActive)return;const path=$('project-path').value.trim();if(!path)return;
  const b=$('save-project');if(b.disabled)return;b.disabled=true;$('project-error').hidden=true;
  try{const out=await json('/project',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body:new URLSearchParams({path})});if(out.status!=='ok')throw Error(out.message||'프로젝트 선택 실패');currentProject=path;$('project-dialog').close();paintProject();await loadStatus();toast('작업할 프로젝트를 선택했습니다.');}
  catch(e){$('project-error').hidden=false;$('project-error').textContent=e.message;}
  finally{b.disabled=false;}
}
async function browseProject(){
  const b=$('browse-project');if(b.disabled)return;b.disabled=true;
  try{const roles=await json('/ops/roles'),out=await json('/ops/pick-folder',{method:'POST',headers:{'X-Solomon-Bridge':roles.csrf}});if(out.path)$('project-path').value=out.path;}
  catch(e){$('project-error').hidden=false;$('project-error').textContent='폴더 선택 창을 열지 못했습니다. 경로를 직접 입력하세요. '+e.message;}
  finally{b.disabled=false;}
}
function persistLaunch(){storageWrite(LAUNCH_KEY,launchRecord);}
function renderLaunch(receipt){
  const state=receipt.state,result=receipt.result||{};
  launchActive=state==='planning'||state==='unknown';paintProject();
  $('launch-progress').hidden=false;
  const labels={planning:'HEAD가 미션을 준비하고 있습니다',started:'미션을 시작했습니다',question:'HEAD가 추가 정보를 요청했습니다',escalated:'작업 시작에 확인이 필요합니다',rejected:'미션을 시작하지 못했습니다',busy:'다른 작업이 진행 중입니다',error:'작업 시작 오류',interrupted:'서버가 중단되어 시작 결과를 확인해야 합니다',unknown:'요청 접수 여부를 확인하고 있습니다'};
  $('launch-title').textContent=labels[state]||state;
  $('launch-message').textContent=result.message||result.error||result.reason||(state==='planning'?'창을 닫거나 새로고침해도 이 요청의 상태를 이어서 확인합니다.':state==='interrupted'?'미션 기록을 먼저 확인하세요. 같은 작업을 자동으로 다시 실행하지 않습니다.':state==='unknown'?'같은 요청 ID로 접수 여부를 다시 확인하거나 재전송할 수 있습니다.':'요청 기록이 서버에 저장되어 있습니다.');
  $('launch-project').textContent=(receipt.project_path||launchRecord?.payload.project_path||'')+' · 요청 '+(receipt.request_id||'');
  const actions=$('launch-actions');actions.replaceChildren();
  if(result.mission_id){const b=el('button','미션 결과 보기','button primary');b.type='button';b.onclick=()=>openDetail(result.mission_id);actions.append(b);}
  if(state==='unknown'){for(const [label,fn] of [['접수 확인',pollLaunch],['같은 요청 재전송',()=>sendLaunch(launchRecord.payload)]]){const b=el('button',label,'button secondary');b.type='button';b.onclick=fn;actions.append(b);}}
  if(['question','escalated'].includes(state)){const a=el('a','작업실에서 확인 ↗','button secondary');a.href='/classic';actions.append(a);}
  if(!launchActive){const b=el('button','닫기','button secondary');b.type='button';b.onclick=()=>{launchRecord=null;persistLaunch();$('launch-progress').hidden=true;};actions.append(b);}
}
async function pollLaunch(){
  if(!launchRecord||launchPolling)return;launchPolling=true;clearTimeout(launchTimer);const id=launchRecord.payload.request_id;
  try{const receipt=await json('/ops/mission-launch?'+new URLSearchParams({request_id:id}));if(!launchRecord||launchRecord.payload.request_id!==id)return;launchRecord.receipt=receipt;persistLaunch();renderLaunch(receipt);if(receipt.state==='planning')launchTimer=setTimeout(pollLaunch,2000);else{loadList();loadStatus();}}
  catch(e){if(!launchRecord||launchRecord.payload.request_id!==id)return;const receipt={request_id:id,state:'unknown',result:{message:'접수 확인 실패 · '+e.message}};renderLaunch(receipt);}
  finally{launchPolling=false;}
}
async function sendLaunch(payload){
  if(launchPosting)return;launchPosting=true;
  launchActive=true;paintProject();renderLaunch({request_id:payload.request_id,state:'planning',project_path:payload.project_path});
  try{const receipt=await post('/ops/mission-launch',payload);launchRecord={payload,receipt};persistLaunch();renderLaunch(receipt);if($('brief-dialog').open)$('brief-dialog').close();if(receipt.state==='planning')launchTimer=setTimeout(pollLaunch,500);else{loadList();loadStatus();}}
  catch(e){const known=[400,403,409].includes(e.status),receipt={request_id:payload.request_id,state:known?'rejected':'unknown',project_path:payload.project_path,result:{error:e.message}};launchRecord={payload,receipt};persistLaunch();renderLaunch(receipt);$('brief-error').hidden=false;$('brief-error').textContent=e.message;}
  finally{launchPosting=false;}
}
async function launchMission(){
  if(launchActive||!$('brief-form').reportValidity())return;
  if(!$('brief-goal').value.trim()){$('brief-goal').focus();return;}
  if(!currentProject){$('brief-error').hidden=false;$('brief-error').textContent='먼저 작업할 프로젝트를 선택하세요.';return;}
  saveBrief();const payload={request_id:'mission-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10),project_path:currentProject,goal:briefText(),profile:$('brief-profile').value,workflow_id:$('brief-workflow').value||'auto',use_project_memory:$('brief-use-memory').checked};
  launchRecord={payload,receipt:{request_id:payload.request_id,state:'unknown'}};persistLaunch();await sendLaunch(payload);
}
function paintControls(m,body){
  if(m.status==='RUNNING'&&m.live)return;
  const box=el('section','','mission-controls'),buttons=el('div','','control-buttons'),message=el('p','','control-result');message.setAttribute('role','status');
  const add=(text,action,reason)=>{const b=el('button',text,'button secondary');b.type='button';b.disabled=controlBusy;b.onclick=()=>controlMission(m,action,reason?reason(): '',box,message);buttons.append(b);};
  if(m.deliverable&&!['applied','discarded'].includes(m.apply_state)&&m.status!=='RUNNING')add('검증된 결과를 원본에 적용','apply');
  if(m.status!=='DONE'&&m.steps.length){
    const feedback=el('textarea');feedback.maxLength=300;feedback.rows=2;feedback.placeholder='추가 수정 지시를 적어주세요. 예: 모바일 오류부터 수정하고 회귀 테스트를 추가해줘';feedback.setAttribute('aria-label','미션 수정 지시');
    box.append(el('p',m.status==='BLOCKED'?'확인이 필요한 항목은 작업실에서 처리하세요. 재계획은 기존 권한 심사를 그대로 거칩니다.':'이전 기록과 작업본을 바탕으로 계속 진행할 수 있습니다.'),feedback);
    add(m.status==='RUNNING'?'중단된 미션 재개':'이어서 진행 · 2단계 추가',m.status==='RUNNING'?'resume':'extend');
    if(m.status!=='RUNNING')add('수정 지시로 재계획','replan',()=>feedback.value.trim());
  }
  if(buttons.children.length){box.append(buttons,message);body.append(box);}
}
async function controlMission(m,action,reason,box,message){
  if(controlBusy)return;if(action==='replan'&&!reason){message.textContent='재계획할 수정 지시를 입력하세요.';return;}
  controlBusy=true;for(const b of box.querySelectorAll('button'))b.disabled=true;
  try{const out=await post('/ops/mission-control',{mission_id:m.mission_id,action,reason});message.textContent={resumed:'미션을 이어서 진행합니다.',applied:'검증된 결과를 원본에 적용했습니다.',blocked:'적용 보류: '+(out.blocks||[]).join(' · ')}[out.status]||out.reason||out.error||out.status;toast(message.textContent);loadList();loadStatus();if(currentDetail?.mission.mission_id===m.mission_id&&$('detail-dialog').open)await openDetail(m.mission_id,true);}
  catch(e){message.textContent='요청 결과를 확인하세요. '+e.message+' 새로고침 후 상태를 확인하고 다시 시도하세요.';}
  finally{controlBusy=false;for(const b of box.querySelectorAll('button'))b.disabled=false;for(const b of $('detail-content').querySelectorAll('.mission-controls button'))b.disabled=false;}
}
async function loadStep(id,index,host,button){
  if(host.dataset.loaded){host.hidden=!host.hidden;button.setAttribute('aria-expanded',String(!host.hidden));return;}
  button.disabled=true;host.hidden=false;button.setAttribute('aria-expanded','true');host.replaceChildren(el('p','실행 근거를 읽고 있습니다…','muted'));
  try{const data=await json('/ops/mission-step?'+new URLSearchParams({mission_id:id,index:String(index)}));host.replaceChildren();if(!data.available)host.append(el('p','아직 생성된 실행 근거가 없거나 이전 기록에 접근할 수 없습니다. 단계가 끝난 뒤 다시 조회할 수 있습니다.'));
    if(data.development_rules?.block_code)host.append(el('p',data.development_rules.block_code+' · '+data.development_rules.guidance));
    if(data.development_rules?.unverified?.length)host.append(el('p','미검증 항목: '+data.development_rules.unverified.join(' · ')));
    for(const c of data.commands){host.append(el('h4',c.label+' · '+(c.passed?'통과':'실패')+' · 종료 코드 '+(c.exit_code??'미기록')),el('pre',typeof c.command==='string'?c.command:JSON.stringify(c.command)),el('pre',c.output||'출력 없음'));if(c.truncated)host.append(el('p','출력이 길어 마지막 12,000자만 표시합니다.'));}
    if(data.review){host.append(el('h4','독립 검수 · '+(data.review.verdict||'미기록')),el('p',data.review.summary||'요약 없음'));for(const key of ['p0','p1','p2'])if(data.review[key]?.length){host.append(el('h4',key.toUpperCase()+' 지적'));const list=el('ul');for(const item of data.review[key])list.append(el('li',item));host.append(list);}}
    if(data.diff){const details=el('details');details.append(el('summary','코드 변경 내용'+(data.diff_truncated?' · 앞부분 16,000자':'')),el('pre',data.diff));host.append(details);}if(data.available)host.dataset.loaded='1';
  }catch(e){host.replaceChildren(el('p','실행 근거 조회 실패 · '+e.message,'form-error'));}
  finally{button.disabled=false;}
}

function paintWorkflow(){
  const selected=$('brief-workflow').value||'auto',entry=workflowCatalog.find(w=>w.id===selected),box=$('workflow-preview');box.replaceChildren();
  if(!entry){box.append(el('p','개발 방식 목록을 확인하고 있습니다.'));return;}
  box.append(el('p',entry.description));if(entry.checklist.length){const list=el('ol');for(const item of entry.checklist)list.append(el('li',item));box.append(list);}box.append(el('small','계획·구현·검수에 전달할 지침이며, 실제 완료는 실행 결과로 확인합니다.'));
}
function workflowCard(entry){
  const b=el('button','','workflow-card');b.type='button';b.dataset.workflow=entry.id;b.append(el('b',entry.title),el('p',entry.description));const list=el('ul');for(const item of entry.checklist)list.append(el('li',item));if(list.children.length)b.append(list);b.append(el('small','이 방식으로 요청 준비 →'));b.onclick=()=>{if($('workflow-dialog').open)$('workflow-dialog').close();openBrief();preferredWorkflow=entry.id;$('brief-workflow').value=entry.id;paintWorkflow();saveBrief();};return b;
}
async function loadWorkflows(){
  try{const data=await json('/ops/workflows');workflowCatalog=data.workflows;const select=$('brief-workflow');select.replaceChildren();for(const entry of workflowCatalog){const o=el('option',entry.title);o.value=entry.id;select.append(o);}select.value=workflowCatalog.some(w=>w.id===preferredWorkflow)?preferredWorkflow:'auto';
    $('workflow-cards').replaceChildren(...['bugfix','test_focus','security'].map(id=>workflowCard(workflowCatalog.find(w=>w.id===id))));$('workflow-library-cards').replaceChildren(...workflowCatalog.map(workflowCard));paintWorkflow();}
  catch(e){$('workflow-cards').replaceChildren(el('p','개발 방식 목록을 읽지 못했습니다. 서버 재시작 후 다시 확인하세요.','muted'));}
}
async function loadProjectMemory(){
  const path=currentProject,seq=++memorySeq,box=$('memory-content');if(!path){box.replaceChildren(el('p','먼저 프로젝트를 선택하세요.'));return;}box.replaceChildren(el('p','검증 완료 기록을 읽고 있습니다…'));
  try{const data=await json('/ops/project-memory?'+new URLSearchParams({path}));if(seq!==memorySeq||path!==currentProject)return;box.replaceChildren();const d=data.discovery;box.append(el('p',(d.stack.length?d.stack.join(' · ')+' · ':'')+'문맥 파일 '+d.listed_files+'개 선택'+(d.truncated?' · 탐색 상한 도달':'')));
    if(!data.history.length)box.append(el('p','테스트와 독립 검수가 통과한 완료 기록이 아직 없습니다.'));for(const record of data.history){const row=el('article','','memory-record');row.append(el('strong',record.goal),el('small',record.mission_id+' · 테스트 '+record.tests.passed+'/'+record.tests.total+' · 검수 '+record.review));if(record.summary)row.append(el('p',record.summary));box.append(row);}box.append(el('p','같은 프로젝트의 완료 기록을 최대 3건 참조합니다. 과거 기록은 참고 자료로 다룹니다.'));}
  catch(e){if(seq===memorySeq)box.replaceChildren(el('p','기록 조회 실패 · '+e.message,'form-error'));}
}

function init(){
  for(const b of document.querySelectorAll('[data-status]'))b.onclick=()=>{clearTimeout(searchTimer);query=$('search').value.trim();filter=b.dataset.status;page=1;updateFilters();loadList();};
  $('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{query=$('search').value.trim();page=1;loadList();},250);};
  $('previous').onclick=()=>{if(page>1){page--;loadList();}};$('next').onclick=()=>{if(page<pages){page++;loadList();}};
  $('refresh').onclick=()=>{loadList();loadStatus();if(currentDetail&&$('detail-dialog').open)openDetail(currentDetail.mission.mission_id,true);};
  $('new-mission').onclick=openBrief;$('empty-action').onclick=openBrief;
  $('choose-project').onclick=openProjects;$('brief-choose-project').onclick=openProjects;$('project-form').onsubmit=selectProject;$('browse-project').onclick=browseProject;
  $('launch-mission').onclick=launchMission;$('brief-profile').onchange=saveBrief;
  $('brief-workflow').onchange=()=>{preferredWorkflow=$('brief-workflow').value;paintWorkflow();saveBrief();};$('brief-use-memory').onchange=saveBrief;
  $('workflow-library').onclick=()=>showDialog('workflow-dialog');$('memory-preview').addEventListener('toggle',()=>{if($('memory-preview').open)loadProjectMemory();});
  for(const b of document.querySelectorAll('.close-dialog'))b.onclick=()=>b.closest('dialog').close();
  for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
  $('detail-dialog').addEventListener('close',()=>{detailSeq++;currentDetail=null;});
  $('brief-form').onsubmit=prepareDraft;
  for(const name of ['goal','criteria','scope'])$('brief-'+name).addEventListener('input',()=>{saveBrief();$('brief-error').hidden=briefAvailable;if(!briefAvailable)$('brief-error').textContent='브라우저 저장소를 사용할 수 없어 초안을 자동 보관하지 못했습니다.';});
  for(const b of document.querySelectorAll('[data-template]'))b.onclick=()=>{if(['goal','criteria','scope'].some(k=>$('brief-'+k).value.trim())&&!confirm('작성 중인 양식을 예시로 바꿀까요?'))return;const t=TEMPLATES[b.dataset.template];for(const k of ['goal','criteria','scope'])$('brief-'+k).value=t[k];saveBrief();$('brief-goal').focus();$('brief-goal').select();};
  $('clear-brief').onclick=()=>{if(!confirm('이 양식의 초안을 지울까요?'))return;for(const k of ['goal','criteria','scope'])$('brief-'+k).value='';saveBrief();$('brief-goal').focus();};
  $('export-report').onclick=downloadReport;
  document.addEventListener('keydown',e=>{if(e.key==='/'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!e.target.closest('input,textarea,[contenteditable]')&&!document.querySelector('dialog[open]')){e.preventDefault();$('search').focus();}});
  loadList();loadStatus();loadWorkflows();
  if(location.hash==='#new')openBrief();
  const pending=storageRead(LAUNCH_KEY);if(pending?.payload&&typeof pending.payload.request_id==='string'){launchRecord=pending;if(pending.receipt&&pending.receipt.state!=='planning'&&pending.receipt.state!=='unknown')renderLaunch(pending.receipt);else{renderLaunch({request_id:pending.payload.request_id,state:'planning'});pollLaunch();}}
  setInterval(()=>{if(!document.hidden){loadStatus();if(!document.querySelector('dialog[open]')&&!$('mission-list').contains(document.activeElement)&&document.activeElement!==$('search'))loadList();}},15000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){loadStatus();loadList();}});
}
init();
})();
