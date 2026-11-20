import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from core import company, staffing, company_meetings as meetings, usage
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


def owner(theme='creative', auto=False):
    return {'owner': {'name':'우리 회사 대표','character':{'gender':'female','age':39,'color':'violet'}},'theme':theme,'auto_meetings':auto}


def test_first_company_starts_with_owner_only_and_persists_hiring():
    initial=company.current();assert initial['company'] is None
    company.save(owner(),initial['revision'])
    assert staffing.current()['members']==[]
    with pytest.raises(ValueError,match='채용'):staffing.validate(staffing.current())
    team=staffing.current();team['members'].append(copy.deepcopy(staffing.DEFAULT_MEMBERS[0]))
    staffing.save(team,team['revision'])
    assert company.current()['company']['owner']['name']=='우리 회사 대표'
    assert len(staffing.current()['members'])==1
    revision=company.current()['revision'];company.save(owner('garden'),revision)
    assert len(staffing.current()['members'])==1
    with pytest.raises(staffing.TeamConflict):company.save(owner(),revision)


def test_legacy_team_preserved_and_company_revision_independent_of_hiring():
    team=staffing.current();staffing.save(team,team['revision']);initial=company.current()
    company.save(owner(),initial['revision']);assert len(staffing.current()['members'])==6
    revision=company.current()['revision'];team=staffing.current();team['members'][0]['name']='새 과장';staffing.save(team,team['revision'])
    assert company.current()['revision']==revision
    company.save(owner('corporate'),revision);assert staffing.current()['members'][0]['name']=='새 과장'


@pytest.mark.parametrize('character',[
 {'gender':'other','age':30,'color':'mint'}, {'gender':[],'age':30,'color':'mint'},
 {'gender':'male','age':True,'color':'mint'}, {'gender':'male','age':17,'color':'mint'},
 {'gender':'female','age':101,'color':'mint'}, {'gender':'female','age':30.5,'color':'mint'},
 {'gender':'female','age':30,'color':'javascript:alert(1)'},
])
def test_character_validation(character):
    with pytest.raises(ValueError):company.validate_character(character)


def test_departments_limit_four_including_one_manager_and_28_total():
    members=[]
    for department in staffing.DEPARTMENTS:
        for i in range(4):
            members.append({'id':department+str(i),'name':'직원','department':department,'position':'manager' if i==0 else 'employee',
                            'slot':{'planning':'HEAD','quality':'REVIEWER'}.get(department,'BUILDER'),'specialty':'general','duties':'지정된 업무를 구현하고 검증합니다.',
                            'character':{'gender':'female','age':29,'color':'blue'}})
    team=staffing.validate({'members':members});assert len(team['members'])==28
    bad=copy.deepcopy(team);bad['members'][1]['position']='manager'
    with pytest.raises(ValueError,match='과장'):staffing.validate(bad)
    bad=copy.deepcopy(team);bad['members'].pop();bad['members'].append({**members[1],'id':'excess'})
    with pytest.raises(ValueError,match='최대 4명'):staffing.validate(bad)
    bad=copy.deepcopy(team);bad['members'][0]['position']='employee'
    with pytest.raises(ValueError,match='과장'):staffing.validate(bad)
    assert staffing.validate(bad,require_ready=False)
    bad['members'][0]['position']='secretary'
    with pytest.raises(ValueError,match='경영지원과'):staffing.validate(bad,require_ready=False)


def test_company_api_auth_validation_conflict_and_new_static(env,http_server):
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    code,raw=request(http_server,'GET','/ops/company');assert code==200
    initial=json.loads(raw);payload=json.dumps({'company':owner(),'expected_revision':initial['revision']})
    assert request(http_server,'POST','/ops/company',payload)[0]==403
    assert request(http_server,'POST','/ops/company',payload,headers={**headers,'Origin':'https://evil.example'})[0]==403
    assert request(http_server,'POST','/ops/company',payload,headers=headers)[0]==200
    assert request(http_server,'POST','/ops/company',payload,headers=headers)[0]==409
    for body in ['[]','{}',' '*4097]:assert request(http_server,'POST','/ops/company',body,headers=headers)[0]==400
    for url in ['/company.js','/meetings.js']:
        assert request(http_server,'GET',url)[0]==200
        assert request(http_server,'GET',url,headers={'Origin':'https://evil.example'})[0]==403


def config():
    return {'head':{'provider':'claude'},'builder':{'provider':'antigravity'},'reviewer':{'provider':'openai'}}


def meeting(tmp_path, **extra):
    project=tmp_path/'game';project.mkdir(exist_ok=True);(project/'project.godot').write_text('[application]\n')
    payload={'request_id':'meeting-test-1234','topic':'Godot 게임 조작 안내 개선','department':'development','kind':'department','project_path':str(project),**extra}
    return meetings.submit(payload,config(),lambda p:(True,str(Path(p).resolve())),background=False)


class FakeRunner:
    def __init__(self,invalid=False):self.calls=[];self.invalid=invalid
    def invoke(self,domain,prompt,cwd,stage):
        self.calls.append((domain,prompt,usage.context()))
        if stage=='MEETING_DISCUSSION':output={'opinion':'HUD 안내를 보강하고 설치가 필요한 기능은 별도 승인이 필요합니다.'}
        elif stage=='MEETING_SYNTHESIS':
            output={'summary':'구현 세부안과 외부 설치안을 구분해 제안합니다.','proposals':[
                {'title':'조작 안내 보강','reason':'현재 목표의 사용성을 개선합니다.','action':'키보드 조작 안내를 표시합니다.','category':'implementation_detail','impact_flags':[]},
                {'title':'외부 패키지 설치','reason':'추가 기능 검토','action':'패키지 버전을 확인합니다.','category':'installation','impact_flags':['installation']},
                {'title':'테스트 보류','reason':'근거 부족','action':'재현 조건을 확인합니다.','category':'test_coverage','impact_flags':[]}]}
        else:
            # IDs are controlled by the Director, not made up by the participant.
            proposals=json.loads(prompt.split('Independently review these proposals: ',1)[1].split('\nJSON ',1)[0])
            output={'reviews':[{'id':p['id'],'verdict':'hold' if i==3 else 'approve','important':False,'reason':'근거를 검토했습니다.'} for i,p in enumerate(proposals,1)]}
            if self.invalid:output['reviews'].pop()
        return {'output':json.dumps(output,ensure_ascii=False),'exit_code':0,'duration_sec':.1}


def test_real_meeting_pipeline_separates_minor_important_and_held_and_records_context(tmp_path):
    m=meeting(tmp_path);runner=FakeRunner();meetings.run(m['id'],runner)
    completed=meetings.report(m['id']);state=meetings.snapshot()
    assert completed['status']=='DONE' and len(completed['transcript'])==3
    assert [a['status'] for a in state['agendas']]==['ADOPTED','PENDING','PENDING']
    assert [c[0] for c in runner.calls]==['GOOGLE','GOOGLE','OPENAI']
    assert 'HUD 안내' in runner.calls[1][1] and 'project.godot' in runner.calls[0][1]
    assert runner.calls[0][2]['staff_id']=='gameplay' and runner.calls[-1][2]['staff_id']=='quality'
    assert len(meetings.project_decisions(m['project_path']))==1
    assert meetings.project_decisions(tmp_path/'other')==[]
    saved=meetings.decide({'ids':[a['id'] for a in state['agendas'] if a['status']=='PENDING'],'action':'approve','expected_revision':state['revision']})
    assert sum(a['status']=='APPROVED' for a in saved['agendas'])==2
    with pytest.raises(staffing.TeamConflict):meetings.decide({'ids':[state['agendas'][1]['id']],'action':'reject','expected_revision':state['revision']})
    assert len(meetings.project_decisions(m['project_path']))==3
    context=staffing.planning_context({'project_path':m['project_path']},staffing.current())
    assert len(context['company_decisions'])==3 and 'do not expand' in context['company_decision_rule']
    assert usage.context()['staff_id'] is None


def test_meeting_replay_busy_and_failure_do_not_adopt_partial_proposals(tmp_path):
    m=meeting(tmp_path);assert meeting(tmp_path)['id']==m['id']
    with pytest.raises(staffing.TeamConflict):meeting(tmp_path,request_id='second-meeting-123')
    meetings.run(m['id'],FakeRunner(invalid=True));state=meetings.snapshot()
    assert state['meetings'][0]['status']=='FAILED' and state['agendas']==[]
    assert len(state['meetings'][0]['transcript'])==3
    with pytest.raises(staffing.TeamConflict):meeting(tmp_path,topic='다른 주제')


def test_executive_meeting_never_automatically_adopts_and_bulk_is_atomic(tmp_path):
    m=meeting(tmp_path,kind='executive');meetings.run(m['id'],FakeRunner())
    state=meetings.snapshot();assert all(a['status']=='PENDING' for a in state['agendas'])
    with pytest.raises(ValueError):meetings.decide({'ids':[state['agendas'][0]['id'],'missing'],'action':'approve','expected_revision':state['revision']})
    assert all(a['status']=='PENDING' for a in meetings.snapshot()['agendas'])


def test_meeting_stop_and_restart_are_not_replayed(tmp_path,monkeypatch):
    m=meeting(tmp_path);assert meetings.stop_all()==1
    meetings.run(m['id'],FakeRunner());assert meetings.report(m['id'])['status']=='STOPPED'
    m=meeting(tmp_path,request_id='restart-meeting-123')
    monkeypatch.setattr('core.mission._pid_alive',lambda pid:False)
    assert meetings.report(m['id'])['status']=='INTERRUPTED'
    assert meetings.listing()['agendas']==[]


def test_automatic_meeting_only_after_completed_mission_and_owner_setting(tmp_path):
    company.save(owner(auto=False),company.current()['revision']);team=staffing.default_team();staffing.save(team,staffing.current()['revision'])
    project=tmp_path/'game';project.mkdir();mission={'mission_id':'MSN-TEST','status':'DONE','goal':'game','summary':'verified','staff_team':team,'project_path':str(project)}
    assert meetings.after_mission(mission,config(),lambda p:(True,p)) is None
    prefs=company.current();company.save(owner(auto=True),prefs['revision'])
    # Capture the real submission contract without invoking paid/live CLI providers in unit tests.
    captured=[]
    from unittest.mock import patch
    with patch.object(meetings,'submit',side_effect=lambda *args,**kwargs:captured.append((args,kwargs)) or {'id':'captured'}):
        assert meetings.after_mission(mission,config(),lambda p:(True,p))['id']=='captured'
        assert meetings.after_mission({**mission,'status':'BLOCKED'},config(),lambda p:(True,p)) is None
    assert captured[0][0][0]['request_id']=='auto-MSN-TEST' and captured[0][1]['team_snapshot']==team


def test_meeting_endpoint_requires_auth_and_invalid_requests_do_not_call_ai(env,http_server):
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    assert request(http_server,'GET','/ops/meetings')[0]==200
    for url in ['/ops/meetings','/ops/meetings/decide']:
        assert request(http_server,'POST',url,'{}')[0]==403
        assert request(http_server,'POST',url,'[]',headers=headers)[0]==400
        assert request(http_server,'POST',url,'{}',headers={**headers,'Origin':'https://evil.example'})[0]==403
    assert meetings.snapshot()['meetings']==[]


def test_owner_only_can_ask_planning_questions_but_cannot_bind_executable_orders():
    from schemas.order import OrderSchema
    empty=staffing.validate({'members':[]},require_ready=False)
    context=staffing.planning_context({'project_path':None},empty)
    staffing.activate_planning(context['staff_team'])
    assert usage.context()['staff_id'] is None
    with pytest.raises(ValueError):staffing.bind_order(OrderSchema(goal='build game'),empty)


def test_department_workload_balancing_preserves_specialty_and_independent_roles():
    from schemas.order import OrderSchema
    team=staffing.default_team()
    team['members'] += [{**team['members'][1],'id':'dev2','name':'추가 개발자','department':'development','position':'employee'},
                        {**team['members'][-1],'id':'qa2','name':'추가 검수자','department':'quality','position':'employee'}]
    first=staffing.bind_order(OrderSchema(goal='player movement',allowed_paths=['src/**']),team)
    second=staffing.bind_order(OrderSchema(goal='player movement',allowed_paths=['src/**']),team,history=[{'order':first.model_dump()}])
    assert first.assigned_staff_id=='gameplay' and second.assigned_staff_id=='dev2'
    assert first.assigned_reviewer_id=='quality' and second.assigned_reviewer_id=='qa2'
    assert staffing.member_for(second,'REVIEWER')['id']=='qa2'
    explicit=staffing.bind_order(OrderSchema(goal='movement',assigned_staff_id='gameplay'),team,history=[{'order':first.model_dump()}])
    assert explicit.assigned_staff_id=='gameplay'
    hud=staffing.bind_order(OrderSchema(goal='HUD UI'),team,history=[{'order':first.model_dump()}])
    assert hud.assigned_staff_id=='interface'


def test_executive_review_reuses_existing_agendas_and_preserves_owner_decision(tmp_path):
    department=meeting(tmp_path);meetings.run(department['id'],FakeRunner())
    before=meetings.snapshot();pending=[a['id'] for a in before['agendas'] if a['status']=='PENDING']
    executive=meeting(tmp_path,kind='executive',request_id='executive-test-123')
    assert executive['pending_input']==pending
    meetings.run(executive['id'],FakeRunner())
    after=meetings.snapshot();assert len(after['agendas'])==len(before['agendas'])
    assert all(a['status']=='PENDING' and a['executive_meeting_id']==executive['id'] for a in after['agendas'] if a['id'] in pending)


def test_three_pending_important_items_trigger_one_executive_batch_without_execution(tmp_path,monkeypatch):
    m=meeting(tmp_path);meetings.run(m['id'],FakeRunner())
    # Explicitly enable the owner's automatic meeting preference, keeping the existing team.
    company.save(owner(auto=True),company.current()['revision'])
    with meetings.LOCK:
        state=meetings._read();source=next(a for a in state['agendas'] if a['status']=='PENDING')
        state['agendas'].append({**source,'id':'extra-pending'});meetings._write(state)
    captured=[]
    monkeypatch.setattr(meetings,'submit',lambda *args,**kw:captured.append((args,kw)) or {'id':'executive-queued'})
    assert meetings.maybe_executive(m)['id']=='executive-queued'
    assert captured[0][0][0]['kind']=='executive' and captured[0][1]['team_snapshot']==m['team']
    assert all(a['status'] in {'ADOPTED','PENDING'} for a in meetings.snapshot()['agendas'])


def test_meeting_uses_real_readonly_runner_commands_in_isolated_scratch(tmp_path,monkeypatch):
    import sys
    from core.process_runner import ProcessTreeRunner
    monkeypatch.setattr('core.research_runner.resolve_cli',lambda name:sys.executable)
    monkeypatch.setattr('core.research_runner.probe_version',lambda executable:'test-version')
    calls=[];fake=FakeRunner()
    def process(**kw):
        calls.append(kw)
        stage=usage.context()['stage'];output=fake.invoke('test',kw['stdin_data'],kw['cwd'],stage)['output']
        return SimpleNamespace(stdout=output,stderr='',exit_code=0,timed_out=False,duration_sec=.1)
    monkeypatch.setattr(ProcessTreeRunner,'run',staticmethod(process))
    project=tmp_path/'game';project.mkdir()
    cfg={'head':{'provider':'antigravity'},'builder':{'provider':'claude'},'reviewer':{'provider':'openai'}}
    m=meetings.submit({'request_id':'readonly-meeting-123','topic':'既存 게임의 테스트와 조작 안내 검토','kind':'department','department':'development','project_path':str(project)},cfg,lambda p:(True,p),background=False)
    meetings.run(m['id'])
    assert meetings.report(m['id'])['status']=='DONE'
    assert all(Path(c['cwd'])!=project for c in calls)
    assert calls[0]['argv'][-2:]==['--tools','']
    assert '--sandbox' in calls[-1]['argv'] and 'read-only' in calls[-1]['argv']
    assert list(project.iterdir())==[]
