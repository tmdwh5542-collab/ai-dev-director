'use strict';
/* Original tile artwork and discrete walking drawings. No external game assets. */
window.OfficeCozy=(()=>{
 const ns='http://www.w3.org/2000/svg';let roomKey='';
 const colors={mint:['#70a478','#3e645b','#44342e'],blue:['#668bb0','#3e526d','#4b393c'],violet:['#ab82aa','#6b527f','#d6cfbc'],coral:['#d38b76','#96594f','#684539'],gold:['#d4ad61','#936d42','#594331']};
 const rect=(x,y,w,h,c)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`;
 function sprite(profile,direction,frame){
  const [coat,shade,hair0]=colors[profile.color]||colors.mint,hair=Number(profile.age)>=60?'#b9b8a2':hair0,skin='#e8b58b',ink='#473a35',pants='#536377',shoe='#493d37',female=profile.gender==='female',back=direction==='up',side=direction==='left'||direction==='right',step=[0,1,2,0,-1,-2][frame],bob=frame===2||frame===5?-1:0;
  let legs='';
  // Side-view strides spread the feet horizontally; front/back strides change leg length.
  if(side){legs=rect(9+step,24,4,6,ink)+rect(9+step,24,3,4,pants)+rect(8+step,29,5,2,shoe)+rect(13-step,24,4,6,ink)+rect(13-step,24,3,4,pants)+rect(12-step,29,5,2,shoe);}
  else{legs=rect(8,24,4,6+step,ink)+rect(9,24,2,4+step,pants)+rect(7,29+step,5,2,shoe)+rect(14,24,4,6-step,ink)+rect(15,24,2,4-step,pants)+rect(14,29-step,5,2,shoe);}
  let head=rect(5,3+bob,16,13,ink)+rect(6,4+bob,14,11,hair)+rect(7,8+bob,12,9,skin);
  if(back){head=rect(5,3+bob,16,14,ink)+rect(6,4+bob,14,12,hair)+rect(8,5+bob,10,2,'#ffffff22');if(female)head+=rect(7,13+bob,12,7,hair);}
  else if(side){head+=rect(6,4+bob,14,5,hair)+rect(6,7+bob,5,8,hair)+rect(17,10+bob,2,2,ink)+rect(19,11+bob,2,3,skin)+rect(14,15+bob,4,1,'#bd7d68');}
  else{head+=rect(6,4+bob,14,5,hair)+rect(6,7+bob,3,5,hair)+rect(9,8+bob,3,2,hair)+rect(11,7+bob,3,2,hair)+rect(9,11+bob,2,2,ink)+rect(16,11+bob,2,2,ink)+rect(12,15+bob,3,1,'#bd7d68');if(female)head+=rect(5,11+bob,2,9,hair)+rect(19,9+bob,2,11,hair);}
  let body=rect(6,17+bob,14,9,ink)+rect(7,18+bob,12,7,coat)+rect(7,23+bob,12,2,shade)+rect(10,17+bob,6,2,back?shade:'#f4e7c9');
  const swing=step>0?1:step<0?-1:0;
  body+=rect(4,18+bob+swing,3,7,shade)+rect(4,23+bob+swing,3,3,skin)+rect(19,18+bob-swing,3,7,shade)+rect(19,23+bob-swing,3,3,skin);
  if(back)body+=rect(10,20+bob,6,1,shade);else body+=rect(12,19+bob,2,5,shade)+rect(16,20+bob,2,1,'#f0dfb4');
  return `<g${direction==='left'?' transform="translate(26 0) scale(-1 1)"':''}>${legs}${body}${head}</g>`;
 }
 function avatar(profile={}){
  const g=document.createElementNS(ns,'g');g.classList.add('avatar-body','cozy-avatar');g.dataset.direction='down';g.dataset.frame='0';
  let drawings='';for(const dir of ['down','up','left','right'])for(let f=0;f<6;f++)drawings+=`<g class="cozy-walk-frame" data-direction="${dir}" data-frame="${f}">${sprite(profile,dir,f)}</g>`;
  g.innerHTML=`<ellipse cx="0" cy="0" rx="19" ry="5" fill="#5d4b36" opacity=".23"/><g transform="translate(-26 -64) scale(2)" shape-rendering="crispEdges">${drawings}</g>`;return g;
 }
 function pose(actor,dx,dy,moving){
  const g=actor.node.querySelector('.cozy-avatar');if(!g)return;
  if(moving&&(Math.abs(dx)+Math.abs(dy)>.01)){const direction=Math.abs(dx)>Math.abs(dy)?(dx>0?'right':'left'):(dy>0?'down':'up');if(g.dataset.direction!==direction)g.dataset.direction=direction;}
  const frame=moving?String(Math.floor((actor.distance||0)/7)%6):'0';if(g.dataset.frame!==frame)g.dataset.frame=frame;
 }
 function portrait(profile={}){
  const [coat,shade,hair0]=colors[profile.color]||colors.mint,hair=Number(profile.age)>=60?'#aaa99b':hair0,female=profile.gender==='female',ink='#4c3935',skin='#ecc09a',shadow='#cf967c';
  const s=document.createElementNS(ns,'svg');s.classList.add('crew-portrait-svg','cozy-portrait');s.setAttribute('viewBox','0 0 64 64');s.setAttribute('shape-rendering','crispEdges');s.setAttribute('aria-hidden','true');
  let art=rect(0,0,64,64,'#9b7952')+rect(2,2,60,60,'#f1dfb5')+rect(5,5,54,54,'#c3d3aa')+rect(5,47,54,12,'#98ae86');
  art+=`<path d="M19 12H23V8H40V10H46V15H49V37H46V48H15V36H13V19H16V14H19Z" fill="${ink}"/>`;
  if(female)art+=rect(13,21,9,30,hair)+rect(43,20,8,32,hair)+rect(16,25,4,26,shade);
  art+=`<path d="M21 46H26V42H38V46H44V49H51V53H55V64H9V55H13V51H21Z" fill="${ink}"/>`;
  art+=rect(14,53,38,11,coat)+rect(11,57,8,7,shade)+rect(46,55,7,9,shade)+rect(24,42,16,8,shadow)+rect(27,44,10,8,skin);
  art+=`<path d="M23 49H27V51H32V56H27V54H24V52H21V50H23ZM37 49H42V51H39V54H36V57H32V53H36Z" fill="#f7e9c9"/>`+rect(31,54,3,10,shade)+rect(42,56,7,2,'#e5c58f');
  art+=rect(17,25,4,9,shadow)+rect(44,25,4,9,shadow)+`<path d="M21 16H42V19H45V34H42V39H38V43H27V41H23V37H20V22H21Z" fill="${skin}"/>`;
  art+=rect(21,29,3,7,shadow)+rect(24,36,4,4,shadow)+rect(28,40,11,2,'#dba68a')+rect(23,22,7,2,'#986a56')+rect(36,22,7,2,'#986a56');
  art+=rect(23,25,7,4,'#f9eacb')+rect(36,25,7,4,'#f9eacb')+rect(26,25,3,4,'#3f463e')+rect(37,25,3,4,'#3f463e')+rect(26,25,1,1,'#fff6dc')+rect(37,25,1,1,'#fff6dc')+rect(23,24,7,1,ink)+rect(36,24,7,1,ink);
  art+=rect(31,29,2,5,'#d9a081')+rect(32,33,3,1,'#bb846d')+rect(29,37,8,1,'#b77f6d')+rect(31,38,4,1,'#e5ae93')+rect(23,32,4,1,'#e0a28c')+rect(39,32,4,1,'#e0a28c');
  art+=`<path d="M18 16H21V11H27V9H39V11H44V15H47V24H43V20H38V17H34V21H30V18H26V23H22V29H18Z" fill="${hair}"/>`+rect(23,13,15,2,'#ffffff22')+rect(21,16,6,2,'#ffffff16')+rect(39,15,4,5,'#ffffff16');
  if(female)art+=rect(44,21,5,2,coat)+rect(45,32,2,4,'#dabd70');
  for(let i=0;i<4;i++)art+=rect(17+i*3,60-i%2,2,1,'#ffffff19');
  s.innerHTML=art;return s;
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
 return {avatar,portrait,pose,station,item,paint,blockers};
})();
