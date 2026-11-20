"""Desktop entry point. Standard library only, so startup failures can be shown before app imports.

The shortcut points to the installed virtualenv's pythonw and this file. A per-install
lock prevents double-clicks from starting two servers. A health identity prevents
opening a different installation just because it uses the configured port.
"""
import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
APP_ID = "ai-dev-director"
PROTOCOL = 1
SETUP_FLOW_VERSION = 1


class DesktopError(RuntimeError):
    pass


def installation_id(root):
    return hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode("utf-8")).hexdigest()


def startup_path(root):
    """Read only this installation's first-run marker; never inspect account settings."""
    marker=Path(root)/'data'/'desktop_setup.json'
    if not marker.exists():return '/office'
    try:
        value=json.loads(marker.read_text(encoding='utf-8'))
        return '/setup' if value.get('pending') is True or value.get('version')!=SETUP_FLOW_VERSION else '/office'
    except (OSError,ValueError,AttributeError):return '/setup'


def configured_port(root):
    try:
        config = json.loads((Path(root) / "companion.json").read_text(encoding="utf-8-sig"))
        port = config.get("port", 8081)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        return port
    except (OSError, ValueError, AttributeError) as exc:
        raise DesktopError("companion.json 설정을 읽을 수 없습니다: " + str(exc)) from exc


def probe(port, timeout=0.7):
    """None means no response yet; any other service/response is treated as a port conflict."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/ops/desktop-health")
        response = connection.getresponse()
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096:
            return {"conflict": True}
        try:
            result = json.loads(body)
            return result if isinstance(result, dict) else {"conflict": True}
        except (ValueError, UnicodeError):
            return {"conflict": True}
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def is_ours(result, root):
    return bool(result and result.get("app") == APP_ID and result.get("protocol") == PROTOCOL
                and result.get("installation_id") == installation_id(root))


@contextmanager
def launch_lock(root, timeout=60):
    data = Path(root) / "data"
    data.mkdir(parents=True, exist_ok=True)
    handle = (data / "desktop-launch.lock").open("a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"0"); handle.flush()
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise DesktopError("다른 실행 창이 시작을 처리하고 있습니다. 잠시 후 다시 눌러주세요.") from exc
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def runtime_python(root):
    relative = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
    executable = Path(root) / relative
    if not executable.is_file():
        raise DesktopError("실행 환경이 없습니다. 압축을 푼 폴더의 INSTALL_DESKTOP.cmd를 먼저 실행하세요.")
    return executable


def _spawn_server(root, executable):
    root = Path(root)
    options = {"cwd": str(root), "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
        if getattr(sys, "frozen", False):
            # PyInstaller's Qt DLL directory must not leak into the independent backend Python.
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
    else:
        options["start_new_session"] = True
    with (root / "data" / "desktop-server.log").open("ab") as stdout, (root / "data" / "desktop-server.err").open("ab") as stderr:
        try:
            return subprocess.Popen([str(executable), str(root / "companion_server.py")], stdout=stdout, stderr=stderr, **options)
        finally:
            if os.name == "nt" and getattr(sys, "frozen", False):
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))


def guard_update(root):
    root=Path(root).resolve();marker=root/'data/update_exit.json'
    if not marker.exists():return
    import re
    try:
        job_id=json.loads(marker.read_text(encoding='utf-8'))['job_id']
        if not re.fullmatch('UPD-[a-f0-9]{20}',job_id):raise ValueError()
        job=root/'data/app_updates'/job_id;record=json.loads((job/'job.json').read_text(encoding='utf-8'))
        if record.get('root')!=str(root):raise ValueError()
        import psutil
        process=json.loads((job/'worker-process.json').read_text(encoding='utf-8')) if (job/'worker-process.json').exists() else record.get('helper') or {}
        try:
            alive=abs(psutil.Process(process['pid']).create_time()-process['created'])<.01
        except (KeyError,psutil.Error):alive=False
        if alive:raise DesktopError('업데이트 적용·복구가 진행 중입니다. 잠시 후 앱이 다시 실행됩니다.')
        journal=json.loads((job/'journal.json').read_text(encoding='utf-8')) if (job/'journal.json').exists() else {}
        if journal.get('stage')=='COMMITTED':marker.unlink();return
        if journal.get('backup_ready'):
            executable=runtime_python(root)
            (job/'worker-process.json').unlink(missing_ok=True)
            with (job/'recovery.log').open('ab') as log:
                helper=subprocess.Popen([str(executable),str(job/'worker.py'),'--recover'],cwd=job,stdout=log,stderr=subprocess.STDOUT,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
                record['helper']={'pid':helper.pid,'created':psutil.Process(helper.pid).create_time()}
                temp=(job/'job.json').with_suffix('.tmp');temp.write_text(json.dumps(record),encoding='utf-8');temp.replace(job/'job.json')
            raise DesktopError('중단된 업데이트 복구를 시작했습니다. 잠시 후 앱이 다시 실행됩니다.')
        marker.unlink()
    except DesktopError:raise
    except (OSError,ValueError,KeyError) as exc:raise DesktopError('업데이트 기록을 확인할 수 없습니다. data/app_updates의 기록을 보존하고 설치 상태를 점검하세요.') from exc


def ensure_server(root=ROOT, timeout=45, python_executable=None):
    root = Path(root).resolve()
    port = configured_port(root)
    with launch_lock(root):
        guard_update(root)
        result = probe(port)
        if is_ours(result, root):
            return f"http://127.0.0.1:{port}/missions"
        if result is not None:
            raise DesktopError(f"포트 {port}에서 다른 프로그램이나 이전 설치본이 실행 중입니다. "
                               "해당 프로그램을 종료하거나 companion.json의 포트를 바꿔주세요. 다른 프로그램은 중지하지 않았습니다.")
        executable = Path(python_executable) if python_executable else runtime_python(root)
        child = _spawn_server(root, executable)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    error_file = root / "data" / "desktop-server.err"
                    tail = error_file.read_bytes()[-3000:].decode("utf-8", errors="replace") if error_file.exists() else ""
                    raise DesktopError("서버가 시작되지 않았습니다. INSTALL_DESKTOP.cmd로 실행 환경을 확인하세요.\n" + tail)
                result = probe(port)
                if is_ours(result, root):
                    return f"http://127.0.0.1:{port}/missions"
                if result is not None:
                    raise DesktopError(f"포트 {port}가 다른 프로그램에 사용되고 있습니다.")
                time.sleep(0.15)
            raise DesktopError("서버 시작 시간이 초과되었습니다. data 폴더의 desktop-server.err를 확인하세요.")
        except Exception:
            # Terminate only the exact child started by this launcher, never a port's unrelated owner.
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)
            raise


def show_error(message, root=ROOT):
    log = Path(root) / "data" / "desktop-launcher.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + message + "\n" + traceback.format_exc() + "\n")
    except OSError:
        pass
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message + "\n\n기록: " + str(log), "AI DEV DIRECTOR", 0x10)
    else:
        print(message, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="AI DEV DIRECTOR desktop launcher")
    parser.add_argument("--check", action="store_true", help="Print local installation status without starting a server")
    args = parser.parse_args()
    try:
        if args.check:
            port = configured_port(ROOT)
            print(json.dumps({"root": str(ROOT), "port": port, "running": is_ours(probe(port), ROOT)}, ensure_ascii=False))
        else:
            from native_app import run
            app, window = run(ROOT)
            return app.exec()
        return 0
    except Exception as exc:
        show_error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
