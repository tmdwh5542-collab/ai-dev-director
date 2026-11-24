import copy
import json
from core import staffing, game_team_setup as game
from tests.test_v301_companion_http import http_server, request


def job(goal='게임 개발', **values):
    return {'status': 'RUNNING', 'project_path': '/game', 'goal': goal, 'steps': [], **values}


def test_all_seven_departments_have_one_manager_and_all_execution_roles():
    result = game.propose({'members': []}, [])
    assert result['team_ready']
    team = staffing.validate(result['prepared_team'])
    assert len(team['members']) == 7
    assert {staffing.department_for(m) for m in team['members']} == set(staffing.DEPARTMENTS)
    assert all(m['position'] == 'manager' for m in team['members'])
    assert all(r['target'] == r['actual'] == 1 for r in result['department_plan'])
    assert not game.propose(team, [])['suggestions']


def test_four_unfinished_tasks_use_two_people_but_completed_tasks_do_not():
    missions = [job('HUD UI 사운드') for _ in range(4)] + [job('레벨 맵', status='DONE') for _ in range(50)]
    result = game.propose({'members': []}, missions)
    plan = {p['department']: p for p in result['department_plan']}
    assert plan['design']['tasks'] == 4  # UI + audio in one mission counts once for the department
    assert plan['design']['actual'] == 2
    assert plan['level']['actual'] == 1
    assert plan['planning']['actual'] == plan['quality']['actual'] == plan['support']['actual'] == 2
    assert any(m['position'] == 'secretary' for m in result['prepared_team']['members'])
    assert all(p['actual'] <= 2 for p in result['department_plan'])


def test_assigned_backlog_project_scope_and_existing_staff_preservation():
    team = game.propose({'members': []}, [])['prepared_team']
    old = copy.deepcopy(team)
    dev = next(m for m in team['members'] if m['department'] == 'development')
    steps = [{'order': {'goal': '작은 기능', 'assigned_staff_id': dev['id']}} for _ in range(4)]
    result = game.propose(team, [job('작은 기능', steps=steps)] + [job('레벨 맵', project_path='/other') for _ in range(20)], project_path='/game')
    plan = {p['department']: p for p in result['department_plan']}
    assert plan['development']['actual'] == 2
    assert plan['level']['actual'] == 1
    assert result['prepared_team']['members'][:7] == old['members']
    assert team == old


def test_overstaffed_departments_and_secretaries_are_never_removed():
    team = staffing.default_team()
    for i in range(3):
        team['members'].append({'id': f'dev_{i}', 'name': f'기존 개발 {i}', 'slot': 'BUILDER', 'specialty': 'gameplay', 'duties': '게임 구현', 'department': 'development', 'position': 'employee'})
    secretary = {'id': 'sec', 'name': '기존 비서', 'slot': 'HEAD', 'specialty': 'planning', 'duties': '보고 취합', 'department': 'support', 'position': 'secretary'}
    team['members'].append(secretary)
    result = game.propose(team, [])
    assert result['team_ready']
    final = result['prepared_team']['members']
    assert all(any(m == old for m in final) for old in team['members'])
    assert next(p for p in result['department_plan'] if p['department'] == 'development')['retained_extra'] == 3
    assert next(p for p in result['department_plan'] if p['department'] == 'support')['actual'] == 2
    assert all(p['assigned'] <= 2 for p in result['department_plan'])
    assert next(p for p in result['department_plan'] if p['department'] == 'development')['assigned'] == 1


def test_inactive_staff_cannot_be_explicitly_assigned_and_snapshot_survives_roster_change():
    from schemas.order import OrderSchema
    team = game.propose({'members': []}, [])['prepared_team']
    dev = next(m for m in team['members'] if m['department'] == 'development')
    inactive = {**dev, 'id': 'reserve_dev', 'name': '지원 개발자', 'position': 'employee'}
    team['members'].append(inactive)
    reviewer = next(m for m in team['members'] if m['slot'] == 'REVIEWER')
    team['members'].append({**reviewer, 'id': 'reserve_reviewer', 'name': '지원 검수자', 'position': 'employee'})
    team = staffing.validate(team)
    bound = staffing.bind_order(OrderSchema(goal='게임 로직', assigned_staff_id='reserve_dev', assigned_reviewer_id='reserve_reviewer'), team)
    assert bound.assigned_staff_id != 'reserve_dev'
    assert bound.assigned_reviewer_id != 'reserve_reviewer'
    captured = copy.deepcopy(bound.staff_team)
    next_team = {**team, 'active_staff_ids': [m['id'] for m in team['members']]}
    saved = staffing.save(next_team, staffing.current()['revision'])
    assert saved['revision'] != team['revision']
    assert bound.staff_team == captured
    assert 'reserve_dev' not in bound.staff_team['active_staff_ids']


def test_bad_existing_execution_roles_do_not_claim_ready_when_capped():
    team = game.propose({'members': []}, [])['prepared_team']
    reviewer = next(m for m in team['members'] if m['slot'] == 'REVIEWER')
    reviewer['slot'] = 'BUILDER'
    other = {**reviewer, 'id': 'quality_2', 'name': '기존 품질 직원', 'position': 'employee'}
    team['members'].append(other)
    result = game.propose(team, [])
    assert not result['team_ready'] and result['blocked'] and result['missing_slots']


def test_readiness_distinguishes_team_from_unverified_login_and_engine(monkeypatch):
    from core import ai_connections, web_workspace
    monkeypatch.setattr(web_workspace, 'project', lambda path: (_ for _ in ()).throw(ValueError()))
    monkeypatch.setattr(ai_connections, 'public', lambda: {'registered': True,
        'settings': {'roles': {'head': 'openai', 'builder': 'claude', 'reviewer': 'antigravity'}, 'connections': {d: {'mode': 'cli', 'model': ''} for d in ai_connections.CLI}},
        'availability': {d: {'cli_installed': d == 'OPENAI', 'key_present': False} for d in ai_connections.CLI}})
    result = game.readiness(game.propose({'members': []}, [])['prepared_team'], {}, '/unknown')
    statuses = {c['id']: c['status'] for c in result['checks']}
    assert statuses['team'] == 'READY'
    assert statuses['head'] == 'CONFIGURED_NOT_AUTHENTICATED'
    assert statuses['builder'] == 'ACTION_REQUIRED'
    assert statuses['project'] == 'ACTION_REQUIRED' and statuses['engine'] == 'NOT_VERIFIED'
    assert not result['authentication_verified'] and not result['engine_execution_verified']
    assert result['starter_brief']['workflow_id'] == 'game'


def test_game_setup_api_auth_atomic_save_and_repeat_safety(http_server, monkeypatch):
    from core.mission import MissionStore
    monkeypatch.setattr(MissionStore, 'all', lambda self: [job('UI HUD') for _ in range(4)])
    monkeypatch.setattr(game, 'readiness', lambda *a: {'checks': [], 'starter_brief': dict(game.STARTER)})
    team = staffing.current()
    data = {'team': team, 'expected_revision': team['revision'], 'goal': '', 'project_path': ''}
    headers = {'Content-Type': 'application/json', 'X-Solomon-Bridge': 'test-token'}
    path = '/ops/team/game-ready'
    assert request(http_server, 'POST', path, json.dumps(data))[0] == 403
    assert request(http_server, 'POST', path, json.dumps(data), headers={**headers, 'Origin': 'https://evil.example'})[0] == 403
    code, raw = request(http_server, 'POST', path, json.dumps(data), headers=headers)
    assert code == 200
    result = json.loads(raw)
    assert result['team'] == staffing.current()
    staffing.validate(result['team'])
    before = copy.deepcopy(result['team'])
    data.update(team=before, expected_revision=before['revision'])
    code, raw = request(http_server, 'POST', path, json.dumps(data), headers=headers)
    assert code == 200 and json.loads(raw)['team'] == before
    data['expected_revision'] = 'stale'
    assert request(http_server, 'POST', path, json.dumps(data), headers=headers)[0] == 409
    assert staffing.current() == before
    from core.device_link import WRITE_API
    assert path in WRITE_API
