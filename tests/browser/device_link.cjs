/* Real HTTPS gateway, independent desktop/phone/tablet sessions; fake AI/engine fixture only. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-device-ui-'));
const child=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[path.join(__dirname,'server.py'),temp],{cwd:root,env:{...process.env,DIRECTOR_UI_LEGACY_COMPANY:'1',DIRECTOR_UI_DEVICE_CHAT:'1'},stdio:['ignore','pipe','pipe']});let browser,serverErrors='';child.stderr.on('data',x=>serverErrors+=x);
function freePort(){return new Promise((resolve,reject)=>{const server=net.createServer();server.on('error',reject);server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});}
(async()=>{try{
 const port=await new Promise((resolve,reject)=>{let out='';const timer=setTimeout(()=>reject(Error(serverErrors||'startup timeout')),20000);child.stdout.on('data',b=>{out+=b;const m=out.match(/^(\d+)$/m);if(m){clearTimeout(timer);resolve(m[1]);}});child.once('exit',()=>{clearTimeout(timer);reject(Error(serverErrors));});});
 const base='http://127.0.0.1:'+port,gatewayPort=await freePort(),secure='https://127.0.0.1:'+gatewayPort;
 browser=await chromium.launch({headless:true,executablePath:process.env.DIRECTOR_UI_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox','--disable-gpu']});
 const pc=await browser.newPage({viewport:{width:1512,height:1100},locale:'ko-KR'}),errors=[];pc.on('pageerror',e=>errors.push(e.message));
 await pc.goto(base+'/devices');await pc.waitForFunction(()=>document.getElementById('device-address').options.length>0);
 assert.match(await pc.locator('#device-state').innerText(),/꺼짐/);
 await pc.locator('#device-address').selectOption('127.0.0.1');await pc.locator('#device-port').fill(String(gatewayPort));await pc.locator('#device-enable').click();await pc.waitForFunction(()=>document.getElementById('device-link-info').hidden===false);
 assert.equal(await pc.locator('#device-url').innerText(),secure+'/pair');await pc.waitForFunction(()=>document.getElementById('device-qr').complete&&document.getElementById('device-qr').naturalWidth>0);
 const artifacts=path.join(root,'artifacts');fs.mkdirSync(artifacts,{recursive:true});
 const phoneContext=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,ignoreHTTPSErrors:true,locale:'ko-KR'}),phone=await phoneContext.newPage();phone.on('pageerror',e=>errors.push(e.message));
 await phone.goto(secure+'/office');await phone.waitForURL('**/pair');
 await pc.locator('#device-new-code').click();await pc.waitForFunction(()=>/^\d{8}$/.test(document.getElementById('device-code').textContent));const code=await pc.locator('#device-code').innerText();
 await pc.screenshot({path:path.join(artifacts,'device-link-pc.png'),fullPage:true});
 await phone.locator('#pair-name').fill('집 휴대폰');await phone.locator('#pair-code').fill(code);await phone.locator('#pair-submit').click();await phone.waitForURL('**/office');await phone.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 assert.equal(await phone.evaluate(()=>isSecureContext),true);assert.equal(await phone.locator('.remote-banner').count(),1);
 assert.equal(await phone.locator('#header-shutdown').isVisible(),false);assert.equal(await phone.locator('a[href="/devices"]').isVisible(),false);
 assert(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 const cookies=await phoneContext.cookies();assert(cookies.some(c=>c.name==='director_device'&&c.secure&&c.httpOnly&&c.sameSite==='Strict'));
 // One-time code cannot be reused by another device.
 const tabletContext=await browser.newContext({viewport:{width:1024,height:1366},hasTouch:true,ignoreHTTPSErrors:true,locale:'ko-KR'}),tablet=await tabletContext.newPage();tablet.on('pageerror',e=>errors.push(e.message));
 await tablet.goto(secure+'/pair');await tablet.locator('#pair-name').fill('집 태블릿');await tablet.locator('#pair-code').fill(code);await tablet.locator('#pair-submit').click();await tablet.waitForFunction(()=>!document.getElementById('pair-error').hidden);assert.match(await tablet.locator('#pair-error').innerText(),/틀리거나 만료/);
 const codeResponse=pc.waitForResponse(r=>r.url()===base+'/ops/devices'&&r.request().method()==='POST'&&r.request().postDataJSON().action==='code');await pc.locator('#device-new-code').click();const next=(await (await codeResponse).json()).code;await tablet.locator('#pair-code').fill(next);await tablet.locator('#pair-submit').click();await tablet.waitForURL('**/office');await tablet.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 // Edit a shared staff member from a phone, then observe the same persisted data from the PC and tablet.
 await phone.locator('#team-edit').click();await phone.waitForFunction(()=>document.getElementById('team-dialog').open);await phone.locator('[data-member=planner] [data-field=name]').fill('모바일 기획 과장');await phone.locator('#team-save').click();await phone.waitForFunction(()=>!document.getElementById('team-dialog').open);
 const localTeam=await (await pc.request.get(base+'/ops/team')).json();assert.equal(localTeam.team.members[0].name,'모바일 기획 과장');
 await tablet.locator('[data-department=planning]').click();await tablet.locator('#refresh').click();await tablet.waitForFunction(()=>document.querySelector('#station-planner .staff-name')?.textContent.includes('모바일'));
 await phone.screenshot({path:path.join(artifacts,'device-link-phone.png'),fullPage:true});await tablet.locator('.workspace').screenshot({path:path.join(artifacts,'device-link-tablet.png')});
 // Room decoration is shared through the authenticated HTTPS gateway, not device-local storage.
 await phone.locator('#decor-toggle').click();await phone.locator('#decor-desk').selectOption('wood');await phone.locator('#decor-save').click();await phone.waitForFunction(()=>document.getElementById('decor-message').textContent.includes('배치를 저장했습니다'));
 const sharedLayout=await (await pc.request.get(base+'/ops/office-layout')).json();assert.equal(sharedLayout.rooms.ceo.desk,'wood');
 await tablet.locator('[data-department=ceo]').click();await tablet.locator('#refresh').click();await tablet.waitForFunction(()=>getComputedStyle(document.querySelector('#station-CEO .modern-desktop')).fill==='rgb(216, 180, 141)');
 // Paired devices can monitor/approve scheduling, while OAuth, PC files and plan edits stay PC-only.
 await phone.goto(secure+'/automation');await phone.waitForFunction(()=>document.getElementById('auto-today')?.children.length===4);
 assert.equal(await phone.locator('#youtube-settings').isVisible(),false);assert.equal(await phone.locator('#auto-asset-panel').isVisible(),false);assert.equal(await phone.locator('#plan-editor').isVisible(),false);
 for(const endpoint of ['/ops/youtube','/ops/automation/asset'])assert.equal(await phone.evaluate(async endpoint=>(await fetch(endpoint)).status,endpoint),403);
 const planDenied=await phone.evaluate(async()=>{const a=await fetch('/ops/roles').then(r=>r.json());return (await fetch('/ops/automation',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':a.csrf},body:JSON.stringify({action:'plan'})})).status;});assert.equal(planDenied,403);
 // Registered PC projects can be selected and launched remotely; the durable receipt is shared.
 await phone.goto(secure+'/missions');await phone.waitForFunction(()=>document.getElementById('project-title').textContent!=='작업 환경 확인 중');
 const choices=await (await pc.request.get(base+'/ops/projects')).json();const selectedProject=choices.projects.find(p=>p.path.endsWith('task-manager'));assert(selectedProject);
 const selected=await phone.evaluate(async path=>{const r=await fetch('/project',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body:new URLSearchParams({path})});return r.json();},selectedProject.path);assert.equal(selected.status,'ok');
 const officeTelemetry=await phone.evaluate(async()=>fetch('/ops/office').then(r=>r.json()));assert(!JSON.stringify(officeTelemetry).includes('ui-test-token'));for(const endpoint of ['/settings','/ops/ai-connections','/ops/skill-library'])assert.equal(await phone.evaluate(async endpoint=>(await fetch(endpoint)).status,endpoint),403);
 let bridgeLeaked=false;const roles=await phone.evaluate(async()=>fetch('/ops/roles').then(r=>r.json()));assert.notEqual(roles.csrf,'ui-test-token');
 const launch=await phone.evaluate(async({path,csrf})=>{const response=await fetch('/ops/mission-launch',{method:'POST',headers:{'Content-Type':'application/json','X-Solomon-Bridge':csrf},body:JSON.stringify({request_id:'phone-persistent-launch-123',project_path:path,goal:'휴대폰에서 요청한 Godot HUD 개선',profile:'quick',workflow_id:'game',use_project_memory:true})});return {status:response.status,body:await response.json()};},{path:selectedProject.path,csrf:roles.csrf});assert.equal(launch.status,202,JSON.stringify(launch));
 await phone.goto(secure+'/office');await phone.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 const receipt=await pc.request.get(base+'/ops/mission-launch?request_id=phone-persistent-launch-123');assert.equal((await receipt.json()).state,'started');
 const forbidden=await phone.evaluate(async()=>{const r=await fetch('/ops/shutdown',{method:'POST'});return r.status;});assert.equal(forbidden,403);
 await phone.goto(secure+'/classic');await phone.waitForSelector('#chat-input');assert.equal(await phone.locator('.remote-banner').count(),1);await phone.locator('#chat-input').fill('현재 게임 프로젝트의 진행 상황을 알려줘');await phone.locator('#chat-form button[type=submit]').click();await phone.waitForFunction(()=>document.getElementById('chat-box').textContent.includes('검증 응답: 현재 게임 프로젝트'));const localChat=await (await pc.request.get(base+'/chat/messages?after_id=0')).json();assert(localChat.messages.some(m=>m.role==='HEAD'&&m.content.includes('검증 응답: 현재 게임 프로젝트')));
 await phone.goto(secure+'/office');await phone.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 // Browser background/reload keeps the paired session. Network loss does not fabricate a successful call.
 await phone.reload();await phone.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 await phoneContext.setOffline(true);await phone.locator('#remote-refresh').click();await phone.waitForFunction(()=>document.querySelector('.remote-banner').dataset.state==='offline');
 await phoneContext.setOffline(false);await phone.locator('#remote-refresh').click();await phone.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 await pc.locator('#device-refresh').click();await pc.waitForFunction(()=>document.querySelectorAll('.paired-row').length===2);
 const row=pc.locator('.paired-row').filter({hasText:'집 휴대폰'});await row.locator('button').click();await phone.locator('#remote-refresh').click();await phone.waitForURL('**/pair?expired=1');
 await tablet.locator('#refresh').click();await tablet.waitForFunction(()=>document.getElementById('connection').textContent==='실시간 연결');
 pc.once('dialog',d=>d.accept());await pc.locator('#device-disable').click();await pc.waitForFunction(()=>document.getElementById('device-link-info').hidden);
 assert.equal((await pc.request.get(base+'/ops/team')).ok(),true,'Disabling remote access leaves the PC running');
 assert.deepEqual(errors,[]);console.log('PASS: real HTTPS pairing and QR, secure per-device cookies, one-time code, separate phone/tablet contexts, cross-device staff sync, registered project selection, durable launch, no bridge-token leak, PC-only endpoints blocked, classic chat page, mobile/tablet layouts, reload/offline/reconnect, individual revoke and gateway disable without stopping PC');
 await phoneContext.close();await tabletContext.close();
 }finally{if(browser)await browser.close();child.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
