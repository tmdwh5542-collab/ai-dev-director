import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import desktop_launcher as launch
from scripts.install_desktop import copy_installation, install_root, verified_files
from tests.test_v301_companion_http import http_server, request  # noqa: F401


@pytest.fixture
def running_server():
    servers = []
    def create(identity):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = json.dumps(identity).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        servers.append((server, thread))
        return server.server_address[1]
    yield create
    for server, thread in servers:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def identity(root):
    return {"app": launch.APP_ID, "protocol": launch.PROTOCOL, "installation_id": launch.installation_id(root)}


def config(root, port):
    root.mkdir(parents=True, exist_ok=True)
    (root / "companion.json").write_text(json.dumps({"port": port}))


def test_installer_seeds_public_update_channel_once(tmp_path):
    import base64
    from scripts.install_desktop import configure_update_channel
    channel={'repository':'example/director','public_key':base64.b64encode(bytes(range(32))).decode()}
    (tmp_path/'release_channel.json').write_text(json.dumps(channel))
    configure_update_channel(tmp_path)
    settings=tmp_path/'data/update_settings.json'
    assert json.loads(settings.read_text()) == {**channel,'auto_check':True,'auto_download':False}
    settings.write_text('{"repository":"user/own-channel"}')
    configure_update_channel(tmp_path)
    assert json.loads(settings.read_text()) == {'repository':'user/own-channel'}


def test_installer_does_not_register_invalid_channel(tmp_path):
    from scripts.install_desktop import configure_update_channel
    (tmp_path/'release_channel.json').write_text(json.dumps({'repository':'invalid','public_key':'invalid'}))
    with pytest.raises(ValueError):configure_update_channel(tmp_path)
    assert not (tmp_path/'data/update_settings.json').exists()


def test_update_channel_setup_needs_only_standard_library(tmp_path):
    import base64
    import subprocess
    channel={'repository':'example/director','public_key':base64.b64encode(bytes(range(32))).decode()}
    (tmp_path/'release_channel.json').write_text(json.dumps(channel))
    source=Path(__file__).resolve().parents[1]
    code="import sys; sys.path.insert(0,sys.argv[1]); from scripts.install_desktop import configure_update_channel; configure_update_channel(sys.argv[2])"
    result=subprocess.run([sys.executable,'-S','-c',code,str(source),str(tmp_path)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'data/update_settings.json').exists()


def test_reuses_only_the_same_installation(tmp_path, running_server, monkeypatch):
    root = tmp_path / "한글 공백 설치"
    port = running_server(identity(root)); config(root, port)
    monkeypatch.setattr(launch, "_spawn_server", lambda *a: pytest.fail("already running"))
    assert launch.ensure_server(root).endswith(f":{port}/missions")


def test_other_installation_is_not_opened_or_killed(tmp_path, running_server, monkeypatch):
    root = tmp_path / "new"
    port = running_server(identity(tmp_path / "old")); config(root, port)
    monkeypatch.setattr(launch, "_spawn_server", lambda *a: pytest.fail("must not start or stop foreign server"))
    with pytest.raises(launch.DesktopError, match="다른 프로그램"):
        launch.ensure_server(root)


def test_double_clicks_start_one_server(tmp_path, monkeypatch):
    root = tmp_path / "app"; config(root, 8091)
    calls, ready = [], threading.Event()
    def probe(port, timeout=0.7):
        return identity(root) if ready.is_set() else None
    def spawn(*args):
        calls.append(args); ready.set()
        return type("Child", (), {"poll": lambda self: None})()
    monkeypatch.setattr(launch, "probe", probe); monkeypatch.setattr(launch, "_spawn_server", spawn)
    with ThreadPoolExecutor(max_workers=4) as pool:
        urls = list(pool.map(lambda _: launch.ensure_server(root, python_executable=sys.executable), range(4)))
    assert len(set(urls)) == 1 and len(calls) == 1


def test_startup_failure_points_to_captured_error(tmp_path, monkeypatch):
    root = tmp_path / "app"; config(root, 8091)
    monkeypatch.setattr(launch, "probe", lambda *a, **kw: None)
    def spawn(*args):
        (root / "data" / "desktop-server.err").write_text("missing dependency", encoding="utf-8")
        return type("Child", (), {"poll": lambda self: 1})()
    monkeypatch.setattr(launch, "_spawn_server", spawn)
    with pytest.raises(launch.DesktopError, match="missing dependency"):
        launch.ensure_server(root, python_executable=sys.executable)


def test_real_process_with_spaces_becomes_ready_and_is_reused(tmp_path):
    root = tmp_path / "한글 경로 with spaces"; root.mkdir()
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    config(root, port)
    script = '''import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps(IDENTITY).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
'''.replace("IDENTITY", repr(identity(root))).replace("PORT", str(port))
    (root / "companion_server.py").write_text(script, encoding="utf-8")
    # Capture the real child to terminate only this test's server afterwards.
    original = launch._spawn_server
    children = []
    from unittest.mock import patch
    def spawn(*args):
        child = original(*args); children.append(child); return child
    try:
        with patch.object(launch, "_spawn_server", spawn):
            url = launch.ensure_server(root, timeout=5, python_executable=sys.executable)
            assert launch.ensure_server(root, python_executable=sys.executable) == url
            assert len(children) == 1 and launch.is_ours(launch.probe(port), root)
    finally:
        for child in children:
            child.terminate(); child.wait(timeout=5)


def distribution(root):
    import hashlib
    root.mkdir()
    files = {"desktop_launcher.py": "# launcher", "companion_server.py": "# server", "requirements.txt": "pyyaml",
             "config.yaml": "keep: default", "companion.json": '{"port":8081}', "console/index.html": "screen"}
    hashes = {}
    for relative, text in files.items():
        p = root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        hashes[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
    (root / "desktop_distribution.json").write_text(json.dumps({"app": launch.APP_ID, "format": 1, "files": hashes}))
    return root


def test_installer_preserves_settings_data_and_runs(tmp_path):
    source = distribution(tmp_path / "unpacked")
    target = tmp_path / "installed"
    copy_installation(source, target)
    port = launch.configured_port(target)
    (target / "config.yaml").write_text("my: settings")
    (target / "data" / "my-state.json").write_text("history")
    (target / "runs").mkdir(); (target / "runs" / "result.json").write_text("result")
    copy_installation(source, target)
    assert launch.configured_port(target) == port
    assert (target / "config.yaml").read_text() == "my: settings"
    assert (target / "data" / "my-state.json").read_text() == "history"
    assert (target / "runs" / "result.json").read_text() == "result"


def test_bad_or_tampered_distribution_is_rejected_before_copy(tmp_path):
    source = distribution(tmp_path / "unpacked")
    (source / "companion_server.py").write_text("tampered")
    with pytest.raises(ValueError, match="변경"):
        copy_installation(source, tmp_path / "target")
    assert not (tmp_path / "target").exists()
    manifest = json.loads((source / "desktop_distribution.json").read_text())
    manifest["files"] = {"../outside.py": "invalid"}
    (source / "desktop_distribution.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="경로"):
        verified_files(source)


def test_installer_rejects_external_destination_link(tmp_path):
    base = tmp_path / "local"; base.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    try:
        (base / "AI Dev Director").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError, match="외부 경로"):
        install_root(base)


def test_health_endpoint_identifies_real_companion_and_blocks_foreign_origin(http_server):
    import companion_server
    code, raw = request(http_server, "GET", "/ops/desktop-health")
    assert code == 200 and launch.is_ours(json.loads(raw), companion_server.ROOT)
    assert request(http_server, "GET", "/ops/desktop-health", headers={"Origin": "https://evil.example"})[0] == 403


def test_first_run_marker_is_per_install_and_acknowledgement_is_preserved(tmp_path):
    from scripts.install_desktop import mark_setup_pending
    target=tmp_path/'한글 설치'
    assert launch.startup_path(target)=='/office'
    mark_setup_pending(target)
    assert launch.startup_path(target)=='/setup'
    marker=target/'data/desktop_setup.json';marker.write_text(json.dumps({'version':launch.SETUP_FLOW_VERSION,'pending':False}),encoding='utf-8')
    mark_setup_pending(target)
    assert launch.startup_path(target)=='/office'
    marker.write_text('broken',encoding='utf-8')
    assert launch.startup_path(target)=='/setup'


def test_setup_release_cannot_silently_omit_tool_assets(tmp_path):
    source=distribution(tmp_path/'unpacked');file=source/'desktop_distribution.json';value=json.loads(file.read_text());value['setup_flow']=1;file.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='필수 파일'):verified_files(source)
    value['setup_flow']=2;file.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='지원하지 않는'):verified_files(source)


def test_release_preflight_excludes_runtime_without_creating_zip():
    from scripts.build_desktop_package import payload_files,preflight
    files=payload_files();assert 'console/setup.html' in files and 'tools/web/package-lock.json' in files
    assert not any('node_modules' in Path(p).parts or p.startswith('data/') and p!='data/.gitkeep' for p in files)
    assert preflight()['zip_created'] is False
