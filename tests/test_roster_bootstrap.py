import copy
import json
import pytest
from core import company, staffing, game_team_setup as game
from tests.test_v301_companion_http import http_server, request


def owner():
    company.save({'owner':{'name':'대표','character':{'gender':'male','age':30,'color':'gold'}},'theme':'garden'}, company.current()['revision'])


def test_empty_company_bootstrap_saves_28_without_ai_or_engine_setup(monkeypatch):
    owner()
    assert staffing.current()['members'] == []
    monkeypatch.setattr(game,'readiness',lambda *a: (_ for _ in ()).throw(AssertionError('Must not require AI setup')))
    result = game.bootstrap(staffing.current()['revision'])
    assert result['changed'] and result['initialized']
    assert len(staffing.current()['members']) == 28
    assert staffing.current() == result['team']
    assert company.current()['roster_initialized']
    assert not game.bootstrap('old-stale-revision')['changed']


def test_reloads_and_manual_changes_never_recreate_or_replace_staff():
    owner()
    result = game.bootstrap(staffing.current()['revision'])
    team = copy.deepcopy(result['team'])
    removed = team['members'].pop()
    team['active_staff_ids'] = [i for i in team['active_staff_ids'] if i != removed['id']]
    team['members'][0]['name'] = '내가 수정한 이름'
    saved = staffing.save(team, result['team']['revision'])
    again = game.bootstrap(saved['revision'])
    assert not again['changed'] and again['team'] == saved
    assert len(staffing.current()['members']) == 27
    assert staffing.current()['members'][0]['name'] == '내가 수정한 이름'


def test_simultaneous_tabs_can_only_create_one_roster():
    from concurrent.futures import ThreadPoolExecutor
    owner()
    revision=staffing.current()['revision']
    def initialize():
        try:
            return game.bootstrap(revision)
        except staffing.TeamConflict:
            return {'changed':False}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:initialize(),range(2)))
    assert sum(bool(r['changed']) for r in results) == 1
    assert len(staffing.current()['members']) == 28
    assert len({m['id'] for m in staffing.current()['members']}) == 28
    assert company.current()['roster_initialized']


def test_owner_required_and_storage_failure_never_claims_completion(monkeypatch):
    result = game.bootstrap(staffing.current()['revision'])
    assert result['needs_owner'] and not result['initialized']
    owner()
    before = staffing.settings_path().read_bytes()
    monkeypatch.setattr(staffing,'save',lambda *a,**kw: (_ for _ in ()).throw(OSError('no disk space')))
    with pytest.raises(OSError):
        game.bootstrap(staffing.current()['revision'])
    assert staffing.settings_path().read_bytes() == before
    assert not company.current()['roster_initialized']


def test_authenticated_bootstrap_is_idempotent_and_not_a_get_side_effect(http_server):
    owner()
    team = staffing.current()
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    body=json.dumps({'expected_revision':team['revision']})
    path='/ops/team/bootstrap'
    assert request(http_server,'POST',path,body)[0] == 403
    assert request(http_server,'POST',path,body,headers={**headers,'Origin':'https://evil.example'})[0] == 403
    assert staffing.current() == team
    code,raw=request(http_server,'POST',path,body,headers=headers)
    assert code == 200 and len(json.loads(raw)['team']['members']) == 28
    code,raw=request(http_server,'POST',path,body,headers=headers)
    assert code == 200 and not json.loads(raw)['changed']
