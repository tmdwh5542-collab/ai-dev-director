"""Real engine behavior, asset continuity and engine-report failure boundaries."""
import json
from pathlib import Path
import shutil
import sys
import subprocess

import pytest

from core.bootstrap import prepare_project, snapshot, git
from core.git_manager import GitManager
from core.project_context import collect_project_context
from core.verifier import Verifier
from core import workflows
from scripts.run_engine_tests import godot_counts, unity_counts

ROOT = Path(__file__).resolve().parents[1]


def test_uncommitted_engine_files_survive_snapshot_with_identity(tmp_path):
    root = Path(prepare_project(tmp_path / 'game'))
    files = {'project.godot': b'config_version=5\n', 'scripts/token_pickup.gd': b'extends Node\n',
             'scripts/token_pickup.gd.uid': b'uid://example', 'scenes/main.tscn': b'[gd_scene format=3]\n',
             'Assets/Player.prefab': b'%YAML 1.1\n', 'Assets/Player.prefab.meta': b'guid: abc123\n',
             'Assets/Code.asmdef': b'{"name":"Game"}', 'assets/tone.ogg': b'OggS\x00\xff',
             'data/level.json': b'{"tiles":[1,2]}', '.gitignore': b'.godot/\nLibrary/\n'}
    for rel, content in {**files, '.godot/cache.json': b'{}', 'Library/cache.json': b'{}',
                         'secrets/account.json': b'{}', 'keys/private_key.pem': b'PRIVATE'}.items():
        path = root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    index = git(root, 'status', '--porcelain'); head = git(root, 'rev-parse', 'HEAD')
    sha = snapshot(root)
    names = git(root, 'ls-tree', '-r', '--name-only', sha).splitlines()
    assert set(names) == set(files)
    for rel, content in files.items():
        saved = subprocess.check_output(['git', 'show', sha + ':' + rel], cwd=root)
        assert saved == content
    assert git(root, 'rev-parse', 'HEAD') == head
    assert git(root, 'status', '--porcelain') == index
    context = collect_project_context(root)
    assert 'Godot' in context['project_discovery']['stack']
    assert not any(p.startswith(('Library/', '.godot/')) for p in context['existing_files'])


def test_untracked_large_asset_fails_explicitly_instead_of_disappearing(tmp_path):
    from core.project_files import MAX_NEW_FILE_BYTES
    root = Path(prepare_project(tmp_path / 'game'))
    with (root / 'world.glb').open('wb') as handle:
        handle.truncate(MAX_NEW_FILE_BYTES + 1)
    with pytest.raises(ValueError, match='SNAPSHOT_ASSET_LIMIT'):
        snapshot(root)


@pytest.mark.parametrize('output', ['', 'DIRECTOR_TESTS {"passed":0,"failed":0,"total":0}',
    'DIRECTOR_TESTS {"passed":true,"failed":0,"total":1}',
    'DIRECTOR_TESTS {"passed":2,"failed":0,"total":1}',
    'DIRECTOR_TESTS {"passed":1,"failed":0,"total":1}\nSCRIPT ERROR: broken code'])
def test_godot_missing_or_invalid_evidence_never_passes(output):
    with pytest.raises((ValueError, TypeError)):
        godot_counts(output)


def test_unity_report_counts_actual_test_cases_and_rejects_empty(tmp_path):
    report = tmp_path / 'result.xml'
    report.write_text('<test-run><test-suite><test-case result="Passed"/><test-case result="Failed"/><test-case result="Skipped"/></test-suite></test-run>')
    assert unity_counts(report) == (1, 1, 1)
    for body in ['<test-run passed="10"/>', '<test-run><test-case result="Skipped"/></test-run>',
                 '<!DOCTYPE test-run [<!ENTITY x "bad">]><test-run/>']:
        report.write_text(body)
        with pytest.raises(ValueError): unity_counts(report)


def test_game_workflow_prioritizes_regression_and_preserves_scope():
    from schemas.order import OrderSchema
    assert workflows.resolve_workflow('auto', 'Godot 게임 만들기') == 'game'
    assert workflows.resolve_workflow('auto', 'Unity 게임 충돌 오류 수정') == 'bugfix'
    order = OrderSchema(goal='game', allowed_paths=['Assets/**'])
    enriched = workflows.apply_workflow(order, 'game')
    assert enriched.allowed_paths == order.allowed_paths
    assert '.meta GUIDs' in enriched.context


RUNNER = '''extends SceneTree
const Movement = preload("res://scripts/movement.gd")
func _init():
    var passed = 0
    var failed = 0
    var checks = [is_equal_approx(Movement.step(0, 10, 0.5), 5), is_equal_approx(Movement.step(4, 0, 1), 4), is_equal_approx(Movement.step(0, 10, 1.0 / 30) * 30, Movement.step(0, 10, 1.0 / 60) * 60)]
    var scene = load("res://scenes/marker.tscn").instantiate()
    checks.append(scene.texture.get_width() == 8)
    scene.free()
    for check in checks:
        if check: passed += 1
        else: failed += 1
    print("DIRECTOR_TESTS " + JSON.stringify({"passed": passed, "failed": failed, "total": checks.size()}))
    quit(1 if failed else 0)
'''


def game_project(root):
    root = Path(prepare_project(root))
    (root / 'scripts').mkdir(); (root / 'tests').mkdir()
    (root / 'scenes').mkdir(); (root / 'assets').mkdir()
    (root / 'assets/marker.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>')
    (root / 'scenes/marker.tscn').write_text('[gd_scene load_steps=2 format=3]\n[ext_resource type="Texture2D" path="res://assets/marker.svg" id="1"]\n[node name="Marker" type="Sprite2D"]\ntexture = ExtResource("1")\n')
    (root / '.gitignore').write_text('.godot/\n*.tmp\n')
    (root / 'project.godot').write_text('config_version=5\n[application]\nconfig/name="Director Engine Audit"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    (root / 'scripts/movement.gd').write_text('extends RefCounted\nstatic func step(x: float, speed: float, delta: float) -> float:\n    return x + speed * delta\n')
    (root / 'tests/director_tests.gd').write_text(RUNNER)
    return root


def engine_command():
    return [sys.executable, str(ROOT / 'scripts/run_engine_tests.py'), '--engine', 'godot', '--executable', shutil.which('godot')]


@pytest.mark.skipif(not shutil.which('godot'), reason='Godot engine is not installed')
def test_real_godot_pass_and_behavior_failure_are_measured(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'engine-data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'engine-config'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'engine-cache'))
    root = game_project(tmp_path / '한글 게임 경로')
    good = Verifier.verify(str(root), test_cmd=engine_command())
    assert good['passed'] and good['test_counts'] == {'passed': 4, 'failed': 0, 'total': 4}, good
    (root / 'scripts/movement.gd').write_text('extends RefCounted\nstatic func step(x: float, speed: float, delta: float) -> float:\n    return 0\n')
    bad = Verifier.verify(str(root), test_cmd=engine_command())
    assert not bad['passed'] and bad['test_counts']['failed'] > 0, bad


@pytest.mark.skipif(not shutil.which('godot'), reason='Godot engine is not installed')
def test_real_godot_worktree_verification_and_apply(tmp_path, monkeypatch):
    from tests.test_v0234_resume_parity import _mock_orch
    from schemas.order import OrderSchema
    from core.result_manager import ResultManager
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'engine-data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'engine-config'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'engine-cache'))
    project = game_project(tmp_path / 'engine-game')
    imported = Verifier.verify(str(project), test_cmd=engine_command(), git_checks=False)
    assert imported['passed'], imported
    git(project, 'add', '.')
    git(project, '-c', 'user.name=Engine Audit', '-c', 'user.email=audit@localhost', 'commit', '-m', 'Playable logic baseline')
    config = {'test_command': engine_command()}
    orch = _mock_orch(bootstrap={'enabled': True}, verification=config)
    def build(builder, order, worktree):
        root = Path(worktree)
        with (root / 'scripts/movement.gd').open('a') as out:
            out.write('static func clamp_health(value: int) -> int:\n    return clampi(value, 0, 100)\n')
        runner = RUNNER.replace('for check in checks:', 'checks.append(Movement.clamp_health(-10) == 0 and Movement.clamp_health(110) == 100)\n    for check in checks:')
        (root / 'tests/director_tests.gd').write_text(runner)
        return ['scripts/movement.gd', 'tests/director_tests.gd']
    result = orch.run(str(project), 'Add game health boundary behavior', order=OrderSchema(
        goal='Add game health boundary behavior', allowed_paths=['scripts/**', 'tests/**'],
        acceptance_criteria=['Movement stays frame-rate independent; health clamps to 0..100']), builder_fn=build)
    assert result['final_state'] == 'PASS', result
    assert result['baseline_verification']['test_counts']['passed'] == 4
    assert result['verification']['test_counts']['passed'] == 5
    before = git(project, 'rev-parse', 'HEAD')
    applied = ResultManager(config={'verification': config}).apply_tree(result['run_id'], request_id='engine-audit-apply')
    assert applied['status'] == 'applied', applied
    assert 'clamp_health' in (project / 'scripts/movement.gd').read_text()
    assert git(project, 'rev-parse', 'HEAD') == before
    final = Verifier.verify(str(project), test_cmd=engine_command(), git_checks=False)
    assert final['passed'] and final['test_counts']['passed'] == 5, final


def test_engine_preset_is_explicit_outside_project_and_survives_runtime_selection(tmp_path, monkeypatch):
    import core.bootstrap as bootstrap
    from core import engine_settings
    director = tmp_path / 'installed-director';director.mkdir()
    project = game_project(tmp_path / 'game')
    command = engine_settings.save(director, project, 'godot', sys.executable)
    assert command[0] == 'python'
    assert not (project / 'engine-projects.json').exists()
    monkeypatch.setattr(bootstrap, 'SOURCE_ROOT', director)
    config = {'verification': {'test_command': 'python -m pytest tests/'}}
    selected = bootstrap.configure_runtime(config, project)
    assert selected['verification']['test_command'] == command
    assert bootstrap.configure_runtime(config, tmp_path/'other')['verification'] == config['verification']
    assert config['verification']['test_command'] == 'python -m pytest tests/'
    with pytest.raises(ValueError): engine_settings.save(director, project, 'shell', sys.executable)
    with pytest.raises(ValueError): engine_settings.save(director, director, 'godot', sys.executable)
    engine_settings.registry_path(director).write_text('{broken')
    with pytest.raises(ValueError): bootstrap.configure_runtime(config, project)


def test_native_guard_rejects_in_root_writes_outside_scope(tmp_path):
    from agents.antigravity_builder import AntigravityBuilder
    from schemas.order import OrderSchema
    worktree = tmp_path / 'game';worktree.mkdir()
    AntigravityBuilder()._setup_scoped_permissions(worktree, OrderSchema(
        goal='Change player script', allowed_paths=['scripts/**'], protected_paths=['scripts/locked/**']))
    guard = worktree / '.agents/permission_guard.py'
    for path, expected in [('scripts/player.gd','allow'), ('scenes/level.tscn','deny'),
                           ('scripts/locked/player.gd','deny'), ('.git/config','deny')]:
        result = subprocess.run([sys.executable, str(guard)], input=json.dumps({'toolCall': {'name':'write_to_file','args':{'TargetFile':str(worktree/path)}}}),
                                capture_output=True, text=True, check=True)
        assert json.loads(result.stdout)['decision'] == expected
