import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from core import setup_assistant as setup,staffing,employee_tools,web_workspace as web
from tests.test_v301_companion_http import http_server,request

@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(setup,'CACHE',None);monkeypatch.setattr(setup,'PROCESS',None)


def test_node_version_requires_successful_parse(monkeypatch):
    monkeypatch.setattr(setup.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=b'v22.19.0\n'))
    assert setup.version('node')['parts']==(22,19,0)
    monkeypatch.setattr(setup.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,stdout=b'v99.0.0'))
    assert not setup.version('node')['installed']


def test_missing_node_blocks_install_without_starting_process(monkeypatch):
    monkeypatch.setattr('core.ai_connections.assert_idle',lambda:None)
    monkeypatch.setattr(setup,'runtime_checks',lambda:{'node_compatible':False,'npm_installed':True})
    with pytest.raises(ValueError,match='Node.js'):setup.install()
    assert setup.PROCESS is None


def test_real_stdio_bridge_and_client_specific_registration(tmp_path):
    project=tmp_path/'한글 프로젝트';project.mkdir();subprocess.run(['git','init',str(project)],capture_output=True,check=True)
    staffing.save(staffing.default_team(),staffing.current()['revision'])
    data={'project_path':str(project),'staff_id':'planner'}
    result=setup.check_mcp(data)
    assert result['status']=='BRIDGE_CHECKED' and not result['client_registered'] and not result['ai_login_verified']
    value=setup.registration(data)
    import tomllib
    assert tomllib.loads(value['codex_toml'])['mcp_servers']['director']['args'][-1]=='planner'
    assert json.loads(value['claude_json'])['mcpServers']['director']['args'][-3]==str(project)
    assert json.loads(value['gemini_json'])['mcpServers']['director']['command']
    monkey=dict(employee_tools.current()['employees']);monkey['planner']=[]
    employee_tools.save({'expected_revision':employee_tools.current()['revision'],'employees':monkey,'research_staff_id':''})
    setup.CACHE={'node':{},'node_compatible':False,'npm_installed':False,'ready':False};setup.CACHED_AT=setup.time.monotonic()
    assert setup.public()['mcp_check'] is None


def test_status_never_claims_api_authentication_or_reads_keys(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-private-value')
    assert 'OPENAI_API_KEY' not in setup.env()
    monkeypatch.setattr(setup,'runtime_checks',lambda:{'node':{'version':'24.0.0'},'node_compatible':True,'npm_installed':True,'ready':True})
    result=setup.public()
    assert result['hermes']['authentication_verified'] is False
    assert 'test-private-value' not in json.dumps(result)
    setup.update('installation',{'status':'RUNNING','log':[]})
    assert setup.public()['installation']['status']=='INTERRUPTED'


def test_setup_is_pc_only_and_mutations_require_bridge(http_server):
    from core.device_link import PAGES,READ_API,WRITE_API
    assert '/setup' not in PAGES and '/ops/setup' not in READ_API|WRITE_API
    assert request(http_server,'GET','/setup')[0]==200
    assert request(http_server,'POST','/ops/setup','{}',{'Content-Type':'application/json'})[0]==403
    assert request(http_server,'POST','/ops/setup','{}',{'Content-Type':'application/json','X-Solomon-Bridge':'test-token','Origin':'https://foreign.example'})[0]==403

def test_installer_fixed_command_sanitized_environment_and_verified_finish(monkeypatch):
    import io,time
    calls=[]
    class Process:
        def __init__(self):self.stdout=io.StringIO('download https://user:password@example.test/?token=secret\n');self.finished=False
        def poll(self):return 0 if self.finished else None
        def wait(self):self.finished=True;return 0
    def start(argv,**kw):calls.append((argv,kw));return Process()
    monkeypatch.setenv('OPENAI_API_KEY','do-not-forward')
    monkeypatch.setattr('core.ai_connections.assert_idle',lambda:None)
    monkeypatch.setattr(setup,'runtime_checks',lambda:{'node_compatible':True,'npm_installed':True,'ready':True})
    monkeypatch.setattr(setup.subprocess,'Popen',start)
    setup.install()
    for _ in range(50):
        if setup.saved()['installation']['status']!='RUNNING':break
        time.sleep(.02)
    value=setup.saved()['installation']
    assert value['status']=='DONE'
    assert calls[0][0]==[setup.sys.executable,str(setup.ROOT/'scripts/setup_web_tools.py')]
    assert 'OPENAI_API_KEY' not in calls[0][1]['env']
    assert 'password@' not in '\n'.join(value['log']) and 'token=secret' not in '\n'.join(value['log'])


def test_intro_acknowledgement_does_not_change_readiness(monkeypatch):
    from core import hermes_agent
    from desktop_launcher import SETUP_FLOW_VERSION
    before=hermes_agent.settings()
    web.atomic(staffing.settings_path().parent/'desktop_setup.json',{'version':SETUP_FLOW_VERSION,'pending':True})
    result=setup.finish_intro()
    assert result['acknowledged'] and result['href']=='/office'
    assert not json.loads((staffing.settings_path().parent/'desktop_setup.json').read_text())['pending']
    assert hermes_agent.settings()==before
