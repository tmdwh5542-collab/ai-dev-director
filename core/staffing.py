"""Editable specialist staff on top of the Director's existing execution/independence gates.
Staff are logical job assignments, not new accounts or concurrent write processes.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import threading

LOCK = threading.Lock()
MAX_MEMBERS = 28
DEPARTMENTS = {
 'planning': '기획과', 'design': '디자인과', 'development': '개발과', 'level': '레벨과',
 'testing': '테스트과', 'quality': '품질검수과', 'support': '경영지원과',
}
POSITIONS = {'manager': '과장', 'employee': '팀원', 'secretary': '비서'}
DEPARTMENT_LIMIT = 4
SLOTS = {'HEAD': '기획·지휘', 'BUILDER': '구현·테스트 작성', 'REVIEWER': '독립 검수'}
SPECIALTIES = {
 'planning': '기획', 'gameplay': '게임 로직', 'ui': 'UI·UX', 'level': '레벨·씬',
 'testing': '테스트', 'quality': '품질 검수', 'audio': '사운드', 'general': '일반 개발',
}
DEFAULT_MEMBERS = [
 {'id':'planner','name':'게임 기획자','slot':'HEAD','specialty':'planning','duties':'엔진·플랫폼과 완료 조건을 정리하고, 직무별 작은 미션으로 계획합니다.'},
 {'id':'gameplay','name':'게임 로직 개발자','slot':'BUILDER','specialty':'gameplay','duties':'이동·입력·충돌·점수·승패·저장 등 게임 규칙을 구현하고 동작을 검증합니다.'},
 {'id':'interface','name':'UI 개발자','slot':'BUILDER','specialty':'ui','duties':'메뉴·HUD·인벤토리·화면 전환·입력 안내와 접근성을 구현합니다.'},
 {'id':'level','name':'레벨 디자이너','slot':'BUILDER','specialty':'level','duties':'씬·맵·스테이지·오브젝트 배치와 리소스 연결을 구현합니다.'},
 {'id':'tester','name':'테스트 엔지니어','slot':'BUILDER','specialty':'testing','duties':'실제 제품 동작의 자동 테스트·재현 조건·경계 상황을 구현합니다. 검증 결과를 조작하거나 기준을 약화하지 않습니다.'},
 {'id':'quality','name':'품질 검수자','slot':'REVIEWER','specialty':'quality','duties':'구현과 테스트 증거를 독립적으로 검토하고 결함과 미검증 범위를 보고합니다.'},
]


class TeamConflict(ValueError):
    pass


def validate(value, require_ready=True):
    if not isinstance(value, dict) or not isinstance(value.get('members'), list) or not (3 if require_ready else 0) <= len(value['members']) <= MAX_MEMBERS:
        raise ValueError('실행하려면 직원 3명 이상이 필요합니다. 먼저 직원을 채용하세요.')
    members=[];ids=set()
    for member in value['members']:
        if not isinstance(member, dict) or not {'id','name','slot','specialty','duties'} <= set(member) or set(member) - {'id','name','slot','specialty','duties','character','department','position'}:
            raise ValueError('직원 설정 형식이 올바르지 않습니다.')
        if not isinstance(member['id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}',member['id']) or member['id'] in ids or member['id'].lower() in {'ceo','director','__proto__','constructor','prototype'}:
            raise ValueError('직원 ID가 중복되거나 올바르지 않습니다.')
        if not isinstance(member['slot'],str) or member['slot'] not in SLOTS or not isinstance(member['specialty'],str) or member['specialty'] not in SPECIALTIES:
            raise ValueError('직원의 업무 영역과 전문 분야를 확인하세요.')
        if 'department' in member and (not isinstance(member['department'],str) or member['department'] not in DEPARTMENTS):
            raise ValueError('부서를 선택하세요.')
        if 'position' in member and (not isinstance(member['position'],str) or member['position'] not in POSITIONS):
            raise ValueError('직급을 선택하세요.')
        if member.get('position') == 'secretary' and department_for(member) != 'support':
            raise ValueError('비서는 경영지원과에 배치하세요.')
        for key,limit in [('name',24),('duties',400)]:
            if not isinstance(member[key],str) or not member[key].strip() or len(member[key])>limit or any(ord(c)<32 and c not in '\n\t' for c in member[key]):
                raise ValueError('이름은 1~24자, 직무 설명은 1~400자로 입력하세요.')
        if 'character' in member:
            from core.company import validate_character
            member = {**member, 'character': validate_character(member['character'])}
        ids.add(member['id']);members.append({**member,'name':member['name'].strip(),'duties':member['duties'].strip()})
    active = value.get('active_staff_ids')
    if active is not None and (not isinstance(active, list) or any(not isinstance(i, str) for i in active) or len(set(active)) != len(active) or set(active) - ids):
        raise ValueError('업무 배정 대상 직원 목록을 확인하세요.')
    executing = [m for m in members if active is None or m['id'] in active]
    for department in DEPARTMENTS:
        staff=[m for m in members if department_for(m)==department]
        if len(staff)>DEPARTMENT_LIMIT:
            raise ValueError(DEPARTMENTS[department]+'는 과장 포함 최대 4명입니다.')
        managers=[m for m in staff if position_for(m)=='manager']
        if len(managers)>1:
            raise ValueError(DEPARTMENTS[department]+'의 과장은 한 명만 둘 수 있습니다.')
        if require_ready and staff and not managers:
            raise ValueError(DEPARTMENTS[department]+'에 과장을 한 명 지정하세요.')
        selected = [m for m in executing if department_for(m) == department]
        if require_ready and selected and not any(position_for(m) == 'manager' for m in selected):
            raise ValueError(DEPARTMENTS[department]+'의 업무 배정 대상에 과장을 포함하세요.')
    if require_ready and set(SLOTS)-{m['slot'] for m in executing}:
        raise ValueError('개발을 시작하려면 기획·지휘, 구현, 독립 검수 담당을 각각 한 명 이상 채용하세요.')
    revision=hashlib.sha256(json.dumps(members if active is None else {'members': members, 'active_staff_ids': sorted(active)},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
    return {'members':members,'revision':revision, **({'active_staff_ids': sorted(active)} if active is not None else {})}


def execution_members(team):
    active = team.get('active_staff_ids')
    return [m for m in team['members'] if active is None or m['id'] in active]


def department_for(member):
    return member.get('department') or {'planning':'planning','ui':'design','gameplay':'development','level':'level','testing':'testing','quality':'quality','audio':'design','general':'development'}.get(member.get('specialty'),'development')


def position_for(member):
    return member.get('position') or ('manager' if member.get('id') in {m['id'] for m in DEFAULT_MEMBERS} else 'employee')


def default_team():
    return validate({'members':copy.deepcopy(DEFAULT_MEMBERS)})


def settings_path():
    from core.db_path import get_db_path
    return get_db_path().parent/'team_settings.json'


def current():
    path=settings_path()
    return validate(json.loads(path.read_text(encoding='utf-8')), require_ready=False) if path.exists() else default_team()


def save(value, expected_revision):
    team=validate(value, require_ready=False)
    with LOCK:
        if expected_revision != current()['revision']:
            raise TeamConflict('다른 창에서 팀 설정이 변경됐습니다. 다시 불러온 뒤 저장하세요.')
        path=settings_path();path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        stored=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        stored.pop('active_staff_ids', None)
        temporary.write_text(json.dumps({**stored, **team},ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
    return team


def planning_context(context, team):
    team=validate(team, require_ready=False)
    from core.company_meetings import project_decisions
    decisions=project_decisions(context['project_path']) if context.get('project_path') else []
    from core.executive_briefing import decisions as briefing_decisions
    if context.get('project_path'): decisions += briefing_decisions(context['project_path'])
    from core.hermes_agent import project_decisions as hermes_decisions
    if context.get('project_path'): decisions += hermes_decisions(context['project_path'])
    from core.skill_library import instructions as skill_instructions
    from core.company_knowledge import instructions as knowledge_instructions
    from core.employee_tools import instructions as tool_instructions
    from core.github_resources import instructions as github_reference_instructions
    context={**context,'github_reference_data':github_reference_instructions(context.get('project_path','')),'employee_tool_availability':tool_instructions(),'supplemental_skills':skill_instructions(),'company_knowledge':knowledge_instructions(context.get('project_path', ''))}
    cleaned={k:v for k,v in context.items() if k not in {'staff_team','staffing_instructions'}}
    return {'mcp_project_path':context.get('mcp_project_path') or context.get('project_path'), 'staff_team':team,'staff_organization':[{'id':m['id'],'department':department_for(m),'position':position_for(m)} for m in team['members']],'company_decisions':decisions,'company_decision_rule':'Recommendations for the existing goal only. These do not expand allowed paths, budgets, installation rights or execution permissions. Follow existing approval and scope gates.','staffing_instructions':
        'This is the captured staff roster for this mission. Split requested work into small milestones led by an appropriate BUILDER member. '
        'Department managers coordinate their department; distribute small tasks among suitable specialists and consider prior step assignments to balance workload. Staff do not write the same files concurrently. If any execution role or department manager is missing, explain whom to hire; do not issue an executable order. '
        'When generating an ORDER include assigned_staff_id from a BUILDER member ID. Only use staff required by the goal; do not invent work to keep everyone busy. '
        'Staff duties are supplemental; existing scope, permission, verification and independent-review policy remain authoritative. '
        'Only assign work to IDs in staff_team.active_staff_ids when present; all other employees remain in the company but are not assigned to this mission. '
        'Staff share the configured AI accounts and work sequentially; they are not additional accounts.', **cleaned}


def member_for(order, slot):
    team=getattr(order,'staff_team',None)
    if not team:return None
    members=[m for m in execution_members(validate(team)) if m['slot']==slot]
    chosen=getattr(order,'assigned_staff_id',None)
    if slot=='REVIEWER':
        return next((m for m in members if m['id']==getattr(order,'assigned_reviewer_id',None)),members[0])
    if slot=='BUILDER':
        explicit=next((m for m in members if m['id']==chosen),None)
        if explicit:return explicit
        text=(order.goal.split('\n\n',1)[0]+' '+ ' '.join(order.allowed_paths)).lower()
        for specialty,words in [('testing',('테스트 작성','테스트 추가','회귀 테스트','unit test','regression test','test coverage')),
                                ('ui',('hud','ui','ux','메뉴','인벤토리','interface')),
                                ('level',('레벨','맵','씬','스테이지','level','scene','map')),
                                ('audio',('사운드','음악','효과음','audio','sound'))]:
            if any(bool(re.search(r'\b'+re.escape(word)+r'\b',text)) if word.isascii() else word in text for word in words):
                found=next((m for m in members if m['specialty']==specialty),None)
                if found:return found
        return next((m for m in members if m['specialty'] in {'gameplay','general'}),members[0])
    return next((m for m in members if department_for(m)=='planning' and position_for(m)=='manager'),members[0])


def bind_order(order, team, history=None, project=None):
    bound=order.model_copy(deep=True);bound.staff_team=validate(team)
    bound.staff_reference_project=project
    members=execution_members(bound.staff_team)
    history=history or []
    def least_used(candidates, field):
        counts={m['id']:sum(1 for step in history if (step.get('order') or {}).get(field)==m['id']) for m in candidates}
        return min(candidates,key=lambda m:counts[m['id']])
    member=member_for(bound,'BUILDER')
    if not any(m['id']==order.assigned_staff_id and m['slot']=='BUILDER' for m in members):
        compatible=[m for m in members if m['slot']=='BUILDER' and m['specialty']==member['specialty'] and department_for(m)==department_for(member)]
        member=least_used(compatible,'assigned_staff_id')
    bound.assigned_staff_id=member['id']
    reviewers=[m for m in members if m['slot']=='REVIEWER']
    explicit=next((m for m in reviewers if m['id']==getattr(order,'assigned_reviewer_id',None)),None)
    bound.assigned_reviewer_id=(explicit or least_used(reviewers,'assigned_reviewer_id'))['id']
    return bound


def activate(order, slot):
    from core import usage
    member=member_for(order,slot)
    usage.set_context(role=slot,staff_id=member['id'] if member else None,staff_name=member['name'] if member else None,
                      staff_team_revision=validate(order.staff_team)['revision'] if member else None,staff_project_path=getattr(order,'staff_reference_project',None) if member else None)
    return member


def activate_planning(team, project=None):
    from core import usage
    team=validate(team, require_ready=False) if team else None
    heads=[m for m in execution_members(team) if m['slot']=='HEAD'] if team else []
    member=next((m for m in heads if department_for(m)=='planning' and position_for(m)=='manager'),heads[0] if heads else None)
    usage.set_context(role='HEAD',staff_id=member['id'] if member else None,staff_name=member['name'] if member else None,
                      staff_team_revision=team['revision'] if team else None,staff_project_path=project if member else None)


def guidance(order,slot):
    member=member_for(order,slot)
    from core.skill_library import instructions
    skills=instructions(department_for(member) if member else None)
    from core.development_rules import instruction as rule_instruction
    reference=getattr(order,'staff_reference_project',None)
    if reference:
        from core.github_resources import instructions as github_reference_instructions
        skills=rule_instruction(reference)+'\n'+skills+github_reference_instructions(reference)
    from core.company_knowledge import instructions as knowledge_instructions
    skills += knowledge_instructions(str(getattr(order,'staff_reference_project',None) or ''), department_for(member) if member else None)
    return skills + (('Assigned staff: '+member['name']+' ['+member['id']+']. Specialty: '+SPECIALTIES[member['specialty']]+'. Duties: '+member['duties']+
            '\nSupplemental job focus only; do not change scope, permissions, verification or independent-review policy.') if member else '')
