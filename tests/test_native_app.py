import subprocess

import pytest

from native_app import app_root, navigation_kind
from scripts.install_desktop import create_shortcut


@pytest.mark.parametrize('url,expected', [
    ('http://127.0.0.1:8091/missions', 'internal'),
    ('http://127.0.0.1:8091/classic', 'internal'),
    ('about:blank', 'internal'),
    ('http://127.0.0.1:8092/missions', 'blocked'),
    ('http://127.0.0.1:8091@evil.example/', 'blocked'),
    ('file:///etc/passwd', 'blocked'),
    ('javascript:alert(1)', 'blocked'),
    ('https://github.com/digilogd-cmd/ai-dev-director', 'external'),
])
def test_navigation_keeps_local_app_origin(url, expected):
    assert navigation_kind(url, 'http://127.0.0.1:8091/missions') == expected


def test_frozen_shell_finds_backend_outside_bundle(tmp_path, monkeypatch):
    import native_app
    (tmp_path / 'companion_server.py').touch()
    (tmp_path / 'companion.json').write_text('{}')
    monkeypatch.setattr(native_app.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(native_app.sys, 'executable', str(tmp_path / 'native/AI-DEV-DIRECTOR/AI-DEV-DIRECTOR.exe'))
    assert app_root() == tmp_path
    with pytest.raises(RuntimeError):
        app_root(tmp_path / 'missing')


def test_shortcut_targets_exe_with_quoted_install_path(tmp_path, monkeypatch):
    target = tmp_path / '한글 공백 설치'
    executable = target / 'native/AI-DEV-DIRECTOR/AI-DEV-DIRECTOR.exe'
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, b'shortcut.lnk', b'')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    create_shortcut(target, executable, ['--app-root', str(target)])
    env = captured['env']
    assert env['ADD_DESKTOP_PYTHONW'] == str(executable)
    assert env['ADD_DESKTOP_ARGUMENTS'] == subprocess.list2cmdline(['--app-root', str(target)])
    assert str(target) not in captured['command'][-1]


def test_stable_graphics_does_not_disable_sandbox(monkeypatch):
    import native_app
    monkeypatch.setenv('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-dev-shm-usage')
    native_app.configure_graphics()
    native_app.configure_graphics()
    flags = native_app.os.environ['QTWEBENGINE_CHROMIUM_FLAGS'].split()
    assert flags.count('--disable-gpu') == 1
    assert '--disable-dev-shm-usage' in flags
    assert '--no-sandbox' not in flags


def test_folder_picker_import_error_is_reported(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path
    monkeypatch.setitem(sys.modules, 'tkinter', None)
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/pick_folder.py'))
    assert namespace['main']() == 1
    assert 'tkinter unavailable' in capsys.readouterr().err


@pytest.mark.parametrize('url,current,main_frame,expected',[
 ('http://127.0.0.1:3000/','/web-workspace',False,True),
 ('https://example.test/','/web-workspace',False,True),
 ('https://user:pass@example.test/','/web-workspace',False,False),
 ('file:///tmp/source.html','/web-workspace',False,False),
 ('javascript:alert(1)','/web-workspace',False,False),
 ('http://127.0.0.1:3000/','/office',False,False),
 ('http://127.0.0.1:3000/','/web-workspace',True,False),
])
def test_only_web_workspace_subframes_can_preview_websites(url,current,main_frame,expected):
    from native_app import preview_frame_allowed
    base='http://127.0.0.1:8091'
    assert preview_frame_allowed(url,base,base+current,main_frame)==expected
