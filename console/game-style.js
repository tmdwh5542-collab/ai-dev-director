'use strict';
window.GameVisuals=(()=>{
 let key='';
 function apply(value){const c=value?.company||{},mode=c.visual_mode||'cozy',room=window.OfficeRoom||'ceo',theme=c.room_themes?.[room]||c.theme||'corporate';const next=mode+':'+theme;
  document.body.dataset.visualMode=mode;document.body.dataset.officeTheme=theme;
  if(key!==next){key=next;document.dispatchEvent(new CustomEvent('game-visual-change',{detail:{mode,theme}}));}
 }
 const ready=fetch('/ops/company',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(v=>{apply(v);return v;}).catch(()=>{apply({company:null});return null;});
 return {apply,ready,mode:()=>document.body.dataset.visualMode||'cozy'};
})();
