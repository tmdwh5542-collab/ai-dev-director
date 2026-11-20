"""CEO-led sequential briefings derived from saved evidence, never fabricated AI speech."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from core import staffing


def path():
    return staffing.settings_path().parent / 'executive_briefings.json'


def read():
    value = json.loads(path().read_text(encoding='utf-8')) if path().exists() else {'sessions': []}
    return {**value, 'revision': hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]}


def write(state):
    state.pop('revision', None)
    p = path(); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix('.tmp'); temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'); temp.replace(p)


def listing():
    with staffing.LOCK:
        return read()


def submit(payload, validate_project):
    if not isinstance(payload, dict): raise ValueError('회의 요청을 확인하세요.')
    with staffing.LOCK:
        state = read()
        if payload.get('expected_revision') != state['revision']: raise staffing.TeamConflict('회의가 변경됐습니다. 다시 확인하세요.')
        if payload.get('action') == 'start':
            ok, project = validate_project(payload.get('project_path', ''))
            if not ok: raise ValueError(str(project))
            if any(s['status']=='ACTIVE' for s in state['sessions']): raise staffing.TeamConflict('진행 중인 임원회의에 먼저 답변하세요.')
            team = staffing.current()
            managers = [m for m in team['members'] if staffing.position_for(m)=='manager']
            if not managers: raise ValueError('먼저 부서 과장을 채용하세요.')
            if len(state['sessions']) >= 100: raise ValueError('임원회의 보관 한도에 도달했습니다.')
            from core.mission import MissionStore
            missions = sorted([m for m in MissionStore().all() if m.get('project_path')==project], key=lambda m:m.get('updated_at',''))[-5:]
            reports = []
            for m in managers:
                department = staffing.department_for(m)
                members = {s['id'] for s in team['members'] if staffing.department_for(s)==department}
                evidence=[]
                for mission in missions:
                    for step in mission.get('steps',[]):
                        order=step.get('order') or {}
                        if {order.get('assigned_staff_id'),order.get('assigned_reviewer_id')} & members:
                            result=step.get('result') or {}
                            evidence.append({'mission_id':mission['mission_id'],'mission_status':mission.get('status'),'goal':str(order.get('goal',''))[:800],
                                'method':str(order.get('implementation_plan') or order.get('steps') or order.get('allowed_paths') or '지시서 상세에서 확인')[:1200],
                                'result':{k:result.get(k) for k in ('final_state','tests','review_verdict')}})
                recommendation=('현재 목표에서 이 부서가 맡을 작업과 완료 기준을 다음 계획에 명시해주세요.' if not evidence else
                    '실패한 단계의 재현 방법과 수정안을 우선 정리해주세요.' if any(e['result'].get('final_state') in {'FAIL','FAILED','BLOCKED','HUMAN_REQUIRED'} for e in evidence) else
                    '확인된 검증 근거를 유지하고 남은 작업을 다음 계획에 정리해주세요.')
                reports.append({'manager_id':m['id'],'name':m['name'],'character':m.get('character'),'department':department,
                    'source':'저장된 배정·미션·검증 기록을 프로그램이 정리한 보고', 'evidence':evidence[-8:],
                    'summary':f"{staffing.DEPARTMENTS[department]} 배정 단계 {len(evidence)}건. 검증 결과는 아래 원본 기록을 확인해주세요." if evidence else '이 부서에 배정된 실행 기록이 아직 없습니다. 완료율을 추정하지 않습니다.',
                    'recommendations':[recommendation,'검증 근거와 남은 작업을 보완해주세요.','우선순위를 정리해 다음 계획에 반영해주세요.'], 'reply':None})
            state['sessions'].append({'id':'BRF-'+uuid.uuid4().hex[:16],'project_path':project,'team_revision':team['revision'],'status':'ACTIVE','index':0,'created_at':datetime.now(timezone.utc).isoformat(),'reports':reports})
        elif payload.get('action') in {'approve','comment'}:
            session=next((s for s in state['sessions'] if s['id']==payload.get('id')),None)
            if not session or session['status']!='ACTIVE': raise ValueError('진행 중인 회의를 선택하세요.')
            if payload.get('index') != session['index']: raise staffing.TeamConflict('발표 순서가 변경됐습니다.')
            reply=payload.get('reply','')
            if not isinstance(reply,str) or len(reply)>2000 or (payload['action']=='comment' and not reply.strip()): raise ValueError('대표 답변을 1~2000자로 입력하세요.')
            session['reports'][session['index']]['reply']={'action':payload['action'],'text':reply.strip() or '보고를 확인하고 승인합니다.','at':datetime.now(timezone.utc).isoformat()}
            session['index']+=1
            if session['index']==len(session['reports']): session['status']='DONE'
        else: raise ValueError('회의 동작을 선택하세요.')
        write(state)
        return read()


def decisions(project):
    return [{'id':s['id']+':'+r['manager_id'],'title':r['name']+' 보고에 대한 대표 지침','action':r['reply']['text'],'status':'APPROVED'}
        for s in listing()['sessions'] if s['project_path']==project for r in s['reports'] if r.get('reply')][-12:]


def telemetry():
    """Keep the current report and history count; never transmit every old evidence bundle in a poll."""
    from core.read_projection import CACHE
    def build():
        state = listing()
        return ({'revision': state['revision'], 'session_count': len(state['sessions']),
                 'sessions': [s for s in state['sessions'] if s['status'] == 'ACTIVE']}, False)
    return CACHE.get(path(), build)


def compact_listing(known_revision=''):
    state = telemetry()
    return {'unchanged': True, 'revision': state['revision']} if known_revision == state['revision'] else state
