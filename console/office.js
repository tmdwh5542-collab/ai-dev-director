'use strict';
(function(){
const $=id=>document.getElementById(id);
const AI={ANTHROPIC:'Claude',GOOGLE:'Google',OPENAI:'Codex'};
const providerName=p=>data?.provider_names?.[p]||AI[p]||p;
const DOMAIN={claude:'ANTHROPIC',antigravity:'GOOGLE',openai:'OPENAI'};
const TEMPLATES={
 CEO:{title:'대표실 · 대표님',name:'대표 · 사용자',symbol:'C',color:'#e5c58e',x:540,y:196,purpose:'만들고 싶은 것과 완료 조건을 정합니다.',detail:'업무 지시서를 준비하고 프로젝트·완료 조건을 확인한 뒤 미션을 시작하세요. 예산과 중요한 결정은 미션 기록에서 확인할 수 있습니다.'},
 HEAD:{title:'기획실 · 개발 이사',name:'기획 · 개발 이사',symbol:'H',color:'#ffc394',x:290,y:334,purpose:'목표를 분석하고 일을 나눠 개발 지시서를 만듭니다.',detail:'HEAD 역할입니다. 계획을 세우고 수정 방향과 다음 단계를 판단합니다. 현재 호출 중이면 실제 호출의 AI를 표시합니다.'},
 BUILDER:{title:'개발실 · 개발 담당',name:'구현 · 개발자',symbol:'B',color:'#89dfca',x:790,y:334,purpose:'지시서에 맞춰 코드·씬·리소스를 구현합니다.',detail:'BUILDER 역할입니다. 허용된 파일 범위에서 격리 작업 폴더를 수정합니다. 완료 여부는 테스트와 독립 검수 뒤에 결정됩니다.'},
 DIRECTOR:{title:'테스트실 · 운영 감독',name:'테스트 · 감독관',symbol:'D',color:'#8dbbff',x:540,y:360,purpose:'설정된 빌드와 동작 테스트를 실행해 증거를 남깁니다.',detail:'프로그램의 검증 단계입니다. AI 호출과 별도로 동작하며, 화면에는 연결된 미션의 VERIFYING 상태를 표시합니다. 실제 통과 결과는 미션의 검증 기록에서 확인하세요.'},
 REVIEWER:{title:'품질실 · 검수 담당',name:'검수 · 품질 담당',symbol:'R',color:'#c5b1ff',x:540,y:492,purpose:'변경 내용을 독립적으로 살펴보고 결함을 찾습니다.',detail:'REVIEWER 역할입니다. 요구사항·부작용·검증 근거를 확인합니다. 구현 담당의 자체 성공 보고만으로 통과하지 않습니다.'}
};
let DEPTS={CEO:{...TEMPLATES.CEO,x:390,y:210,scale:.8}};
const STAFF_POSITIONS=[[245,235],[550,235],[245,445],[550,445]];
const SPECIALTY_COLORS={planning:'#ffc394',gameplay:'#89dfca',ui:'#89cfff',level:'#b8d894',testing:'#f1ce82',quality:'#c5b1ff',audio:'#efa5bd',general:'#b5c4d6'};
let teamRevision=null,visibleTeam=null,setupShown=false,departmentFilter='ceo';
try{departmentFilter=localStorage.getItem('director.office.room')||'ceo';}catch(e){}
window.OfficeRoom=departmentFilter;

const STAGES={HERMES_ADVISORY:'Hermes 자료 분석·보고 중',MEETING_DISCUSSION:'회의 의견 검토 중',MEETING_SYNTHESIS:'회의 안건 종합 중',MEETING_REVIEW:'회의 독립 검토 중',CHAT:'요청 확인 중',MISSION_PLANNING:'다음 단계 계획 중',PLANNING:'지시서 작성 중',ORDER_READY:'구현 준비 중',BUILDING:'코드·리소스 구현 중',VERIFYING:'검증 단계',REVIEWING:'독립 검수 중',DECIDING:'결과 판단 중'};
const STATUS={RUNNING:'진행 중',DONE:'완료',FAILED:'실패',BLOCKED:'확인 필요',STOPPED:'중단',INCOMPLETE:'예산 소진'};
let data=null,selected='planner',connected=false,polling=false,stopped=false,token=null,lastSuccess=0,nextPollAt=0,pollFailures=0;
const svgNS='http://www.w3.org/2000/svg';
function text(id,value){const node=$(id);value=String(value??'—');if(node.textContent!==value)node.textContent=value;}
function element(tag,value,cls){const n=document.createElement(tag);if(value!=null)n.textContent=String(value);if(cls)n.className=cls;return n;}
function clock(sec){sec=Math.max(0,Math.floor(Number(sec)||0));return sec<60?sec+'초':sec<3600?Math.floor(sec/60)+'분 '+sec%60+'초':Math.floor(sec/3600)+'시간 '+Math.floor(sec%3600/60)+'분';}
function tokenText(total){if(!total)return '—';const value=Number(total.tokens||0);if(!value&&total.unknown_calls)return '미기록';return (Number(total.exact_tokens||0)<value?'~':'')+value.toLocaleString('ko-KR')+(total.unknown_calls?' + 미기록':'');}
function time(iso){if(!iso)return null;const date=new Date(iso+(/Z|[+-]\d\d:\d\d$/.test(iso)?'':'Z'));return Number.isFinite(date.getTime())?date:null;}
function stamp(iso){const date=time(iso);return date?new Intl.DateTimeFormat('ko-KR',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date):'—';}
function createStation(role){
 const d=DEPTS[role],g=document.createElementNS(svgNS,'g');g.id='station-'+role;g.classList.add('workstation');g.setAttribute('role','button');g.setAttribute('tabindex','0');g.setAttribute('aria-label',d.title+' 상세');g.setAttribute('aria-pressed','false');g.setAttribute('transform',`translate(${d.x} ${d.y}) scale(${d.scale||1})`);if(d.memberId)g.classList.add('staff-member');g.style.setProperty('--accent',d.color);g.dataset.busy='false';g.dataset.meetingParticipant=String(!!d.meetingSeat);
 // These SVG strings contain only static, locally defined geometry. API/user text is assigned with textContent below.
 g.innerHTML=`<rect class="selection" x="-112" y="-85" width="224" height="185" rx="6"/>
 <rect class="desk-rug" x="-110" y="-72" width="220" height="156" rx="8" fill="#c5d5dd" opacity=".38"/>
 <rect x="-85" y="-26" width="180" height="73" rx="5" fill="#a8b7c1" opacity=".3"/>
 <path d="M-75 25V56M74 25V56" stroke="#7b909d" stroke-width="7"/>
 <rect class="modern-desktop" x="-90" y="-44" width="180" height="78" rx="5" fill="#f7fafc" stroke="#9aaebc" stroke-width="3"/>
 <path d="M-85 28H85" stroke="#dae3e8" stroke-width="5"/>
 <path d="M0-22V-9M-16-8H16" stroke="#4b6474" stroke-width="5"/>
 <rect x="-49" y="-83" width="98" height="60" rx="4" fill="#314c5d" stroke="#243e4e" stroke-width="3"/>
 <rect class="monitor-light" x="-42" y="-76" width="84" height="46" rx="2" fill="#79c7d6"/>
 <path class="screen-line" d="M-34-65H15M-34-55H30M-34-45H0" stroke="#c8eff0" stroke-width="3"/>
 <rect x="-39" y="1" width="68" height="16" rx="3" fill="#c9d7df"/><path d="M-31 6H20M-26 11H13" stroke="#95aab6" stroke-width="2"/>
 <rect x="42" y="-2" width="13" height="20" rx="6" fill="#dae5ea" stroke="#a4b8c3" stroke-width="2"/>
 <rect x="-76" y="-25" width="19" height="22" rx="3" fill="#6e9686"/><path d="M-66-25V-43M-66-34L-77-42M-66-31L-56-43" stroke="#649e7a" stroke-width="5"/>
 <circle class="led" cx="73" cy="18" r="3"/>
 <rect class="office-chair" x="-17" y="49" width="40" height="27" rx="7" fill="#536d80" stroke="#3c5669" stroke-width="3"/><path d="M3 77V85M-9 87H15" stroke="#536d80" stroke-width="4"/>
 <g transform="translate(0 115)"><text class="staff-name" y="4"></text><text class="staff-state" y="21"></text></g>`;
 if(d.visitReason&&!d.visitReason.includes('협업'))g.innerHTML='<rect class="selection" x="-32" y="-35" width="64" height="98"/><circle class="led" cx="0" cy="0" r="0"/><g><text class="staff-name"></text><text class="staff-state"></text></g>';
 if(role==='DIRECTOR')g.innerHTML='<rect class="selection" x="-75" y="-65" width="150" height="165"/><rect x="-45" y="-65" width="90" height="100" fill="#557489" stroke="#72645b" stroke-width="4"/><path d="M-30-45H25M-30-25H25M-30-5H25" stroke="#c2d8d4" stroke-width="8"/><circle class="led" cx="30" cy="20" r="4"/><g transform="translate(0 70)"><text class="staff-name" y="0"></text><text class="staff-state" y="18"></text></g>';
 g.lastElementChild.classList.add('station-caption');
 const badge=document.createElementNS(svgNS,'rect');badge.classList.add('desk-nametag');for(const [key,value] of Object.entries({x:-80,y:-13,width:160,height:43,rx:6}))badge.setAttribute(key,value);g.lastElementChild.insertBefore(badge,g.lastElementChild.firstChild);
 if(d.memberId){g.lastElementChild.setAttribute('transform','translate(0 85)');}
 g.querySelector('.staff-name').textContent=d.name.length>14?d.name.slice(0,13)+'…':d.name;g.querySelector('.staff-state').textContent=role==='CEO'?'목표와 완료 조건 결정':'연결 중';
 g.addEventListener('click',()=>select(role));g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(role);}});$('stations').append(g);window.OfficeFurniture?.station(g,!(d.visitReason&&!d.visitReason.includes('협업')));
}
function liveJobs(){return connected?(data?.activity.working_now||[]):[];}
function focusMission(){const activity=data?.activity;return activity?(activity.missions||[]).find(m=>m.mission_id===activity.focus_mission_id)||null:null;}
function verificationStage(){
 const run=data?.status.run,mission=focusMission();
 return connected&&mission?.live&&run?.state==='VERIFYING'&&(mission.steps||[]).some(step=>step.run_id===run.run_id);
}
function staffJobs(key){const d=DEPTS[key];return d?.memberId?liveJobs().filter(w=>w.staff_id===d.memberId&&w.role===d.slot&&w.staff_team_revision===visibleTeam?.revision):[];}
function assignment(key){
 const d=DEPTS[key],actual=staffJobs(key),assigned=DOMAIN[data?.roles.roles?.[{HEAD:'head',BUILDER:'builder',REVIEWER:'reviewer'}[d?.slot]]];
 return actual.length?[...new Set(actual.map(w=>w.provider))]:assigned?[assigned]:[];
}
function renderTeam(){
 const mission=focusMission(),current=data?.team?.team;
 const captured=mission?.live&&mission.staff_team?.members?mission.staff_team:null;
 const team=captured||current;if(!team)return;const owner=data?.company?.company?.owner;
 window.OfficeRoom=departmentFilter;companyEditor.apply(data.company);document.body.classList.toggle('company-setup-required',!owner);
 visibleTeam=team;
 text('team-summary','팀 '+team.members.length+'명');
 text('team-note',captured&&current&&captured.revision!==current.revision?'진행 중인 미션은 시작할 때의 '+team.members.length+'명 팀을 사용합니다. 저장한 '+current.members.length+'명 팀은 새 미션부터 적용됩니다.':'직무에 맞는 직원이 순서대로 일합니다. 팀 설정은 다음 미션부터 적용됩니다.');
 const visualRevision=team.revision+data.company.revision+departmentFilter+JSON.stringify(data.visitors||[]);if(teamRevision===visualRevision)return;teamRevision=visualRevision;
 if(!['ceo',...Object.keys(data.team.departments||{})].includes(departmentFilter))departmentFilter='ceo';
 window.OfficeRoom=departmentFilter;
 DEPTS={CEO:{...TEMPLATES.CEO,name:owner?.name||'대표 · 사용자',title:owner?owner.name+' · 대표':'대표 캐릭터 만들기',x:390,y:departmentFilter==='ceo'?210:175,scale:.8}};
 if(departmentFilter==='testing')DEPTS.DIRECTOR={...TEMPLATES.DIRECTOR,x:670,y:490,scale:.7};
 const departmentOf=m=>m.department||({planning:'planning',ui:'design',gameplay:'development',level:'level',testing:'testing',quality:'quality',audio:'design',general:'development'}[m.specialty]||'development');
 const positionOf=m=>m.position||(data.team.default_team.members.some(s=>s.id===m.id)?'manager':'employee');
 const destinations=new Map((data.visitors||[]).filter(v=>v.team_revision===team.revision).map(v=>[v.id,v]));
 const home=m=>positionOf(m)==='secretary'?'ceo':departmentOf(m);
 const visibleMembers=team.members.filter(m=>(destinations.get(m.id)?.room||home(m))===departmentFilter);
 const rooms=[['ceo','대표실 · 비서실'],...Object.entries(data.team.departments||{})];
 function changeRoom(id){departmentFilter=id;window.OfficeRoom=id;try{localStorage.setItem('director.office.room',id);}catch(e){}teamRevision=null;paint();}
 $('room-prev').onclick=()=>changeRoom(rooms[(rooms.findIndex(r=>r[0]===departmentFilter)+rooms.length-1)%rooms.length][0]);
 $('room-next').onclick=()=>changeRoom(rooms[(rooms.findIndex(r=>r[0]===departmentFilter)+1)%rooms.length][0]);
 text('room-name',rooms.find(r=>r[0]===departmentFilter)?.[1]);text('office-title',rooms.find(r=>r[0]===departmentFilter)?.[1]);
 $('department-tabs').replaceChildren();for(const [id,name] of rooms){const button=element('button',name);button.type='button';button.dataset.department=id;button.setAttribute('aria-pressed',String(departmentFilter===id));button.onclick=()=>changeRoom(id);$('department-tabs').append(button);}
 let meetingIndex=0;
 visibleMembers.forEach((member,index)=>{
  const visit=destinations.get(member.id),isMeeting=!!visit&&!visit.reason.includes('협업'),seat=isMeeting?window.OfficeMeetingSeat(meetingIndex++):null;
  const base=TEMPLATES[member.slot],position=seat||(positionOf(member)==='secretary'?[390,485]:visit?[680,470]:STAFF_POSITIONS[index%4]);if(!base||!position)return;
  DEPTS[member.id]={...base,name:member.name,title:member.name+' · '+(data.team.specialties[member.specialty]||member.specialty),purpose:member.duties,
   color:SPECIALTY_COLORS[member.specialty]||'#b5c4d6',x:position[0],y:position[1],scale:.64,character:member.character||{gender:'male',age:30,color:({planning:'gold',gameplay:'mint',ui:'blue',level:'coral',testing:'gold',quality:'violet',audio:'coral',general:'blue'}[member.specialty]||'mint')},slot:member.slot,memberId:member.id,symbol:Array.from(member.name)[0],
   meetingSeat:seat,visitReason:visit?.reason,position:positionOf(member),detail:(data.team.departments?.[departmentOf(member)]||'')+' · '+(data.team.positions?.[positionOf(member)]||'')+' / '+base.detail+' 직무: '+member.duties};
 });
 if(visibleMembers.some(m=>destinations.get(m.id)?.reason.includes('임원')))DEPTS.CEO.meetingSeat=[885,310];
 $('stations').replaceChildren();$('staff-selector').replaceChildren();
 for(const member of team.members){const button=element('button',member.name);button.type='button';button.dataset.staff=member.id;button.setAttribute('aria-pressed','false');button.onclick=()=>select(member.id);$('staff-selector').append(button);}
 // Draw back-to-front so furniture and people keep the correct perspective.
 Object.keys(DEPTS).sort((a,b)=>DEPTS[a].y-DEPTS[b].y).forEach(createStation);
 const paths=$('staff-routes');paths.replaceChildren();
 for(const [key,d] of Object.entries(DEPTS))if(d.memberId){const path=document.createElementNS(svgNS,'path');path.classList.add('staff-route');path.dataset.staff=key;paths.append(path);}
 for(const id of ['route-director','route-return']){const path=document.createElementNS(svgNS,'path');path.id=id;paths.append(path);}
 if(!DEPTS[selected])selected=visibleMembers.find(m=>m.slot==='HEAD')?.id||visibleMembers[0]?.id||'CEO';select(selected);
 if(!team.members.length)text('team-note','대표님 혼자 시작했습니다. 직원 채용·편집에서 기획·구현·독립 검수 담당을 만들어 개발팀을 구성하세요.');
}
function worker(key){
 const d=DEPTS[key];
 if(key==='CEO')return {provider:'사용자',state:'업무 결정',task:'목표와 완료 조건을 정해주세요.',busy:false};
 if(!connected)return {provider:key==='DIRECTOR'?'AI DEV DIRECTOR':assignment(key).map(providerName).join(' · ')||'미확인',state:stopped?'시스템 중지됨':'연결 확인 필요',task:'작업 상태를 확인할 수 없습니다. 연결 복구 후 다시 확인합니다.',busy:false};
 if(key==='DIRECTOR')return {provider:'AI DEV DIRECTOR',state:verificationStage()?'검증 단계':'대기',task:verificationStage()?'연결된 미션의 빌드·테스트 검증 단계입니다.':'AI 호출이 끝나면 설정된 검증 절차를 담당합니다.',busy:verificationStage()};
 const jobs=staffJobs(key),providers=assignment(key),health=providers.map(p=>data.status.providers?.[p]?.status);
 return {provider:jobs.some(j=>j.runtime==='hermes-sdk')?'Hermes · '+providers.map(p=>({OPENAI:'OpenAI API',ANTHROPIC:'Claude API',GOOGLE:'Gemini API'}[p]||p)).join(' · '):providers.map(providerName).join(' · ')||'미배정',state:jobs.length?'업무 수행 중':health.some(h=>h==='UNAVAILABLE'||h==='QUOTA_EXHAUSTED')?'AI 상태 확인 필요':'대기',staffName:jobs[0]?.staff_name,
 visitReason:d.visitReason,meeting:!!d.visitReason&&!d.visitReason.includes('협업')||jobs.some(w=>String(w.stage).startsWith('MEETING_')),task:jobs.length?jobs.map(w=>(STAGES[w.stage]||w.stage_ko||w.stage||'AI 호출 중')+' · '+clock(w.elapsed_sec)).join(' / '):'다음 업무를 기다리고 있습니다.',busy:jobs.length>0};
}
function paintRoutes(){
 for(const path of document.querySelectorAll('.staff-route')){const d=DEPTS[path.dataset.staff];path.setAttribute('d',`M${d.x} ${d.y+65}V365H740`);path.classList.toggle('active',connected&&worker(path.dataset.staff).busy);}
}
function select(role){if(!DEPTS[role]){const member=visibleTeam?.members.find(m=>m.id===role);if(member){departmentFilter=[...(data?.visitors||[])].reverse().find(v=>v.id===role&&v.team_revision===visibleTeam.revision)?.room||(member.position==='secretary'?'ceo':member.department||({planning:'planning',ui:'design',gameplay:'development',level:'level',testing:'testing',quality:'quality'}[member.specialty]||'development'));teamRevision=null;selected=role;paint();}return;}selected=role;for(const key of Object.keys(DEPTS)){const node=$('station-'+key);node.classList.toggle('selected',key===role);node.setAttribute('aria-pressed',String(key===role));}for(const button of $('staff-selector').children)button.setAttribute('aria-pressed',String(button.dataset.staff===role));paintDepartment();}
function paintDepartment(){
 const d=DEPTS[selected],w=worker(selected);const appearance=(selected==='CEO'?data?.company?.company?.owner?.character:d.character)||{gender:'male',age:30,color:'gold'};const portraitKey=JSON.stringify([selected,appearance,document.body.dataset.visualMode||'illustrated']);if($('department-portrait').dataset.character!==portraitKey){$('department-portrait').replaceChildren(window.OfficeCharacters.portrait(appearance));$('department-portrait').dataset.character=portraitKey;}text('department-title',w.staffName||d.title);text('department-purpose',d.purpose);const profile=selected==='CEO'?data?.company?.company?.owner?.character:d.character; if(profile)text('department-purpose',(profile.gender==='female'?'여성':'남성')+' · '+profile.age+'세 / '+d.purpose);text('department-symbol',d.symbol);$('department-symbol').style.color=d.color;text('department-provider',w.provider);text('department-state',w.state);text('department-task',w.task);text('department-detail',d.detail);
}
function paintLedger(){
 const calls=data?.activity.recent_calls||[],list=$('work-ledger');
 const key=JSON.stringify(calls.slice(0,5));if(list.dataset.content===key)return;list.dataset.content=key;
 const fragment=document.createDocumentFragment();
 for(const call of calls.slice(0,5)){
  const item=element('li'),body=element('div',null,'ledger-content');body.append(element('strong',(call.runtime==='hermes-sdk'?'Hermes · ':'')+({OPENAI:'OpenAI',ANTHROPIC:'Claude',GOOGLE:'Google'}[call.provider]||call.provider||'AI')+' · '+(call.staff_name||TEMPLATES[call.role]?.name||call.role||'역할 미기록')));
  body.append(element('small',(({OK:'호출 완료',RUNNING:'호출 중',FAILED:'호출 실패',ERROR:'오류',TIMEOUT:'시간 초과',INTERRUPTED:'중단됨'}[call.status]||call.status||'상태 미기록'))+' · '+clock(call.seconds)+(call.mission_id?' · '+call.mission_id:'')));
  item.append(element('span',null,'ledger-dot'),body,element('time',stamp(call.at)));fragment.append(item);
 }
 if(!calls.length)fragment.append(element('li','아직 AI 호출 기록이 없습니다. 업무 지시서를 준비해보세요.'));list.replaceChildren(fragment);
}
function paint(){
 renderTeam();
 $('scene').dataset.connected=String(connected);
 let count=0;
 for(const role of Object.keys(DEPTS)){const w=worker(role),node=$('station-'+role);node.dataset.busy=String(w.busy);const name=w.staffName||DEPTS[role].name,label=Array.from(name);const shown=label.length>12?label.slice(0,12).join('')+'…':name;if(node.querySelector('.staff-name').textContent!==shown)node.querySelector('.staff-name').textContent=shown;node.querySelector('.staff-state').textContent=role==='CEO'?'목표와 완료 조건 결정':w.busy?(role==='DIRECTOR'?'검증 단계':w.provider+' · 업무 중'):w.state;if(w.busy)count++;}
 meetings.setContext({project_path:data?.status.project_path,team:data?.team});hermes.setContext({project_path:data?.status.project_path,team:data?.team?.team});
 decor.setContext({room:departmentFilter,revision:data?.layout_revision,connected,stations:DEPTS});
 scene.sync(DEPTS,data?.company?.company?.owner,worker,connected,!!data?.status?.approval?.required,data?.company?.company?.room_themes?.[departmentFilter]||data?.company?.company?.theme,data?.deliveries||[]);window.OfficeRoom=departmentFilter;
 for(const button of $('department-tabs').children){const id=button.dataset.department;if(id==='ceo')continue;const members=visibleTeam?.members.filter(m=>(m.department||({planning:'planning',ui:'design',gameplay:'development',level:'level',testing:'testing',quality:'quality',audio:'design',general:'development'}[m.specialty]||'development'))===id)||[];const active=new Set(liveJobs().filter(j=>j.staff_team_revision===visibleTeam.revision&&members.some(m=>m.id===j.staff_id)).map(j=>j.staff_id)).size;button.textContent=(data?.team?.departments?.[id]||id)+' · '+members.length+'/4'+(active?' · 업무 '+active:'');}
 paintRoutes();
 text('delivery-note',data?.deliveries?.length?'보고 전달: '+[...new Set(data.deliveries.map(d=>d.phase))].join(' · ')+' / 미션·회의 원본 기록을 프로그램이 취합합니다.':'');
 text('activity-chip',!connected?(stopped?'시스템 중지':'연결 확인 중'):count?count+'개 부서 업무 중':liveJobs().length?(liveJobs().some(j=>j.staff_id)?'AI 업무 진행 중 · 다른 사무실':'AI 호출 중 · 직원 미기록'):'다음 업무 대기');$('activity-chip').classList.toggle('active',connected&&count>0);
 text('stat-working',connected?liveJobs().length:'—');const today=data?.activity.usage?.today?.total;
 text('stat-calls',today?Number(today.calls||0).toLocaleString('ko-KR'):'—');text('stat-time',today?clock(today.seconds):'—');text('stat-tokens',tokenText(today));
 const mission=focusMission();text('project-name',data?.status.project_name||'프로젝트 미선택');text('project-path',data?.status.project_path||'미션 센터에서 작업할 폴더를 선택하세요.');
 text('mission-state',mission?(mission.status==='RUNNING'&&!mission.live?'중단됨 · 재개 대기':STATUS[mission.status]||mission.status):'업무 대기');text('mission-goal',mission?.goal||'아직 미션 기록이 없습니다. 첫 업무를 지시해보세요.');paintDepartment();paintLedger();
 text('connection',connected?'실시간 연결':stopped?'중지됨':'연결 확인');$('connection-dot').classList.toggle('online',connected);
}
async function json(url,options={},signal){const r=await fetch(url,{cache:'no-store',...options,signal});const body=await r.json();if(!r.ok||body.error)throw Error(body.error||'서버 응답 '+r.status);return body;}
async function poll(){
 if(polling||stopped)return;polling=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
 try{const payload=await json('/ops/office?team_revision='+encodeURIComponent(data?.team?.team?.revision||'')+'&company_revision='+encodeURIComponent(data?.company?.revision||''),{},controller.signal);
  const {activity,status,roles}=payload,team=payload.team||data?.team,company=payload.company||data?.company;
  if(!Array.isArray(activity?.working_now)||!Array.isArray(team?.team?.members)||!company)throw Error('작업 상태 응답을 확인할 수 없습니다.');
  if(stopped)return;data={...payload,team,company};executive.setRevision(payload.briefing_revision);meetings.setRevision(payload.meeting_revision);hermes.setRevision(payload.hermes_revision);connected=true;lastSuccess=Date.now();pollFailures=0;nextPollAt=lastSuccess+(activity.working_now.length||payload.deliveries?.length||payload.meeting_active||payload.hermes_active?3000:8000);$('office-error').hidden=true;text('last-updated','최근 갱신 '+new Date(lastSuccess).toLocaleTimeString('ko-KR',{hour12:false}));paint();if(!company.company&&!setupShown){setupShown=true;companyEditor.open();}

 }catch(error){pollFailures++;nextPollAt=Date.now()+Math.min(30000,3000*2**Math.min(pollFailures-1,4));if(!stopped){connected=false;$('office-error').hidden=false;text('office-error','서버 연결을 확인하고 있습니다. 표시된 기록은 마지막 수신 내용이며, 현재 업무 상태는 확인되지 않았습니다. '+(error.name==='AbortError'?'응답 시간 초과':error.message));paint();}}
 finally{clearTimeout(timeout);polling=false;}
}
async function control(kind){
 const shutdown=kind==='shutdown';if(!confirm(shutdown?'시스템을 중지할까요? 진행 중인 작업이 중단될 수 있습니다. 기록과 작업본은 유지됩니다.':'진행 중인 미션을 정지할까요? 작업 기록은 유지됩니다.'))return;
 const buttons=shutdown?[$('shutdown'),$('header-shutdown')]:[$(kind)];for(const button of buttons)button.disabled=true;
 try{if(!token||!connected){const roles=await json('/ops/roles');token=roles.csrf;}
  await json(shutdown?'/ops/shutdown':'/ops/missions/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':token},body:JSON.stringify({reason:'회사 사무실에서 작업 정지',by:'사용자'})});
  if(shutdown){stopped=true;connected=false;$('office-error').hidden=false;text('office-error','시스템을 중지했습니다. 재설치하려면 앱 창을 닫은 뒤 설치 파일을 실행하세요.');paint();}else await poll();
 }catch(error){$('office-error').hidden=false;text('office-error','중지 요청을 완료하지 못했습니다. '+error.message);}finally{for(const button of buttons)button.disabled=stopped;}
}
$('office-brief').addEventListener('submit',event=>{
 event.preventDefault();const goal=$('office-goal').value.trim();if(!goal)return;
 try{const previous=JSON.parse(localStorage.getItem('director.mission.brief.v1')||'{}');if(previous.goal&&previous.goal!==goal&&!confirm('미션 센터에 작성 중인 목표가 있습니다. 새 목표로 바꿀까요?'))return;
  localStorage.setItem('director.mission.brief.v1',JSON.stringify({...previous,goal}));localStorage.removeItem('director.office.goal');location.assign('/missions#new');
 }catch(error){$('brief-error').hidden=false;text('brief-error','초안을 보관하지 못했습니다. 내용을 복사해 미션 센터에 붙여 넣어주세요.');}
});
try{$('office-goal').value=localStorage.getItem('director.office.goal')||'';}catch(error){/* Editing still works without local storage. */}
$('office-goal').addEventListener('input',()=>{try{localStorage.setItem('director.office.goal',$('office-goal').value);}catch(error){$('brief-error').hidden=false;text('brief-error','입력 내용을 자동 저장하지 못했습니다. 화면을 이동하기 전에 복사해주세요.');}});
const meetings=window.OfficeMeetings({readJSON:json});
const viewport=window.OfficeViewport();
const decor=window.OfficeDecor({readJSON:json,viewport});
const scene=window.OfficeScene({select,getRoute:(a,x,y)=>decor.route(a,x,y)});
const hermes=window.OfficeHermes({readJSON:json,onChange:()=>poll()});
const executive=window.OfficeExecutive({readJSON:json,getProject:()=>data?.status?.project_path,onChange:()=>poll()});
const companyEditor=window.OfficeCompany({readJSON:json,onSaved:(state,message)=>{if(state){if(data)data.company=state;teamRevision=null;poll();}else{$('office-error').hidden=false;text('office-error',message);}}});
for(const role of Object.keys(DEPTS))createStation(role);select('CEO');
const editor=window.OfficeTeamEditor({readJSON:json,onSaved:(team,message)=>{if(team){if(data)data.team.team=team;poll();}else{$('office-error').hidden=false;text('office-error',message);}}});
$('team-edit').onclick=()=>{if(!data?.company?.company){companyEditor.open();return;}editor.open();};
$('company-edit').onclick=companyEditor.open;
$('refresh').onclick=()=>{if(stopped){location.reload();return;}poll();};$('stop-missions').onclick=()=>control('stop-missions');$('shutdown').onclick=()=>control('shutdown');$('header-shutdown').onclick=()=>control('shutdown');
let visualFrame=null;document.addEventListener('game-visual-change',()=>{if(!visualFrame)visualFrame=requestAnimationFrame(()=>{visualFrame=null;paint();});});
setInterval(()=>{text('clock',new Date().toLocaleTimeString('ko-KR',{hour12:false}));if(connected&&Date.now()-lastSuccess>15000){connected=false;paint();}},1000);
setInterval(()=>{if(!document.hidden&&Date.now()>=nextPollAt)poll();},1000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});poll();
})();
