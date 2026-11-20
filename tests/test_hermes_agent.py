import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from core import hermes_agent as h, staffing, usage
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


def configured(monkeypatch):
    monkeypatch.setenv('DIRECTOR_TEST_HERMES_KEY','unit-test-secret')
    cfg={**h.DEFAULT,'enabled':True,'python_path':sys.executable,'model':'test-model','key_env':'DIRECTOR_TEST_HERMES_KEY'}
    h.save(cfg);return cfg


def submitted(tmp_path,monkeypatch,**kwargs):
    configured(monkeypatch);project=tmp_path/'game';project.mkdir(exist_ok=True)
    return h.submit({'request_id':'hermes-unit-request-123','project_path':str(project),'staff_id':staffing.current()['members'][0]['id'],
                     'question':'현재 자료를 분석하고 개선안을 보고해줘','material':'기존 테스트 결과는 통과입니다.',**kwargs},lambda p:(True,p),background=False)


def result(text=None,ok=True,exit_code=0,timed_out=False):
    report={'summary':'기록을 분석했습니다.','recommendations':['현재 목표 범위 안에서 조작 안내를 보완하세요.'],'questions':['지원할 입력 장치를 확인해주세요.']}
    body={'protocol':'director-hermes-sdk-v1','ok':ok,'version':'test-sdk','text':text or json.dumps(report,ensure_ascii=False),'usage':{'api_calls':1,'total_tokens':120},'error':None if ok else '완성된 보고서가 아닙니다.'}
    return SimpleNamespace(stdout=json.dumps(body),stderr='should never be published unit-test-secret',duration_sec=.2,exit_code=exit_code,timed_out=timed_out,pid=12345)


def test_hermes_is_optional_and_settings_never_store_a_secret(monkeypatch):
    assert not h.public()['settings']['enabled']
    cfg=configured(monkeypatch);assert h.public()['key_present']
    assert 'unit-test-secret' not in h.settings_path().read_text()
    for value in [{**cfg,'timeout':True},{**cfg,'daily_limit':31},{**cfg,'python_path':'relative'}, {**cfg,'enabled':True,'model':''}, {**cfg,'provider':'auto'}]:
        with pytest.raises(ValueError):h.save(value)


def test_real_job_contract_ledger_and_owner_adoption(tmp_path,monkeypatch):
    job=submitted(tmp_path,monkeypatch,question='文字 그대로 $(echo unsafe) / !명령이 아닌 자료 분석')
    before=usage.context();calls=[]
    def runner(argv,**kw):
        calls.append(argv);payload=json.loads(Path(argv[argv.index('--request')+1]).read_text())
        assert payload['provider']=='openai-api' and payload['model']=='test-model'
        assert payload['prompt']==job['prompt'] and not kw.get('stdin_data')
        assert job['question'] not in ' '.join(argv) and kw['cwd']!=job['project_path']
        assert kw['env']['DIRECTOR_HERMES_API_KEY']=='unit-test-secret' and 'DIRECTOR_TEST_HERMES_KEY' not in kw['env']
        assert kw['env']['HERMES_SAFE_MODE']=='1' and kw['env']['HERMES_HOME']!=str(Path.home()/'.hermes')
        return result()
    h.run(job['id'],runner);saved=h.detail(job['id']);assert saved['status']=='READY' and len(calls)==1
    assert usage.context().get('runtime')==before.get('runtime')
    call=usage.recent_calls()[0];assert call['runtime']=='hermes-sdk' and call['provider']=='OPENAI' and call['staff_name']==job['staff_name']
    assert h.project_decisions(job['project_path'])==[]
    state=h.listing();h.decide({'id':job['id'],'action':'approve','expected_revision':state['revision']})
    context=staffing.planning_context({'project_path':job['project_path']},staffing.current())
    assert any(d['id']==job['id'] for d in context['company_decisions'])
    assert h.project_decisions(str(tmp_path/'other'))==[]
    assert 'unit-test-secret' not in json.dumps(h.listing()) and 'unit-test-secret' not in h.jobs_path().read_text()
    assert 'prompt' not in saved and 'config' not in saved


def test_replay_conflict_daily_budget_and_active_job_prevent_duplicate_calls(tmp_path,monkeypatch):
    job=submitted(tmp_path,monkeypatch);cfg=h.settings();cfg['daily_limit']=1;h._write(h.settings_path(),cfg)
    payload={'request_id':job['request_id'],'project_path':job['project_path'],'staff_id':job['staff_id'],'question':job['question'],'material':'기존 테스트 결과는 통과입니다.'}
    assert h.submit(payload,lambda p:(True,p),background=False)['id']==job['id']
    with pytest.raises(staffing.TeamConflict):h.submit({**payload,'question':'다른 질문'},lambda p:(True,p),background=False)
    with pytest.raises(staffing.TeamConflict):h.submit({**payload,'request_id':'another-request-id'},lambda p:(True,p),background=False)
    h.run(job['id'],lambda *a,**k:result())
    with pytest.raises(ValueError,match='오늘 요청 한도'):h.submit({**payload,'request_id':'another-request-id'},lambda p:(True,p),background=False)
    with pytest.raises(staffing.TeamConflict):h.decide({'id':job['id'],'action':'approve','expected_revision':'stale'})


@pytest.mark.parametrize('reply', [result(ok=False,exit_code=2),result(timed_out=True,exit_code=-1),result(text='not a JSON report'),result(text='{"summary":"looks good","recommendations":"bad","questions":[]}')])
def test_failed_partial_or_malformed_result_is_not_adopted(tmp_path,monkeypatch,reply):
    job=submitted(tmp_path,monkeypatch);h.run(job['id'],lambda *a,**k:reply)
    assert h.detail(job['id'])['status']=='FAILED' and h.project_decisions(job['project_path'])==[]
    assert 'unit-test-secret' not in json.dumps(h.listing())


def test_stop_wins_a_racing_success_and_queued_work_never_runs(tmp_path,monkeypatch):
    job=submitted(tmp_path,monkeypatch)
    def runner(*a,**k):h.stop(job['id']);return result()
    h.run(job['id'],runner);assert h.detail(job['id'])['status']=='STOPPED'
    second=h.submit({'request_id':'second-hermes-request','project_path':job['project_path'],'staff_id':job['staff_id'],'question':'새 업무'},lambda p:(True,p),background=False)
    h.stop(second['id']);h.run(second['id'],lambda *a,**k:pytest.fail('stopped work executed'))
    assert h.detail(second['id'])['status']=='STOPPED'


def test_missing_runtime_and_key_are_explicit_not_fake_healthy(tmp_path,monkeypatch):
    configured(monkeypatch);monkeypatch.delenv('DIRECTOR_TEST_HERMES_KEY')
    with pytest.raises(ValueError,match='API 키'):h.submit({'request_id':'missing-key-request','project_path':str(tmp_path),'staff_id':'planner','question':'분석'},lambda p:(True,p),background=False)
    assert not h.public()['key_present'] and not h.public()['probe']
    monkeypatch.setattr(h.ProcessTreeRunner,'run',lambda *a,**k:result(ok=False,exit_code=2))
    assert h.probe()['probe']['ok'] is False


def test_integration_and_configuration_http_boundaries(env,http_server,monkeypatch):
    headers={'X-Solomon-Bridge':'test-token','Content-Type':'application/json'}
    for route in ['/ops/hermes/settings','/ops/hermes/probe','/ops/hermes/tasks','/ops/hermes/stop','/ops/hermes/decide']:
        assert request(http_server,'POST',route,'{}')[0]==403
        assert request(http_server,'POST',route,'[]',headers=headers)[0]==400
    assert request(http_server,'GET','/ops/hermes/settings')[0]==200
    assert request(http_server,'GET','/hermes.js')[0]==200
    from core.device_link import READ_API,WRITE_API,ASSETS
    assert '/ops/hermes/tasks' in READ_API&WRITE_API and '/hermes.js' in ASSETS
    assert '/ops/hermes/settings' not in READ_API|WRITE_API and '/ops/hermes/probe' not in READ_API|WRITE_API


def test_live_call_guard_and_owner_death_are_fail_closed(tmp_path,monkeypatch):
    job=submitted(tmp_path,monkeypatch);h.run(job['id'])
    assert h.detail(job['id'])['status']=='FAILED' and not usage.running_now()
    state=h._state();state['jobs'][0].update(status='RUNNING',owner_pid=99999999);h._write(h.jobs_path(),state)
    assert h.listing()['jobs'][0]['status']=='INTERRUPTED'


def test_sdk_worker_runs_in_a_real_separate_process_with_explicit_contract_and_no_network(tmp_path):
    root=tmp_path/'sdk';root.mkdir();(root/'tools').mkdir();(root/'tools/__init__.py').write_text('')
    (root/'tools/hosted_tool_policy.py').write_text("HOST_FEATURES={'memory','skills','tools','plugins'}")
    (root/'run_agent.py').write_text('''
import json
class AIAgent:
 def __init__(self,provider,model,api_key,base_url,enabled_toolsets,skip_context_files,skip_memory,skip_background_review,max_iterations,max_tokens,capabilities,**kwargs):
  assert enabled_toolsets==[] and skip_memory and skip_context_files and skip_background_review
  assert max_iterations==1 and all(v is False for v in capabilities.values())
  self.tools=[]
 def run_conversation(self,prompt):
  return {'completed':True,'final_response':json.dumps({'summary':'isolated SDK result','recommendations':[],'questions':[]}), 'api_calls':1}
 def close(self):pass
''')
    env={**os.environ,'DIRECTOR_TESTING':'1','DIRECTOR_HERMES_BRIDGE_STUB':'1','DIRECTOR_HERMES_API_KEY':'fake-secret','HERMES_HOME':str(tmp_path/'profile')}
    command=[sys.executable,'-I',str(h.WORKER),'--sdk-root',str(root)]
    probe=subprocess.run(command+['--probe'],env=env,capture_output=True,text=True,timeout=15)
    assert probe.returncode==0 and json.loads(probe.stdout)['ok']
    req=tmp_path/'request.json';req.write_text(json.dumps({'provider':'openai-api','model':'test','base_url':'https://api.openai.com/v1','timeout':30,'prompt':'do not execute $(anything)'}))
    answer=subprocess.run(command+['--request',str(req)],env=env,capture_output=True,text=True,timeout=15)
    assert answer.returncode==0 and json.loads(answer.stdout)['ok'] and 'fake-secret' not in answer.stdout


def test_global_stop_includes_queued_hermes_jobs(tmp_path,monkeypatch,env):
    import dashboard_server as d
    job=submitted(tmp_path,monkeypatch)
    monkeypatch.setattr(h.ProcessTreeRunner,'kill_active',lambda:[])
    response=d.stop_missions('stop all')
    assert response['status']=='stopped' and response['hermes']==1
    assert h.detail(job['id'])['status']=='STOPPED'
