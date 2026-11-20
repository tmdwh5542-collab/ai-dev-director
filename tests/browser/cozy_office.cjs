/* Real rendered cozy room and direction/stride transitions; isolated data, no AI calls. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-cozy-')),art=path.join(root,'artifacts/cozy-review');fs.mkdirSync(art,{recursive:true});
const server=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[root+'/tests/browser/server.py',temp],{cwd:root,env:{...process.env,DIRECTOR_UI_LEGACY_COMPANY:'1',DIRECTOR_UI_ILLUSTRATED:'1'},stdio:['ignore','pipe','pipe']});let browser,context,errors=[];server.stderr.on('data',()=>{});
(async()=>{try{
 const port=await new Promise((resolve,reject)=>{let s='';server.stdout.on('data',b=>{s+=b;const m=s.match(/^(\d+)$/m);if(m)resolve(m[1])});server.on('exit',()=>reject(Error('fixture exited')))}),base='http://127.0.0.1:'+port;
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});context=await browser.newContext({viewport:{width:1600,height:1100},recordVideo:process.env.DIRECTOR_RECORD_VIDEO?{dir:art,size:{width:1600,height:1100}}:undefined});const page=await context.newPage(),recordingStart=Date.now();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/office');await page.waitForFunction(()=>document.querySelector('#characters .illustrated-avatar'));
 await page.locator('#company-edit').click();await page.locator('#visual-mode').selectOption('cozy');await page.locator('#company-save').click();await page.waitForFunction(()=>document.querySelector('#characters .cozy-avatar'));
 await page.locator('#company-edit').click();
 await page.locator('#owner-gender').selectOption('female');await page.locator('#character-style-gallery button[data-look=mint]').click();
 assert.equal(await page.locator('#owner-color').inputValue(),'mint');
 await page.locator('#character-style-gallery').screenshot({path:path.join(art,'female-presets.png')});
 await page.locator('#owner-gender').selectOption('male');await page.locator('#character-style-gallery button[data-look=blue]').click();
 assert.equal(await page.locator('#owner-preview .cozy-portrait').getAttribute('data-preset'),'blue');
 await page.locator('#character-style-gallery').screenshot({path:path.join(art,'male-presets.png')});
 await page.locator('#company-save').click();await page.waitForFunction(()=>!document.getElementById('company-dialog').open);
 await page.reload();await page.waitForFunction(()=>document.querySelector('#characters .cozy-avatar'));
 const company=await page.evaluate(()=>fetch('/ops/company').then(r=>r.json()));assert.equal(company.company.owner.character.color,'blue');
 const asset=await page.request.get(base+'/crew-portraits-cozy-hd.png');assert.equal(asset.status(),200);
 await page.evaluate(async()=>{const img=new Image();img.src='/crew-portraits-cozy-hd.png';await img.decode();if(img.naturalWidth!==1983)throw Error('portrait atlas missing');});
 await page.locator('#office-scene').scrollIntoViewIfNeeded();await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-ceo.png')});
 await page.screenshot({path:path.join(art,'cozy-full.png')});fs.writeFileSync(path.join(art,'video-walking-offset.json'),JSON.stringify({seconds:(Date.now()-recordingStart)/1000}));
 async function goal(x,y){await page.locator('#office-scene').evaluate((svg,point)=>{const q=new DOMPoint(...point).matrixTransform(svg.getScreenCTM());svg.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:q.x,clientY:q.y}));},[x,y]);}
 const actor=page.locator('[data-character=CEO]'),samples=[];
 for(const [direction,x,y] of [['right',650,365],['left',120,365],['down',120,540],['up',120,300]]){
  await goal(x,y);await page.waitForFunction(dir=>document.querySelector('[data-character=CEO] .cozy-avatar')?.dataset.direction===dir,direction);
  const frames=await actor.locator('.cozy-avatar').evaluate(node=>new Promise(resolve=>{const seen=new Set(),started=performance.now(),timer=setInterval(()=>{seen.add(node.dataset.frame);if(performance.now()-started>650){clearInterval(timer);resolve([...seen]);}},35);}));samples.push([direction,...frames]);
  assert(frames.length>=3,'walking must change several rendered stride drawings: '+direction+' '+JSON.stringify(frames));
  await page.waitForFunction(()=>document.querySelector('[data-character=CEO]').dataset.moving==='false');
  assert.equal(await actor.locator('.cozy-avatar').getAttribute('data-frame'),'0');
 }
 await page.locator('#team-edit').click();await page.waitForFunction(()=>document.getElementById('team-dialog').open);
 const employee=page.locator('.team-member').first();await employee.locator('[data-field=gender]').selectOption('female');await employee.locator('.staff-preset-chooser summary').click();await employee.locator('.staff-preset-chooser button[data-look=gold]').click();
 await employee.locator('.staff-preset-chooser').screenshot({path:path.join(art,'employee-presets.png')});await page.locator('#team-save').click();await page.waitForFunction(()=>!document.getElementById('team-dialog').open);
 const team=await page.evaluate(()=>fetch('/ops/team').then(r=>r.json()));assert.equal(team.team.members[0].character.color,'gold');assert.equal(team.team.members[0].character.gender,'female');
 for(const room of ['planning','development','testing']){await page.locator('[data-department='+room+']').click();await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-'+room+'.png')});}
 await page.locator('#decor-toggle').click();await page.locator('#decor-kind').selectOption('plant');await page.locator('#decor-add').click();await page.locator('#decor-save').click();await page.waitForFunction(()=>document.getElementById('decor-message').textContent.includes('배치를 저장했습니다'));assert(await page.locator('.decor-cozy-art').count());await page.locator('#decor-toggle').click();
 await page.locator('#company-edit').click();await page.locator('#theme-scope').selectOption('all');await page.locator('[data-theme=garden]').click();await page.locator('#company-save').click();await page.waitForFunction(()=>!document.getElementById('company-dialog').open);await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-garden.png')});
 await page.setViewportSize({width:390,height:844});await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-mobile.png')});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.reload();await page.waitForFunction(()=>document.body.dataset.visualMode==='cozy'&&document.querySelector('.cozy-avatar'));assert.equal(await page.locator('.illustrated-avatar').count(),0);assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(art,'stride-samples.json'),JSON.stringify(samples));const video=page.video();await context.close();context=null;if(video)await video.saveAs(path.join(art,'cozy-walking.webm'));
 console.log('PASS cozy: actual 4-direction travel, multiple stride drawings, idle frame, saved theme and custom furniture, reload persistence, mobile width and recorded browser video');
}finally{if(context)await context.close();if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
