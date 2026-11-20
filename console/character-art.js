'use strict';
/* Original in-app artwork: a pixel map sprite and a matching cel-shaded portrait.
   All colors and geometry are local constants. Profile text is never parsed as markup. */
window.OfficeCharacters=(()=>{
 const ns='http://www.w3.org/2000/svg';
 const palettes={
  mint:{coat:'#54a999',shade:'#327478',light:'#b7e4ca',hair:'#263f48',hairLight:'#507a83',eye:'#d79c43'},
  blue:{coat:'#5b7dc4',shade:'#354a83',light:'#c4d8ed',hair:'#343249',hairLight:'#77718e',eye:'#53b6bd'},
  violet:{coat:'#8d71ae',shade:'#514369',light:'#ded0ed',hair:'#dddde8',hairLight:'#ffffff',eye:'#9b6aaf'},
  coral:{coat:'#d66c59',shade:'#8d4144',light:'#f1cbaa',hair:'#56333f',hairLight:'#a55c65',eye:'#65a39e'},
  gold:{coat:'#d8a04e',shade:'#8b6639',light:'#f3dba1',hair:'#38363c',hairLight:'#767077',eye:'#b67b45'}
 };
 function palette(character){const p={...(palettes[character?.color]||palettes.mint)};if(Number(character?.age)>=60){p.hair='#9195a4';p.hairLight='#e3e1df';}return p;}
 function svg(){return document.createElementNS(ns,'svg');}
 function pixelAvatar(character={}){
  const p=palette(character),female=character.gender==='female',g=document.createElementNS(ns,'g');g.classList.add('avatar-body');
  const back=female?`<path d="M4 9H28V30H24V33H19V27H10V32H5V27H3V17H4Z" fill="${p.hair}"/>`:'';
  const fringe=female?'M5 7H9V4H24V7H28V17H25V13H22V10H19V14H15V12H12V16H8V20H5Z':'M4 9H7V5H11V3H23V5H27V8H29V16H25V12H21V10H18V13H14V11H11V15H7V18H4Z';
  g.innerHTML=`<g class="pixel-sprite" transform="translate(-32 -96) scale(2)" shape-rendering="crispEdges">
   <path d="M7 45H25V46H28V48H5V47H3V46H7Z" fill="#282731" opacity=".28"/>${back}
   <g class="avatar-legs"><g class="leg-left"><path d="M8 37H15V45H13V47H6V44H8Z" fill="#292c3d"/><path d="M9 38H13V44H9Z" fill="#596274"/><path d="M6 45H14V48H5V47H6Z" fill="#242331"/><path d="M6 47H14V48H5V47Z" fill="#e2dccd"/></g><g class="leg-right"><path d="M17 37H24V44H26V47H18V45H17Z" fill="#292c3d"/><path d="M18 38H22V44H18Z" fill="#596274"/><path d="M18 45H26V46H28V48H18Z" fill="#242331"/><path d="M18 47H28V48H18Z" fill="#e2dccd"/></g></g>
   <path d="M7 27H12V25H21V27H25V40H7Z" fill="#292735"/><path d="M9 28H23V38H9Z" fill="${p.coat}"/><path d="M9 33H13V38H9ZM20 29H23V38H20Z" fill="${p.shade}"/><path d="M12 27H20V29H18V32H15V29H12Z" fill="#f6edda"/><path d="M15 31H18V37H15Z" fill="#343644"/><path d="M19 30H22V32H19Z" fill="${p.light}"/><path d="M9 37H23V40H9Z" fill="#34313e"/><path d="M13 37H17V39H13Z" fill="#eacb76"/>
   <g class="avatar-arm arm-left"><path d="M6 27H9V37H7V40H3V31H4V28H6Z" fill="#292735"/><path d="M5 30H8V36H4V32H5Z" fill="${p.coat}"/><path d="M4 36H7V39H4Z" fill="#e6b697"/></g><g class="avatar-arm arm-right"><path d="M23 27H26V28H28V31H29V40H25V37H23Z" fill="#292735"/><path d="M24 30H27V32H28V36H24Z" fill="${p.coat}"/><path d="M25 36H28V39H25Z" fill="#e6b697"/></g>
   <path d="M12 23H20V28H12Z" fill="#bb816f"/><path d="M8 9H24V12H26V21H24V24H21V26H12V24H8V21H6V13H8Z" fill="#292735"/><path d="M9 11H23V14H25V20H23V23H20V24H12V23H9V20H7V14H9Z" fill="#edc6a8"/><path d="M8 18H10V22H13V24H12V23H9V20H8Z" fill="#d6a087"/>
   <path d="${fringe}" fill="${p.hair}"/><path d="M9 7H12V5H22V7H18V9H13V10H9Z" fill="${p.hairLight}"/>
   <path d="M10 16H14V20H10ZM19 16H23V20H19Z" fill="#fffbef"/><path d="M11 17H14V20H11ZM19 17H22V20H19Z" fill="${p.eye}"/><path d="M12 17H14V20H12ZM19 17H21V20H19Z" fill="#292735"/><path d="M10 16H12V18H10ZM19 16H21V18H19Z" fill="#ffffff"/><path d="M10 15H14V16H10ZM19 15H23V16H19Z" fill="#292735"/><path d="M15 22H19V23H15Z" fill="#ad6e67"/>
   ${female?`<path d="M25 13H28V15H25Z" fill="${p.coat}"/><path d="M24 21H26V24H24Z" fill="#e7bc65"/>`:`<path d="M6 20H8V22H6Z" fill="#b3bfcb"/>`}
  </g>`;return g;
 }
 let atlasSequence=0;
 function illustratedAvatar(character={}){
  const keys=['mint','blue','violet','coral','gold'],column=Math.max(0,keys.indexOf(character.color)),centers=[258,635,1015,1380,1740],row=character.gender==='female'?1:0;
  const left=centers[column]-110,top=row?393:-4,id='hd-crew-'+(++atlasSequence),g=document.createElementNS(ns,'g');g.classList.add('avatar-body','illustrated-avatar');g.dataset.look=keys[column];
  const image=`<image href="/crew-illustrated.png?v=1" x="${-left}" y="${-top}" width="1983" height="793"/>`;
  g.innerHTML=`<ellipse cx="0" cy="2" rx="24" ry="7" fill="#081525" opacity=".28"/><svg x="-38" y="-138" width="76" height="138" viewBox="0 0 220 404" overflow="visible" aria-hidden="true"><defs><clipPath id="${id}-top"><rect width="220" height="270"/></clipPath><clipPath id="${id}-left"><rect y="265" width="110" height="139"/></clipPath><clipPath id="${id}-right"><rect x="110" y="265" width="110" height="139"/></clipPath></defs><g class="hd-leg-left"><g clip-path="url(#${id}-left)">${image}</g></g><g class="hd-leg-right"><g clip-path="url(#${id}-right)">${image}</g></g><g clip-path="url(#${id}-top)">${image}</g></svg>`;
  return g;
 }
 function avatar(character={}){if(window.GameVisuals?.mode()==='cozy')return window.OfficeCozy.avatar(character);return (window.GameVisuals?.mode()||document.body.dataset.visualMode||'illustrated')==='pixel'?pixelAvatar(character):illustratedAvatar(character);}
 function vectorPortrait(character={}){
  const p=palette(character),female=character.gender==='female',s=svg();s.setAttribute('viewBox','0 0 240 240');s.setAttribute('aria-hidden','true');s.classList.add('crew-portrait-svg');
  const back=female?`<path d="M69 54L89 23L135 15L169 31L186 70L181 119L196 181L157 201L85 183L56 144L66 103Z" fill="${p.hair}" stroke="#292735" stroke-width="3"/>`:`<path d="M73 57L83 30L116 15L153 23L175 46L181 82L168 120L80 122L62 90Z" fill="${p.hair}" stroke="#292735" stroke-width="3"/>`;
  const hair=female?'M70 85L67 62L78 36L107 20L143 23L166 38L177 67L174 99L161 81L153 54L143 77L124 62L116 87L105 59L94 81L85 77L79 104Z':'M67 85L64 62L76 37L95 32L104 19L127 24L144 19L169 43L179 72L171 96L157 79L147 52L138 68L126 56L109 77L99 60L84 84L78 104Z';
  s.innerHTML=`<path d="M0 0H240V240H0Z" fill="#f3ead5"/><path d="M0 16H176L240 80V143L0 207Z" fill="${p.light}"/><path d="M0 190L240 59V87L0 218Z" fill="${p.coat}" opacity=".38"/><path d="M163 0H240V70Z" fill="#2b2934"/><text x="174" y="21" fill="#f5efd9" font-size="10" font-family="monospace">CREW</text>${back}
   <path d="M40 240L48 187L89 159L155 155L199 185L213 240Z" fill="#282a37" stroke="#27242e" stroke-width="4"/><path d="M47 237L56 192L88 173L103 201L95 240Z" fill="${p.coat}"/><path d="M151 169L191 191L207 240H159L146 197Z" fill="${p.coat}"/><path d="M56 204L78 190L73 240H45Z M179 191L195 203L207 240H185Z" fill="${p.shade}"/>
   <path d="M102 132L100 167L119 191L143 165L140 130Z" fill="#d9a18a" stroke="#292735" stroke-width="2"/><path d="M102 143L121 162L142 141L140 130L103 132Z" fill="#ba7f73"/><path d="M97 162L119 179L104 203L86 172Z M145 159L121 178L141 201L158 169Z" fill="#f8f0db" stroke="#292735" stroke-width="2"/><path d="M114 183L124 180L131 192L122 205L128 240H110L116 204L108 195Z" fill="${p.shade}"/>
   <path d="M77 75L89 45L126 34L157 51L167 83L160 120L142 145L120 154L97 144L81 123Z" fill="#efc8ad" stroke="#292735" stroke-width="3"/><path d="M81 83L89 119L104 136L123 146L141 142L120 154L97 144L81 123L77 93Z" fill="#dca58d"/>
   <path d="M80 85L75 83L71 91L77 107L83 110Z M166 85L173 87L172 100L164 108Z" fill="#e6b69a" stroke="#292735" stroke-width="2"/>
   <path d="M89 91L99 85L112 88L116 99L111 109L99 111L89 103Z M131 96L136 87L150 84L160 92L156 106L143 110L133 105Z" fill="#fff9ec" stroke="#2b2934" stroke-width="2.5"/>
   <path d="M100 88L109 89L113 98L109 107L100 109L96 101Z M141 88L150 87L155 94L151 105L142 108L137 101Z" fill="${p.eye}"/><path d="M103 91L109 94L108 105L103 107L100 102Z M145 90L151 93L149 103L144 106L141 101Z" fill="#282b3b"/><path d="M97 90L103 90L104 95L98 97Z M140 90L146 89L147 94L141 96Z" fill="#ffffff"/>
   <path d="M88 91L100 85L112 87 M131 94L139 86L152 84L160 89" fill="none" stroke="#292735" stroke-width="4"/><path d="M119 104L116 118L121 120" fill="none" stroke="#bc8376" stroke-width="1.8"/><path d="M111 132L120 134L130 130" fill="none" stroke="#9e5e66" stroke-width="2.2"/>
   <path d="${hair}" fill="${p.hair}" stroke="#292735" stroke-width="3"/><path d="M79 56L105 33L137 31L151 40L130 38L111 49L106 66L99 47L86 69Z" fill="${p.hairLight}"/><path d="M151 44L162 61L168 88L159 77Z" fill="${p.hairLight}"/>
   ${female?`<path d="M163 65L178 70L176 76L162 71Z" fill="${p.coat}" stroke="#292735" stroke-width="1.5"/><path d="M166 104L171 107L167 120L162 116Z" fill="#d8ae5c"/>`:'<path d="M76 106L82 105L83 112L77 114Z" fill="#c4cbd0" stroke="#292735" stroke-width="1.5"/>'}
   <path d="M65 211L87 201L91 210L70 219Z" fill="${p.light}" stroke="#292735" stroke-width="2"/><path d="M71 208L81 204M73 213L86 207" stroke="#292735" stroke-width="2"/><path d="M170 201L181 207L177 224L166 218Z" fill="#292735"/><path d="M173 208L178 210L175 218L170 215Z" fill="${p.light}"/>
   <path d="M0 230H56V240H0Z M224 207H240V240H224Z" fill="#292735"/><text x="8" y="238" fill="#f5edda" font-size="7" font-family="monospace">OFFICE CREW</text>`;
  return s;
 }
 function portrait(character={}){
  if(window.GameVisuals?.mode()==='cozy')return window.OfficeCozy.portrait(character);
  const s=svg();s.setAttribute('viewBox','0 0 240 240');s.setAttribute('aria-hidden','true');s.classList.add('crew-portrait-svg');
  const keys=['mint','blue','violet','coral','gold'],column=Math.max(0,keys.indexOf(character.color)),row=character.gender==='female'?1:0;
  const cell=svg();cell.setAttribute('x','0');cell.setAttribute('y','0');cell.setAttribute('width','240');cell.setAttribute('height','240');cell.setAttribute('viewBox',`${column*1983/5} ${row*793/2} 396.6 396.5`);cell.setAttribute('preserveAspectRatio','xMidYMid slice');
  const art=document.createElementNS(ns,'image');art.setAttribute('href',(window.GameVisuals?.mode()||'illustrated')==='illustrated'?'/crew-portraits-hd.png?v=1':'/crew-portraits.png?v=1');art.setAttribute('width','1983');art.setAttribute('height','793');art.addEventListener('error',()=>{const fallback=vectorPortrait(character);s.replaceChildren(...Array.from(fallback.childNodes));s.dataset.artFallback='vector';},{once:true});cell.append(art);s.append(cell);return s;
 }
 function preview(host,character){const key=JSON.stringify(character)+':'+(window.GameVisuals?.mode()||'illustrated');if(host.dataset.portrait===key&&host.firstElementChild)return;host.replaceChildren(portrait(character));host.dataset.portrait=key;}
 return {avatar,portrait,preview};
})();
