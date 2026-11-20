/* Durable launch/control UI regression. Uses only the disposable Python fixture server. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'director-execution-'));
const artifacts=process.env.DIRECTOR_UI_ARTIFACTS||path.join(root,'artifacts');fs.mkdirSync(artifacts,{recursive:true});
const child=spawn(process.env.DIRECTOR_UI_PYTHON||'python',[path.join(__dirname,'server.py'),temp],{cwd:root,stdio:['ignore','pipe','pipe']});
let browser,serverErrors='';child.stderr.on('data',b=>serverErrors+=b);
async function run(){
  const port=await new Promise((resolve,reject)=>{let output='';const t=setTimeout(()=>reject(Error(serverErrors||'Server startup timed out')),15000);child.stdout.on('data',b=>{output+=b;const m=output.match(/^(\d+)$/m);if(m){clearTimeout(t);resolve(m[1]);}});child.once('exit',code=>{clearTimeout(t);reject(Error('Server exited '+code+': '+serverErrors));});});
  browser=await chromium.launch({headless:true,...(process.env.DIRECTOR_UI_CHROMIUM?{executablePath:process.env.DIRECTOR_UI_CHROMIUM}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1440,height:1060},locale:'ko-KR',timezoneId:'Asia/Seoul',reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:'+port;
  await page.goto(base+'/missions');await page.waitForFunction(()=>document.getElementById('stat-all').textContent==='13');
  let launchPosts=0;page.on('request',r=>{if(new URL(r.url()).pathname==='/ops/mission-launch'&&r.method()==='POST')launchPosts++;});
  await page.waitForSelector('#workflow-cards button');assert.equal(await page.locator('#workflow-cards button').count(),3);
  await page.click('#workflow-library');assert.equal(await page.locator('#workflow-library-cards button').count(),7);
  await page.screenshot({path:path.join(artifacts,'workflow-library.png')});
  await page.locator('#workflow-library-cards [data-workflow="test_focus"]').click();
  assert.equal(await page.inputValue('#brief-workflow'),'test_focus');assert.equal(launchPosts,0,'Choosing a workflow must not start a job');
  await page.click('#memory-preview summary');await page.waitForSelector('.memory-record');
  assert((await page.locator('.memory-record').count())<=3);assert.match(await page.locator('#memory-content').innerText(),/Python/);assert.match(await page.locator('#memory-content').innerText(),/검수 PASS/);
  await page.uncheck('#brief-use-memory');await page.fill('#brief-goal','테스트 중심 개발 방식 확인');
  await page.reload();await page.waitForSelector('#workflow-cards button');await page.click('#new-mission');
  assert.equal(await page.inputValue('#brief-workflow'),'test_focus');assert.equal(await page.locator('#brief-use-memory').isChecked(),false);
  await page.locator('#brief-dialog .close-dialog').click();
  const originalProject=await page.evaluate(()=>document.getElementById('brief-project').textContent);
  // Native dialog failures leave a working manual path fallback.
  await page.route('**/ops/pick-folder',r=>r.fulfill({status:409,json:{error:'fixture native dialog unavailable'}}));
  await page.click('#choose-project');await page.waitForSelector('#recent-projects button');
  assert((await page.locator('#recent-projects button').count())>=2);
  await page.click('#browse-project');await page.waitForFunction(()=>!document.getElementById('project-error').hidden);
  const newProject=path.join(path.dirname(originalProject),'새 프로젝트');
  await page.fill('#project-path',newProject);await page.click('#save-project');await page.waitForFunction(()=>!document.getElementById('project-dialog').open);
  await page.waitForFunction(()=>document.getElementById('project-title').textContent.includes('새 프로젝트'));
  assert(fs.existsSync(path.join(newProject,'.git')));
  // Start one captured project/profile and reconnect to its persisted receipt while planning.
  await page.click('#new-mission');await page.fill('#brief-goal','계획 대기 · 실행 센터 확인');await page.fill('#brief-criteria','한글 경로에서 실행');await page.selectOption('#brief-profile','deep');
  const accepted=page.waitForResponse(r=>new URL(r.url()).pathname==='/ops/mission-launch'&&r.request().method()==='POST');
  await page.click('#launch-mission');assert.equal((await accepted).status(),202);
  assert.equal(await page.locator('#choose-project').isDisabled(),true);
  const record=await page.evaluate(()=>JSON.parse(localStorage.getItem('director.mission.launch.v1')));
  assert.equal(record.payload.project_path,newProject);assert.equal(record.payload.profile,'deep');
  assert.equal(record.payload.workflow_id,'test_focus');assert.equal(record.payload.use_project_memory,false);
  await page.reload();await page.waitForFunction(()=>document.getElementById('launch-title').textContent==='미션을 시작했습니다');
  assert.equal(launchPosts,1);
  const receipt=await page.request.get(base+'/ops/mission-launch?request_id='+record.payload.request_id);
  const launchResult=(await receipt.json()).result;assert.equal(launchResult.profile,'deep');assert.equal(launchResult.workflow_id,'test_focus');assert.deepEqual(launchResult.memory_sources,[]);
  await page.screenshot({path:path.join(artifacts,'execution-center-launch.png')});
  await page.getByRole('button',{name:'미션 결과 보기',exact:true}).click();await page.waitForFunction(()=>!document.getElementById('export-report').disabled);assert.match(await page.locator('#detail-content').innerText(),/실행 센터 확인/);assert.match(await page.locator('#detail-content').innerText(),/요청한 개발 방식 · 테스트 중심/);assert.match(await page.locator('#detail-content').innerText(),/기록 참고를 사용하지/);await page.keyboard.press('Escape');
  await page.locator('#launch-actions').getByRole('button',{name:'닫기',exact:true}).click();
  // HEAD questions and rejections are shown as such, never as a successfully running mission.
  await page.click('#new-mission');await page.fill('#brief-goal','확인 질문');await page.click('#launch-mission');await page.waitForFunction(()=>document.getElementById('launch-title').textContent.includes('추가 정보'));assert.match(await page.locator('#launch-message').innerText(),/어떤 화면/);
  await page.locator('#launch-actions').getByRole('button',{name:'닫기',exact:true}).click();
  await page.click('#new-mission');await page.fill('#brief-goal','시작 거절');await page.click('#launch-mission');await page.waitForFunction(()=>document.getElementById('launch-title').textContent==='미션을 시작하지 못했습니다');assert.match(await page.locator('#launch-message').innerText(),/테스트용 시작 거절/);
  await page.locator('#launch-actions').getByRole('button',{name:'닫기',exact:true}).click();
  // Simulate an accepted POST whose response is lost. A receipt lookup recovers it without re-submission.
  await page.route('**/ops/mission-launch',async route=>{if(route.request().method()!=='POST')return route.continue();await route.fetch();await route.abort('connectionreset');});
  await page.click('#new-mission');await page.fill('#brief-goal','응답 유실 복구 확인');await page.click('#launch-mission');await page.waitForFunction(()=>document.getElementById('launch-title').textContent.includes('접수 여부'));
  const postsBeforeCheck=launchPosts;
  await page.locator('#brief-dialog .close-dialog').click();await page.getByRole('button',{name:'접수 확인',exact:true}).click();await page.waitForFunction(()=>document.getElementById('launch-title').textContent==='미션을 시작했습니다');assert.equal(launchPosts,postsBeforeCheck);
  await page.unroute('**/ops/mission-launch');await page.locator('#launch-actions').getByRole('button',{name:'닫기',exact:true}).click();
  // Failure details load verifier output, reviewer feedback and the diff from the real bounded API.
  await page.click('[data-status="FAILED"]');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='2');
  await page.getByRole('button',{name:'사용자 입력 검증 강화 상세 보기',exact:true}).click();await page.waitForFunction(()=>!document.getElementById('export-report').disabled);
  await page.getByRole('button',{name:'실행 로그 · 검수 지적 · 변경 내용 보기',exact:true}).click();await page.waitForSelector('.step-evidence pre');
  assert.match(await page.locator('.step-evidence').innerText(),/종료 코드 1/);assert.match(await page.locator('.step-evidence').innerText(),/빈 입력이 허용됨/);assert.match(await page.locator('.step-evidence').innerText(),/공백 입력도 거부/);assert.equal(await page.locator('.step-evidence img').count(),0);
  await page.locator('.step-evidence summary').click();assert.match(await page.locator('.step-evidence').innerText(),/return value.strip/);
  await page.screenshot({path:path.join(artifacts,'execution-center-evidence.png')});
  await page.getByRole('button',{name:'수정 지시로 재계획',exact:true}).click();assert.match(await page.locator('.control-result').innerText(),/수정 지시를 입력/);
  await page.getByRole('textbox',{name:'미션 수정 지시',exact:true}).fill('공백 입력도 거부하고 회귀 테스트를 추가해줘');
  await page.getByRole('button',{name:'수정 지시로 재계획',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#detail-content .status-pill')?.textContent==='진행 중');await page.keyboard.press('Escape');
  // STOPPED missions can continue from their saved work instead of creating an unrelated new job.
  await page.click('[data-status="STOPPED"]');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='1');await page.locator('.mission-open').click();await page.waitForFunction(()=>!document.getElementById('export-report').disabled);
  await page.getByRole('button',{name:'이어서 진행 · 2단계 추가',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#detail-content .status-pill')?.textContent==='진행 중');await page.keyboard.press('Escape');
  // Conflict feedback stays explicit. The UI does not request skipping conflicting files.
  await page.route('**/ops/mission-control',route=>{const p=route.request().postDataJSON();assert.equal(p.on_conflict,undefined);return route.fulfill({json:{status:'blocked',blocks:['사용자가 수정한 파일']}});});
  await page.fill('#search','로그인 오류');await page.click('[data-status="DONE"]');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='1');await page.locator('.mission-open').click();await page.waitForFunction(()=>!document.getElementById('export-report').disabled);
  await page.getByRole('button',{name:'검증된 결과를 원본에 적용',exact:true}).click();await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('적용 보류'));assert.match(await page.locator('#toast').innerText(),/사용자가 수정한 파일/);await page.keyboard.press('Escape');
  await page.setViewportSize({width:390,height:844});await page.click('#new-mission');assert(await page.evaluate(()=>document.getElementById('brief-dialog').getBoundingClientRect().width<=innerWidth));
  assert(await page.evaluate(()=>{const r=document.getElementById('launch-mission').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}),'Mobile launch button stays visible while the form scrolls');
  await page.screenshot({path:path.join(artifacts,'execution-center-mobile-brief.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: workflow library, no auto execution on choice, bounded verified memory, opt-out persistence, captured workflow/profile/path, project selection, async launch/reconnect, question/rejection, lost response recovery, real failure evidence, replan/resume, conflicts, mobile form.');
}
run().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();child.kill('SIGTERM');fs.rmSync(temp,{recursive:true,force:true});});
