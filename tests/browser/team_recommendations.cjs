/* Context-aware recruiting on an isolated company; no provider calls or user data. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-recruit-')),art=path.join(root,'artifacts/recruit-review');fs.mkdirSync(art,{recursive:true});
const server=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[root+'/tests/browser/server.py',temp],{cwd:root,env:{...process.env,DIRECTOR_UI_LEGACY_COMPANY:'1'},stdio:['ignore','pipe','pipe']});let browser;server.stderr.on('data',()=>{});
(async()=>{try{
 const port=await new Promise((resolve,reject)=>{let s='';server.stdout.on('data',b=>{s+=b;const m=s.match(/^(\d+)$/m);if(m)resolve(m[1])});server.on('exit',()=>reject(Error('fixture exited')))}),base='http://127.0.0.1:'+port;
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/office');await page.waitForFunction(()=>document.querySelector('.office-character'));
 await page.locator('#company-edit').click();await page.locator('#visual-mode').selectOption('cozy');await page.locator('#company-save').click();await page.waitForFunction(()=>document.body.dataset.visualMode==='cozy');
 await page.locator('#team-edit').click();await page.waitForFunction(()=>document.getElementById('team-dialog').open);
 await page.locator('#team-recommend-policy').selectOption('specialty');
 const old=await (await page.request.get(base+'/ops/team')).json();assert.equal(old.team.members.length,6);
 // Recommendations must analyze this unsaved draft, not replace it with the saved six-person team.
 while(await page.locator('.team-member').count())await page.locator('.team-remove').first().click();
 await page.locator('#team-recommend-goal').fill('Godot 게임의 전투, HUD, 맵, 사운드와 테스트');await page.locator('#team-recommend').click();await page.waitForFunction(()=>document.querySelectorAll('.team-recommend-card').length>=6);
 assert.equal(await page.locator('.team-member').count(),0);assert.deepEqual((await (await page.request.get(base+'/ops/team')).json()).team,old.team);
 await page.locator('#team-dialog').evaluate(d=>{d.scrollTop+=document.querySelector('.team-recommend-panel').getBoundingClientRect().top-d.getBoundingClientRect().top-110;});await page.screenshot({path:path.join(art,'team-recommendations-desktop.png')});
 // A sound team member depends on the proposed design manager; adding this employee adds both.
 await page.locator('.team-recommend-card').filter({hasText:'사운드 개발자'}).locator('button').click();
 assert.equal(await page.locator('.team-member').count(),2);const first=page.locator('.team-member').first();assert.equal(await first.locator('[data-field=specialty]').inputValue(),'ui');assert.equal(await first.locator('[data-field=position]').inputValue(),'manager');
 await page.locator('#team-recommend-all').click();const count=await page.locator('.team-member').count();assert(count>=6&&count<=28);
 await page.locator('.team-member').first().locator('[data-field=name]').fill('우리 기획 담당');assert.equal(await page.locator('.team-recommend-card').count(),0);
 await page.locator('#team-recommend').click();await page.waitForFunction(()=>document.getElementById('team-recommend-summary').textContent.includes('채용 0명'));
 assert.equal(await page.locator('.team-recommend-card').count(),0);assert.match(await page.locator('#team-recommend-results').innerText(),/추가 채용이 필요하지 않습니다/);
 await page.locator('#team-save').click();await page.waitForFunction(()=>!document.getElementById('team-dialog').open);await page.reload();await page.waitForFunction(()=>document.querySelector('.office-character'));
 const saved=(await (await page.request.get(base+'/ops/team')).json()).team;assert.equal(saved.members.length,count);assert.equal(saved.members[0].name,'우리 기획 담당');
 for(const dept of Object.keys(old.departments)){const people=saved.members.filter(m=>m.department===dept);assert(people.length<=4);if(people.length)assert.equal(people.filter(m=>m.position==='manager').length,1);}
 assert(['HEAD','BUILDER','REVIEWER'].every(slot=>saved.members.some(m=>m.slot===slot)));
 await page.locator('#team-edit').click();await page.locator('#team-recommend-policy').selectOption('specialty');await page.locator('#team-recommend-goal').fill('audio 사운드 기능 1건');await page.setViewportSize({width:390,height:844});await page.locator('#team-recommend').click();await page.waitForFunction(()=>document.getElementById('team-recommend-summary').textContent.includes('채용 0명'));
 await page.locator('#team-dialog').evaluate(d=>{d.scrollTop+=document.querySelector('.team-recommend-panel').getBoundingClientRect().top-d.getBoundingClientRect().top-110;});await page.screenshot({path:path.join(art,'team-recommendations-mobile.png')});assert(await page.locator('#team-dialog').evaluate(n=>n.scrollWidth<=n.clientWidth+1));
 // Changes in another window invalidate the server revision without discarding this window's draft.
 const roles=await (await page.request.get(base+'/ops/roles')).json(),remote=JSON.parse(JSON.stringify(saved));remote.members[0].name='다른 창 변경';const response=await page.request.post(base+'/ops/team',{headers:{'X-Solomon-Bridge':roles.csrf},data:{team:remote,expected_revision:saved.revision}});assert.equal(response.status(),200);
 await page.locator('#team-recommend').click();await page.waitForFunction(()=>document.getElementById('team-error').textContent.includes('다른 창'));
 assert.equal(await page.locator('.team-member').first().locator('[data-field=name]').inputValue(),'우리 기획 담당');assert.equal(await page.locator('.team-recommend-card').count(),0);assert.deepEqual(errors,[]);
 console.log('PASS recruiting: unsaved draft and unfinished workload, automatic role/department/position, dependent manager, individual/all proposals, invalidation after edits, no duplicate hires, persistence, capacity, mobile and concurrent-window conflict (no AI calls)');
}finally{if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
