import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import staffing,usage
from schemas.order import OrderSchema
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server,request  # noqa: F401


def test_default_six_and_validation_does_not_allow_missing_independent_role():
    team=staffing.default_team()
    assert len(team['members'])==6 and {m['slot'] for m in team['members']}==set(staffing.SLOTS)
    bad=copy.deepcopy(team);bad['members']=[m for m in bad['members'] if m['slot']!='REVIEWER']
    with pytest.raises(ValueError):staffing.validate(bad)
    for key,value in [('id','CEO'),('id','__proto__'),('slot',[]),('specialty',{}),('duties','x'*401),('name','')]:
        bad=copy.deepcopy(team);bad['members'][0][key]=value
        with pytest.raises(ValueError):staffing.validate(bad)
    for size in [2,9]:
        bad=copy.deepcopy(team);bad['members']=[{**team['members'][0],'id':f'm{i}'} for i in range(size)]
        with pytest.raises(ValueError):staffing.validate(bad)


def test_save_is_revision_checked_and_preserves_snapshot_and_scope():
    original=staffing.current()
    order=OrderSchema(goal='Implement HUD inventory',allowed_paths=['ui/**'],protected_paths=['ui/locked/**'],max_files_changed=2,risk_level='HIGH',requires_human_approval=True)
    bound=staffing.bind_order(order,original)
    assert bound.assigned_staff_id=='interface'
    before,after=order.model_dump(),bound.model_dump()
    for key in ['staff_team','assigned_staff_id','assigned_reviewer_id']:before.pop(key);after.pop(key)
    assert before==after
    edited=copy.deepcopy(original);edited['members'][2]['name']='새 UI 담당';edited['members'][2]['duties']='접근성 검수와 HUD 구현'
    saved=staffing.save(edited,original['revision'])
    assert staffing.current()==saved and saved['revision']!=original['revision']
    assert staffing.member_for(bound,'BUILDER')['name']=='UI 개발자'
    with pytest.raises(staffing.TeamConflict):staffing.save(original,original['revision'])
    assert staffing.current()==saved


@pytest.mark.parametrize('goal,expected',[('Build player movement','gameplay'),('HUD 메뉴 구현','interface'),('씬 레벨 배치','level'),('회귀 테스트 추가','tester')])
def test_assignment_uses_specialty_and_never_assigns_reviewer_to_implementation(goal,expected):
    order=OrderSchema(goal=goal,allowed_paths=['src/**'],assigned_staff_id='quality')
    bound=staffing.bind_order(order,staffing.default_team())
    assert bound.assigned_staff_id==expected
    assert staffing.member_for(bound,'REVIEWER')['id']=='quality'


def test_team_endpoint_local_token_and_conflict(env,http_server):
    code,raw=request(http_server,'GET','/ops/team');value=json.loads(raw)
    assert code==200 and len(value['team']['members'])==6
    assert request(http_server,'GET','/ops/team',headers={'Origin':'https://evil.example'})[0]==403
    payload={'team':value['team'],'expected_revision':value['team']['revision']}
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    assert request(http_server,'POST','/ops/team',json.dumps(payload),headers={'Content-Type':'application/json'})[0]==403
    payload['team']['members'][0]['name']='<img src=x onerror=alert(1)>'[:24]
    code,raw=request(http_server,'POST','/ops/team',json.dumps(payload),headers=headers)
    assert code==200 and json.loads(raw)['team']['members'][0]['name']==payload['team']['members'][0]['name']
    assert request(http_server,'POST','/ops/team',json.dumps(payload),headers=headers)[0]==409
    assert request(http_server,'POST','/ops/team','[]',headers=headers)[0]==400
    assert request(http_server,'POST','/ops/team','x'*16001,headers=headers)[0]==400
    foreign={**headers,'Origin':'https://evil.example'}
    assert request(http_server,'POST','/ops/team',json.dumps(payload),headers=foreign)[0]==403


def test_work_ledger_keeps_assigned_staff_names_after_rename():
    order=staffing.bind_order(OrderSchema(goal='HUD',allowed_paths=['ui/**']),staffing.current())
    staffing.activate(order,'BUILDER');usage.set_context(role='BUILDER',stage='BUILDING',mission_id='MSN-STAFF')
    row=usage.call_started(['codex'],'implementation prompt')
    running=usage.running_now()[0]
    assert running['staff_id']=='interface' and running['staff_name']=='UI 개발자'
    team=staffing.current();old_revision=team['revision'];team['members'][2]['name']='새 이름';staffing.save(team,old_revision)
    usage.call_finished(row,['codex'],'implementation prompt',SimpleNamespace(stdout='done',stderr='',exit_code=0,duration_sec=1,timed_out=False))
    assert usage.recent_calls()[0]['staff_name']=='UI 개발자'
    assert usage.mission_calls('MSN-STAFF')[0]['staff_id']=='interface'
    staffing.activate(OrderSchema(goal='legacy'),'BUILDER')
    assert usage.context()['staff_id'] is None


def test_mission_keeps_original_team_through_execution_and_replanning(tmp_path,monkeypatch):
    from core.mission import MissionRunner,MissionStore
    from tests.test_v306_head_proxy_autonomy import proxy_orch,quiet,good_build,review_green,decide_by_tests
    contexts=[];built=[]
    first=OrderSchema(goal='Add a tested helper',allowed_paths=['feature.py','tests/**'])
    def factory():
        orch=proxy_orch(max_repairs=0)
        quiet(monkeypatch,orch);review_green(monkeypatch,orch);decide_by_tests(monkeypatch,orch)
        build=good_build([])
        def record(order,worktree_path,builder_fn=None):
            built.append((copy.deepcopy(order.staff_team),order.assigned_staff_id))
            return build(order,worktree_path)
        orch.builder.run=record
        def plan(goal,history,context,cwd=None):
            contexts.append(context)
            return {'status':'CONTINUE','order':first.model_copy(update={'assigned_staff_id':'interface'}).model_dump(),'summary':'next'} if len(contexts)==1 else {'status':'DONE','summary':'done'}
        orch.head.plan_next=plan
        return orch
    store=MissionStore(tmp_path/'missions');runner=MissionRunner(factory,store)
    mission=runner.create(str(tmp_path/'game'),first.goal,first,config={'autonomy':{'max_steps':2,'auto_apply':'off'}})
    original=copy.deepcopy(mission['staff_team'])
    team=staffing.current();old=team['revision'];team['members'][0]['name']='다음 미션 기획자';staffing.save(team,old)
    result=runner.run(mission['mission_id'])
    assert result['status']=='DONE' and result['staff_team']==original
    assert [member for _,member in built]==['gameplay','interface']
    assert all(team==original for team,_ in built)
    assert contexts and all(context['staff_team']==original for context in contexts)


@pytest.mark.parametrize('provider',['claude','codex'])
def test_real_reviewer_prompt_and_call_context_receive_captured_quality_staff(tmp_path,monkeypatch,provider):
    import sys
    from agents.claude_reviewer import ClaudeReviewer
    from agents.codex_reviewer import CodexReviewer
    from core.process_runner import ProcessTreeRunner
    captured=[]
    def run(**kwargs):
        captured.append((kwargs['stdin_data'],usage.context()))
        return SimpleNamespace(stdout=json.dumps({'verdict':'pass','p0':[],'p1':[],'p2':[],'summary':'ok'}),stderr='',exit_code=0,timed_out=False,duration_sec=.1)
    monkeypatch.setattr(ProcessTreeRunner,'run',staticmethod(run))
    cls=ClaudeReviewer if provider=='claude' else CodexReviewer
    agent=cls(executable=sys.executable);monkeypatch.setattr(agent,'get_version',lambda:'stub')
    team=staffing.current();team['members'][-1]['name']='독립 QA';team['members'][-1]['duties']='재시작과 저장 손상 재현 조건을 확인하세요.'
    order=staffing.bind_order(OrderSchema(goal='HUD',allowed_paths=['ui/**']),team)
    agent.review(order,'diff',{'passed':True,'test_counts':{'passed':1,'failed':0,'total':1}},worktree_path=str(tmp_path))
    assert '독립 QA' in captured[0][0] and '재시작과 저장 손상' in captured[0][0]
    assert captured[0][1]['staff_id']=='quality' and captured[0][1]['role']=='REVIEWER'


def test_proposal_builder_receives_specialist_focus_and_does_not_expand_scope(tmp_path,monkeypatch):
    import sys
    from agents.proposal_builder import ProposalBuilder
    from core.research_runner import TriadResearchRunner
    from core.bootstrap import prepare_project
    captured=[]
    def invoke(self,domain,prompt,cwd,stage):
        captured.append((prompt,usage.context()))
        return {'output':json.dumps({'files':[{'path':'ui/hud.txt','content':'HUD'}],'summary':'done'}),
                'invocation':'stub','exit_code':0,'duration_sec':.1}
    monkeypatch.setattr(TriadResearchRunner,'invoke',invoke)
    root=Path(prepare_project(tmp_path/'game'));team=staffing.current();team['members'][2]['duties']='키보드 조작과 HUD 대비를 확인하세요.'
    order=staffing.bind_order(OrderSchema(goal='HUD',allowed_paths=['ui/**']),team)
    result=ProposalBuilder(provider='claude',executable=sys.executable).run(order,str(root))
    assert result.status=='COMPLETED' and (root/'ui/hud.txt').read_text()=='HUD'
    assert '키보드 조작과 HUD 대비' in captured[0][0] and 'Assigned staff: UI 개발자' in captured[0][0]
    assert captured[0][1]['staff_id']=='interface' and captured[0][1]['role']=='BUILDER'
    assert order.allowed_paths==['ui/**']


def test_existing_work_ledger_migrates_without_relabeling_old_calls():
    import sqlite3
    from core.db_path import get_db_path
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute('''CREATE TABLE ai_usage(id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, ended_at TEXT,status TEXT NOT NULL,
        provider TEXT NOT NULL,role TEXT,stage TEXT,run_id TEXT,mission_id TEXT,pid INTEGER,duration_sec REAL,prompt_chars INTEGER,output_chars INTEGER,
        tokens_in INTEGER,tokens_out INTEGER,tokens_total INTEGER,tokens_exact INTEGER DEFAULT 0,exit_code INTEGER,source TEXT DEFAULT 'live')''')
        conn.execute("INSERT INTO ai_usage(started_at,status,provider,role,mission_id) VALUES('2026-01-01','OK','OPENAI','BUILDER','MSN-LEGACY')")
    assert usage.mission_calls('MSN-LEGACY')[0]['staff_id'] is None
    order=staffing.bind_order(OrderSchema(goal='HUD'),staffing.default_team());staffing.activate(order,'BUILDER')
    row=usage.call_started(['codex'],'work')
    assert row==2 and usage.running_now()[0]['staff_id']=='interface'
    assert usage.running_now()[0]['role']=='BUILDER'
