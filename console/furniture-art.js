'use strict';
// Atlas cells share a fixed elevated camera. Rotation selects another drawing;
// it never rotates the furniture's vertical axis onto the floor.
window.OfficeFurniture=(()=>{
 const ns='http://www.w3.org/2000/svg',materials={white:0,wood:1,graphite:2},chairs={blue:3,mint:4,coral:5};let palette='',ready=false;
 function art(kind,col,row,x,y,w,h){
  const columns=kind==='chair'?6:3,rows=kind==='chair'?3:2,cw=1983/columns,ch=793/rows;
  // Narrow objects have deliberately wider transparent atlas gutters.
  const crop=kind==='chair'?[75,0,225,ch]:kind==='plant'?[140,0,390,ch]:[0,0,cw,ch];
  return `<svg class="furniture-sprite" x="${x}" y="${y}" width="${w}" height="${h}" viewBox="${col*cw+crop[0]} ${row*ch+crop[1]} ${crop[2]} ${crop[3]}" preserveAspectRatio="none" overflow="hidden" aria-hidden="true"><image data-furniture-src="/furniture-${kind}-hd.png?v=1" width="1983" height="793"/></svg>`;
 }
 function activate(){const hd=ready&&window.GameVisuals?.mode()==='illustrated';for(const image of document.querySelectorAll('[data-furniture-src]')){if(hd){if(!image.hasAttribute('href'))image.setAttribute('href',image.dataset.furnitureSrc);}else image.removeAttribute('href');}}
 function station(node,hasDesk=true){
  if(!node.querySelector('.workstation-classic-art')){const legacy=document.createElementNS(ns,'g');legacy.classList.add('workstation-classic-art');for(const child of [...node.children])if(!child.classList.contains('selection')&&!child.classList.contains('station-caption'))legacy.append(child);node.insertBefore(legacy,node.lastElementChild);node.dataset.hasDesk=String(hasDesk);}
  paintStation(node);activate();
 }
 function paintStation(node){window.OfficeCozy?.station(node);if(node.dataset.hasDesk!=='true')return;const scene=document.getElementById('office-scene'),material=scene?.dataset.furnitureMaterial||'white',chair=scene?.dataset.furnitureChair||'blue',key=material+chair;if(node.dataset.furniturePalette===key)return;node.dataset.furniturePalette=key;node.querySelector('.workstation-hd-art')?.remove();const g=document.createElementNS(ns,'g');g.classList.add('workstation-hd-art');g.innerHTML=art('desk',materials[material],0,-114,-104,228,145)+art('chair',chairs[chair],2,-27,24,54,73);node.insertBefore(g,node.lastElementChild);}
 function refresh(){for(const node of document.querySelectorAll('.workstation'))paintStation(node);const scene=document.getElementById('office-scene'),key=(scene?.dataset.furnitureMaterial||'white')+(scene?.dataset.furnitureChair||'blue');if(key!==palette){palette=key;const host=document.getElementById('illustrated-meeting-props');if(host){const col=materials[scene.dataset.furnitureMaterial||'white'],chair=chairs[scene.dataset.furnitureChair||'blue'];let contents='';for(let i=0;i<8;i++){const [x,y]=window.OfficeMeetingSeat(i);contents+=i%2?`<g transform="translate(${x*2} 0) scale(-1 1)">${art('chair',chair,1,x-27,y-58,54,68)}</g>`:art('chair',chair,1,x-27,y-58,54,68);}contents+=art('chair',chair,0,858,252,54,68);host.innerHTML=contents+art('table',col,1,780,305,210,220);}}activate();}
 function item(value){const cozy=window.OfficeCozy?.item(value)||'';const r=value.rotation===90,row=r?1:0,col=materials[value.color]??0;const sizes={desk:r?[-44,-97,88,136]:[-70,-70,140,89],table:r?[-48,-52,96,120]:[-70,-37,140,84],chair:[-23,-57,46,69],partition:r?[-26,-91,52,104]:[-70,-72,140,85],plant:[-27,-68,54,82]};const [x,y,w,h]=sizes[value.kind];return cozy+`<g class="decor-hd-art" transform="rotate(${-value.rotation})">${art(value.kind,col,row,x,y,w,h)}<rect class="decor-hitbox" x="${x}" y="${y}" width="${w}" height="${h}" fill="transparent"/></g>`;}
 document.addEventListener('game-visual-change',refresh);window.GameVisuals?.ready.then(()=>{ready=true;refresh();});
 return {station,refresh,activate,item};
})();
