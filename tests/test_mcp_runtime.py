import json
from pathlib import Path
import pytest
from core import mcp_runtime as runtime, staffing, usage
from scripts.director_mcp import dispatch


def configured(tmp_path, monkeypatch):
    from core import setup_assistant, web_workspace
    project = tmp_path / 'game'
    project.mkdir()
    monkeypatch.setattr(web_workspace, 'project', lambda p: project)
    monkeypatch.setattr(setup_assistant, 'check_mcp', lambda value: {'tools':['github_read']})
    result = runtime.configure({'project_path':str(project),'staff_id':'planner'})
    assert result['bridge_checked'] and not result['client_invocation_verified']
    return project


def test_runtime_flags_bind_actual_staff_and_do_not_relax_permissions(tmp_path, monkeypatch):
    project = configured(tmp_path, monkeypatch)
    usage.set_context(staff_id='gameplay',staff_project_path=str(project),stage='BUILDING')
    codex = runtime.augment(['codex','exec','--sandbox','read-only','-'])
    assert codex[-4:] == ['exec','--sandbox','read-only','-']
    import tomllib
    overrides = tomllib.loads('\n'.join(codex[i+1] for i,v in enumerate(codex) if v=='-c'))
    config = overrides['mcp_servers']['ai_dev_director_resources']
    assert config['args'][-1] == '--reference-only'
    assert config['args'][config['args'].index('--staff')+1] == 'gameplay'
    claude = runtime.augment(['claude','--print','--output-format','json'])
    assert claude[1] == '--mcp-config'
    entry = json.loads(claude[2])['mcpServers']['ai_dev_director_resources']
    assert entry['args'] == config['args']
    assert set(config['enabled_tools']) == {'github_search','github_read','github_acquire'}
    assert 'Bash' not in claude[claude.index('--allowedTools')+1]
    assert '--dangerously-skip-permissions' not in claude
    assert not any('approval' in s for s in codex)
    assert list(project.iterdir()) == []  # No project/account configuration files were edited.


def test_no_opt_in_no_other_project_no_login_or_meeting_attachment(tmp_path, monkeypatch):
    usage.set_context(staff_id='planner',staff_project_path=str(tmp_path),stage='BUILDING')
    argv=['codex','exec','--sandbox','read-only','-']
    assert runtime.augment(argv) == argv

    project=configured(tmp_path,monkeypatch)
    usage.set_context(staff_project_path=str(project))
    assert runtime.augment(['codex','--version']) == ['codex','--version']
    assert runtime.augment(['claude','auth','login']) == ['claude','auth','login']
    usage.set_context(stage='MEETING_DISCUSSION')
    assert runtime.augment(argv) == argv
    usage.set_context(stage='BUILDING',staff_project_path=str(tmp_path/'other'))
    assert runtime.augment(argv) == argv


def test_actual_process_runner_receives_the_scoped_mcp_flags(tmp_path, monkeypatch):
    from core.process_runner import ProcessTreeRunner, ProcessResult
    project=configured(tmp_path,monkeypatch)
    usage.set_context(staff_id='gameplay',staff_project_path=str(project),stage='BUILDING')
    captured=[]
    def run(cls, argv, **kwargs):
        captured.extend(argv)
        return ProcessResult(0,'fake local process','',False,0,123)
    monkeypatch.setattr(ProcessTreeRunner,'_run_process',classmethod(run))
    ProcessTreeRunner.run(['codex','exec','--sandbox','read-only','-'],cwd=str(project),stdin_data='test')
    assert 'mcp_servers.ai_dev_director_resources.command=' in captured[2]
    assert captured[-4:]==['exec','--sandbox','read-only','-']


def test_reference_only_bridge_never_exposes_project_files(tmp_path):
    result = dispatch({'method':'tools/list'},str(tmp_path),'planner',True)
    assert result['tools'] and all(t['name'].startswith('github_') for t in result['tools'])
    refused = dispatch({'method':'tools/call','params':{'name':'project_files','arguments':{}}},str(tmp_path),'planner',True)
    assert refused['isError']


def test_staff_project_context_reaches_planning_and_order_execution():
    from schemas.order import OrderSchema
    team=staffing.default_team()
    staffing.activate_planning(team,'C:/game')
    assert usage.context()['staff_project_path']=='C:/game'
    bound=staffing.bind_order(OrderSchema(goal='HUD'),team,project='C:/game')
    staffing.activate(bound,'BUILDER')
    assert usage.context()['staff_project_path']=='C:/game'
    staffing.activate_planning(None)
    assert usage.context()['staff_project_path'] is None


def test_two_provider_preset_keeps_builder_and_reviewer_distinct(monkeypatch):
    from core import ai_connections
    monkeypatch.setattr(ai_connections,'assert_idle',lambda:None)
    result=runtime.configure_codex_claude()
    saved=ai_connections.load()
    assert result['roles']==saved['roles']
    assert saved['roles']['builder'] != saved['roles']['reviewer']
    assert saved['roles']['head']==saved['roles']['reviewer']=='claude'
    assert saved['allow_same_provider'] and not result['authenticated']
