/* Context-aware recruiting on an isolated company; no provider calls or user data. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-recruit-')),art=path.join(root,'artifacts/game-team-review');fs.mkdirSync(art,{recursive:true});
const server=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[root+'/tests/browser/server.py',temp],{cwd:root,env:{...process.env,DIRECTOR_UI_LEGACY_COMPANY:'1'},stdio:['ignore','pipe','pipe']});let browser;server.stderr.on('data',()=>{});
(async()=>{try{
 const port=await new Promise((resolve,reject)=>{let s='';server.stdout.on('data',b=>{s+=b;const m=s.match(/^(\d+)$/m);if(m)resolve(m[1])});server.on('exit',()=>reject(Error('fixture exited')))}),base='http://127.0.0.1:'+port;
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/office');await page.waitForFunction(()=>document.querySelector('.office-character'));
 await page.locator('#company-edit').click();await page.locator('#visual-mode').selectOption('cozy');await page.locator('#company-save').click();await page.waitForFunction(()=>document.body.dataset.visualMode==='cozy');
 await page.locator('#team-edit').click();await page.waitForFunction(()=>document.getElementById('team-dialog').open);
 assert.equal(await page.locator('#team-recommend-policy').inputValue(),'game_departments');
 await page.locator('#team-recommend-goal').fill('Godot 게임의 전투와 맵을 만들고 테스트');
 await page.locator('#team-recommend').click();await page.waitForFunction(()=>document.querySelector('.game-department-plan li'));
 assert.equal(await page.locator('.game-department-plan li').count(),7);
 const before=(await (await page.request.get(base+'/ops/team')).json()).team;assert.equal(before.members.length,6);
 await page.locator('#team-game-ready').click();await page.waitForSelector('#team-game-start');
 const saved=(await (await page.request.get(base+'/ops/team')).json()).team;
 for(const d of ['planning','design','development','level','testing','quality','support']){const staff=saved.members.filter(m=>m.department===d||(!m.department&&({planning:'planning',ui:'design',gameplay:'development',level:'level',testing:'testing',quality:'quality'}[m.specialty]===d)));assert(staff.length>=1&&staff.length<=2);}
 assert(saved.members.slice(0,6).every((m,i)=>m.id===before.members[i].id&&m.name===before.members[i].name));
 assert.match(await page.locator('#team-game-checks').innerText(),/실제 PC 검증 필요/);
 await page.locator('#team-dialog').evaluate(d=>{d.scrollTop+=document.getElementById('team-game-checks').getBoundingClientRect().top-d.getBoundingClientRect().top-100;});await page.screenshot({path:path.join(art,'game-team-ready-desktop.png')});
 const count=saved.members.length;await page.locator('#team-game-ready').click();await page.waitForSelector('#team-game-start');assert.equal((await (await page.request.get(base+'/ops/team')).json()).team.members.length,count);
 await page.setViewportSize({width:390,height:844});await page.locator('#team-dialog').evaluate(d=>{d.scrollTop+=document.getElementById('team-game-checks').getBoundingClientRect().top-d.getBoundingClientRect().top-100;});await page.screenshot({path:path.join(art,'game-team-ready-mobile.png')});assert(await page.locator('#team-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1));
 await page.locator('#team-game-start').click();await page.waitForURL('**/missions#new');await page.waitForFunction(()=>document.getElementById('brief-workflow').value==='game');assert.equal(await page.locator('#brief-profile').inputValue(),'standard');assert((await page.locator('#brief-goal').inputValue()).length>0);assert((await page.locator('#brief-criteria').inputValue()).length>0);assert.deepEqual(errors,[]);
 console.log('PASS game setup: 7 staffed departments at 1/2 people, atomic roster save, original staff retained, repeat safety, honest checks, mobile and game workflow/criteria handoff without AI calls');
}finally{if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exitCode=1});
