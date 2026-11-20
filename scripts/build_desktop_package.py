"""Windows package builder with a source-only preflight. --check never creates a ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.release_contract import SETUP_FLOW,require_setup_files
from release_version import VERSION


def payload_files(output=None):
    raw=subprocess.check_output(['git','-C',str(ROOT),'ls-files','--cached','--others','--exclude-standard','-z'])
    candidates=sorted({p.decode('utf-8') for p in raw.split(b'\0') if p});files=[]
    excluded={'node_modules','.venv','.git','__pycache__','native','build','dist','artifacts','runs','research','.director_worktrees'}
    for relative in candidates:
        source=ROOT/relative;parts=Path(relative).parts
        if any(part in excluded for part in parts) or not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):continue
        if output and source.resolve()==Path(output).resolve():continue
        if relative.startswith('data/') and relative!='data/.gitkeep':continue
        if any(part in {'secrets','credentials'} for part in parts) or source.name.startswith('.env') or source.suffix.lower() in {'.key','.pem','.pfx','.token','.db','.sqlite3'}:continue
        files.append(relative)
    require_setup_files(files)
    return files


def preflight():
    files=payload_files()
    return {'app':'ai-dev-director','setup_flow':SETUP_FLOW,'status':'PASS','file_count':len(files),'source_bytes':sum((ROOT/f).stat().st_size for f in files),'zip_created':False,
            'checks':['setup screen + installer + first-run routing','pinned Node package manifest + lockfile','Monaco/PixiJS assets + original licenses','runtime data, credentials and node_modules excluded'],
            'unverified':['actual Windows installer execution','user AI login/API billing','hardware GPU performance']}


def build(output):
    output=Path(output).resolve();files=payload_files(output)
    manifest={'app':'ai-dev-director','format':1,'edition':'native-desktop-v3-web-tools-setup','setup_flow':SETUP_FLOW,'version':VERSION,'files':{}}
    prefix='AI DEV DIRECTOR';output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for relative in files:
            content=(ROOT/relative).read_bytes()
            if relative.lower().endswith('.cmd'):content=content.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            manifest['files'][relative]=hashlib.sha256(content).hexdigest();archive.writestr(prefix+'/'+relative,content)
        archive.writestr(prefix+'/desktop_distribution.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise RuntimeError('ZIP integrity check failed')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',nargs='?',default=str(ROOT/'dist/AI-DEV-DIRECTOR-Windows.zip'));parser.add_argument('--check',action='store_true',help='Validate payload without making a ZIP');args=parser.parse_args()
    print(json.dumps(preflight(),ensure_ascii=False,indent=2) if args.check else build(args.output))
