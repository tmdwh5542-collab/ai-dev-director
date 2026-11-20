/* Real workshop polling/navigation regression against isolated fixtures; no AI CLI calls. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=mkdtempSync(path.join(tmpdir(),'director-workshop-'));
const server=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[path.join(__dirname,'server.py'),temp],{cwd:root,stdio:['ignore','pipe','pipe']});
let errors='',browser;server.stderr.on('data',b=>errors+=b);
(async()=>{
 try{
  const port=await new Promise((resolve,reject)=>{let output='';const timeout=setTimeout(()=>reject(Error('server timeout '+errors)),20000);server.stdout.on('data',b=>{output+=b;const m=output.match(/^(\d+)$/m);if(m){clearTimeout(timeout);resolve(m[1]);}});server.once('exit',()=>{clearTimeout(timeout);reject(Error(errors));});});
  browser=await chromium.launch({headless:true,executablePath:process.env.DIRECTOR_UI_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});
  const page=await browser.newPage(),pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));
  await page.goto('http://127.0.0.1:'+port+'/');await page.click('#tab-workshop');
  const frame=page.frameLocator('#workspace');await frame.locator('#ai-mission details').first().waitFor();
  const result=await page.evaluate(async()=>{
   const d=document.getElementById('workspace').contentDocument;
   const a=await fetch('/ops/activity').then(r=>r.json());
   const focus=a.missions.find(m=>m.mission_id===a.focus_mission_id);
   paintMission(focus);const details=d.querySelector('#ai-mission details');details.open=true;
   const summary=details.querySelector('summary');summary.tabIndex=0;summary.focus();
   paintMission(focus);
   const sameDetails=details===d.querySelector('#ai-mission details')&&details.open&&d.activeElement===summary;
   const work={working_now:[{role:'BUILDER',provider:'GOOGLE',elapsed_sec:1}]};
   paintNow(work,focus);const dot=d.querySelector('#ai-now .dot');
   work.working_now[0].elapsed_sec=17;paintNow(work,focus);
   return {sameDetails,sameDot:dot===d.querySelector('#ai-now .dot'),updated:d.querySelector('#ai-now').textContent.includes('17초')};
  });
  assert.deepEqual(result,{sameDetails:true,sameDot:true,updated:true});
  // Actual user actions must retain the iframe document and the parent app.
  await frame.locator('#chat-input').evaluate(n=>{n.ownerDocument.defaultView.__stabilityMarker='kept';n.value='보관할 입력';});
  await frame.locator('#new-chat-btn').click();
  await page.waitForFunction(()=>!document.getElementById('workspace').contentDocument.getElementById('new-chat-btn').disabled);
  await frame.getByRole('button',{name:'경로 직접 입력',exact:true}).click();
  await frame.locator('#project-input').fill(path.join(temp,'task-manager'));
  await frame.locator('#project-btn').click();
  await page.waitForFunction(()=>!document.getElementById('workspace').contentDocument.getElementById('project-btn').disabled);
  assert.equal(await frame.locator('body').evaluate(n=>n.ownerDocument.defaultView.__stabilityMarker),'kept');
  await page.waitForTimeout(5500);
  assert.equal(await frame.locator('body').evaluate(n=>n.ownerDocument.defaultView.__stabilityMarker),'kept');
  assert.deepEqual(pageErrors,[]);
  console.log('PASS: polling preserves nodes/details/focus; new chat and project selection retain iframe across subsequent polling');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
