import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from core import web_workspace as web,employee_tools as tools,staffing

@pytest.fixture
def repo(tmp_path):
    p=tmp_path/'website';p.mkdir();subprocess.run(['git','init',str(p)],capture_output=True,check=True)
    (p/'index.html').write_text('<h1>Before</h1>');(p/'.env').write_text('SECRET=test')
    (p/'package.json').write_text(json.dumps({'scripts':{'dev':'node server.cjs'}}))
    return p

def test_checkpoint_compare_and_restore_conflicts_and_undo(repo):
    cp=web.snapshot(repo);(repo/'index.html').write_text('<h1>After</h1>');(repo/'new.ts').write_text('export const x=1;')
    difference=web.comparison(repo,cp['id']);assert len(difference['files'])==2
    (repo/'index.html').write_text('New concurrent content')
    with pytest.raises(staffing.TeamConflict):web.restore(repo,cp['id'],difference['revision'])
    difference=web.comparison(repo,cp['id']);result=web.restore(repo,cp['id'],difference['revision'])
    assert (repo/'index.html').read_text()=='<h1>Before</h1>' and not (repo/'new.ts').exists()
    assert (repo/'.env').read_text()=='SECRET=test'
    undo=web.comparison(repo,result['undo_checkpoint']);web.restore(repo,result['undo_checkpoint'],undo['revision'])
    assert (repo/'index.html').read_text()=='New concurrent content' and (repo/'new.ts').exists()

def test_editor_safe_paths_and_cas(repo,tmp_path):
    before=web.read(repo,'index.html');result=web.save_file(repo,{'path':'index.html','expected_sha256':before['sha256'],'content':'new'})
    assert result['checkpoint']
    with pytest.raises(staffing.TeamConflict):web.save_file(repo,{'path':'index.html','expected_sha256':before['sha256'],'content':'overwrite'})
    for path in ['../outside.ts','.env','node_modules/a.js','secrets.json','/etc/passwd']:
        with pytest.raises(ValueError):web.source(repo,path)
    target=tmp_path/'external.ts';target.write_text('private');(repo/'linked.ts').symlink_to(target)
    with pytest.raises(ValueError):web.read(repo,'linked.ts')
    assert '.env' not in web.names(repo)

def test_employee_scopes_and_mcp_fixed_project(repo):
    staffing.save(staffing.default_team(),staffing.current()['revision']);state=tools.current()
    tools.save({'expected_revision':state['revision'],'employees':{'planner':['project_files']},'research_staff_id':'planner'})
    assert 'index.html' in tools.invoke('planner','project_files',{'project_path':str(repo)})['files']
    with pytest.raises(ValueError):tools.invoke('planner','project_read',{'project_path':str(repo),'path':'index.html'})
    from scripts.director_mcp import dispatch
    listing=dispatch({'method':'tools/list'},str(repo),'planner');assert [x['name'] for x in listing['tools']]==['project_files']
    result=dispatch({'method':'tools/call','params':{'name':'project_files','arguments':{'project_path':'/other'}}},str(repo),'planner')
    assert result['isError']
    assert dispatch({'method':'initialize'},str(repo),'planner')['capabilities']['tools']

def test_unowned_servers_and_foreign_audits_are_rejected(repo):
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with pytest.raises(ValueError,match='포트'):web.start_server(repo,{'script':'dev','port':port})
    for url in ['http://127.0.0.1:8081','http://192.168.0.1','https://example.com','file:///etc/passwd']:
        with pytest.raises(ValueError):web.audit(repo,{'url':url})
    with pytest.raises(ValueError):web.start_server(repo,{'script':'dev; echo unsafe','port':3000})
    assert not web.stop_server(repo)['running']

def test_owned_server_real_start_stop(repo):
    import socket
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    (repo/'server.cjs').write_text("require('http').createServer((req,res)=>res.end('fixture')).listen(Number(process.env.PORT),'127.0.0.1');console.log('fixture ready');")
    try:
        web.start_server(repo,{'script':'dev','port':port})
        for _ in range(60):
            status=web.server_status(repo)
            if status['ready']:break
            time.sleep(.1)
        assert status['ready'] and status['owned']
        assert any('fixture ready' in line for line in status['log'])
        assert not web.stop_server(repo)['running']
    finally:web.stop_server(repo)

def test_mcp_stdio_round_trip_for_scoped_employee(repo):
    import os
    staffing.save(staffing.default_team(),staffing.current()['revision'])
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'project_files','arguments':{}}}]
    result=subprocess.run([sys.executable,str(web.ROOT/'scripts/director_mcp.py'),'--project',str(repo),'--staff','planner'],input='\n'.join(json.dumps(x) for x in requests)+'\n',text=True,capture_output=True,timeout=15,env=os.environ.copy())
    assert result.returncode==0,result.stderr
    responses=[json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses)==3 and responses[0]['result']['serverInfo']['name']=='ai-dev-director-readonly'
    assert not responses[2]['result']['isError']
    assert 'index.html' in json.loads(responses[2]['result']['content'][0]['text'])['files']

def test_edit_rechecks_file_after_automatic_backup(repo,monkeypatch):
    before=web.read(repo,'index.html');snapshot=web.snapshot
    def concurrent_snapshot(p,label):
        result=snapshot(p,label);(p/'index.html').write_text('External editor update');return result
    monkeypatch.setattr(web,'snapshot',concurrent_snapshot)
    with pytest.raises(staffing.TeamConflict):web.save_file(repo,{'path':'index.html','expected_sha256':before['sha256'],'content':'stale overwrite'})
    assert (repo/'index.html').read_text()=='External editor update'
