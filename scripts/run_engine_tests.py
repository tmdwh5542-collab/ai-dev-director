"""Trusted engine test adapter. Configure its absolute path in Director's per-project verification.
Godot projects provide tests/director_tests.gd and emit one DIRECTOR_TESTS JSON summary.
Unity uses a fresh NUnit XML report from its actual EditMode/PlayMode runner.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.process_runner import ProcessTreeRunner


def godot_counts(output):
    summaries = re.findall(r'^DIRECTOR_TESTS\s+(\{[^\r\n]+\})\s*$', output, re.M)
    if len(summaries) != 1:
        raise ValueError('Godot 테스트 결과 요약이 없거나 중복됐습니다.')
    value = json.loads(summaries[0])
    if not isinstance(value, dict) or any(type(value.get(k)) is not int or value[k] < 0 for k in ('passed', 'failed', 'total')):
        raise ValueError('Godot 테스트 수가 올바르지 않습니다.')
    if value['total'] != value['passed'] + value['failed'] or value['total'] == 0:
        raise ValueError('실행된 테스트가 없거나 테스트 합계가 다릅니다.')
    if re.search(r'^\s*(?:SCRIPT ERROR|ERROR):', output, re.M):
        raise ValueError('Godot 오류가 있어 성공으로 인정하지 않습니다.')
    return value['passed'], value['failed'], 0


def unity_counts(report):
    raw = Path(report).read_bytes()
    if len(raw) > 10_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unity 테스트 보고서를 안전하게 읽을 수 없습니다.')
    tree = ET.fromstring(raw)
    counts = {'Passed': 0, 'Failed': 0, 'Skipped': 0, 'Inconclusive': 0}
    for case in tree.iter('test-case'):
        result = case.get('result')
        if result not in counts:
            raise ValueError('알 수 없는 Unity 테스트 결과입니다: ' + str(result))
        counts[result] += 1
    if not sum(counts.values()) or not counts['Passed'] + counts['Failed'] + counts['Inconclusive']:
        raise ValueError('실행된 Unity 테스트가 없습니다.')
    return counts['Passed'], counts['Failed'] + counts['Inconclusive'], counts['Skipped']


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['godot', 'unity'], required=True)
    parser.add_argument('--executable', help='Absolute engine executable path, or executable on PATH')
    parser.add_argument('--unity-platform', choices=['EditMode', 'PlayMode'], default='EditMode')
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        executable = args.executable or ('godot' if args.engine == 'godot' else 'Unity')
        executable = shutil.which(executable) or executable
        if not Path(executable).is_file():
            raise ValueError('게임 엔진을 찾지 못했습니다. --executable에 설치된 실행 파일의 절대 경로를 지정하세요.')
        project = Path.cwd().resolve()
        with tempfile.TemporaryDirectory(prefix='director-engine-tests-') as temporary:
            report = Path(temporary) / 'results.xml'
            if args.engine == 'godot':
                if not (project / 'project.godot').is_file() or not (project / 'tests/director_tests.gd').is_file():
                    raise ValueError('project.godot과 tests/director_tests.gd가 필요합니다. docs/GAME_DEVELOPMENT_KO.md를 확인하세요.')
                imported = ProcessTreeRunner.run([executable, '--headless', '--path', str(project), '--editor', '--import'],
                                                 cwd=str(project), timeout=args.timeout)
                import_output = (imported.stdout or '') + '\n' + (imported.stderr or '')
                print(import_output)
                if imported.timed_out or imported.exit_code != 0 or re.search(r'^\s*(?:SCRIPT ERROR|ERROR):', import_output, re.M):
                    raise ValueError('Godot 씬·리소스 가져오기가 실패했습니다.')
                command = [executable, '--headless', '--path', str(project), '--script', 'res://tests/director_tests.gd']
            else:
                if not (project / 'ProjectSettings/ProjectVersion.txt').is_file():
                    raise ValueError('Unity 프로젝트 루트가 아닙니다.')
                command = [executable, '-batchmode', '-nographics', '-projectPath', str(project), '-runTests',
                           '-testPlatform', args.unity_platform, '-testResults', str(report), '-logFile', '-']
            result = ProcessTreeRunner.run(command, cwd=str(project), timeout=args.timeout)
            output = (result.stdout or '') + '\n' + (result.stderr or '')
            print(output, end='' if output.endswith('\n') else '\n')
            if result.timed_out:
                raise ValueError('게임 엔진 테스트 제한 시간을 넘었습니다.')
            passed, failed, skipped = godot_counts(output) if args.engine == 'godot' else unity_counts(report)
            print(f'{passed} passed, {failed} failed, {skipped} skipped')
            return 1 if failed or result.exit_code != 0 else 0
    except Exception as exc:
        print('ENGINE_TEST_ERROR: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
