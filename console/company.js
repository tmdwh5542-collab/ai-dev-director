'use strict';
window.OfficeCompany=function({readJSON,onSaved}){
 const artThemes={corporate:{name:'로열 시티 본사',description:'금빛 채광 · 도시 전망 · 고급 본사'},creative:{name:'네온 시티 스튜디오',description:'야간 도시 · 청록 네온 · 크리에이티브'},garden:{name:'스카이 가든 아틀리에',description:'화이트 오크 · 플랜트 월 · 따뜻한 채광'}};
 const $=id=>document.getElementById(id);let state=null,latest=null,theme='corporate',saving=false,dirty=false;
 function error(message){$('company-error').textContent=message||'';$('company-error').hidden=!message;}
 function character(){return {gender:$('owner-gender').value,age:Number($('owner-age').value),color:$('owner-color').value};}
 function preview(){for(const card of $('office-themes').children){const d=($('visual-mode').value==='illustrated'?artThemes:state.themes)[card.dataset.theme];card.querySelector('strong').textContent=d.name;card.querySelector('small').textContent=d.description;}window.OfficeCharacters.preview($('owner-preview'),character());
  const host=$('character-style-gallery'),key=$('owner-gender').value+':'+$('owner-color').value+':'+$('visual-mode').value;if(host.dataset.character===key)return;host.dataset.character=key;host.replaceChildren();
  for(const [color,name] of Object.entries({mint:'시티 러너',blue:'나이트 코더',violet:'실버 노트',coral:'레드 라인',gold:'골든 아워'})){
   const button=document.createElement('button');button.type='button';button.dataset.look=color;button.setAttribute('aria-pressed',String(color===$('owner-color').value));button.setAttribute('aria-label',name+' 스타일 선택');
   const art=document.createElement('span');art.className='style-thumb';art.append(window.OfficeCharacters.portrait({...character(),color}));const label=document.createElement('span');label.textContent=name;button.append(art,label);button.onclick=()=>{$('owner-color').value=color;$('owner-color').dispatchEvent(new Event('input',{bubbles:true}));};host.append(button);
  }
 }

 function selectTheme(key){theme=key;for(const card of $('office-themes').children)card.setAttribute('aria-pressed',String(card.dataset.theme===key));document.getElementById('owner-preview').dataset.theme=key;}
 async function request(url,options={}){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);try{return await readJSON(url,options,controller.signal);}catch(e){if(e.name==='AbortError')throw Error('응답 시간이 초과됐습니다. 다시 열어 저장 여부를 확인하세요.');throw e;}finally{clearTimeout(timer);}}
 function apply(value){latest=value;document.body.dataset.officeTheme=value.company?.room_themes?.[window.OfficeRoom||'ceo']||value.company?.theme||'corporate';if(!$('company-dialog').open){state=value;window.GameVisuals?.apply(value);}}
 async function open(){
  if(saving)return;
  try{apply(await request('/ops/company'));const owner=state.company?.owner;theme=state.company?.room_themes?.[window.OfficeRoom||'ceo']||state.company?.theme||'corporate';$('theme-scope').value=state.company?'room':'all';
   $('visual-mode').value=state.company?.visual_mode||'cozy';$('auto-meetings').checked=state.company?!!state.company.auto_meetings:true;$('owner-name').value=owner?.name||'';$('owner-gender').value=owner?.character.gender||'male';$('owner-age').value=owner?.character.age||30;$('owner-color').value=owner?.character.color||'gold';
   $('company-title').textContent=owner?'대표 캐릭터 · 사무실 설정':'대표 캐릭터를 만들어주세요';$('company-save').textContent=owner?'회사 설정 저장':'회사 시작하기';
   $('company-close').hidden=!owner;$('company-intro').textContent=state.existing_team?'저장된 직원 구성을 유지하며 대표와 사무실을 설정합니다.':'대표 한 명으로 회사를 시작합니다. 그다음 필요한 직원을 직접 만들고 채용하세요.';
   $('company-save-note').textContent='이 PC에 저장됩니다. 같은 회사의 프로젝트에 공통으로 적용됩니다.';
   $('office-themes').replaceChildren();for(const [key,value] of Object.entries(state.themes)){const button=document.createElement('button');button.type='button';button.className='theme-card';button.dataset.theme=key;const scene=document.createElement('span');scene.className='theme-thumbnail';scene.setAttribute('aria-hidden','true');const name=document.createElement('strong');name.textContent=value.name;const detail=document.createElement('small');detail.textContent=value.description;button.append(scene,name,detail);button.onclick=()=>{selectTheme(key);dirty=true;};$('office-themes').append(button);}
   selectTheme(theme);preview();dirty=false;error('');$('company-dialog').showModal();
  }catch(e){onSaved(null,e.message);}
 }
 for(const field of ['owner-name','owner-gender','owner-age','owner-color','auto-meetings','theme-scope','visual-mode'])$(field).addEventListener('input',()=>{dirty=true;if(field==='visual-mode'){window.GameVisuals?.apply({company:{...(state?.company||{}),theme,visual_mode:$('visual-mode').value}});}preview();error('');});
 $('company-form').onsubmit=async event=>{event.preventDefault();if(saving)return;saving=true;error('');for(const field of $('company-form').querySelectorAll('input,select,button'))field.disabled=true;
  try{const roles=await request('/ops/roles');const result=await request('/ops/company',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify({company:{...(state.company||{}),visual_mode:$('visual-mode').value,owner:{name:$('owner-name').value,character:character()},theme:$('theme-scope').value==='all'?theme:(state.company?.theme||theme),room_themes:$('theme-scope').value==='all'?{}:{...(state.company?.room_themes||{}),[window.OfficeRoom||'ceo']:theme},auto_meetings:$('auto-meetings').checked},expected_revision:state.revision})});dirty=false;$('company-dialog').close();apply(result);onSaved(result);}
  catch(e){error(e.message);}finally{saving=false;for(const field of $('company-form').querySelectorAll('input,select,button'))field.disabled=false;}
 };
 function close(event){if(saving||!state?.company){event?.preventDefault();return;}if(dirty&&!confirm('저장하지 않은 회사 설정을 닫을까요?')){event?.preventDefault();return;}$('company-dialog').close();if(latest)apply(latest);}
 $('company-close').onclick=()=>close();$('company-dialog').addEventListener('cancel',close);
 return {open,apply};
};

// Shared chair/visitor anchors; unrelated secretary and desk indices never move a seat.
window.OfficeMeetingSeat=index=>index<8?[815+(index%2)*145,342+Math.floor(index/2)*58]:[130+((index-8)%6)*100,370+Math.floor((index-8)/6)*60];
window.OfficeScene=function({select,getRoute}){
 const ns='http://www.w3.org/2000/svg',host=document.getElementById('characters'),svg=document.getElementById('office-scene');
 const actors=new Map(),reduce=matchMedia('(prefers-reduced-motion: reduce)');let connected=false,enabled=false,frame=null,last=0,theme=null,decorRoom=null,wanderIndex=0,sceneVisible=true;const metrics={frames:0,transformWrites:0,culled:0,totalFrameMs:0,maxFrameMs:0};window.OfficePerformance=metrics;
 const lounge=[[250,365],[540,365],[250,565],[540,565]];
 function target(actor,x,y){
  if(Math.hypot(actor.tx-x,actor.ty-y)<1)return;actor.tx=x;actor.ty=y;
  actor.path=getRoute?.(actor,x,y)||[];
  if(actor.path.length){if(reduce.matches){const p=actor.path[actor.path.length-1];actor.x=p[0];actor.y=p[1];actor.path=[];place(actor);}else start();return;}
  // A shared aisle keeps cross-office travel away from other workstations.
  if(Math.abs(actor.x-x)>120&&Math.abs(actor.y-y)>45)actor.path.push([540,400]);
  actor.path.push([x,y]);if(reduce.matches){actor.x=x;actor.y=y;actor.path=[];place(actor);}else start();
 }
 function place(a){window.OfficeCozy?.pose(a,a.dx||0,a.dy||0,a.path.length>0);const view=svg.viewBox.baseVal,visible=a.x+80>=view.x&&a.x-80<=view.x+view.width&&a.y+50>=view.y&&a.y-160<=view.y+view.height;a.node.dataset.inCamera=String(visible);if(!visible){metrics.culled++;return;}metrics.transformWrites++;a.node.dataset.atDesk=String(Math.hypot(a.x-a.rest[0],a.y-a.rest[1])<45);a.node.setAttribute('transform',`translate(${a.x.toFixed(1)} ${a.y.toFixed(1)}) scale(${a.home.meetingSeat && window.GameVisuals?.mode()==='illustrated' ? .52 : .78})`);a.node.dataset.moving=String(a.path.length>0);}
 function tick(now){frame=null;if(document.hidden||!sceneVisible||!connected||!enabled||window.OfficeDecorEditing){last=0;return;}if(last&&now-last<32){frame=requestAnimationFrame(tick);return;}const begun=performance.now();metrics.frames++;const dt=Math.min((now-(last||now))/1000,.08);last=now;let moving=false;
  for(const a of actors.values())if(a.path.length){const [x,y]=a.path[0],dx=x-a.x,dy=y-a.y,d=Math.hypot(dx,dy),step=100*dt;a.dx=dx;a.dy=dy;a.distance=(a.distance||0)+Math.min(d,step);if(d<=step||d<1){a.x=x;a.y=y;a.path.shift();}else{a.x+=dx/d*step;a.y+=dy/d*step;}place(a);moving ||=a.path.length>0;}
  // Foot position determines the character overlap order.
  const focused=document.activeElement;let movedFocus=false;
  [...actors.values()].sort((a,b)=>a.y-b.y).forEach((a,index)=>{if(host.children[index]!==a.node){movedFocus ||= a.node===focused;host.insertBefore(a.node,host.children[index]||null);}});
  if(movedFocus)focused.focus({preventScroll:true});
  const elapsed=performance.now()-begun;metrics.totalFrameMs+=elapsed;metrics.maxFrameMs=Math.max(metrics.maxFrameMs,elapsed);if(moving)frame=requestAnimationFrame(tick);else last=0;
 }
 function start(){if(!frame&&connected&&enabled&&sceneVisible&&!document.hidden&&!window.OfficeDecorEditing){last=0;frame=requestAnimationFrame(tick);}}
 function create(key,profile,home,index){
  const node=document.createElementNS(ns,'g');node.classList.add('office-character');node.dataset.character=key;node.setAttribute('role','button');node.setAttribute('tabindex','0');node.setAttribute('aria-label',profile.name+' · 캐릭터와 업무 보기');node.append(window.OfficeCharacters.avatar(profile.character));
  const plate=document.createElementNS(ns,'g');plate.classList.add('character-nameplate');const badge=document.createElementNS(ns,'rect');badge.classList.add('avatar-nameplate');const width=Math.min(152,Math.max(76,Array.from(profile.name).length*9+16));for(const [k,v] of Object.entries({x:-width/2,y:7,width,height:24,rx:6}))badge.setAttribute(k,v);const label=document.createElementNS(ns,'text');label.classList.add('avatar-label');label.setAttribute('y','24');label.textContent=Array.from(profile.name).slice(0,15).join('')+(Array.from(profile.name).length>15?'…':'');plate.append(badge,label);node.append(plate);
  const speech=document.createElementNS(ns,'g');speech.classList.add('character-speech');speech.innerHTML='<rect class="speech-bg" x="-76" y="-132" width="152" height="27" rx="8"/><path d="M-5-105L0-99L5-105" class="speech-bg"/><text class="speech-text" y="-114"></text>';node.append(speech);
  node.onclick=e=>{e.stopPropagation();select(key);};node.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(key);}};host.append(node);
  const rest=home.meetingSeat||[home.x+30,home.y+65];const entry=home.visitReason?[75,360]:rest;const a={node,key,x:entry[0],y:entry[1],tx:entry[0],ty:entry[1],home,rest,path:[],state:null,signature:JSON.stringify(profile)+(document.body.dataset.visualMode||'illustrated')};place(a);return a;
 }
 function decorate(key){if(theme===key&&decorRoom===window.OfficeRoom)return;theme=key;decorRoom=window.OfficeRoom;const d=document.getElementById('theme-decor');
  const colors={corporate:['#aac4d3','#58798b'],creative:['#cdb89e','#8b7562'],garden:['#b4cebd','#678b77']},c=colors[key]||colors.corporate;
  d.innerHTML=`<g class="office-lounge" transform="translate(8 35) scale(.75)"><rect x="76" y="163" width="160" height="56" rx="10" fill="#a8bac4" opacity=".25" transform="translate(0 6)"/><rect x="76" y="158" width="160" height="52" rx="9" fill="${c[0]}" stroke="${c[1]}" stroke-width="2"/><path d="M87 164V200M153 164V200M224 164V200" stroke="${c[1]}" stroke-opacity=".45" stroke-width="3"/><rect x="92" y="221" width="130" height="22" rx="5" fill="#f6fafb" stroke="#a2b5be" stroke-width="2"/></g>
  <g><rect x="908" y="160" width="80" height="35" rx="4" fill="#e6eef1" stroke="#9cb3bf" stroke-width="2"/><rect x="924" y="147" width="43" height="22" rx="4" fill="#3d5665"/><rect x="931" y="153" width="12" height="7" fill="#a3d4db"/><path d="M973 163V183" stroke="#809ba9" stroke-width="3"/></g>`;
  if(key==='creative')d.innerHTML+='<rect x="294" y="149" width="280" height="25" rx="5" fill="#f8fbfc" stroke="#a7b7be" stroke-width="2"/><path d="M311 163H389M311 169H353M420 158H550M420 169H496" stroke="#79a4b1" stroke-width="3"/>';
  if(key==='garden')d.innerHTML+='<rect x="294" y="150" width="280" height="32" rx="5" fill="#e1eee3" stroke="#a2bca9" stroke-width="2"/><g fill="#81a68a"><circle cx="320" cy="155" r="15"/><circle cx="360" cy="155" r="17"/><circle cx="402" cy="155" r="14"/><circle cx="448" cy="155" r="17"/><circle cx="491" cy="155" r="15"/><circle cx="540" cy="155" r="18"/></g>';
  if(decorRoom==='ceo')d.innerHTML+='<path d="M88 390H320M480 390H730" stroke="#99b5c3" stroke-width="5"/><path d="M93 382H315M485 382H725" stroke="#f6fdff" stroke-width="3"/><rect x="97" y="228" width="126" height="27" rx="4" fill="#f4fafc"/><text x="160" y="247" text-anchor="middle" fill="#53717f" font-size="14">EXECUTIVE OFFICE</text><rect x="97" y="450" width="156" height="27" rx="4" fill="#f4fafc"/><text x="175" y="469" text-anchor="middle" fill="#53717f" font-size="14">비서실 · 보고 접수</text>';


 }
 function sync(depts,owner,getWorker,isConnected,approval,companyTheme,deliveries=[]){
  connected=isConnected;enabled=!!owner;const artKey=companyTheme||'corporate';window.OfficeCozy?.paint(window.OfficeRoom||'ceo',artKey);const plate=document.getElementById('illustrated-office-image'),src='/office-'+artKey+'-hd.png?v=1';if((document.body.dataset.visualMode||'illustrated')==='illustrated'){if(plate?.getAttribute('href')!==src)plate?.setAttribute('href',src);}else plate?.removeAttribute('href');decorate(artKey);
  const keys=new Set(Object.keys(depts).filter(k=>k!=='DIRECTOR'&&enabled));for(const [key,a] of actors)if(!keys.has(key)){a.node.remove();actors.delete(key);}
  let index=0;for(const key of keys){const d=depts[key],profile=key==='CEO'?owner:{name:d.name,character:d.character||{gender:'male',age:30,color:'mint'}},signature=JSON.stringify(profile)+(document.body.dataset.visualMode||'illustrated');let a=actors.get(key);
   if(!a||a.signature!==signature||a.home.x!==d.x||a.home.y!==d.y){a?.node.remove();a=create(key,profile,d,index);actors.set(key,a);}if(key!=='CEO')index++;
   a.home=d;const w=getWorker(key),state=!connected?'offline':key==='CEO'?(d.meetingSeat?'meeting':'owner'):approval&&d.slot==='HEAD'?'waiting':w.meeting?'meeting':w.busy?'working':'idle';
   a.node.dataset.state=state;
   a.node.querySelector('.speech-text').textContent=state==='offline'?'연결 확인':state==='waiting'?'사용자 확인 필요':state==='meeting'?(w.visitReason||'회의 중 · '+w.provider):state==='working'?'업무 중 · '+w.provider:state==='owner'?'대표 · 바닥을 눌러 이동':'업무 대기';
   if(a.state!==state){if(state==='meeting')target(a,...(d.meetingSeat||window.OfficeMeetingSeat(index-1)));else if(state==='working')target(a,d.x+42,d.y+24);else if(state==='waiting')target(a,680,350);else if(state==='idle')target(a,...a.rest);a.state=state;}
  }
  for(const a of actors.values())if(a.delivery&&!deliveries.some(d=>d.secretary_id===a.key||d.manager_id===a.key)){a.delivery=false;a.state=null;target(a,...a.rest);}
  for(const delivery of deliveries){
   const manager=actors.get(delivery.manager_id),secretary=actors.get(delivery.secretary_id);
   if(manager){const first=!manager.delivery;manager.delivery=true;manager.node.querySelector('.speech-text').textContent=delivery.phase+(delivery.secretary_id?'':' · 비서 미채용: 보고함 전달');
    if(delivery.elapsed>=52){if(first){manager.x=75;manager.y=360;place(manager);}target(manager,manager.home.x+30,manager.home.y+65);}else if(delivery.elapsed<12)target(manager,1000,360);else if(delivery.elapsed<32)target(manager,470,495);else target(manager,1000,360);}
   if(secretary&&delivery.elapsed>=32&&delivery.elapsed<52){secretary.delivery=true;secretary.node.querySelector('.speech-text').textContent='취합한 보고서 대표 전달';target(secretary,470,260);}
  }
  start();
 }
 svg.addEventListener('click',event=>{
  if(!enabled||!connected||window.OfficeDecorEditing||event.target.closest('.workstation,.office-character,.decor-item'))return;const matrix=svg.getScreenCTM();if(!matrix)return;const p=svg.createSVGPoint();p.x=event.clientX;p.y=event.clientY;const point=p.matrixTransform(matrix.inverse()),x=point.x,y=point.y;
  // Keep the representative inside the diamond floor, with a margin from the walls.
  if(x<70||x>1010||y<145||y>600)return;
  const a=actors.get('CEO');if(a){target(a,x,y);select('CEO');}
 });
 setInterval(()=>{if(!connected||!enabled||document.hidden||reduce.matches)return;const idle=[...actors.values()].filter(a=>a.key!=='CEO'&&a.state==='idle'&&!a.path.length);if(idle.length){const a=idle[wanderIndex++%idle.length],rest=lounge[(wanderIndex+2)%lounge.length];target(a,...rest);}},18000);
 document.addEventListener('office-decor-change',()=>{for(const a of actors.values()){const x=a.tx,y=a.ty;a.tx=-999;target(a,x,y);}start();});
 const visibility=new IntersectionObserver(entries=>{sceneVisible=entries[0].isIntersecting;svg.dataset.sceneVisible=String(sceneVisible);if(sceneVisible)start();else if(frame){cancelAnimationFrame(frame);frame=null;last=0;}},{rootMargin:'120px'});visibility.observe(svg);
 new MutationObserver(()=>{for(const a of actors.values())place(a);}).observe(svg,{attributes:true,attributeFilter:['viewBox']});
 document.addEventListener('visibilitychange',()=>{svg.dataset.tabVisible=String(!document.hidden);if(!document.hidden)start();else if(frame){cancelAnimationFrame(frame);frame=null;last=0;}});
 return {sync};
};
