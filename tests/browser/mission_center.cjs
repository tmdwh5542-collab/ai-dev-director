/* Optional browser regression: npm install --no-save playwright
   DIRECTOR_UI_PYTHON=.venv/bin/python node tests/browser/mission_center.cjs
   Uses a disposable server/database; never starts real AI CLIs. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {mkdtempSync,mkdirSync,readFileSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),temp=mkdtempSync(path.join(tmpdir(),'director-ui-'));
const artifacts=process.env.DIRECTOR_UI_ARTIFACTS||path.join(root,'artifacts');mkdirSync(artifacts,{recursive:true});
const python=process.env.DIRECTOR_UI_PYTHON||'python';
const server=spawn(python,[path.join(__dirname,'server.py'),temp],{cwd:root,stdio:['ignore','pipe','pipe']});
let serverErrors='';server.stderr.on('data',b=>serverErrors+=b);
let browser;
async function text(page,selector){return page.locator(selector).innerText();}
async function run(){
  const port=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Fixture server startup timed out: '+serverErrors)),20000);server.stdout.on('data',b=>{output+=b;const match=output.match(/^(\d+)$/m);if(match){clearTimeout(timer);resolve(match[1]);}});server.once('exit',code=>{clearTimeout(timer);reject(Error('Fixture server exited '+code+': '+serverErrors));});});
  const base='http://127.0.0.1:'+port;
  const executablePath=process.env.DIRECTOR_UI_CHROMIUM;
  browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{}),args:['--no-sandbox','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1440,height:1080},locale:'ko-KR',timezoneId:'Asia/Seoul',reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/missions');await page.waitForFunction(()=>document.getElementById('stat-all').textContent==='13');
  assert.equal(await page.locator('#mission-list tr').count(),10);
  assert.equal(await text(page,'#stat-done'),'7');
  assert.equal(await text(page,'#stat-attention'),'4');
  await page.screenshot({path:path.join(artifacts,'mission-center-desktop.png'),fullPage:true});
  await page.click('#next');await page.waitForFunction(()=>document.getElementById('page-number').textContent==='2 / 2');
  assert.equal(await page.locator('#mission-list tr').count(),3);
  // Untrusted mission text is displayed as text, never interpreted as markup.
  assert.equal(await page.locator('#mission-list img').count(),0);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  await page.click('#previous');await page.waitForFunction(()=>document.getElementById('page-number').textContent==='1 / 2');
  await page.fill('#search','모바일');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='1');
  await page.click('.mission-open');await page.waitForFunction(()=>document.getElementById('export-report').disabled===false);
  assert.match(await text(page,'#detail-content'),/12\/12 통과/);
  assert.match(await text(page,'#detail-content'),/원본에 적용됨/);
  const downloadPromise=page.waitForEvent('download');await page.click('#export-report');const download=await downloadPromise;
  const report=readFileSync(await download.path(),'utf8');assert.match(report,/모바일 화면/);assert.match(report,/검수: PASS/);assert.match(report,/REVIEWER \/ OPENAI/);
  await page.screenshot({path:path.join(artifacts,'mission-center-report.png'),fullPage:true});
  await page.keyboard.press('Escape');
  await page.fill('#search','존재하지않는검색');await page.waitForFunction(()=>!document.getElementById('empty-state').hidden);
  assert.match(await text(page,'#empty-title'),/조건에 맞는/);await page.click('#empty-action');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='13');
  await page.click('[data-status="BLOCKED"]');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='1');assert.match(await text(page,'#mission-list'),/확인 필요/);
  await page.click('[data-status=""]');await page.waitForFunction(()=>document.getElementById('result-count').textContent==='13');
  // Drafts persist across reload, then transfer to the stage without submitting.
  await page.click('#new-mission');await page.fill('#brief-goal','검색 필터를 개선해줘');await page.fill('#brief-criteria','한글 검색과 모바일 화면을 확인해줘');await page.fill('#brief-scope','기존 로그인 유지');
  await page.reload();await page.click('#new-mission');assert.equal(await page.inputValue('#brief-goal'),'검색 필터를 개선해줘');
  await page.click('#brief-form button[type="submit"]');await page.waitForURL(base+'/');
  await page.waitForFunction(()=>document.getElementById('chat-text').value.includes('검색 필터를 개선해줘'));
  const draft=await page.inputValue('#chat-text');assert.match(draft,/완료 조건/);assert.match(draft,/기존 로그인 유지/);assert.match(draft,/\[자동 절차\]/);
  let calls=0,requestIds=[];
  await page.route('**/chat',async route=>{calls++;requestIds.push(new URLSearchParams(route.request().postData()).get('request_id'));if(calls===1)return route.fulfill({json:{status:'busy'}});if(calls===2)return route.abort('connectionreset');return route.fulfill({json:{status:'accepted'}});});
  await page.click('#chat-send');await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);assert.equal(await page.inputValue('#chat-text'),draft);
  await page.click('#chat-send');await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);assert.equal(await page.inputValue('#chat-text'),draft);
  await page.reload();await page.waitForFunction(()=>document.getElementById('chat-text').value.length>0);assert.equal(await page.inputValue('#chat-text'),draft);
  await page.click('#chat-send');await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);assert.equal(await page.inputValue('#chat-text'),'');assert.equal(requestIds[1],requestIds[2]);
  // An unreadable response is ambiguous: preserve the idempotency key on retry.
  await page.unroute('**/chat');let invalidCount=0,invalidIds=[];
  await page.route('**/chat',route=>{invalidIds.push(new URLSearchParams(route.request().postData()).get('request_id'));return ++invalidCount===1?route.fulfill({body:'invalid json',contentType:'application/json'}):route.fulfill({json:{status:'accepted'}});});
  await page.fill('#chat-text','응답 오류 복구 확인');await page.click('#chat-send');await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);assert.equal(await page.inputValue('#chat-text'),'응답 오류 복구 확인');
  await page.click('#chat-send');await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);assert.equal(await page.inputValue('#chat-text'),'');assert.equal(invalidIds[0],invalidIds[1]);
  // A new draft typed during an in-flight request must survive its success response.
  await page.unroute('**/chat');let release;const gate=new Promise(resolve=>release=resolve);
  await page.route('**/chat',async route=>{await gate;await route.fulfill({json:{status:'accepted'}});});
  await page.fill('#chat-text','첫 번째 요청');await page.click('#chat-send');await page.fill('#chat-text','다음 작업 초안');release();await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);assert.equal(await page.inputValue('#chat-text'),'다음 작업 초안');
  await page.goto(base+'/missions');await page.waitForFunction(()=>document.getElementById('stat-all').textContent==='13');
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(artifacts,'mission-center-mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,nodes:[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1&&!n.closest('.table-wrap')&&!n.closest('dialog')).map(n=>({tag:n.tagName,id:n.id,class:n.className,width:n.getBoundingClientRect().width}))}));
  assert(overflow.scroll<=overflow.width,'Mobile page must not overflow: '+JSON.stringify(overflow));
  await page.click('#new-mission');assert(await page.evaluate(()=>document.getElementById('brief-dialog').getBoundingClientRect().width<=innerWidth));await page.keyboard.press('Escape');
  // Outage states never masquerade as an empty successful result.
  await page.route('**/ops/missions?*',route=>route.fulfill({status:500,json:{error:'fixture outage'}}));await page.click('#refresh');await page.waitForFunction(()=>!document.getElementById('page-error').hidden);assert.match(await text(page,'#page-error'),/fixture outage/);
  // Initial empty state is actionable and does not show fixture metrics.
  await page.unroute('**/ops/missions?*');await page.route('**/ops/missions?*',route=>route.fulfill({json:{missions:[],counts:{all:0},total:0,page:1,pages:1,limit:10}}));await page.reload();await page.waitForFunction(()=>document.getElementById('stat-all').textContent==='0');assert.match(await text(page,'#empty-title'),/첫 번째 미션/);
  await page.screenshot({path:path.join(artifacts,'mission-center-empty.png'),fullPage:true});
  // Test multiple breakpoints, including the side navigation transition.
  for(const width of [360,768,800,1024,1280]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width);}
  const blockedContext=await browser.newContext({viewport:{width:390,height:844}});
  await blockedContext.addInitScript(()=>{Storage.prototype.setItem=function(){throw new Error('blocked storage');};});
  const blocked=await blockedContext.newPage();await blocked.goto(base+'/missions');await blocked.click('#new-mission');await blocked.fill('#brief-goal','저장소 제한 확인');
  await blocked.waitForFunction(()=>!document.getElementById('brief-error').hidden);await blocked.click('#brief-form button[type="submit"]');assert.equal(new URL(blocked.url()).pathname,'/missions');assert.equal(await blocked.inputValue('#brief-goal'),'저장소 제한 확인');await blockedContext.close();
  assert.deepEqual(errors,[],'Unexpected JavaScript errors');
  console.log('PASS: pagination, Korean search, filters, evidence, safe text, report download, drafts, failed-send recovery, idempotent retry, concurrent edits, mobile, outage and empty states.');
}
run().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.kill('SIGTERM');rmSync(temp,{recursive:true,force:true});});
