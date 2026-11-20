// Runs only against the owned loopback development server selected by the host.
import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';
const require=createRequire(new URL('../tools/web/package.json',import.meta.url)),[kind,url,out]=process.argv.slice(2),base=new URL(url);
if(base.protocol!=='http:'||!['127.0.0.1','localhost'].includes(base.hostname))throw Error('Owned loopback development URL required');
const executable=process.env.DIRECTOR_WEB_CHROMIUM||(['linux'].includes(process.platform)&&fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined);
const input=JSON.parse(fs.readFileSync(0,'utf8')||'{}');
if(kind==='browser'){
 const {chromium}=require('playwright'),browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{}),args:process.platform==='linux'?['--no-sandbox']:[]});
 try{const details=[];for(const [device,width,height] of [['desktop',1440,900],['tablet',768,1024],['mobile',390,844]]){
  const context=await browser.newContext({viewport:{width,height},serviceWorkers:'block',acceptDownloads:false});
  // A redirect/subresource cannot reach the Director, a router, or arbitrary LAN services.
  await context.route('**/*',route=>{const u=new URL(route.request().url());return u.origin===base.origin?route.continue():route.abort();});
  const page=await context.newPage(),errors=[],failed=[];page.on('pageerror',e=>errors.push(e.message.slice(0,1000)));page.on('response',r=>{if(r.status()>=400)failed.push({url:r.url(),status:r.status()});});
  const response=await page.goto(url,{waitUntil:'networkidle',timeout:25000});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  const steps=[];for(const action of input.steps||[]){try{const node=page.locator(action.selector).first();if(action.action==='fill')await node.fill(action.value||'',{timeout:2500});else await node.click({timeout:2500});steps.push({action:action.action,selector:action.selector,passed:true});}catch(e){steps.push({action:action.action,selector:action.selector,passed:false,error:e.message.slice(0,500)});}}
  const controls=await page.locator('button,a,input,select,textarea').evaluateAll(nodes=>nodes.slice(0,200).map(n=>({tag:n.tagName,name:(n.getAttribute('aria-label')||n.innerText||n.getAttribute('placeholder')||'').slice(0,100)})));
  const screenshot=device+'.png';await page.screenshot({path:path.join(out,screenshot),fullPage:true});details.push({device,width,status:response?.status(),overflow,steps,errors,failed:failed.slice(0,30),controls:controls.length,screenshot});await context.close();
 }console.log(JSON.stringify({summary:`3개 화면 검수 완료 · 가로 넘침 ${details.filter(x=>x.overflow).length}개 · JS 오류 ${details.reduce((n,x)=>n+x.errors.length,0)}개`,scope:'실제 페이지 탐색·반응형·콘솔·HTTP 오류·스크린샷. 명시한 click/fill 단계만 수행하며 별도 로그인 정보를 사용하지 않습니다. 다른 출처 요청은 차단합니다.',viewports:details}));
 }finally{await browser.close();}
}else if(kind==='lighthouse'){
 const {default:lighthouse}=await import(pathToFileURL(require.resolve('lighthouse')).href),chromeLauncher=await import(pathToFileURL(require.resolve('chrome-launcher')).href);
 const chrome=await chromeLauncher.launch({chromePath:executable,chromeFlags:['--headless',...(process.platform==='linux'?['--no-sandbox']:[])]});
 try{const r=await lighthouse(url,{port:chrome.port,output:'json',onlyCategories:['performance','accessibility','best-practices','seo'],logLevel:'error',blockedUrlPatterns:['*://192.168.*/*','*://10.*/*','*://169.254.*/*']});
 const lhr=r.lhr,categories=Object.fromEntries(Object.entries(lhr.categories).map(([k,v])=>[k,v.score===null?null:Math.round(v.score*100)]));
 const findings=Object.values(lhr.audits).filter(a=>a.score!==null&&a.score<1).slice(0,30).map(a=>({id:a.id,title:a.title,score:a.score,description:a.description}));fs.writeFileSync(path.join(out,'lighthouse.json'),JSON.stringify(lhr));
 console.log(JSON.stringify({summary:'Lighthouse 실측 완료',categories,findings,scope:'로컬 개발 빌드의 단일 모바일 실측. 운영 성능이나 부하 테스트와 다릅니다.'}));
 }finally{await chrome.kill();}
}else throw Error('Unknown audit kind');
