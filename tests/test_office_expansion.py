import copy
import io
import json
from types import SimpleNamespace
import urllib.error
import pytest
from core import staffing, company, ai_connections as ai, executive_briefing as brief, skill_library as skills, office_maps
from core.provider_manager import ProviderManager, ProviderStatus, FailoverMode
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


def setup_ai(provider='openai',mode='api'):
    return {'roles':dict.fromkeys(('head','builder','reviewer'),provider),'allow_same_provider':True,
        'connections':{d:{'mode':mode,'model':'test-model' if mode=='api' else '', 'key_env':ai.DEFAULT_ENV[d]} for d in ai.CLI}}


def test_single_provider_requires_explicit_consent_and_preserves_selection():
    value=setup_ai();value['allow_same_provider']=False
    with pytest.raises(ValueError):ai.save(value)
    assert not ai.path().exists()
    value['allow_same_provider']=True;ai.save(value)
    config=ai.apply({})
    assert all(config[s]['provider']=='openai' for s in ('head','builder','reviewer'))
    pm=ProviderManager();pm.set_status('OPENAI',ProviderStatus.HEALTHY);pm.set_status('GOOGLE',ProviderStatus.UNAVAILABLE);pm.set_status('ANTHROPIC',ProviderStatus.UNAVAILABLE)
    assert pm.get_failover_mode()[0]==FailoverMode.DEGRADED
    assigned=pm.resolve_roles('openai','openai','openai',strict=True)
    assert assigned['can_proceed'] and assigned['reviewer_provider']=='openai'
    pm.set_status('OPENAI',ProviderStatus.AUTH_FAILED)
    assert pm.get_failover_mode()[0]==FailoverMode.STOP


@pytest.mark.parametrize('domain,response,expected',[
 ('OPENAI',{'output':[{'content':[{'type':'output_text','text':'openai output'}]}]},'openai output'),
 ('ANTHROPIC',{'content':[{'type':'text','text':'claude output'}]},'claude output'),
 ('GOOGLE',{'candidates':[{'content':{'parts':[{'text':'thinking','thought':True},{'text':'gemini output'}]}}]},'gemini output')])
def test_api_transport_real_formats_no_secret_persistence_or_cli_required(monkeypatch,domain,response,expected):
    from core import usage
    ai.save(setup_ai());secret='not-a-real-secret-ABC';monkeypatch.setenv(ai.DEFAULT_ENV[domain],secret)
    calls=[]
    def opener(req,timeout):
        calls.append((req,timeout));return io.BytesIO(json.dumps(response).encode())
    result=ai.invoke_api(domain,'actual prompt',opener=opener)
    assert result['output']==expected and result['api_key_used'] and result['exit_code'] is None
    assert calls[0][0].full_url.startswith('https://') and secret not in calls[0][0].full_url
    assert secret not in ai.path().read_text() and secret not in json.dumps(ai.public()) and secret not in json.dumps(usage.recent_calls())
    assert usage.recent_calls()[0]['provider']==domain
    with pytest.raises(RuntimeError,match='유료'):ai.invoke_api(domain,'blocked live call')


def test_api_failure_redacts_provider_body(monkeypatch):
    ai.save(setup_ai());monkeypatch.setenv('OPENAI_API_KEY','private-key')
    def fail(req,timeout):raise urllib.error.HTTPError(req.full_url,401,'private-key',{},io.BytesIO(b'private-key'))
    with pytest.raises(RuntimeError,match='unauthorized') as error:ai.invoke_api('OPENAI','prompt',opener=fail)
    assert 'private-key' not in str(error.value)


def test_configured_api_health_does_not_require_cli_or_claim_verified(monkeypatch):
    ai.save(setup_ai('antigravity'));monkeypatch.setenv('GEMINI_API_KEY','test-key')
    pm=ProviderManager();pm.check_health()
    assert pm.status_map['GOOGLE']==ProviderStatus.RECOVERING
    pm.mark_trial_candidates()
    assert 'GOOGLE' in pm.usable_domains()
    monkeypatch.delenv('GEMINI_API_KEY');pm.check_health()
    assert pm.get_failover_mode()[0]==FailoverMode.STOP


def test_configured_agents_route_all_roles_without_google_cli(monkeypatch):
    ai.save(setup_ai());from core.orchestrator import Orchestrator
    orch=Orchestrator(ai.apply({}))
    assert orch.head.domain=='OPENAI' and orch.reviewer.domain=='OPENAI' and orch.builder.provider=='openai'
    from core.research_runner import TriadResearchRunner
    monkeypatch.setattr(TriadResearchRunner,'invoke',lambda self,*a,**k:{'output':'{"result":"{\\"answer\\":1}"}','api_key_used':False})
    from agents.connected_roles import ConnectedHead
    head=ConnectedHead('ANTHROPIC');assert head._extract_json(head._invoke_cli('prompt'))=={'answer':1}


def test_room_background_overrides_and_full_reset():
    value={'owner':{'name':'대표','character':{'gender':'male','age':30,'color':'gold'}},'theme':'corporate','room_themes':{'ceo':'garden','design':'creative'}}
    company.save(value,company.current()['revision']);assert company.current()['company']['room_themes']['ceo']=='garden'
    value['theme']='creative';value['room_themes']={};company.save(value,company.current()['revision']);assert company.current()['company'].get('room_themes',{})=={}
    value['room_themes']={'unknown':'garden'}
    with pytest.raises(ValueError):company.validate(value)


def test_briefing_sequential_owner_decisions_and_planning_context(tmp_path,monkeypatch):
    project=str(tmp_path/'game');team=staffing.current()
    # Evidence belongs only to the department of the assigned worker.
    from core.mission import MissionStore
    mission={'mission_id':'MSN-EVIDENCE','project_path':project,'status':'DONE','steps':[{'order':{'assigned_staff_id':'gameplay','goal':'이동 구현','allowed_paths':['src/**']},'result':{'final_state':'PASS','tests':{'passed':True}}}]}
    monkeypatch.setattr(MissionStore,'all',lambda self:[mission])
    state=brief.submit({'action':'start','project_path':project,'expected_revision':brief.listing()['revision']},lambda p:(True,p))
    session=state['sessions'][0];assert len(session['reports'])==6
    assert next(r for r in session['reports'] if r['department']=='development')['evidence'][0]['goal']=='이동 구현'
    assert not next(r for r in session['reports'] if r['department']=='design')['evidence']
    with pytest.raises(staffing.TeamConflict):brief.submit({'action':'approve','id':session['id'],'index':0,'expected_revision':'stale'},lambda p:(True,p))
    for i in range(6):
        state=brief.submit({'action':'approve','id':session['id'],'index':i,'reply':'검증을 보완하세요','expected_revision':state['revision']},lambda p:(True,p))
    assert state['sessions'][0]['status']=='DONE'
    context=staffing.planning_context({'project_path':project},team)
    assert any(d['action']=='검증을 보완하세요' for d in context['company_decisions'])
    assert brief.decisions(str(tmp_path/'other'))==[]


def test_compact_office_removes_credentials_full_evidence_and_unchanged_metadata():
    team=staffing.current();prefs=company.current()
    d=SimpleNamespace(build_activity_payload=lambda:{'working_now':[],'focus_mission_id':'M','missions':[{'mission_id':'M','goal':'goal','steps':[{'run_id':'R','order':{'secret':'huge'}}]}]},build_status_payload=lambda:{'project_path':'/tmp/game','csrf':'secret','some_extra':'large'},load_config=lambda:{'head':{'provider':'claude'},'builder':{'provider':'antigravity'},'reviewer':{'provider':'openai'}})
    result=office_maps.snapshot(d,{'team_revision':[team['revision']],'company_revision':[prefs['revision']]})
    assert 'team' not in result and 'company' not in result and 'secret' not in json.dumps(result)
    assert result['activity']['missions'][0]['steps']==[{'run_id':'R'}]


def test_skills_are_reviewed_instructions_and_do_not_run_code():
    value={'id':'unity','name':'Unity 가이드','content':'의존성을 확인하고 승인된 테스트만 실행한다.','source':'https://github.com/test/repo','enabled':True,'department':'development'}
    state=skills.save({'skills':[value],'expected_revision':skills.current()['revision']})
    assert 'Unity 가이드' in skills.instructions('development') and not skills.instructions('quality')
    context=staffing.planning_context({'project_path':'/tmp/game'},staffing.current());assert 'Unity 가이드' in context['supplemental_skills']
    with pytest.raises(staffing.TeamConflict):skills.save({'skills':[],'expected_revision':'stale'})
    for url in ['http://127.0.0.1/a.md','https://example.org/a.md','https://raw.githubusercontent.com/a/b/main/a.py','https://github.com/a/b/blob/main/a.md?token=secret']:
        with pytest.raises(ValueError):skills.preview(url)


def test_setup_and_briefing_http_auth_boundary(env,http_server):
    headers={'X-Solomon-Bridge':'test-token','Content-Type':'application/json'}
    for route in ['/ops/ai-connections','/ops/ai-login','/ops/skill-library','/ops/skill-preview','/ops/briefings']:
        assert request(http_server,'POST',route,'{}')[0]==403
        assert request(http_server,'POST',route,'[]',headers=headers)[0]==400
    assert request(http_server,'POST','/ops/ai-connections',json.dumps(setup_ai()),headers=headers)[0]==200
    assert request(http_server,'GET','/ops/ai-connections')[0]==200
    from core.device_link import READ_API,WRITE_API,PAGES
    assert '/ops/briefings' in READ_API&WRITE_API
    assert not {'/settings','/ops/ai-connections','/ops/ai-login','/ops/skill-library'} & (READ_API|WRITE_API|PAGES)


def test_report_delivery_uses_actual_completed_records_and_requires_created_secretary(monkeypatch):
    from datetime import datetime, timezone, timedelta
    from core import company_meetings
    team=staffing.current();secretary={**copy.deepcopy(team['members'][0]),'id':'secretary','name':'비서','department':'support','position':'secretary','specialty':'general'}
    team['members'].append(secretary);team=staffing.save(team,team['revision'])
    completed_at=(datetime.now(timezone.utc)-timedelta(seconds=20)).isoformat()
    source={'id':'MTG-actual-report','team':team,'status':'DONE','kind':'department','department':'development','moderator_id':'gameplay','updated_at':completed_at}
    def save_report(): company_meetings.path().write_text(json.dumps({'meetings':[source],'agendas':[]}))
    save_report()
    dashboard=SimpleNamespace(build_activity_payload=lambda:{'missions':[],'working_now':[]},build_status_payload=lambda:{},load_config=lambda:{r:{'provider':p} for r,p in [('head','claude'),('builder','antigravity'),('reviewer','openai')]})
    result=office_maps.snapshot(dashboard,{})
    delivery=result['deliveries'][0];assert delivery['manager_id']=='gameplay' and delivery['secretary_id']=='secretary'
    assert delivery['phase']=='비서에게 보고서 제출' and result['visitors'][0]['room']=='ceo'
    source['updated_at']=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    save_report()
    assert not office_maps.snapshot(dashboard,{})['deliveries']
    assert source['status']=='DONE','Ending the motion must never delete or change the original report'
    source['updated_at']=completed_at;source['status']='FAILED'
    save_report()
    assert not office_maps.snapshot(dashboard,{})['deliveries'],'Failed discussions must not masquerade as delivered reports'


def test_same_provider_meeting_is_explicitly_labeled_and_never_auto_adopts(tmp_path):
    from core import company_meetings as meetings
    from tests.test_company import FakeRunner, config
    ai.save(setup_ai(mode='cli'));project=tmp_path/'game';project.mkdir()
    m=meetings.submit({'request_id':'same-provider-meeting','topic':'테스트 안내 검토','department':'development','kind':'department','project_path':str(project)},ai.apply(config()),lambda p:(True,p),background=False)
    assert m['reduced_independence']
    runner=FakeRunner();meetings.run(m['id'],runner)
    result=meetings.report(m['id']);assert result['status']=='DONE'
    assert {call[0] for call in runner.calls}=={'OPENAI'}
    assert all(a['status']!='ADOPTED' for a in meetings.listing()['agendas'])
