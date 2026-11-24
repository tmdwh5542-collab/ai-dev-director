"""Compact room telemetry: private bridge credentials and full mission evidence never leave here."""
from datetime import datetime, timezone
from core import staffing, company, company_meetings, executive_briefing


def snapshot(dashboard, query):
    current_team=staffing.current(); team=current_team; preferences=company.current()
    activity=getattr(dashboard,'build_office_activity_payload',dashboard.build_activity_payload)()
    mission_views=activity.get('missions',[])
    focus=next((m for m in mission_views if m.get('mission_id')==activity.get('focus_mission_id')),None)
    if focus:
        activity['missions']=[{k:v for k,v in focus.items() if k in {'mission_id','goal','status','live','staff_team','steps'}}]
        activity['missions'][0]['steps']=[{'run_id':s.get('run_id')} for s in focus.get('steps',[])]
    else: activity['missions']=[]
    status=getattr(dashboard,'build_office_status_payload',dashboard.build_status_payload)()
    status={k:status.get(k) for k in ('project_name','project_path','providers','run','approval')}
    from core.role_settings import current
    meeting_state=company_meetings.telemetry()
    meetings=meeting_state['actors']
    now=datetime.now(timezone.utc).timestamp(); visitors=[]; deliveries=[]
    # Travel is a visual representation of real calls, never an extra parallel worker.
    for job in activity.get('working_now',[]):
        member=next((m for m in team['members'] if m['id']==job.get('staff_id')),None)
        if not member or job.get('staff_team_revision')!=team['revision']: continue
        target='development' if job.get('stage')=='BUILDING' else 'testing' if job.get('stage')=='REVIEWING' else None
        if target and staffing.department_for(member)!=target:
            visitors.append({'id':member['id'],'room':target,'reason':staffing.DEPARTMENTS[target]+' 협업'})
    completed=[]
    for mission in mission_views:
        captured=mission.get('staff_team') or {}
        if mission.get('status')!='DONE' or captured.get('revision')!=team['revision']: continue
        ids={s.get('assigned_staff_id') for s in mission.get('steps',[]) if s.get('assigned_staff_id')}
        departments={staffing.department_for(m) for m in captured.get('members',[]) if m['id'] in ids}
        if any(s.get('review') for s in mission.get('steps',[])): departments.add('quality')
        if mission.get('steps'): departments.add('planning')
        for department in departments:
            manager=next((m for m in captured.get('members',[]) if staffing.department_for(m)==department and staffing.position_for(m)=='manager'),None)
            if manager:
                completed.append({'id':mission['mission_id']+':'+department,'team':captured,'status':'DONE','kind':'mission_report','department':department,'moderator_id':manager['id'],'updated_at':mission.get('updated_at','')})
    for m in meetings+completed:
        if m.get('team',{}).get('revision')!=team['revision']: continue
        if m['status'] in company_meetings.ACTIVE:
            visitors.extend({'id':ident,'room':'ceo' if m['kind']=='executive' else m['department'],'reason':'회의 참석'} for ident in dict.fromkeys(m['participants']+[m['moderator_id'],m['reviewer_id']]))
        elif m['status']=='DONE' and m['kind']!='executive':
            try: elapsed=now-datetime.fromisoformat(m['updated_at'].replace('Z','+00:00')).replace(tzinfo=timezone.utc).timestamp()
            except (ValueError,KeyError): continue
            if 0<=elapsed<70:
                secretary=next((s for s in team['members'] if s.get('position')=='secretary'),None)
                phase='출발' if elapsed<12 else '비서에게 보고서 제출' if elapsed<32 else '대표에게 취합 보고' if elapsed<52 else '부서 복귀'
                deliveries.append({'id':m['id'],'manager_id':m['moderator_id'],'secretary_id':secretary['id'] if secretary else None,'phase':phase,'elapsed':elapsed,'home':m['department']})
                if 12<=elapsed<52: visitors.append({'id':m['moderator_id'],'room':'ceo','reason':phase})
    briefings=executive_briefing.telemetry()
    briefing=next((s for s in reversed(briefings['sessions']) if s['status']=='ACTIVE'),None)
    if briefing and briefing['team_revision']==team['revision']:
        visitors.extend({'id':r['manager_id'],'room':'ceo','reason':'진행 보고 중' if i==briefing['index'] else '임원회의 참석'} for i,r in enumerate(briefing['reports']))
    visitors=[{**v,'team_revision':team['revision']} for v in visitors]
    from core.hermes_agent import telemetry as hermes_telemetry, ACTIVE as HERMES_ACTIVE
    hermes=hermes_telemetry()
    config=dashboard.load_config()
    names={d:({'OPENAI':'OpenAI API','ANTHROPIC':'Claude API','GOOGLE':'Gemini API'} if c['mode']=='api' else {'OPENAI':'Codex','ANTHROPIC':'Claude','GOOGLE':'Antigravity'})[d] for d,c in config.get('ai_connections',{}).get('connections',{}).items()}
    from core.office_layout import current as layout_current
    result={'layout_revision':layout_current()['revision'],'hermes_revision':hermes['ui_revision'],'hermes_active':any(j['status'] in HERMES_ACTIVE for j in hermes['jobs']),'meeting_revision':meeting_state['revision'],'meeting_active':any(m['status'] in company_meetings.ACTIVE for m in meetings),'provider_names':names,'briefing_revision':briefings['revision'],'activity':activity,'status':status,'roles':{'roles':current(config)},'visitors':visitors,'deliveries':deliveries}
    if query.get('team_revision',[''])[0]!=current_team['revision']:
        result['team']={'team':current_team,'default_team':staffing.default_team(),'specialties':staffing.SPECIALTIES,'departments':staffing.DEPARTMENTS,'positions':staffing.POSITIONS}
    if query.get('company_revision',[''])[0]!=preferences['revision']: result['company']=preferences
    return result
