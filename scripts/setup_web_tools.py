"""Install the pinned optional local web toolchain. No project dependencies are changed."""
from pathlib import Path
import os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    node=shutil.which('node')
    if not node:raise SystemExit('Node.js 22.19 이상을 먼저 설치하세요.')
    result=subprocess.run([node,'--version'],capture_output=True,timeout=5)
    match=re.search(rb'(\d+)\.(\d+)\.(\d+)',result.stdout)
    if result.returncode or not match or tuple(map(int,match.groups()))<(22,19,0):raise SystemExit('Node.js 22.19 이상이 필요합니다.')
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm:raise SystemExit('Node.js 22.19 이상과 npm을 설치한 뒤 다시 실행하세요.')
    subprocess.run([npm,'ci','--ignore-scripts','--no-audit','--no-fund'],cwd=ROOT/'tools/web',check=True)
    source=ROOT/'tools/web/node_modules/monaco-editor/min/vs';target=ROOT/'console/vendor/monaco/vs'
    if target.exists():shutil.rmtree(target)
    shutil.copytree(source,target)
    shutil.copyfile(source.parents[1]/'LICENSE',target.parent/'LICENSE')
    pixi=ROOT/'console/vendor/pixi';pixi.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'tools/web/node_modules/pixi.js/dist/pixi.min.js',pixi/'pixi.min.js')
    shutil.copyfile(ROOT/'tools/web/node_modules/pixi.js/dist/packages/unsafe-eval.js',pixi/'csp-support.js')
    shutil.copyfile(ROOT/'tools/web/node_modules/pixi.js/LICENSE',pixi/'LICENSE')
    subprocess.run([str(ROOT/'tools/web/node_modules/.bin'/('playwright.cmd' if os.name=='nt' else 'playwright')),'install','chromium'],check=True)
    print('웹 검수 도구와 Monaco 설치 완료')
