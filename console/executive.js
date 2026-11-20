'use strict';
window.OfficeExecutive=function({readJSON,getProject,onChange}){
 const $=id=>document.getElementById(id);let state=null,busy=false,loading=false,generation=0,renderKey=null;
 function showError(e){$('briefing-error').hidden=!e;$('briefing-error').textContent=e?.message||'';}
 async function post(value){if(busy)return;busy=true;showError(null);try{const roles=await readJSON('/ops/roles');state=await readJSON('/ops/briefings',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':roles.csrf},body:JSON.stringify({...value,expected_revision:state.revision})});generation++;render();onChange();}catch(e){showError(e);await refresh();}finally{busy=false;}}
 function el(tag,text){const n=document.createElement(tag);if(text)n.textContent=text;return n;}
 function render(){if(renderKey===state?.revision)return;renderKey=state?.revision;const host=$('briefing-content');host.replaceChildren();const s=[...(state?.sessions||[])].reverse().find(x=>x.status==='ACTIVE');$('briefing-call').disabled=!!s;
  if(!s){host.append(el('p',(state?.session_count??state?.sessions.length)?'지난 임원회의 '+(state.session_count??state.sessions.length)+'회 · 대표 지침은 다음 계획에 반영됩니다.':'호출하면 현재 팀의 과장들이 순서대로 보고합니다.'));return;}
  const r=s.reports[s.index];host.append(el('h3',(s.index+1)+' / '+s.reports.length+' · '+r.name+' 과장'),el('p',r.summary),el('small',r.source));
  const evidence=el('pre',JSON.stringify(r.evidence,null,2));evidence.className='briefing-evidence';host.append(evidence);
  const reply=el('textarea');reply.maxLength=2000;reply.rows=3;reply.placeholder='보고 내용에 대한 대표 답변 또는 수정 지침';reply.setAttribute('aria-label','대표 답변');host.append(reply);
  const choices=el('div');choices.className='briefing-choices';for(const text of r.recommendations){const b=el('button',text);b.type='button';b.className='secondary';b.onclick=()=>reply.value=text;choices.append(b);}host.append(choices);
  for(const [action,label] of [['approve','보고 승인 · 다음 과장'],['comment','답변 전달 · 다음 과장']]){const b=el('button',label);b.className='primary';b.type='button';b.onclick=()=>post({action,id:s.id,index:s.index,reply:reply.value});host.append(b);}
 }
 async function refresh(){if(loading)return;loading=true;const seq=++generation;try{const result=await readJSON('/ops/briefings?compact=1&revision='+encodeURIComponent(state?.revision||''));if(seq===generation&&!result.unchanged){state=result;render();}}catch(e){showError(e);}finally{loading=false;}}
 $('briefing-call').onclick=async()=>{if(!state)await refresh();if(state)post({action:'start',project_path:getProject()});};refresh();return {refresh,setRevision:revision=>{if(revision&&state?.revision!==revision)refresh();}};
};
