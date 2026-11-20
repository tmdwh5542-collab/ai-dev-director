/* Real rendered cozy room and direction/stride transitions; isolated data, no AI calls. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-cozy-')),art=path.join(root,'artifacts/cozy-review');fs.mkdirSync(art,{recursive:true});
const server=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[root+'/tests/browser/server.py',temp],{cwd:root,env:{...process.env,DIRECTOR_UI_LEGACY_COMPANY:'1',DIRECTOR_UI_ILLUSTRATED:'1'},stdio:['ignore','pipe','pipe']});let browser,context,errors=[];server.stderr.on('data',()=>{});
(async()=>{try{
 const port=await new Promise((resolve,reject)=>{let s='';server.stdout.on('data',b=>{s+=b;const m=s.match(/^(\d+)$/m);if(m)resolve(m[1])});server.on('exit',()=>reject(Error('fixture exited')))}),base='http://127.0.0.1:'+port;
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});context=await browser.newContext({viewport:{width:1600,height:1100},recordVideo:process.env.DIRECTOR_RECORD_VIDEO?{dir:art,size:{width:1600,height:1100}}:undefined});const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/office');await page.waitForFunction(()=>document.querySelector('#characters .illustrated-avatar'));
 await page.locator('#company-edit').click();await page.locator('#visual-mode').selectOption('cozy');await page.locator('#company-save').click();await page.waitForFunction(()=>document.querySelector('#characters .cozy-avatar'));
 await page.locator('#office-scene').scrollIntoViewIfNeeded();await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-ceo.png')});
 async function goal(x,y){await page.locator('#office-scene').evaluate((svg,point)=>{const q=new DOMPoint(...point).matrixTransform(svg.getScreenCTM());svg.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:q.x,clientY:q.y}));},[x,y]);}
 const actor=page.locator('[data-character=CEO]'),samples=[];
 for(const [direction,x,y] of [['right',650,365],['left',120,365],['down',120,540],['up',120,300]]){
  await goal(x,y);await page.waitForFunction(dir=>document.querySelector('[data-character=CEO] .cozy-avatar')?.dataset.direction===dir,direction);
  const frames=new Set();for(let i=0;i<7;i++){await page.waitForTimeout(90);const f=await actor.locator('.cozy-avatar').getAttribute('data-frame');frames.add(f);samples.push([direction,f]);if(i===1||i===3)await actor.locator('.cozy-avatar').screenshot({path:path.join(art,'walk-'+direction+'-'+i+'.png')});}
  assert(frames.size>=3,'walking must change several rendered stride drawings');
  await page.waitForFunction(()=>document.querySelector('[data-character=CEO]').dataset.moving==='false');
  assert.equal(await actor.locator('.cozy-avatar').getAttribute('data-frame'),'0');
 }
 for(const room of ['planning','development','testing']){await page.locator('[data-department='+room+']').click();await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-'+room+'.png')});}
 await page.locator('#decor-toggle').click();await page.locator('#decor-kind').selectOption('plant');await page.locator('#decor-add').click();await page.locator('#decor-save').click();await page.waitForFunction(()=>document.getElementById('decor-message').textContent.includes('배치를 저장했습니다'));assert(await page.locator('.decor-cozy-art').count());await page.locator('#decor-toggle').click();
 await page.locator('#company-edit').click();await page.locator('#theme-scope').selectOption('all');await page.locator('[data-theme=garden]').click();await page.locator('#company-save').click();await page.waitForFunction(()=>!document.getElementById('company-dialog').open);await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-garden.png')});
 await page.setViewportSize({width:390,height:844});await page.locator('.office-panel').screenshot({path:path.join(art,'cozy-mobile.png')});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.reload();await page.waitForFunction(()=>document.body.dataset.visualMode==='cozy'&&document.querySelector('.cozy-avatar'));assert.equal(await page.locator('.illustrated-avatar').count(),0);assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(art,'stride-samples.json'),JSON.stringify(samples));const video=page.video();await context.close();context=null;if(video)await video.saveAs(path.join(art,'cozy-walking.webm'));
 console.log('PASS cozy: actual 4-direction travel, multiple stride drawings, idle frame, saved theme and custom furniture, reload persistence, mobile width and recorded browser video');
}finally{if(context)await context.close();if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
