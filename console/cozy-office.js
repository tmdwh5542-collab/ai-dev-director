'use strict';
/* Original tile artwork and discrete walking drawings. No external game assets. */
window.OfficeCozy=(()=>{
 const ns='http://www.w3.org/2000/svg';let roomKey='';
 // One identity catalogue drives the illustrated portrait and every walking frame.
 const looks={
  mint:{name:'시티 러너',coat:'#a2c4ae',shade:'#638b7a',hair:'#365957',light:'#63817b',male:'웨이브 단발 · 초록 눈 · 부드러운 인상',female:'롱 포니테일 · 초록 눈 · 골드 헤어핀'},
  blue:{name:'나이트 코더',coat:'#4c5d85',shade:'#323e60',hair:'#36364f',light:'#686580',male:'인디고 웨이브 · 가는 눈매 · 사각 안경',female:'인디고 포니테일 · 푸른 눈 · 또렷한 인상'},
  violet:{name:'실버 노트',coat:'#9a739a',shade:'#624a71',hair:'#c3b6d1',light:'#e7dae7',male:'실버 웨이브 · 보라 눈 · 차분한 인상',female:'실버 웨이브 보브 · 보라 눈 · 부드러운 인상'},
  coral:{name:'레드 라인',coat:'#db937d',shade:'#a25850',hair:'#9b4e37',light:'#c57a57',male:'오번 웨이브 · 갈색 눈 · 밝은 인상',female:'오번 보브 · 둥근 눈매 · 골드 귀걸이'},
  gold:{name:'골든 아워',coat:'#514743',shade:'#332e31',hair:'#5a4038',light:'#916d54',male:'브라운 올백 · 깊은 눈매 · 짧은 수염',female:'브라운 보브 · 갈색 눈 · 둥근 안경'}
 };
 function appearance(profile={}){const key=Object.hasOwn(looks,profile.color)?profile.color:'mint';return {...looks[key],key,female:profile.gender==='female'};}
 const rect=(x,y,w,h,c)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`;
 function sprite(profile,direction,frame){
  const look=appearance(profile),{coat,shade}=look,hair=Number(profile.age)>=60?'#b9b8a2':look.hair,skin='#e8b58b',ink='#473a35',pants='#536377',shoe='#493d37',female=profile.gender==='female',back=direction==='up',side=direction==='left'||direction==='right',step=[0,1,2,0,-1,-2][frame],bob=frame===2||frame===5?-1:0;
  let legs='';
  // Side-view strides spread the feet horizontally; front/back strides change leg length.
  if(side){legs=rect(9+step,24,4,6,ink)+rect(9+step,24,3,4,pants)+rect(8+step,29,5,2,shoe)+rect(13-step,24,4,6,ink)+rect(13-step,24,3,4,pants)+rect(12-step,29,5,2,shoe);}
  else{legs=rect(8,24,4,6+step,ink)+rect(9,24,2,4+step,pants)+rect(7,29+step,5,2,shoe)+rect(14,24,4,6-step,ink)+rect(15,24,2,4-step,pants)+rect(14,29-step,5,2,shoe);}
  let head=rect(5,3+bob,16,13,ink)+rect(6,4+bob,14,11,hair)+rect(7,8+bob,12,9,skin);
  if(back){head=rect(5,3+bob,16,14,ink)+rect(6,4+bob,14,12,hair)+rect(8,5+bob,10,2,'#ffffff22');if(female)head+=rect(7,13+bob,12,look.key==='mint'||look.key==='blue'?10:4,hair);}
  else if(side){head+=rect(6,4+bob,14,5,hair)+rect(6,7+bob,5,8,hair)+rect(17,10+bob,2,2,ink)+rect(19,11+bob,2,3,skin)+rect(14,15+bob,4,1,'#bd7d68');}
  else{head+=rect(6,4+bob,14,5,hair)+rect(6,7+bob,3,5,hair)+rect(9,8+bob,3,2,hair)+rect(11,7+bob,3,2,hair)+rect(9,11+bob,2,2,ink)+rect(16,11+bob,2,2,ink)+rect(12,15+bob,3,1,'#bd7d68');if(female)head+=rect(5,11+bob,2,look.key==='mint'||look.key==='blue'?9:5,hair)+rect(19,9+bob,2,look.key==='mint'||look.key==='blue'?11:7,hair);}
  // Distinct silhouettes and accessories remain readable at the office's small scale.
  head+=rect(8,5+bob,8,1,Number(profile.age)>=60?'#dad8c4':look.light);
  if(female&&(look.key==='mint'||look.key==='blue')){
   const sway=frame===2?1:frame===5?-1:0;
   head=rect((side?3:19)+sway,8+bob,4,14,hair)+rect((side?2:20)+sway,18+bob,4,4,hair)+head;
   head+=rect(side?5:19,7+bob,3,2,'#e0b568');
  }
  if(!back){
   if((!female&&look.key==='blue')||(female&&look.key==='gold'))head+=side?rect(16,10+bob,5,1,'#37343c')+rect(16,12+bob,4,1,'#37343c'):rect(8,10+bob,5,1,'#37343c')+rect(8,13+bob,5,1,'#37343c')+rect(15,10+bob,5,1,'#37343c')+rect(15,13+bob,5,1,'#37343c')+rect(8,11+bob,1,2,'#37343c')+rect(12,11+bob,4,1,'#37343c')+rect(19,11+bob,1,2,'#37343c');
   if(!female&&look.key==='gold')head+=rect(side?15:10,14+bob,side?4:8,2,'#92725b');
   if(female)head+=rect(side?11:6,14+bob,1,2,'#e9c56d');
  }
  let body=rect(6,17+bob,14,9,ink)+rect(7,18+bob,12,7,coat)+rect(7,23+bob,12,2,shade)+rect(10,17+bob,6,2,back?shade:'#f4e7c9');
  const swing=step>0?1:step<0?-1:0;
  body+=rect(4,18+bob+swing,3,7,shade)+rect(4,23+bob+swing,3,3,skin)+rect(19,18+bob-swing,3,7,shade)+rect(19,23+bob-swing,3,3,skin);
  if(back)body+=rect(10,20+bob,6,1,shade);else body+=rect(12,19+bob,2,5,shade)+rect(16,20+bob,2,1,'#f0dfb4');
  return `<g${direction==='left'?' transform="translate(26 0) scale(-1 1)"':''}>${legs}${body}${head}</g>`;
 }
 function avatar(profile={},still=false){
  const g=document.createElementNS(ns,'g');g.classList.add('avatar-body','cozy-avatar');g.dataset.direction='down';g.dataset.frame='0';
  let drawings='';for(const dir of (still?['down']:['down','up','left','right']))for(let f=0;f<(still?1:6);f++)drawings+=`<g class="cozy-walk-frame" data-direction="${dir}" data-frame="${f}">${sprite(profile,dir,f)}</g>`;
  g.innerHTML=`<ellipse cx="0" cy="0" rx="19" ry="5" fill="#5d4b36" opacity=".23"/><g transform="translate(-26 -64) scale(2)" shape-rendering="crispEdges">${drawings}</g>`;return g;
 }
 function pose(actor,dx,dy,moving){
  const g=actor.node.querySelector('.cozy-avatar');if(!g)return;
  if(moving&&(Math.abs(dx)+Math.abs(dy)>.01)){const direction=Math.abs(dx)>Math.abs(dy)?(dx>0?'right':'left'):(dy>0?'down':'up');if(g.dataset.direction!==direction)g.dataset.direction=direction;}
  const frame=moving?String(Math.floor((actor.distance||0)/7)%6):'0';if(g.dataset.frame!==frame)g.dataset.frame=frame;
 }
 function portrait(profile={}){
  const look=appearance(profile),keys=Object.keys(looks),column=keys.indexOf(look.key),row=look.female?1:0;
  const s=document.createElementNS(ns,'svg');s.classList.add('crew-portrait-svg','cozy-portrait');s.dataset.preset=look.key;s.setAttribute('viewBox','0 0 240 240');s.setAttribute('aria-hidden','true');
  // A nested viewport clips all four edges, so adjacent portraits cannot bleed through.
  const cell=document.createElementNS(ns,'svg');for(const [k,v] of Object.entries({x:0,y:0,width:240,height:240,viewBox:`${column*396.6} ${row*396.5} 396.6 396.5`,preserveAspectRatio:'xMidYMid meet',overflow:'hidden'}))cell.setAttribute(k,v);
  const art=document.createElementNS(ns,'image');art.setAttribute('href','/crew-portraits-cozy-hd.png?v=1');art.setAttribute('width','1983');art.setAttribute('height','793');
  art.addEventListener('error',()=>{if(s.dataset.artFallback)return;s.dataset.artFallback='previous-illustration';art.setAttribute('href','/crew-portraits-hd.png?v=1');},{once:true});cell.append(art);s.append(cell);return s;
 }

 function plant(x,y){return `<g transform="translate(${x} ${y})">${rect(-13,-12,26,22,'#8c5640')}${rect(-16,-16,32,8,'#c08359')}${rect(-8,-39,16,25,'#427455')}${rect(-21,-34,13,12,'#66985d')}${rect(8,-43,14,15,'#83a969')}${rect(-6,-48,12,12,'#8eb878')}${rect(-7,-6,14,4,'#dfac75')}</g>`;}
 function desk(w=156,material='wood'){const top=material==='white'?'#dfd6b6':material==='graphite'?'#737b77':'#c69762';return rect(-w/2+8,12,w-16,27,'#75503c')+rect(-w/2,0,w,20,'#6d4936')+rect(-w/2+4,-34,w-8,42,top)+rect(-w/2+8,-30,w-16,3,'#e6bf89')+rect(-w/2+14,20,10,22,'#73513e')+rect(w/2-24,20,10,22,'#73513e');}
 function chair(x,y,color='#759891'){return `<g transform="translate(${x} ${y})">${rect(-16,-29,32,23,'#4d5c52')}${rect(-12,-25,24,15,color)}${rect(-18,-5,36,15,'#4d5c52')}${rect(-14,-4,28,9,color)}${rect(-13,10,5,8,'#604c3d')}${rect(8,10,5,8,'#604c3d')}</g>`;}
 function station(node){if(node.dataset.hasDesk!=='true')return;const scene=document.getElementById('office-scene'),key=(scene?.dataset.furnitureMaterial||'white')+(scene?.dataset.furnitureChair||'blue');if(node.dataset.cozyPalette===key)return;node.dataset.cozyPalette=key;node.querySelector('.workstation-cozy-art')?.remove();const g=document.createElementNS(ns,'g');g.classList.add('workstation-cozy-art');g.setAttribute('shape-rendering','crispEdges');g.innerHTML=rect(-86,-37,176,120,'#694f3220')+desk(156,scene?.dataset.furnitureMaterial)+rect(-30,-67,64,41,'#514c42')+rect(-25,-62,54,30,'#638b87')+rect(-21,-58,26,3,'#bedac1')+rect(-21,-51,39,3,'#a6cbb6')+rect(-2,-26,7,9,'#514c42')+rect(-13,-17,29,5,'#514c42')+rect(-29,-7,59,9,'#ede2bf')+rect(44,-22,12,18,'#f6e8c6')+plant(-56,-14)+chair(0,72);node.insertBefore(g,node.lastElementChild);}
 function item(value){const tall=value.rotation===90,w=tall?70:120,h=tall?90:54;let art='';if(value.kind==='plant')art=plant(0,0);else if(value.kind==='chair')art=chair(0,0);else if(value.kind==='partition')art=rect(-w/2,-h/2,w,14,'#775940')+rect(-w/2+4,-h/2+4,w-8,Math.max(12,h-4),'#96a78b')+rect(-w/2,-h/2,w,4,'#d1b47f');else art=desk(w,value.color)+(value.kind==='desk'?rect(-24,-48,48,25,'#4d655e')+rect(-20,-44,40,17,'#8fb8a1'):'');return `<g class="decor-cozy-art" transform="rotate(${-value.rotation})" shape-rendering="crispEdges">${art}</g>`;}
 function paint(room='ceo',theme='corporate'){
  const host=document.getElementById('cozy-architecture');if(!host)return;const key=room+':'+theme;if(key===roomKey)return;roomKey=key;
  const names={ceo:'대표실 · 비서실',planning:'기획과',design:'디자인과',development:'개발과',level:'레벨과',testing:'테스트과',quality:'품질검수과',support:'경영지원과'},sky=theme==='creative'?'#8c99b5':theme==='garden'?'#a4d4bf':'#acd5dc',wood=theme==='creative'?'#bd9276':theme==='garden'?'#b5a477':'#cda36f';
  let a=rect(25,48,1030,590,'#624b3b')+rect(37,60,1006,568,'#876348');
  for(let y=130;y<620;y+=32)for(let x=48;x<990;x+=64){const tone=((x/64+y/32)|0)%3===0?'#d5b381':wood;a+=rect(x+(y%64?0:-24),y,62,30,tone)+rect(x+(y%64?0:-24)+6,y+23,37,2,'#805d3c22');}
  a+=rect(40,64,1000,76,'#f1dfae')+rect(40,125,1000,13,'#8e674a')+rect(40,132,1000,7,'#604934');
  for(let x=90;x<980;x+=200){a+=rect(x-8,70,154,58,'#76543f')+rect(x,74,138,46,sky)+rect(x+20,100,50,20,'#789875')+rect(x+74,94,40,26,'#94b481')+rect(x+12,83,32,5,'#e8eed0')+rect(x+37,79,22,7,'#e8eed0')+rect(x+94,99,5,21,'#695a3c')+rect(x+83,98,26,9,'#4b8059')+rect(x+87,90,18,10,'#729454')+rect(x+92,86,8,7,'#9bb56b')+rect(x+60,75,5,45,'#f4e5bc')+rect(x-5,120,148,9,'#d7b47b')+rect(x+8,122,18,4,'#8ca263')+rect(x+14,119,4,4,'#d79880')+rect(x+104,122,17,4,'#8ca263')+rect(x+108,119,4,4,'#d9b969')+rect(x,76,138,3,'#e8f3d8');}
  // A consistent floor-plan room, with an actual opening instead of a floating glass box.
  a+=rect(755,224,252,330,'#927353')+rect(765,235,232,305,'#c5c49b')+rect(779,252,204,270,'#aeb18a')+rect(748,213,267,15,'#75523c')+rect(748,228,12,120,'#d6b985')+rect(748,440,12,116,'#d6b985')+rect(1005,224,12,332,'#d6b985')+rect(748,548,269,10,'#75523c')+rect(752,348,8,90,'#8f7850');
  a+=rect(810,178,150,28,'#72543e')+`<text x="885" y="197" text-anchor="middle" fill="#fff0cb" font-size="15">회의실</text>`;
  for(let i=0;i<8;i++){const [x,y]=window.OfficeMeetingSeat?.(i)||[815+(i%2)*145,342+Math.floor(i/2)*58];a+=chair(x,y,'#7e9a85');}
  a+=chair(885,310,'#8d947a')+rect(847,324,78,183,'#694f3c')+rect(843,316,84,178,'#d1ab76')+rect(849,320,72,4,'#f0d09b')+rect(853,491,8,24,'#745039')+rect(907,491,8,24,'#745039')+rect(868,381,34,23,'#f7e7ba')+rect(876,387,18,3,'#8f9b89');
  // Domestic details make small offices feel inhabited without blocking their aisles.
  a+=rect(70,157,114,46,'#73523d')+rect(76,163,102,34,'#d2b689');for(let i=0;i<9;i++)a+=rect(82+i*10,167,7,27,['#83986c','#b77960','#e1c586'][i%3]);
  a+=plant(92,260)+plant(1016,189)+rect(74,576,145,27,'#72523d')+rect(79,565,135,28,'#8fa47d')+rect(80,559,30,27,'#b8c998')+rect(181,559,30,27,'#b8c998')+rect(87,599,9,9,'#644733')+rect(196,599,9,9,'#644733');
  a+=rect(535,148,175,26,'#745640')+`<text x="622" y="167" text-anchor="middle" fill="#fff0ca" font-size="15">${names[room]||'우리 회사'}</text>`;
  host.innerHTML=a;host.setAttribute('shape-rendering','crispEdges');
 }
 function blockers(){return window.GameVisuals?.mode()==='cozy'?[[65,150,193,208],[65,220,120,266],[65,550,230,610],[748,213,1017,228],[748,228,760,348],[748,440,760,558],[1005,224,1017,558],[748,548,1017,558],[842,318,930,512]]:[];}
 return {avatar,portrait,pose,station,item,paint,blockers,looks,appearance};
})();
