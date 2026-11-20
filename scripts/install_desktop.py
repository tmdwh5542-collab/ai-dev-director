"""Per-user Windows setup; invoked once by INSTALL_DESKTOP.cmd after extracting the ZIP."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import socket
import venv

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from desktop_launcher import configured_port, launch_lock, probe, SETUP_FLOW_VERSION
from scripts.release_contract import SETUP_FLOW, require_setup_files

MANIFEST = "desktop_distribution.json"
PRESERVE = {"config.yaml", "companion.json"}


def install_root(local_app_data):
    base = Path(local_app_data).resolve()
    target = base / "AI Dev Director" / "mission-center-v3"
    if base not in target.resolve().parents:
        raise ValueError("사용자 설치 폴더가 외부 경로로 연결되어 있습니다")
    return target


def safe_path(root, relative):
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or any(part in ("..", ".git", ".venv") for part in path.parts) or "\\" in relative or ":" in relative:
        raise ValueError("설치 목록의 경로가 올바르지 않습니다: " + relative)
    destination = Path(root) / Path(*path.parts)
    if Path(root).resolve() not in destination.resolve().parents:
        raise ValueError("설치 폴더 밖의 경로입니다: " + relative)
    return destination


def verified_files(source):
    try:
        manifest = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Windows 설치용 ZIP 전체를 먼저 압축 해제한 뒤 INSTALL_DESKTOP.cmd를 실행하세요.") from exc
    if manifest.get("app") != "ai-dev-director" or manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("설치 목록 형식을 확인할 수 없습니다")
    files = []
    for relative, digest in manifest["files"].items():
        path = safe_path(source, relative)
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("설치 파일이 없거나 변경되었습니다. ZIP을 다시 압축 해제하세요: " + relative)
        files.append(relative)
    required = {"desktop_launcher.py", "companion_server.py", "requirements.txt", "config.yaml", "companion.json"}
    if not required.issubset(files):
        raise ValueError("필수 실행 파일이 설치 목록에 없습니다")
    if manifest.get("setup_flow") is not None and (type(manifest["setup_flow"]) is not int or manifest["setup_flow"]!=SETUP_FLOW):
        raise ValueError("지원하지 않는 설치·연결 안내 버전입니다")
    if manifest.get("setup_flow") == SETUP_FLOW:
        require_setup_files(files)
    return files


def available_port(preferred=8091):
    for port in (preferred, 0):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("로컬 실행 포트를 확보하지 못했습니다")


def copy_installation(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("새 설치용 ZIP을 다른 폴더에 압축 해제한 뒤 설치를 실행하세요.")
    files = verified_files(source)
    fresh = not (target / "companion.json").exists()
    # Validate every destination before replacing any source file (including parent symlinks).
    for relative in files:
        safe_path(target, relative)
    target.mkdir(parents=True, exist_ok=True)
    for relative in files:
        destination = safe_path(target, relative)
        if destination.exists() and relative in PRESERVE:
            continue
        if relative.startswith("data/") and relative != "data/.gitkeep":
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(safe_path(source, relative), destination)
    (target / "data").mkdir(exist_ok=True)
    if fresh:
        config_path = target / "companion.json"
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        config["port"] = available_port()
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def configure_update_channel(target):
    """Seed the release's public update channel once; preserve user trust settings."""
    target = Path(target)
    settings = target / 'data/update_settings.json'
    channel = target / 'release_channel.json'
    if settings.exists() or not channel.is_file():
        return
    value = json.loads(channel.read_text(encoding='utf-8'))
    # Setup runs before dependency installation; use only the Python standard library.
    if not isinstance(value.get('repository'), str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}', value['repository']):
        raise ValueError('업데이트 저장소 형식이 올바르지 않습니다.')
    try:
        if len(base64.b64decode(value['public_key'], validate=True)) != 32:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('업데이트 공개키 형식이 올바르지 않습니다.') from exc
    settings.parent.mkdir(parents=True, exist_ok=True)
    with settings.open('x', encoding='utf-8') as stream:
        json.dump({'repository':value['repository'], 'public_key':value['public_key'],
                   'auto_check':True, 'auto_download':False}, stream, ensure_ascii=False, indent=2)


def mark_setup_pending(target):
    marker=Path(target)/'data'/'desktop_setup.json'
    try:
        value=json.loads(marker.read_text(encoding='utf-8'))
        if value.get('version')==SETUP_FLOW_VERSION:return
    except (OSError,ValueError,AttributeError):pass
    marker.parent.mkdir(parents=True,exist_ok=True)
    temp=marker.with_suffix('.tmp')
    temp.write_text(json.dumps({'version':SETUP_FLOW_VERSION,'pending':True},ensure_ascii=False),encoding='utf-8');temp.replace(marker)


def create_shortcut(target, pythonw, arguments=None):
    # Paths travel via environment variables, never interpolated into PowerShell source.
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktop) { throw 'Desktop folder is unavailable' }
$path = Join-Path $desktop 'AI DEV DIRECTOR v3.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($path)
$link.TargetPath = $env:ADD_DESKTOP_PYTHONW
$link.Arguments = $env:ADD_DESKTOP_ARGUMENTS
$link.WorkingDirectory = $env:ADD_DESKTOP_ROOT
$link.IconLocation = $env:ADD_DESKTOP_PYTHONW + ',0'
$link.Description = 'AI DEV DIRECTOR - Mission Center'
$link.Save()
Write-Output $path
"""
    environment = dict(os.environ)
    environment.update(ADD_DESKTOP_ROOT=str(target), ADD_DESKTOP_PYTHONW=str(pythonw),
                       ADD_DESKTOP_ARGUMENTS=subprocess.list2cmdline(arguments if arguments is not None else [str(target / "desktop_launcher.py")]))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=environment, capture_output=True)
    if result.returncode:
        raise RuntimeError("바탕화면 바로가기를 만들지 못했습니다:\n" + result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace").strip()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        if os.name != "nt":
            raise RuntimeError("이 설치 파일은 Windows용입니다. 다른 OS에서는 기존 Python 실행 안내를 사용하세요.")
        if sys.version_info < (3, 10):
            raise RuntimeError("Python 3.10 이상이 필요합니다: https://www.python.org/downloads/windows/")
        if sys.maxsize <= 2**32:
            raise RuntimeError("전용 앱은 64비트 Python이 필요합니다: https://www.python.org/downloads/windows/")
        if not shutil.which("git"):
            raise RuntimeError("Git이 필요합니다. https://git-scm.com/download/win 에서 설치한 뒤 다시 실행하세요.")
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("사용자 설치 폴더 LOCALAPPDATA를 찾을 수 없습니다")
        target = install_root(local)
        verified_files(SOURCE)
        with launch_lock(target):
            if (target / "companion.json").exists() and probe(configured_port(target)) is not None:
                raise RuntimeError("설정된 포트에서 프로그램이 실행 중입니다. AI DEV의 시스템 중지 버튼 등으로 해당 프로그램을 종료한 뒤 설치를 다시 실행하세요.")
            print("[1/4] 사용자 전용 폴더에 설치합니다:", target, flush=True)
            copy_installation(SOURCE, target)
            configure_update_channel(target)
            environment = target / ".venv"
            python = environment / "Scripts" / "python.exe"
            if not python.exists():
                print("[2/4] Python 실행 환경을 준비합니다.", flush=True)
                venv.EnvBuilder(with_pip=True).create(str(environment))
            print("[3/4] 필요한 Python 패키지를 설치합니다. 처음에는 인터넷 연결이 필요합니다.", flush=True)
            subprocess.run([str(python), "-m", "pip", "install", "-r", str(target / "requirements-native.txt")], check=True, cwd=str(target))
            subprocess.run([str(python), "-c", "import yaml, click, pydantic, psutil"], check=True)
            pythonw = environment / "Scripts" / "pythonw.exe"
            if not pythonw.is_file():
                raise RuntimeError("pythonw.exe가 준비되지 않았습니다. Python 설치 상태를 확인하세요.")
            print("[4/4] 전용 앱 EXE를 만들고 바탕화면 바로가기를 연결합니다. 시간이 걸릴 수 있습니다.", flush=True)
            subprocess.run([str(python), str(target / "scripts" / "build_native_app.py")], check=True, cwd=str(target))
            executable = target / "native" / "AI-DEV-DIRECTOR" / "AI-DEV-DIRECTOR.exe"
            shortcut = create_shortcut(target, executable, ["--app-root", str(target)])
            mark_setup_pending(target)
        print("설치 완료:", shortcut, flush=True)
        print("첫 실행은 설치·연결 점검으로 이어집니다. Node 도구·MCP·Hermes는 필요에 맞게 설정하거나 나중에 진행할 수 있습니다.", flush=True)
        print("이후에는 바탕화면의 AI DEV DIRECTOR v3 아이콘을 눌러 사용하세요.", flush=True)
        subprocess.Popen([str(executable), "--app-root", str(target)], cwd=str(target))
        return 0
    except Exception as exc:
        print("\n설치 오류:", exc, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
