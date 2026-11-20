"""Compact office reads must retain evidence, invalidation, and approval behavior."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import pytest
import dashboard_server as d
from core import usage, company_meetings as meetings, executive_briefing as brief, office_queries
from core.read_projection import ProjectionCache
from core.state_machine import StateMachine
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


def test_sql_today_total_matches_ledger_with_old_failed_unknown_and_running_rows():
    now=datetime.utcnow()
    kst=(now+timedelta(hours=9)).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(hours=9)
    with usage._conn() as conn:
        rows=[(now.isoformat(),'OK',1.25,120,1),(now.isoformat(),'ERROR',2.35,None,0),
              (now.isoformat(),'INTERRUPTED',.34,90,0),(now.isoformat(),'RUNNING',None,None,0),
              ((kst-timedelta(microseconds=1)).isoformat(),'OK',88,999,1),
              (kst.isoformat(),'OK',3,5,1)]
        conn.executemany('INSERT INTO ai_usage(started_at,status,duration_sec,tokens_total,tokens_exact,provider) VALUES(?,?,?,?,?,\'OPENAI\')',rows)
    assert usage.today_total()==usage.summary()['today']['total']


def test_compact_status_preserves_fresh_stale_test_run_and_approval_selection(env,monkeypatch):
    sm=StateMachine()
    now=datetime.utcnow()
    with d.get_db_conn() as conn:
        for ident,state,created,updated in [('RUN-OLD','BUILDING',now-timedelta(minutes=50),now-timedelta(minutes=50)),
                ('RUN-NEW','PASS',now-timedelta(minutes=2),now-timedelta(minutes=2)),
                ('RUN-LIVE','VERIFYING',now-timedelta(minutes=3),now),('RUN-TEST-FAKE','BUILDING',now,now)]:
            conn.execute('INSERT INTO runs(run_id,project_path,goal,current_state,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (ident,'/tmp/game','goal',state,created.isoformat(),updated.isoformat()))
    compact=office_queries.status();full=d.build_status_payload()
    assert compact['run']['run_id']==full['run']['run_id']=='RUN-LIVE'
    assert compact['run']['state']==full['run']['state']=='VERIFYING'
    assert compact['approval']==full['approval']
    with d.get_db_conn() as conn:conn.execute("UPDATE runs SET current_state='HUMAN_REQUIRED' WHERE run_id='RUN-LIVE'")
    compact=office_queries.status();full=d.build_status_payload()
    assert compact['run']['run_id']==full['run']['run_id']=='RUN-NEW'
    assert compact['project_path']==full['project_path']
    # The compact path must not build results/research/full-provider recovery views.
    monkeypatch.setattr(d,'build_research_status_payload',lambda:pytest.fail('research scan in office poll'))
    monkeypatch.setattr(d,'_result_manager',lambda:pytest.fail('result scan in office poll'))
    assert office_queries.status()['run']['run_id']=='RUN-NEW'


def test_compact_activity_avoids_per_step_run_queries_and_all_history_totals(env,monkeypatch):
    from core.mission import MissionStore
    team={'revision':'captured','members':[]}
    mission={'mission_id':'MSN-PERF','status':'RUNNING','owner_pid':os.getpid(),'updated_at':'2026-01-01',
             'staff_team':team,'steps':[{'run_id':'R','order':{'assigned_staff_id':'dev'},'result':{'review_verdict':'pass'}}]}
    monkeypatch.setattr(MissionStore,'all',lambda self:[mission])
    monkeypatch.setattr(StateMachine,'get_run',lambda *a:pytest.fail('per-step DB lookup'))
    monkeypatch.setattr(usage,'summary',lambda *a:pytest.fail('all-history aggregation'))
    monkeypatch.setitem(d._USAGE_BACKFILLED,'done',True)
    payload=office_queries.activity()
    assert payload['missions'][0]['live'] and payload['missions'][0]['staff_team']==team
    assert payload['missions'][0]['steps'][0]=={'run_id':'R','assigned_staff_id':'dev','review':'pass'}
    assert set(payload['usage'])=={'today'} and 'events' not in payload and len(payload['recent_calls'])<=5


def test_projection_cache_reuses_small_views_but_invalidates_replace_write_delete_and_bounds_memory(tmp_path):
    cache=ProjectionCache(limit=2);p=tmp_path/'state.json';p.write_text('{"n":1}');calls=[]
    def build():calls.append(1);return json.loads(p.read_text()),False
    first=cache.get(p,build);first['n']=900
    assert cache.get(p,build)=={'n':1} and len(calls)==1
    replacement=p.with_suffix('.tmp');replacement.write_text('{"n":2}');replacement.replace(p)
    assert cache.get(p,build)=={'n':2} and len(calls)==2
    p.write_text('{"n":3}')
    assert cache.get(p,build)=={'n':3}
    p.unlink()
    assert cache.get(p,lambda:({'missing':True},False))=={'missing':True}
    for i in range(4):cache.get(tmp_path/str(i),lambda:({'ok':True},False))
    assert len(cache.entries)==2


def test_cached_live_meeting_detects_owner_death_without_file_changes(monkeypatch):
    from core import staffing
    from core import mission
    state={'meetings':[{'id':'MTG-PERF','status':'RUNNING','owner_pid':123,'team':staffing.current(),
                       'transcript':[],'context':{},'topic':'topic'}],'agendas':[]}
    meetings.path().write_text(json.dumps(state));alive=[True]
    monkeypatch.setattr(mission,'_pid_alive',lambda pid:alive[0])
    initial=meetings.compact_listing();assert initial['meetings'][0]['status']=='RUNNING'
    assert meetings.compact_listing(initial['revision'])['unchanged']
    alive[0]=False
    after=meetings.compact_listing(initial['revision'])
    assert after['meetings'][0]['status']=='INTERRUPTED' and after['revision']!=initial['revision']
    assert meetings.report('MTG-PERF')['status']=='INTERRUPTED'


def test_compact_journals_do_not_send_old_evidence_but_detail_and_full_reads_keep_it():
    state={'sessions':[{'id':'BRF-OLD','status':'DONE','reports':[{'evidence':'keep original evidence'}]},
                       {'id':'BRF-ACTIVE','status':'ACTIVE','reports':[{'evidence':'current evidence'}]}]}
    brief.path().write_text(json.dumps(state))
    compact=brief.compact_listing();assert compact['session_count']==2
    assert len(compact['sessions'])==1 and compact['sessions'][0]['id']=='BRF-ACTIVE'
    assert 'keep original evidence' not in json.dumps(compact)
    assert brief.listing()['sessions'][0]['reports'][0]['evidence']=='keep original evidence'
    assert brief.compact_listing(compact['revision'])['unchanged']
    state['sessions'][1]['status']='DONE';brief.path().write_text(json.dumps(state))
    after=brief.compact_listing(compact['revision']);assert not after['sessions'] and after['session_count']==2


def test_compact_poll_routes_preserve_auth_and_legacy_reads(env,http_server):
    for endpoint in ['/ops/meetings','/ops/briefings']:
        code,raw=request(http_server,'GET',endpoint+'?compact=1');assert code==200
        initial=json.loads(raw)
        code,raw=request(http_server,'GET',endpoint+'?compact=1&revision='+initial['revision'])
        assert code==200 and json.loads(raw)=={'unchanged':True,'revision':initial['revision']}
        assert request(http_server,'GET',endpoint,headers={'Origin':'https://evil.example'})[0]==403
        assert 'unchanged' not in json.loads(request(http_server,'GET',endpoint)[1])
