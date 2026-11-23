import copy
import json
import pytest
from core import staffing
from core.team_recommendations import recommend, classify
from tests.test_v301_companion_http import http_server, request


def apply(team, result):
    members = copy.deepcopy(team['members'])
    for s in result['suggestions']:
        if s['kind'] == 'promote':
            next(m for m in members if m['id'] == s['member']['id'])['position'] = 'manager'
        else:
            members.append(s['member'])
    return staffing.validate({'members': members}, require_ready=False)


def mission(goal, **kw):
    return {'status': 'RUNNING', 'goal': goal, 'project_path': '/game', 'steps': [], **kw}


def test_empty_company_can_build_game_team_without_saving_or_mutating_input():
    team = {'members': []}
    before = copy.deepcopy(team)
    result = recommend(team, [], 'Godot 게임의 전투·맵·HUD와 테스트')
    ready = staffing.validate(apply(team, result))
    assert len(ready['members']) == 6
    assert {m['specialty'] for m in ready['members']} == {'planning', 'quality', 'gameplay', 'ui', 'level', 'testing'}
    assert team == before
    assert recommend(ready, [], 'Godot 게임의 전투·맵·HUD와 테스트')['suggestions'] == []


def test_no_evidence_uses_minimal_execution_roles_and_says_why():
    result = recommend({'members': []}, [])
    team = staffing.validate(apply({'members': []}, result))
    assert len(team['members']) == 3
    assert {m['slot'] for m in team['members']} == set(staffing.SLOTS)
    assert result['summary']['active_missions'] == 0
    assert '로컬 규칙' in result['basis']


def test_current_staff_are_preserved_and_only_unfinished_project_work_counts():
    team = staffing.default_team()
    original = copy.deepcopy(team)
    missions = [mission('UI 화면 구현', project_path='/other') for _ in range(12)]
    missions += [mission('UI 화면 구현', status='DONE') for _ in range(12)]
    missions += [mission('UI 화면 구현') for _ in range(7)]
    result = recommend(team, missions, project_path='/game/')
    hires = [s['member'] for s in result['suggestions'] if s['kind'] == 'hire']
    assert len(hires) == 2 and all(m['specialty'] == 'ui' for m in hires)
    assert all(m['position'] == 'employee' for m in hires)
    assert result['summary']['active_missions'] == 7
    assert apply(team, result)['members'][:6] == original['members']
    assert team == original


def test_pending_assignments_drive_load_but_finished_steps_do_not():
    team = staffing.default_team()
    steps = [{'order': {'assigned_staff_id': 'interface', 'goal': 'HUD'}} for _ in range(7)]
    steps += [{'order': {'assigned_staff_id': 'interface', 'goal': 'HUD'}, 'result': {'final_state': 'PASS'}} for _ in range(20)]
    result = recommend(team, [mission('HUD', steps=steps)])
    assert len(result['suggestions']) == 2
    assert all(s['member']['specialty'] == 'ui' and '7건' in s['reason'] for s in result['suggestions'])


def test_independent_review_backlog_adds_reviewers_without_changing_builder_roles():
    team = staffing.default_team()
    steps = [{'order': {'assigned_reviewer_id': 'quality', 'goal': '일반 기능'}} for _ in range(7)]
    result = recommend(team, [mission('일반 기능', steps=steps)])
    hires = [s['member'] for s in result['suggestions'] if s['member']['slot'] == 'REVIEWER']
    assert len(hires) == 2
    assert all(m['specialty'] == 'quality' and m['position'] == 'employee' for m in hires)
    assert apply(team, result)['members'][:6] == team['members']


def test_full_department_promotes_existing_person_and_never_exceeds_capacity():
    team = staffing.default_team()
    for m in team['members']:
        m['position'] = 'employee'
    for i in range(3):
        team['members'].append({'id': f'ui_{i}', 'name': f'UI {i}', 'slot': 'BUILDER', 'specialty': 'ui', 'department': 'design', 'position': 'employee', 'duties': 'UI 구현'})
    result = recommend(team, [mission('HUD') for _ in range(20)])
    final = apply(team, result)
    staffing.validate(final)
    assert len([m for m in final['members'] if staffing.department_for(m) == 'design']) == 4
    assert len([m for m in final['members'] if staffing.department_for(m) == 'design' and staffing.position_for(m) == 'manager']) == 1
    for old in team['members']:
        new = next(m for m in final['members'] if m['id'] == old['id'])
        assert {k: v for k, v in old.items() if k != 'position'} == {k: v for k, v in new.items() if k != 'position'}


def test_new_department_team_member_depends_on_its_manager():
    result = recommend(staffing.default_team(), [mission('audio sound') for _ in range(7)])
    hires = [s for s in result['suggestions'] if s['kind'] == 'hire']
    # Design's existing UI manager remains the only manager; these are ordinary team members.
    assert all(s['member']['position'] == 'employee' for s in hires)
    empty = recommend({'members': []}, [mission('audio sound') for _ in range(7)])
    audio = [s for s in empty['suggestions'] if s['member']['specialty'] == 'audio']
    assert audio[0]['member']['position'] == 'manager'
    assert all(s['depends_on'] == [audio[0]['id']] for s in audio[1:])


def test_secretary_keeps_her_role_when_support_needs_a_manager():
    team = staffing.default_team()
    secretary = {'id': 'secretary', 'name': '비서', 'slot': 'HEAD', 'specialty': 'planning', 'duties': '대표 보고 취합', 'department': 'support', 'position': 'secretary'}
    team['members'].append(secretary)
    result = recommend(team, [])
    final = apply(team, result)
    assert next(m for m in final['members'] if m['id'] == 'secretary') == secretary
    assert len(result['suggestions']) == 1
    assert result['suggestions'][0]['member']['department'] == 'support'
    assert result['suggestions'][0]['member']['position'] == 'manager'
    staffing.validate(final)


def test_limits_and_word_matching():
    assert 'ui' not in classify('build quick guide')
    assert {'ui', 'gameplay'} <= classify('Unity UI 게임')
    with pytest.raises(ValueError):
        recommend({'members': []}, [], goal='x' * 2001)
    with pytest.raises(ValueError):
        recommend({'members': []}, [], goal=[])
    full = staffing.default_team()
    for dept in staffing.DEPARTMENTS:
        count = sum(staffing.department_for(m) == dept for m in full['members'])
        for i in range(count, 4):
            full['members'].append({'id': dept + str(i), 'name': dept + str(i), 'slot': 'BUILDER', 'specialty': 'general', 'duties': '기존 업무', 'department': dept, 'position': 'manager' if i == 0 else 'employee'})
    result = recommend(full, [mission('audio UI Unity') for _ in range(20)])
    assert not result['suggestions'] and result['blocked']
    assert len(apply(full, result)['members']) == 28


def test_recommendation_api_requires_auth_rejects_stale_draft_and_never_saves(http_server, monkeypatch):
    from core.mission import MissionStore
    monkeypatch.setattr(MissionStore, 'all', lambda self: [mission('Godot UI')])
    team = staffing.current()
    payload = {'team': team, 'expected_revision': team['revision'], 'goal': '게임 사운드', 'project_path': ''}
    data = json.dumps(payload)
    headers = {'Content-Type': 'application/json', 'X-Solomon-Bridge': 'test-token'}
    assert request(http_server, 'POST', '/ops/team/recommendations', data)[0] == 403
    assert request(http_server, 'POST', '/ops/team/recommendations', data, headers={**headers, 'Origin': 'https://evil.example'})[0] == 403
    code, body = request(http_server, 'POST', '/ops/team/recommendations', data, headers=headers)
    assert code == 200 and json.loads(body)['suggestions']
    assert staffing.current() == team
    payload['expected_revision'] = 'stale'
    assert request(http_server, 'POST', '/ops/team/recommendations', json.dumps(payload), headers=headers)[0] == 409
    assert request(http_server, 'POST', '/ops/team/recommendations', '[]', headers=headers)[0] == 400
    assert request(http_server, 'POST', '/ops/team/recommendations', 'x' * 64001, headers=headers)[0] == 400
    from core.device_link import WRITE_API
    assert '/ops/team/recommendations' in WRITE_API
