"""Isolated local office benchmark; fake history only, never invokes an AI.
Run from the repository with .venv/bin/python scripts/benchmark_office.py.
Add --large-journals for retained meeting/evidence history.
"""
import concurrent.futures, http.client, json, os, pathlib, shutil, sqlite3, statistics, subprocess, sys, tempfile, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
folder=pathlib.Path(tempfile.mkdtemp(prefix='director-opt-'))
process=subprocess.Popen([sys.executable,str(ROOT/'tests/browser/server.py'),str(folder)],cwd=ROOT,env={**os.environ,'DIRECTOR_UI_LEGACY_COMPANY':'1'},stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
try:
    port=int(process.stdout.readline().strip())
    def request(path):
        start=time.perf_counter();conn=http.client.HTTPConnection('127.0.0.1',port,timeout=30);conn.request('GET',path);r=conn.getresponse();body=r.read();conn.close()
        assert r.status==200,(r.status,body[:100])
        return ((time.perf_counter()-start)*1000,len(body),json.loads(body))
    # Realistic retained history; all writes are confined to this disposable fixture.
    source=json.loads(next((folder/'missions').glob('MSN-*.json')).read_text())
    for i in range(150):
        item={**source,'mission_id':f'MSN-PERF-{i:04}','status':'DONE','owner_pid':None,'goal':'성능 검사용 게임 미션','updated_at':'2025-01-01T00:00:00','summary':'완료된 과거 미션'}
        (folder/'missions'/f'{item["mission_id"]}.json').write_text(json.dumps(item))
    with sqlite3.connect(folder/'director.db') as conn:
        columns=[r[1] for r in conn.execute('PRAGMA table_info(ai_usage)') if r[1]!='id']
        sql=', '.join(columns)
        for _ in range(9):conn.execute(f'INSERT INTO ai_usage ({sql}) SELECT {sql} FROM ai_usage')
        rows=conn.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0]
    if '--large-journals' in sys.argv:
        team=request('/ops/team')[2]['team']
        journals=[{'id':'MTG-PERF-'+str(i),'status':'DONE','kind':'department','department':'development','team':team,'moderator_id':'gameplay','reviewer_id':'quality','participants':['gameplay'],'topic':'과거 회의','project_path':'/tmp/game','created_at':'2025-01-01T00:00:00','updated_at':'2025-01-01T00:00:00','summary':'저장된 보고','context':{'text':'history '*4096},'transcript':[{'content':'evidence '*2048}]} for i in range(200)]
        (folder/'company_meetings.json').write_text(json.dumps({'meetings':journals,'agendas':[]},ensure_ascii=False))
        sessions=[{'id':'BRF-PERF-'+str(i),'status':'DONE','team_revision':team['revision'],'reports':[{'manager_id':'planner','evidence':[{'method':'saved method '*2000}]}]} for i in range(100)]
        (folder/'executive_briefings.json').write_text(json.dumps({'sessions':sessions}))
    first=request('/ops/office')[2]
    query='/ops/office?team_revision='+first['team']['team']['revision']+'&company_revision='+first['company']['revision']
    for _ in range(3):request(query)
    samples=[request(query) for _ in range(15)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: multi=list(pool.map(request,[query]*16))
    print(json.dumps({'large_journals':'--large-journals' in sys.argv,'history_missions':163,'ledger_rows':rows,'warm_median_ms':round(statistics.median(s[0] for s in samples),2),'warm_p95_ms':round(sorted(s[0] for s in samples)[-2],2),'multi4_median_ms':round(statistics.median(s[0] for s in multi),2),'warm_bytes':samples[-1][1],'initial_bytes':len(json.dumps(first,ensure_ascii=False).encode()),'activity_fields':list(first['activity'])},ensure_ascii=False))
finally:
    process.terminate();process.wait(timeout=10);shutil.rmtree(folder)
