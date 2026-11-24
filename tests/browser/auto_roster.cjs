/* Context-aware recruiting on an isolated company; no provider calls or user data. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-recruit-')),art=path.join(root,'artifacts/auto-roster-review');fs.mkdirSync(art,{recursive:true});
const server=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[root+'/tests/browser/server.py',temp],{cwd:root,env:{...process.env,DIRECTOR_UI_LEGACY_COMPANY:'1',DIRECTOR_UI_COZY:'1',DIRECTOR_UI_AUTO_ROSTER:'1',DIRECTOR_UI_EMPTY_COMPANY:'1'},stdio:['ignore','pipe','pipe']});let browser;server.stderr.on('data',()=>{});
(async()=>{try{
 const port=await new Promise((resolve,reject)=>{let s='';server.stdout.on('data',b=>{s+=b;const m=s.match(/^(\d+)$/m);if(m)resolve(m[1])});server.on('exit',()=>reject(Error('fixture exited')))}),base='http://127.0.0.1:'+port;
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const initial=(await (await page.request.get(base+'/ops/team')).json()).team;assert.equal(initial.members.length,0);
 await page.goto(base+'/office');await page.waitForFunction(()=>document.getElementById('team-summary').textContent.includes('재직 28명'));
 const saved=(await (await page.request.get(base+'/ops/team')).json()).team;assert.equal(saved.members.length,28);
 assert.equal(await page.locator('.staff-member').count(),4);assert.equal(await page.locator('[data-department=planning]').getAttribute('aria-pressed'),'true');
 assert.deepEqual(new Set(saved.members.map(m=>m.department)),new Set(['planning','design','development','level','testing','quality','support']));
 await page.locator('#refresh').click();await page.waitForTimeout(500);assert.deepEqual((await (await page.request.get(base+'/ops/team')).json()).team,saved);
 await page.locator('.office-panel').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(art,'automatic-28-staff.png')});
 await page.reload();await page.waitForFunction(()=>document.getElementById('team-summary').textContent.includes('재직 28명'));assert.deepEqual((await (await page.request.get(base+'/ops/team')).json()).team,saved);
 const edited=JSON.parse(JSON.stringify(saved)),removed=edited.members.pop();edited.active_staff_ids=edited.active_staff_ids.filter(id=>id!==removed.id);edited.members[0].name='내 직원 이름';
 const roles=await (await page.request.get(base+'/ops/roles')).json();const response=await page.request.post(base+'/ops/team',{headers:{'X-Solomon-Bridge':roles.csrf},data:{team:edited,expected_revision:saved.revision}});assert.equal(response.status(),200);
 await page.reload();await page.waitForFunction(()=>document.getElementById('team-summary').textContent.includes('재직 27명'));await page.waitForTimeout(3500);
 const last=(await (await page.request.get(base+'/ops/team')).json()).team;assert.equal(last.members.length,27);assert.equal(last.members[0].name,'내 직원 이름');assert.deepEqual(errors,[]);
 console.log('PASS real first-entry automatic bootstrap: zero saved staff to 28, current department actors visible, refresh/reload idempotence, durable roster, later manual edits preserved, no AI setup or paid call');
}finally{if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
