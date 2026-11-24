'use strict';
// Shared within the office page. All saved fields are data; rendered values never become HTML.
window.OfficeTeamEditor=function({readJSON,onSaved,getProject=()=>''}){
 const $=id=>document.getElementById(id);
 let catalogue=null,draft=null,revision=null,dirty=false,saving=false,recommending=false,proposal=null,proposalFingerprint='',applied=new Set();
 function invalidateRecommendations(){$('team-game-checks').replaceChildren();proposal=null;applied.clear();$('team-recommend-all').hidden=true;$('team-recommend-results').replaceChildren();$('team-recommend-summary').textContent='직원 구성이나 예정 업무를 바꾸면 다시 추천받으세요.';}
 function renderRecommendations(){
  if(!proposal)return;
  const summary=proposal.summary,remaining=proposal.suggestions.filter(s=>!applied.has(s.id));
  $('team-recommend-summary').textContent=`기존 ${summary.existing_members}명 · 미완료 미션 ${summary.active_missions}건 · 채용 ${summary.proposed_hires}명 · 과장 지정 ${summary.proposed_promotions}건. `+(applied.size?'추가한 내용은 아직 편집안입니다. 아래 팀 설정 저장을 눌러 적용하세요.':'추천 이유를 확인하고 개별 추가 또는 추천 팀 전체 추가를 선택하세요.');
  const host=$('team-recommend-results');host.replaceChildren();
  if(proposal.department_plan)renderDepartments(host,proposal.department_plan);
  for(const item of proposal.suggestions){
   const card=document.createElement('article');card.className='team-recommend-card';card.dataset.suggestion=item.id;
   const title=document.createElement('strong');title.textContent=(item.kind==='promote'?'과장 지정 · ':'채용 · ')+item.member.name;
   const roles=document.createElement('p');roles.textContent=[catalogue.specialties[item.member.specialty],catalogue.slots[item.member.slot],catalogue.departments[item.member.department],catalogue.positions[item.member.position]].join(' · ');
   const reason=document.createElement('p');reason.textContent=item.reason+(item.related_tasks?.length?' 관련 업무: '+item.related_tasks.join(' / '):'')+(item.depends_on.some(id=>!applied.has(id))?' 부서 과장 제안도 함께 추가됩니다.':'');
   const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=applied.has(item.id)?'편집안에 추가됨':'이 제안 추가';button.disabled=applied.has(item.id)||saving||recommending;button.onclick=()=>applySuggestions([item.id]);card.append(title,roles,reason,button);host.append(card);
  }
  for(const text of [...proposal.blocked,...(proposal.missing_managers?.length?['과장 지정이 필요한 부서: '+proposal.missing_managers.join(', ')]:[]),...(proposal.missing_slots.length?['아직 필요한 업무 영역: '+proposal.missing_slots.join(', ')]:[]),proposal.basis,proposal.notice]){const p=document.createElement('p');p.className='team-recommend-warning';p.textContent=text;host.append(p);}
  if(!proposal.suggestions.length){const p=document.createElement('p');p.textContent=proposal.blocked.length?'정원 때문에 추가 채용을 제안하지 못했습니다.':'현재 업무와 직원 구성을 기준으로 추가 채용이 필요하지 않습니다.';host.prepend(p);}
  $('team-recommend-all').hidden=!remaining.length;$('team-recommend-all').disabled=saving||recommending;
 }
 function applySuggestions(ids){
  if(saving||recommending||!proposal)return;
  if(proposalFingerprint!==JSON.stringify(draft.members)){invalidateRecommendations();return;}
  const selected=new Set();
  function include(id){if(applied.has(id)||selected.has(id))return;const item=proposal.suggestions.find(s=>s.id===id);if(!item)return;selected.add(id);item.depends_on.forEach(include);}
  ids.forEach(include);
  for(const item of proposal.suggestions.filter(s=>selected.has(s.id))){
   if(item.kind==='promote'){const member=draft.members.find(m=>m.id===item.member.id);if(member)member.position='manager';}
   else if(!draft.members.some(m=>m.id===item.member.id))draft.members.push(JSON.parse(JSON.stringify(item.member)));
   applied.add(item.id);
  }
  dirty=true;if(proposal.prepared_team?.active_staff_ids&&applied.size===proposal.suggestions.length)draft.active_staff_ids=[...proposal.prepared_team.active_staff_ids];else delete draft.active_staff_ids;message('');render();proposalFingerprint=JSON.stringify(draft.members);renderRecommendations();
 }
 $('team-recommend').onclick=async()=>{
  if(saving||recommending)return;
  const project=$('team-recommend-scope').value==='project'?getProject():'';
  if($('team-recommend-scope').value==='project'&&!project){message('현재 프로젝트가 없습니다. 미션 센터에서 프로젝트를 선택하거나 회사 전체 범위를 선택하세요.');return;}
  recommending=true;invalidateRecommendations();message('');$('team-recommend-summary').textContent='현재 직원과 미완료 업무를 분석하고 있습니다.';
  for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=true;
  try{const roles=await request('/ops/roles');proposal=await request('/ops/team/recommendations',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify({team:draft,expected_revision:revision,goal:$('team-recommend-goal').value,project_path:project||'',policy:$('team-recommend-policy').value})});proposalFingerprint=JSON.stringify(draft.members);}
  catch(error){$('team-recommend-summary').textContent='추천을 불러오지 못했습니다.';message(error.message);}
  finally{recommending=false;for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=false;$('team-add').disabled=draft.members.length>=catalogue.max_members;renderRecommendations();}
 };
 function renderDepartments(host,plan){
  const list=document.createElement('ul');list.className='game-department-plan';
  for(const row of plan){const li=document.createElement('li');li.textContent=`${row.name} · 업무 배정 ${row.assigned??row.target}명 / 재직 ${row.actual}명 · 관련 업무 ${row.tasks}건 / 미완료 단계 ${row.pending_steps}건`+(row.retained_extra?' · 기존 인원 유지':'');list.append(li);}host.append(list);
 }
 function showGameReadiness(value,plan){
  const host=$('team-game-checks');host.replaceChildren();const title=document.createElement('h3');title.textContent='게임 개발팀 저장 완료 · 실행 준비 점검';host.append(title);renderDepartments(host,plan);
  const labels={READY:'준비됨',CONFIGURED_NOT_AUTHENTICATED:'연결 도구 확인 · 로그인/할당량 미검증',ACTION_REQUIRED:'설정 필요',DETECTED_NOT_EXECUTED:'프로젝트 감지 · 실행 미검증',NOT_VERIFIED:'실제 PC 검증 필요',REQUIRES_MCP:'도구 제공 · AI 클라이언트 MCP 등록 필요'};
  const list=document.createElement('ul');for(const check of value.checks){const li=document.createElement('li');li.textContent=check.title+' — '+(labels[check.status]||check.status);list.append(li);}host.append(list);
  const note=document.createElement('p');note.className='team-recommend-warning';note.textContent=value.notice;host.append(note);
  for(const [href,label] of [['/settings','AI 연결 설정'],['/setup','PC 도구 점검']]){const a=document.createElement('a');a.href=href;a.className='secondary';a.textContent=label;host.append(a);}
  const start=document.createElement('button');start.type='button';start.className='primary';start.id='team-game-start';start.textContent='게임 개발 지시서로 이동';start.onclick=()=>{
   try{const prior=JSON.parse(localStorage.getItem('director.mission.brief.v1')||'{}');const brief={...value.starter_brief,...prior,workflow_id:'game'};for(const key of ['goal','criteria','scope'])if(typeof brief[key]!=='string'||!brief[key].trim())brief[key]=value.starter_brief[key];localStorage.setItem('director.mission.brief.v1',JSON.stringify(brief));location.assign('/missions#new');}catch(e){message('지시서를 보관하지 못했습니다. 미션 센터에서 게임 개발 방식을 선택하세요.');}
  };host.append(start);
 }
 $('team-game-ready').onclick=async()=>{
  if(saving||recommending)return;
  const project=$('team-recommend-scope').value==='project'?getProject():'';
  if($('team-recommend-scope').value==='project'&&!project){message('현재 프로젝트가 없습니다. 회사 전체 범위를 선택하거나 미션 센터에서 프로젝트를 선택하세요.');return;}
  recommending=true;invalidateRecommendations();message('');$('team-recommend-summary').textContent='전 부서 각 4명, 총 28명으로 채우고 업무 배정 1~2명을 계산해 저장합니다.';
  for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=true;
  try{const roles=await request('/ops/roles');const result=await request('/ops/team/game-ready',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify({team:draft,expected_revision:revision,goal:$('team-recommend-goal').value,project_path:project||'',game_project_path:getProject()||''})});
   draft=JSON.parse(JSON.stringify(result.team));revision=draft.revision;dirty=false;render();onSaved(result.team,result.message);$('team-recommend-summary').textContent=result.message;showGameReadiness(result.readiness,result.department_plan);
  }catch(error){$('team-recommend-summary').textContent='자동 구성을 저장하지 못했습니다.';message(error.message);}
  finally{recommending=false;for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=false;$('team-add').disabled=draft.members.length>=catalogue.max_members;}
 };
 $('team-recommend-all').onclick=()=>{if(proposal)applySuggestions(proposal.suggestions.map(s=>s.id));};
 for(const id of ['team-recommend-goal','team-recommend-scope','team-recommend-policy'])$(id).addEventListener('input',invalidateRecommendations);
 async function request(url,options){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);try{return await readJSON(url,options,controller.signal);}catch(error){if(error.name==='AbortError')throw Error('서버 응답 시간이 초과됐습니다. 서버 설정을 다시 불러와 저장 여부를 확인하세요.');throw error;}finally{clearTimeout(timer);}}
 function message(value){$('team-error').hidden=!value;$('team-error').textContent=value||'';if(value&&$('team-dialog').open)$('team-error').scrollIntoView({block:'nearest'});}
 function field(tag,label,value,member,key,options){
  const wrapper=document.createElement('label');wrapper.className='team-field';const title=document.createElement('span');title.textContent=label;
  const input=document.createElement(tag);input.dataset.field=key;
  if(options)for(const [id,text] of Object.entries(options)){const option=document.createElement('option');option.value=id;option.textContent=text;input.append(option);}
  input.value=value;input.required=true;
  if(key==='name')input.maxLength=24;if(key==='age'){input.type='number';input.min=18;input.max=100;input.step=1;}if(key==='duties'){input.maxLength=400;input.rows=2;}
  input.addEventListener('input',()=>{member[key]=key==='age'?Number(input.value):input.value;dirty=true;if(['department','position','slot','specialty'].includes(key))delete draft.active_staff_ids;message('');invalidateRecommendations();});wrapper.append(title,input);return wrapper;
 }
 function render(){
  const list=$('team-members');list.replaceChildren();
  for(const member of draft.members){
   const row=document.createElement('section');row.className='team-member';row.dataset.member=member.id;
   member.department ||= ({planning:'planning',ui:'design',gameplay:'development',level:'level',testing:'testing',quality:'quality',audio:'design',general:'development'}[member.specialty]||'development');member.position ||= (catalogue.default_team.members.some(m=>m.id===member.id)?'manager':'employee');
   const head=document.createElement('div');head.className='team-member-fields';
   head.append(field('input','직원 이름',member.name,member,'name'),field('select','전문 분야',member.specialty,member,'specialty',catalogue.specialties),field('select','업무 영역',member.slot,member,'slot',catalogue.slots));
   head.append(field('select','소속 부서',member.department,member,'department',catalogue.departments),field('select','직급',member.position,member,'position',catalogue.positions));
   const remove=document.createElement('button');remove.type='button';remove.className='team-remove';remove.textContent='삭제';remove.setAttribute('aria-label',member.name+' 삭제');remove.disabled=false;
   remove.onclick=()=>{draft.members=draft.members.filter(m=>m.id!==member.id);dirty=true;delete draft.active_staff_ids;invalidateRecommendations();render();};
   head.append(remove);row.append(head);if(draft.active_staff_ids){const status=document.createElement('p');status.className='muted';status.textContent=draft.active_staff_ids.includes(member.id)?'다음 미션 업무 배정 대상':'지원·대기 직원 · 재직 유지';row.append(status);}
   if(!member.character)member.character={gender:'male',age:30,color:'mint'};
   const character=document.createElement('div');character.className='staff-character-fields';const preview=document.createElement('div');preview.className='staff-avatar-preview';window.OfficeCharacters.preview(preview,member.character);
   character.append(preview,field('select','성별',member.character.gender,member.character,'gender',{male:'남성',female:'여성'}),field('input','나이',member.character.age,member.character,'age'),field('select','외형 프리셋',member.character.color,member.character,'color',{mint:'민트 · 시티 러너',blue:'블루 · 나이트 코더',violet:'바이올렛 · 실버 노트',coral:'코랄 · 레드 라인',gold:'골드 · 골든 아워'}));
   const presets=document.createElement('details');presets.className='staff-preset-chooser';const summary=document.createElement('summary');summary.textContent='얼굴·헤어·눈 프리셋 고르기';const gallery=document.createElement('div');presets.append(summary,gallery);
   function refresh(){window.OfficeCharacters.preview(preview,member.character);window.OfficeCharacters.presets(gallery,member.character,color=>{member.character.color=color;character.querySelector('[data-field=color]').value=color;dirty=true;invalidateRecommendations();message('');refresh();});}
   const note=document.createElement('p');note.className='preset-note';note.textContent='성별별 5종 · 얼굴·헤어·눈·의상이 함께 바뀌는 완성형 프리셋입니다. 코지 픽셀 모드에서 대응하는 픽셀 외형을 함께 볼 수 있습니다.';presets.append(note);
   character.addEventListener('input',refresh);refresh();row.append(character,presets,field('textarea','담당 직무',member.duties,member,'duties'));list.append(row);
  }
  $('team-count').textContent=draft.members.length+' / '+catalogue.max_members+'명 · '+(['HEAD','BUILDER','REVIEWER'].every(slot=>draft.members.some(m=>m.slot===slot))?'개발팀 구성 완료':'기획·구현·검수 담당 채용 필요');$('team-add').disabled=draft.members.length>=catalogue.max_members||saving;
 }
 async function reload(){
  if(dirty&&!confirm('작성 중인 팀 설정을 서버의 설정으로 바꿀까요?'))return;
  try{catalogue=await request('/ops/team');draft=JSON.parse(JSON.stringify(catalogue.team));revision=catalogue.team.revision;dirty=false;invalidateRecommendations();message('');render();}catch(error){message(error.message);}
 }
 async function open(){
  if(saving||recommending)return;
  try{catalogue=await request('/ops/team');draft=JSON.parse(JSON.stringify(catalogue.team));revision=draft.revision;dirty=false;invalidateRecommendations();message('');render();$('team-dialog').showModal();}catch(error){onSaved(null,error.message);}
 }
 $('team-add').onclick=()=>{if(draft.members.length>=catalogue.max_members)return;draft.members.push({id:'staff_'+crypto.randomUUID().replaceAll('-','').slice(0,20),name:'새 직원',department:'development',position:draft.members.some(m=>m.department==='development'&&m.position==='manager')?'employee':'manager',slot:'BUILDER',specialty:'general',duties:'이 직원이 맡을 작업과 완료 조건을 구체적으로 작성하세요.',character:{gender:'male',age:30,color:'mint'}});dirty=true;delete draft.active_staff_ids;invalidateRecommendations();render();$('team-members').lastElementChild.querySelector('input').focus();};
 $('team-default').onclick=()=>{if(!confirm('편집 중인 구성을 기본 게임 개발팀 6명으로 바꿀까요? 저장 버튼을 눌러야 적용됩니다.'))return;draft=JSON.parse(JSON.stringify(catalogue.default_team));dirty=true;delete draft.active_staff_ids;invalidateRecommendations();message('');render();};
 $('team-reload').onclick=reload;
 $('team-form').onsubmit=async event=>{
  event.preventDefault();if(saving||recommending)return;saving=true;for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=true;$('team-save').disabled=true;$('team-close').disabled=true;$('team-default').disabled=true;$('team-reload').disabled=true;message('');
  try{const roles=await request('/ops/roles');const result=await request('/ops/team',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify({team:draft,expected_revision:revision})});dirty=false;revision=result.team.revision;$('team-dialog').close();onSaved(result.team,result.message);}
  catch(error){message(error.message);}
  finally{saving=false;for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=false;$('team-save').disabled=false;$('team-close').disabled=false;$('team-default').disabled=false;$('team-reload').disabled=false;render();renderRecommendations();}
 };
 function close(event){if(saving||recommending){event?.preventDefault();return;}if(dirty&&!confirm('저장하지 않은 팀 설정을 닫을까요?')){event?.preventDefault();return;}$('team-dialog').close();}
 $('team-close').onclick=()=>close();$('team-dialog').addEventListener('cancel',close);
 return {open};
};
