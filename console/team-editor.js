'use strict';
// Shared within the office page. All saved fields are data; rendered values never become HTML.
window.OfficeTeamEditor=function({readJSON,onSaved}){
 const $=id=>document.getElementById(id);
 let catalogue=null,draft=null,revision=null,dirty=false,saving=false;
 async function request(url,options){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);try{return await readJSON(url,options,controller.signal);}catch(error){if(error.name==='AbortError')throw Error('서버 응답 시간이 초과됐습니다. 서버 설정을 다시 불러와 저장 여부를 확인하세요.');throw error;}finally{clearTimeout(timer);}}
 function message(value){$('team-error').hidden=!value;$('team-error').textContent=value||'';if(value&&$('team-dialog').open)$('team-error').scrollIntoView({block:'nearest'});}
 function field(tag,label,value,member,key,options){
  const wrapper=document.createElement('label');wrapper.className='team-field';const title=document.createElement('span');title.textContent=label;
  const input=document.createElement(tag);input.dataset.field=key;
  if(options)for(const [id,text] of Object.entries(options)){const option=document.createElement('option');option.value=id;option.textContent=text;input.append(option);}
  input.value=value;input.required=true;
  if(key==='name')input.maxLength=24;if(key==='age'){input.type='number';input.min=18;input.max=100;input.step=1;}if(key==='duties'){input.maxLength=400;input.rows=2;}
  input.addEventListener('input',()=>{member[key]=key==='age'?Number(input.value):input.value;dirty=true;message('');});wrapper.append(title,input);return wrapper;
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
   remove.onclick=()=>{draft.members=draft.members.filter(m=>m.id!==member.id);dirty=true;render();};
   head.append(remove);row.append(head);
   if(!member.character)member.character={gender:'male',age:30,color:'mint'};
   const character=document.createElement('div');character.className='staff-character-fields';const preview=document.createElement('div');preview.className='staff-avatar-preview';window.OfficeCharacters.preview(preview,member.character);
   character.append(preview,field('select','성별',member.character.gender,member.character,'gender',{male:'남성',female:'여성'}),field('input','나이',member.character.age,member.character,'age'),field('select','캐릭터 스타일',member.character.color,member.character,'color',{mint:'민트 · 시티 러너',blue:'블루 · 나이트 코더',violet:'바이올렛 · 실버 노트',coral:'코랄 · 레드 라인',gold:'골드 · 골든 아워'}));
   character.addEventListener('input',()=>window.OfficeCharacters.preview(preview,member.character));row.append(character,field('textarea','담당 직무',member.duties,member,'duties'));list.append(row);
  }
  $('team-count').textContent=draft.members.length+' / '+catalogue.max_members+'명 · '+(['HEAD','BUILDER','REVIEWER'].every(slot=>draft.members.some(m=>m.slot===slot))?'개발팀 구성 완료':'기획·구현·검수 담당 채용 필요');$('team-add').disabled=draft.members.length>=catalogue.max_members||saving;
 }
 async function reload(){
  if(dirty&&!confirm('작성 중인 팀 설정을 서버의 설정으로 바꿀까요?'))return;
  try{catalogue=await request('/ops/team');draft=JSON.parse(JSON.stringify(catalogue.team));revision=catalogue.team.revision;dirty=false;message('');render();}catch(error){message(error.message);}
 }
 async function open(){
  if(saving)return;
  try{catalogue=await request('/ops/team');draft=JSON.parse(JSON.stringify(catalogue.team));revision=draft.revision;dirty=false;message('');render();$('team-dialog').showModal();}catch(error){onSaved(null,error.message);}
 }
 $('team-add').onclick=()=>{if(draft.members.length>=catalogue.max_members)return;draft.members.push({id:'staff_'+crypto.randomUUID().replaceAll('-','').slice(0,20),name:'새 직원',department:'development',position:draft.members.some(m=>m.department==='development'&&m.position==='manager')?'employee':'manager',slot:'BUILDER',specialty:'general',duties:'이 직원이 맡을 작업과 완료 조건을 구체적으로 작성하세요.',character:{gender:'male',age:30,color:'mint'}});dirty=true;render();$('team-members').lastElementChild.querySelector('input').focus();};
 $('team-default').onclick=()=>{if(!confirm('편집 중인 구성을 기본 게임 개발팀 6명으로 바꿀까요? 저장 버튼을 눌러야 적용됩니다.'))return;draft=JSON.parse(JSON.stringify(catalogue.default_team));dirty=true;message('');render();};
 $('team-reload').onclick=reload;
 $('team-form').onsubmit=async event=>{
  event.preventDefault();if(saving)return;saving=true;for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=true;$('team-save').disabled=true;$('team-close').disabled=true;$('team-default').disabled=true;$('team-reload').disabled=true;message('');
  try{const roles=await request('/ops/roles');const result=await request('/ops/team',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify({team:draft,expected_revision:revision})});dirty=false;revision=result.team.revision;$('team-dialog').close();onSaved(result.team,result.message);}
  catch(error){message(error.message);}
  finally{saving=false;for(const field of $('team-form').querySelectorAll('input,select,textarea,button'))field.disabled=false;$('team-save').disabled=false;$('team-close').disabled=false;$('team-default').disabled=false;$('team-reload').disabled=false;render();}
 };
 function close(event){if(saving){event?.preventDefault();return;}if(dirty&&!confirm('저장하지 않은 팀 설정을 닫을까요?')){event?.preventDefault();return;}$('team-dialog').close();}
 $('team-close').onclick=()=>close();$('team-dialog').addEventListener('cancel',close);
 return {open};
};
