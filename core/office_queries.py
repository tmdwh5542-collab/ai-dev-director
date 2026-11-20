"""Read only the evidence used by the office, without building the full dashboard."""
from datetime import datetime, timedelta
from pathlib import Path
from core import usage
from core.mission import MissionStore, _pid_alive
from core.state_machine import TERMINAL_STATES


def activity():
    import dashboard_server as d
    missions = sorted(MissionStore().all(), key=lambda m: m.get('updated_at', ''), reverse=True)
    # Preserve the one-time import of historical usage; no repeated all-history totals.
    if not d._USAGE_BACKFILLED['done']:
        try:
            usage.backfill_from_runs(d.DIRECTOR_ROOT / 'runs', missions)
        except Exception:
            pass  # Match the dashboard: one unreadable old report must not break live telemetry.
        d._USAGE_BACKFILLED['done'] = True
    views = []
    for m in missions[:5]:
        views.append({
            'mission_id': m['mission_id'], 'goal': m.get('goal', '')[:400],
            'status': m.get('status'), 'updated_at': m.get('updated_at'),
            'live': m.get('status') == 'RUNNING' and _pid_alive(m.get('owner_pid')),
            'staff_team': m.get('staff_team'),
            'steps': [{'run_id': s.get('run_id'),
                       'assigned_staff_id': (s.get('order') or {}).get('assigned_staff_id'),
                       'review': (s.get('result') or {}).get('review_verdict')}
                      for s in m.get('steps', [])],
        })
    focus = next((m for m in views if m['live']), views[0] if views else None)
    return {'missions': views, 'focus_mission_id': focus['mission_id'] if focus else None,
            'working_now': usage.running_now(), 'usage': {'today': {'total': usage.today_total()}},
            'recent_calls': usage.recent_calls(5)}


def status():
    import dashboard_server as d
    cutoff = (datetime.utcnow() - timedelta(seconds=d.ACTIVE_RUN_WINDOW_SEC)).isoformat()
    terminal = sorted(TERMINAL_STATES)
    placeholders = ','.join('?' for _ in terminal)
    with d.get_db_conn() as conn:
        providers = {r['provider']: {'status': r['status']} for r in conn.execute('SELECT provider,status FROM provider_health')}
        # Same selection as the dashboard: latest fresh nonterminal run, otherwise latest run.
        run = conn.execute(
            f"SELECT run_id,current_state FROM runs WHERE substr(run_id,1,9) != 'RUN-TEST-' "
            f"AND current_state NOT IN ({placeholders}) AND updated_at >= ? ORDER BY created_at DESC LIMIT 1",
            (*terminal, cutoff)).fetchone()
        if run is None:
            run = conn.execute("SELECT run_id,current_state FROM runs WHERE substr(run_id,1,9) != 'RUN-TEST-' ORDER BY created_at DESC LIMIT 1").fetchone()
        session = conn.execute('SELECT project_path FROM chat_sessions WHERE id=?', (d.active_session_id(),)).fetchone()
        details = ''
        if run and run['current_state'] == 'HUMAN_REQUIRED':
            transition = conn.execute('SELECT details FROM state_transitions WHERE run_id=? ORDER BY id DESC LIMIT 1', (run['run_id'],)).fetchone()
            details = (transition['details'] or '')[:300] if transition else ''
    project = ((session['project_path'] if session else '') or '').strip()
    return {'project_path': project, 'project_name': Path(project).name if project else '',
            'providers': providers,
            'run': {'run_id': run['run_id'] if run else 'NONE', 'state': run['current_state'] if run else 'NONE'},
            'approval': d.approval_info(run['run_id'], run['current_state'], details) if run else {'required': False}}
