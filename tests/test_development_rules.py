import json,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from core import development_rules as rules,staffing
from schemas.order import OrderSchema
from core.project_context import collect_project_context
from core.verifier import Verifier

@pytest.fixture
def project(tmp_path):
    root=tmp_path/'game';root.mkdir();subprocess.run(['git','init',str(root)],capture_output=True,check=True)
    (root/'project.godot').write_text('[application]\nconfig/name="fixture"')
    (root/'player.gd').write_text('extends Node\n')
    (root/'AGENTS.md').write_text('Preserve existing rules.',encoding='utf-8')
    return root

def save(project,**settings):
    return rules.save({'project_path':str(project),'expected_revision':rules.public(project)['revision'],'settings':{**rules.DEFAULT,**settings}},lambda p:(True,p))

def test_balanced_rules_inspection_and_existing_documents_are_preserved(project,monkeypatch):
    monkeypatch.setattr('core.ai_connections.assert_idle',lambda:None)
    original=(project/'AGENTS.md').read_bytes();save(project,level='quick')
    context=rules.enrich(collect_project_context(project))
    assert 'PROJECT DEVELOPMENT RULES' in context['development_rules']
    assert context['project_inspection']['source_samples'][0]['path']=='player.gd'
    assert any(d['path']=='AGENTS.md' for d in context['project_inspection']['documents'])
    assert (project/'AGENTS.md').read_bytes()==original and not (project/'CLAUDE.md').exists()
    small=OrderSchema(goal='버튼 글자색 변경',allowed_paths=['player.gd'])
    important=OrderSchema(goal='플레이어 이동 기능 구현',allowed_paths=['player.gd'])
    assert not rules.critical(small,project,{**rules.DEFAULT,'level':'strict'})
    assert rules.critical(important,project,{**rules.DEFAULT,'level':'quick'})

def test_tests_alone_cannot_satisfy_important_runtime_requirement(project):
    order=OrderSchema(goal='충돌 처리 구현',allowed_paths=['player.gd'])
    assessment=rules.assess(project,order,project,{'passed':True},SimpleNamespace(verdict='pass'),lambda *a,**k:pytest.fail('must not execute an unspecified command'))
    assert not assessment['passed'] and assessment['block_code']=='RUNTIME_NOT_CONFIGURED'
    assert assessment['tests_passed'] and not assessment['runtime']['executed']

def test_real_runtime_command_and_failure_are_distinct(project):
    order=OrderSchema(goal='플레이어 이동 기능 구현',allowed_paths=['player.gd'])
    cfg={**rules.DEFAULT,'runtime_command':[sys.executable,'-c','print("movement fixture ran")'],'runtime_scope':'local command fixture only'}
    assessment=rules.assess(project,order,project,{'passed':True},None,Verifier._execute_cmd,settings=cfg)
    assert assessment['passed'] and assessment['runtime']['executed'] and assessment['runtime']['exit_code']==0
    assert assessment['runtime']['worktree_stamp']==rules.tree_stamp(project)
    (project/'player.gd').write_text('extends Node\n# modified after run')
    assert assessment['runtime']['worktree_stamp']!=rules.tree_stamp(project)
    cfg['runtime_command']=[sys.executable,'-c','raise SystemExit(4)']
    bad=rules.assess(project,order,project,{'passed':True},None,Verifier._execute_cmd,settings=cfg)
    assert not bad['passed'] and bad['block_code']=='RUNTIME_CHECK_FAILED'

def test_recorded_failures_are_project_scoped_observations_not_instructions(project,tmp_path):
    rules.record(project,'RUN-1','충돌 수정','FAIL',{'block_code':'RUNTIME_CHECK_FAILED'},[])
    rules.record(project,'RUN-1','충돌 수정','FAIL',{'block_code':'RUNTIME_CHECK_FAILED'},[])
    rules.record(project,'RUN-2','충돌 수정','FAIL',{'block_code':'RUNTIME_CHECK_FAILED'},[])
    entry=rules.public(project)['failures'][0]
    assert entry['count']==2 and entry['type']=='observed_failure_not_verified_root_cause'
    assert 'RUNTIME_CHECK_FAILED' in rules.instruction(project)
    assert not rules.public(tmp_path/'other')['failures']

def test_project_rule_configuration_has_revision_and_scope_validation(project,monkeypatch):
    monkeypatch.setattr('core.ai_connections.assert_idle',lambda:None)
    old=rules.public(project);save(project,level='strict')
    with pytest.raises(staffing.TeamConflict):rules.save({'project_path':str(project),'expected_revision':old['revision'],'settings':rules.DEFAULT},lambda p:(True,p))
    with pytest.raises(ValueError):save(project,runtime_command=['python','test.py'],runtime_scope='')

def test_small_wording_changes_do_not_create_runtime_or_approval_requirements(project):
    cfg={**rules.DEFAULT,'level':'strict'}
    assert not rules.critical(OrderSchema(goal='충돌 처리 설명 문서 오타 수정',allowed_paths=['README.md']),project,cfg)
    assert not rules.critical(OrderSchema(goal='저장 버튼 글자색만 수정',allowed_paths=['player.gd']),project,cfg)


def test_orchestrator_refuses_head_pass_without_runtime_evidence():
    from tests.test_v0236_evidence_isolation import _orch_pass_head,_deciding_run
    from tests.test_v0231_chat_stabilization import make_git_project
    with make_git_project() as project:
        orch=_orch_pass_head();order=OrderSchema(goal='플레이어 충돌 처리 구현',allowed_paths=['src/'])
        run_id,wt,sm=_deciding_run(project,orch,order)
        result=orch.resume(run_id)
        assert result['final_state']=='FAIL'
        assert result['development_rules']['block_code']=='RUNTIME_NOT_CONFIGURED'
        assert rules.public(project)['failures']
        assert orch._load_json(run_id,'final_evidence.json')['head_decision']=='FAIL'


def test_runtime_evidence_is_rejected_when_source_changed_after_check():
    from tests.test_v0236_evidence_isolation import _orch_pass_head,_deciding_run
    from tests.test_v0231_chat_stabilization import make_git_project
    with make_git_project() as project:
        orch=_orch_pass_head();order=OrderSchema(goal='플레이어 충돌 처리 구현',allowed_paths=['src/'])
        run_id,wt,sm=_deciding_run(project,orch,order)
        cfg={**rules.DEFAULT,'runtime_command':[sys.executable,'-c','print("fixture")'],'runtime_scope':'fixture execution'}
        assessment=rules.assess(project,order,wt,{'passed':True},None,Verifier._execute_cmd,settings=cfg)
        assert assessment['passed']
        orch._save_json(run_id,'development_rules.json',assessment)
        (Path(wt)/'src'/'runtime_changed.py').write_text('# changed after runtime')
        result=orch.resume(run_id)
        assert result['final_state']=='FAIL' and result['development_rules']['block_code']=='RUNTIME_EVIDENCE_STALE'

def test_cosmetic_followup_cannot_hide_failed_important_runtime_check(project):
    mission={'project_path':str(project),'goal':'플레이어 충돌 처리 구현','steps':[{'result':{'final_state':'FAIL','development_rules':{'runtime_required':True,'passed':False}}},{'result':{'final_state':'PASS','development_rules':{'runtime_required':False,'passed':True}}}]}
    assert not rules.mission_completion(mission)['passed']
    mission['steps'].append({'result':{'final_state':'PASS','development_rules':{'runtime_required':True,'passed':True}}})
    assert rules.mission_completion(mission)['passed']
    mission['steps']=[]
    assert not rules.mission_completion(mission)['passed']
    mission['goal']='저장 버튼 글자색만 수정'
    assert rules.mission_completion(mission)['passed']

def test_only_director_owned_engine_adapters_can_supply_existing_runtime_evidence():
    from core import development_rules as rules
    adapter=str(Path(rules.__file__).resolve().parents[1]/'scripts/run_engine_tests.py')
    verified={'test':{'executed':True,'passed':True,'exit_code':0,'command':'engine adapter','output':'4 passed'},'test_counts':{'total':4}}
    assert rules.engine_runtime_evidence(['python',adapter,'--engine','godot'],verified)['source']=='director_engine_adapter'
    assert rules.engine_runtime_evidence(['python',adapter,'--engine','unity','--unity-platform','EditMode'],verified) is None
    assert rules.engine_runtime_evidence(['python',adapter,'--engine','unity','--unity-platform','PlayMode'],verified)
    assert rules.engine_runtime_evidence(['python','/untrusted/run_engine_tests.py','--engine','godot'],verified) is None
    assert rules.engine_runtime_evidence(['python','-m','pytest'],verified) is None
