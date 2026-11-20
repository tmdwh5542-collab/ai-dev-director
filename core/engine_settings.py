"""Explicit per-project engine test presets stored outside the Builder's project."""
import json
import os
from pathlib import Path
import threading

_LOCK = threading.Lock()


def registry_path(director):
    return Path(director) / 'data' / 'engine-projects.json'


def read_registry(director):
    path = registry_path(director)
    if not path.exists(): return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict): raise ValueError('게임 검증 설정 파일 형식이 올바르지 않습니다.')
    return value


def project_key(project):
    return os.path.normcase(str(Path(project).resolve()))


def test_command(director, value):
    engine, executable = value.get('engine'), value.get('executable')
    if engine not in {'godot', 'unity'} or not isinstance(executable, str) or not Path(executable).is_absolute():
        raise ValueError('저장된 게임 엔진 검증 설정을 확인하세요.')
    platform = value.get('unity_platform', 'EditMode')
    if platform not in {'EditMode', 'PlayMode'}: raise ValueError('Unity 테스트 모드가 올바르지 않습니다.')
    return ['python', str(Path(director).resolve() / 'scripts/run_engine_tests.py'), '--engine', engine,
            '--executable', executable, '--unity-platform', platform]


def override_for(project, director):
    value = read_registry(director).get(project_key(project))
    if value is None: return {}
    if not isinstance(value, dict): raise ValueError('게임 프로젝트 검증 설정이 손상됐습니다.')
    return {'test_command': test_command(director, value)}


def save(director, project, engine, executable, unity_platform='EditMode'):
    if not str(project).strip() or not str(executable).strip(): raise ValueError('프로젝트 폴더와 엔진 실행 파일을 선택하세요.')
    director, project, executable = Path(director).resolve(), Path(project).resolve(), Path(executable).resolve()
    if director == project or director in project.parents or project in director.parents:
        raise ValueError('감독관 설치 폴더와 별개의 게임 프로젝트를 선택하세요.')
    marker = 'project.godot' if engine == 'godot' else 'ProjectSettings/ProjectVersion.txt'
    if not project.is_dir() or not (project / marker).is_file(): raise ValueError('선택한 엔진의 프로젝트 루트가 아닙니다.')
    if not executable.is_file(): raise ValueError('엔진 실행 파일을 찾을 수 없습니다.')
    value = {'engine': engine, 'executable': str(executable), 'unity_platform': unity_platform}
    command = test_command(director, value)
    with _LOCK:
        registry = read_registry(director)
        registry[project_key(project)] = value
        path = registry_path(director);path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    return command
