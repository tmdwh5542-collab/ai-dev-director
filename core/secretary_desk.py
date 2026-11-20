"""Evidence-derived inbox, with explicit original routes and no model calls."""
from core import company_meetings, executive_briefing, hermes_agent
from core.mission import MissionStore, _pid_alive
from core.company_knowledge import revision


def summary():
    cards=[]
    missions=sorted(MissionStore().all(),key=lambda m:m.get('updated_at',''),reverse=True)
    for m in missions[:20]:
        status=m.get('status','UNKNOWN')
        if status in {'FAILED','BLOCKED','INCOMPLETE','RUNNING'}:
            live=status=='RUNNING' and _pid_alive(m.get('owner_pid'))
            cards.append({'kind':'mission','id':m['mission_id'],'title':m.get('goal','')[:200], 'status':status if status!='RUNNING' or live else 'INTERRUPTED','detail':str(m.get('blocked_reason') or ('실제 실행 기록을 확인하세요.' if live else '미션 상세에서 남은 단계와 검증 결과를 확인하세요.'))[:500],'project_path':m.get('project_path',''),'href':'/missions'})
    for a in company_meetings.telemetry()['agendas']:
        if a.get('status')=='PENDING':cards.append({'kind':'approval','id':a['id'],'title':str(a.get('title') or a.get('topic') or a.get('summary') or '회의 안건 승인')[:200],'status':'PENDING','detail':'회의 근거를 검토하고 대표 승인/보류를 선택하세요.','project_path':a.get('project_path',''),'href':'/office#meetings-title'})
    active=next(iter(executive_briefing.telemetry()['sessions']),None)
    if active:cards.append({'kind':'briefing','id':active['id'],'title':'진행 중인 임원회의','status':'ACTIVE','detail':'부서별 보고를 확인하고 대표 답변을 제출하세요.','project_path':active.get('project_path',''),'href':'/office#executive-title'})
    for j in hermes_agent.telemetry()['jobs']:
        if j['status'] in {'READY','FAILED','INTERRUPTED'}:cards.append({'kind':'hermes','id':j['id'],'title':str(j.get('question') or 'Hermes 분석 보고')[:200],'status':j['status'],'detail':'분석 보고서와 출처를 확인하세요. 채택 전에는 다음 계획에 반영되지 않습니다.','project_path':j.get('project_path',''),'href':'/office#hermes-title'})
    from core.scheduled_work import listing as automation_listing
    automation=automation_listing()
    automation_cards=[]
    for j in automation['jobs']:
        if j['status'] in {'READY_REVIEW','FAILED','MISSED','NEEDS_REVIEW'} or (j.get('error') and j['status'] in {'SCHEDULED','PUBLISHED','VERIFYING','STOPPING'}):
            automation_cards.append({'kind':'automation','id':j['id'],'title':(j.get('media') or {}).get('title') or j['plan_name'], 'status':j['status'],'detail':j.get('error') or '예약 영상과 공개 시간을 검토하세요.','project_path':j['publish_at'],'href':'/automation'})
    from core.web_workspace import root as web_root
    for path in sorted(web_root().glob('*/reports/AUD-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:10]:
        import json
        report=json.loads(path.read_text(encoding='utf-8'))
        cards.append({'kind':'web-audit','id':report['id'],'title':'웹 검수 · '+report['kind'],'status':report['status'],'detail':report.get('summary','실제 검수 기록'),'project_path':report['project_path'],'href':'/web-workspace'})
    from core.development_rules import state as rule_state
    for project,entries in rule_state()['failures'].items():
        if entries:
            entry=entries[-1];cards.append({'kind':'development-rule','id':entry['signature'],'title':'프로젝트 실패 참고 · '+str(entry['count'])+'회','status':'OBSERVED','detail':entry['observation'],'project_path':project,'href':'/settings#development-rules'})
    cards=automation_cards+cards
    value={'automation_today':automation['today'],'cards':cards[:50],'missions_total':len(missions),'source':'저장된 미션·회의·분석·예약 업무 기록을 프로그램이 정리했습니다. AI 추론이나 완료율 추정은 하지 않습니다.'}
    return {**value,'revision':revision(value)}
