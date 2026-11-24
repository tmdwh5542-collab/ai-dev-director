"""Opt-in per-project GitHub MCP attachment for Director-launched Codex/Claude work.

Uses process-local CLI settings, never writes the user's AI account configuration.
"""
import json
import os
import sys
import threading
from pathlib import Path
from core import staffing

LOCK = threading.Lock()
ROOT = Path(__file__).resolve().parents[1]


def path():
    return staffing.settings_path().parent / 'mcp_runtime.json'


def current():
    return json.loads(path().read_text(encoding='utf-8')) if path().exists() else {'projects': {}}


def key(project):
    return os.path.normcase(str(Path(project).resolve()))


def configure(value):
    from core import setup_assistant, web_workspace as web
    project = web.project(value.get('project_path'))
    enabled = value.get('enabled', True)
    if type(enabled) is not bool:
        raise ValueError('자동 MCP 연결 설정을 확인하세요.')
    check = setup_assistant.check_mcp(value) if enabled else None
    with LOCK:
        state = current()
        state['projects'][key(project)] = {'enabled': enabled, 'clients': ['OPENAI', 'ANTHROPIC'], 'checked': bool(check)}
        web.atomic(path(), state)
    return {'configured': enabled, 'project_path': str(project), 'clients': ['Codex', 'Claude Code'], 'bridge_checked': bool(check),
            'client_authenticated': False, 'client_invocation_verified': False,
            'notice': '이 프로그램이 실행하는 Codex·Claude Code 작업에 GitHub 자료용 MCP를 자동 연결하도록 저장했습니다. 다음 호출부터 적용됩니다. 외부 데스크톱 앱의 전역 설정·로그인은 바꾸지 않으며 실제 클라이언트 도구 호출은 아직 미검증입니다.'}


def augment(argv):
    from core import usage, employee_tools
    if not argv:
        return argv
    provider = usage.provider_of(argv[0])
    if provider not in {'OPENAI', 'ANTHROPIC'}:
        return argv
    if provider == 'OPENAI' and 'exec' not in argv or provider == 'ANTHROPIC' and '--print' not in argv:
        return argv
    ctx = usage.context()
    if str(ctx.get('stage','')).startswith(('MEETING_', 'HERMES_')):
        return argv
    project, ident = ctx.get('staff_project_path'), ctx.get('staff_id')
    if not project or not ident:
        return argv
    cfg = current()['projects'].get(key(project), {})
    if not cfg.get('enabled') or provider not in cfg.get('clients', []):
        return argv
    if not any(m['id'] == ident for m in staffing.current()['members']):
        return argv  # old captured employees may no longer have current MCP access
    allowed = [t for t in employee_tools.allowed(ident) if t in {'github_search','github_read','github_acquire'}]
    if not allowed:
        return argv
    args = [str(ROOT / 'scripts/director_mcp.py'), '--project', str(project), '--staff', ident, '--reference-only']
    entry = {'command': sys.executable, 'args': args}
    name = 'ai_dev_director_resources'
    if provider == 'OPENAI':
        flags = ['-c', 'mcp_servers.' + name + '.command=' + json.dumps(sys.executable),
                 '-c', 'mcp_servers.' + name + '.args=' + json.dumps(args, ensure_ascii=False),
                 '-c', 'mcp_servers.' + name + '.enabled_tools=' + json.dumps(allowed)]
    else:
        flags = ['--mcp-config', json.dumps({'mcpServers': {name: entry}}, ensure_ascii=False),
                 '--allowedTools', ','.join('mcp__'+name+'__'+tool for tool in allowed)]
    return [argv[0], *flags, *argv[1:]]


def configure_codex_claude():
    from core import ai_connections
    ai_connections.assert_idle()
    value = ai_connections.public()['settings']
    value['roles'] = {'head':'claude','builder':'openai','reviewer':'claude'}
    value['allow_same_provider'] = True
    for domain in ('OPENAI','ANTHROPIC'):
        value['connections'][domain].update(mode='cli',model='')
    ai_connections.save(value)
    return {'roles':value['roles'],'configured':True,'authenticated':False,
            'notice':'기획 Claude Code · 구현 Codex · 검수 Claude Code로 저장했습니다. 구현과 검수는 다른 AI를 사용하지만 기획과 검수는 Claude를 공유합니다. 로그인·할당량은 실제 호출 전 미검증입니다.'}
