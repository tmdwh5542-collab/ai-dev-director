"""Full game departments with one/two assigned workers, additive staffing and honest local readiness."""
import copy
import os
import uuid
from pathlib import Path
from core import staffing
from core.team_recommendations import ACTIVE, ROLES, classify, recommend

DEFAULT_GOAL = '게임 엔진과 플랫폼을 확인하고 이동·상호작용·승패·재시작이 가능한 작은 플레이 루프를 구현해줘.'
STARTER = {'goal': DEFAULT_GOAL, 'workflow_id': 'game', 'profile': 'standard',
           'criteria': '엔진에서 실행 가능한 씬, 입력·충돌·상태 전환·재시작 검증, 실제 실행 증거와 미검증 항목 보고',
           'scope': '선택한 게임 프로젝트 안에서 작은 플레이 루프부터 구현. 엔진 캐시·빌드 출력은 제외하고 기존 리소스 참조를 보존.',
           'use_project_memory': True}
PRIMARY = {'planning': 'planning', 'design': 'ui', 'development': 'gameplay', 'level': 'level',
           'testing': 'testing', 'quality': 'quality', 'support': 'support'}


def propose(team, missions, goal='', project_path=''):
    base = recommend(team, missions, goal, project_path)  # shared validation, scope and promotion rules
    original = staffing.validate(team, require_ready=False)
    members = copy.deepcopy(original['members'])
    actions = [copy.deepcopy(s) for s in base['suggestions'] if s['kind'] == 'promote']
    for action in actions:
        next(m for m in members if m['id'] == action['member']['id'])['position'] = 'manager'
    dependencies = {staffing.department_for(s['member']): s['id'] for s in actions}
    key = lambda s: os.path.normcase(str(s).replace('\\', '/').rstrip('/'))
    selected = [m for m in missions if m.get('status') in ACTIVE and (not project_path or key(m.get('project_path', '')) == key(project_path))]
    tasks = {d: 0 for d in staffing.DEPARTMENTS}
    pending = {d: 0 for d in staffing.DEPARTMENTS}
    pending_by_staff = {}
    by_id = {m['id']: m for m in members}
    kinds = set()

    def count(text):
        found = classify(text) or {'general'}
        kinds.update(found)
        for dept in {ROLES[k][2] for k in found}:
            tasks[dept] += 1
    for m in selected:
        text = str(m.get('goal', ''))[:4000]
        for step in m.get('steps', []):
            if (step.get('result') or {}).get('final_state') in {'PASS', 'DONE'}:
                continue
            order = step.get('order') or {}
            text += ' ' + str(order.get('goal', ''))[:2000]
            text += ' ' + ' '.join(str(p)[:200] for p in order.get('allowed_paths', [])[:40])
            for ident in {order.get('assigned_staff_id'), order.get('assigned_reviewer_id')} - {None}:
                if ident in by_id:
                    pending[staffing.department_for(by_id[ident])] += 1
                    pending_by_staff[ident] = pending_by_staff.get(ident, 0) + 1
        count(text)
    if goal.strip():
        count(goal)
    for dept in ('planning', 'quality', 'support'):
        tasks[dept] = max(tasks[dept], len(selected) + bool(goal.strip()))
    targets = {d: 2 if max(tasks[d], pending[d]) >= 4 else 1 for d in tasks}
    blocked = []

    def people(dept):
        return [m for m in members if staffing.department_for(m) == dept]

    def add(dept, specialty, secretary=False):
        if len(people(dept)) >= staffing.DEPARTMENT_LIMIT or len(members) >= staffing.MAX_MEMBERS:
            text = staffing.DEPARTMENTS[dept] + ': 부서 정원이 가득 차 필수 역할을 추가할 수 없습니다. 직무·직급을 직접 조정하세요.'
            if text not in blocked:
                blocked.append(text)
            return False
        name, slot, _, duties = ROLES[specialty]
        manager = any(staffing.position_for(m) == 'manager' for m in people(dept))
        if specialty == 'support' and manager:
            name = '경영지원 담당'
        if secretary:
            name, duties = '대표 비서', '부서 보고를 취합하고 대표에게 전달하며 회의와 보고 일정의 누락을 점검합니다.'
        names = {m['name'] for m in members}
        stem = name
        i = 2
        while name in names:
            name = stem + ' ' + str(i)
            i += 1
        index = len(members)
        member = {'id': 'staff_' + uuid.uuid4().hex[:20], 'name': name, 'slot': slot,
                  'specialty': 'planning' if specialty == 'support' else specialty, 'department': dept,
                  'position': 'secretary' if secretary else 'employee' if manager else 'manager',
                  'duties': duties + (' 우선 업무: ' + goal[:120] if goal.strip() else ''),
                  'character': {'gender': 'female' if index % 2 else 'male', 'age': 30,
                                'color': ('mint', 'blue', 'violet', 'coral', 'gold')[index % 5]}}
        action = {'id': 'hire_' + member['id'], 'kind': 'hire', 'member': member,
                  'depends_on': [dependencies[dept]] if manager and dept in dependencies else [],
                  'reason': f'{staffing.DEPARTMENTS[dept]}의 관련 미완료·예정 업무 {tasks[dept]}건, 배정된 미완료 단계 {pending[dept]}건. 재직 정원은 4명으로 채우고 업무는 기본 1명, 4건 이상은 2명에게 배정합니다.',
                  'related_tasks': [goal[:140]] if goal.strip() else []}
        actions.append(action)
        if not manager and not secretary:
            dependencies[dept] = action['id']
        members.append(member)
        return True

    # Every game department exists, even when no specialist keywords were observed.
    for dept, primary in PRIMARY.items():
        if not people(dept):
            add(dept, primary)
        elif not any(staffing.position_for(m) == 'manager' for m in people(dept)):
            targets[dept] = 2
            add(dept, primary)  # e.g. keep a secretary, add the support manager
        while len(people(dept)) < staffing.DEPARTMENT_LIMIT:
            specialty = 'audio' if dept == 'design' and not any(m['specialty'] == 'audio' for m in people(dept)) else 'general' if dept == 'development' and not any(m['specialty'] == 'general' for m in people(dept)) else primary
            secretary = dept == 'support' and not any(staffing.position_for(m) == 'secretary' for m in people(dept))
            if not add(dept, specialty, secretary):
                break
    # Preserve existing roles; if a department has an unusual roster, fill missing execution gates within the roster capacity.
    for slot, dept in [('HEAD', 'planning'), ('BUILDER', 'development'), ('REVIEWER', 'quality')]:
        if not any(m['slot'] == slot for m in members):
            targets[dept] = 2
            add(dept, PRIMARY[dept])
    selected_staff = []
    for dept in tasks:
        staff = people(dept)
        manager = next((m for m in staff if staffing.position_for(m) == 'manager'), None)
        if manager:
            selected_staff.append(manager)
        primary = 'audio' if dept == 'design' and 'audio' in kinds else 'general' if dept == 'development' and 'general' in kinds else PRIMARY[dept]
        others = sorted([m for m in staff if m is not manager], key=lambda m: (dept == 'support' and m['position'] != 'secretary', m['specialty'] != primary, pending_by_staff.get(m['id'], 0), m['id']))
        selected_staff.extend(others[:max(0, targets[dept] - bool(manager))])
    for slot in staffing.SLOTS:
        if any(m['slot'] == slot for m in selected_staff):
            continue
        for candidate in [m for m in members if m['slot'] == slot and m not in selected_staff]:
            dept = staffing.department_for(candidate)
            selected_dept = [m for m in selected_staff if staffing.department_for(m) == dept]
            if len(selected_dept) < 2:
                selected_staff.append(candidate)
                targets[dept] = 2
                break
            replace = next((m for m in selected_dept if staffing.position_for(m) != 'manager' and sum(x['slot'] == m['slot'] for x in selected_staff) > 1), None)
            if replace:
                selected_staff.remove(replace)
                selected_staff.append(candidate)
                break
    active_ids = [m['id'] for m in selected_staff]
    missing_managers = [staffing.DEPARTMENTS[d] for d in tasks if not any(staffing.department_for(m) == d and staffing.position_for(m) == 'manager' for m in selected_staff)]
    missing_slots = [label for slot, label in staffing.SLOTS.items() if not any(m['slot'] == slot for m in selected_staff)]
    team_ready = not missing_managers and not missing_slots and not blocked
    prepared = staffing.validate({'members': members, 'active_staff_ids': active_ids}, require_ready=team_ready)
    return {**base, 'suggestions': actions, 'blocked': blocked, 'missing_managers': missing_managers, 'missing_slots': missing_slots,
            'summary': {**base['summary'], 'proposed_hires': sum(s['kind'] == 'hire' for s in actions), 'proposed_promotions': sum(s['kind'] == 'promote' for s in actions)},
            'department_plan': [{'department': d, 'name': staffing.DEPARTMENTS[d], 'tasks': tasks[d], 'pending_steps': pending[d],
                                 'target': targets[d], 'actual': len(people(d)), 'assigned': sum(staffing.department_for(m) == d for m in selected_staff), 'retained_extra': max(0, sum(staffing.department_for(m) == d for m in original['members']) - targets[d])} for d in tasks],
            'team_ready': team_ready, 'prepared_team': prepared,
            'basis': '게임 개발 7개 부서를 과장 포함 각 4명, 총 28명으로 채웁니다. 재직 인원과 업무 배정 인원을 구분합니다. 부서별 미완료·예정 업무 또는 배정된 미완료 단계가 3건 이하면 1명, 4건 이상이면 2명입니다. 기존 인원은 줄이지 않습니다. 기획·검수·지원은 전체 미완료 업무도 고려합니다. 기존 비서 보존이나 필수 역할 보강이 필요하면 2명까지 배치합니다. 시간·난이도의 실측은 아닌 로컬 참고 기준입니다.'}


def readiness(team, config, project_path=''):
    from core import ai_connections, role_settings, web_workspace
    checks = [{'id': 'team', 'title': '7개 부서 각 4명·총 28명·업무 배정 1~2명', 'status': 'READY'}]
    staffing.validate(team)
    cfg = ai_connections.public()
    roles = cfg['settings']['roles'] if cfg['registered'] else role_settings.current(config)
    for role, provider in roles.items():
        domain = ai_connections.DOMAINS[provider]
        connection = cfg['settings']['connections'][domain]
        available = cfg['availability'][domain]
        present = available['key_present'] and bool(connection['model']) if connection['mode'] == 'api' else available['cli_installed']
        checks.append({'id': role, 'title': role.upper() + ' · ' + domain,
                       'status': 'CONFIGURED_NOT_AUTHENTICATED' if present else 'ACTION_REQUIRED'})
    checks.append({'id':'github','title':'GitHub 기술·스킬 검색/문서 받기 · 직원별 허용 도구','status':'REQUIRES_MCP'})
    engine = None
    try:
        if not project_path:
            raise ValueError('프로젝트 선택 필요')
        project = web_workspace.project(project_path)
        path = Path(project)
        if (path / 'project.godot').is_file():
            engine = 'Godot'
        elif (path / 'ProjectSettings/ProjectVersion.txt').is_file():
            engine = 'Unity'
        elif next(path.glob('*.uproject'), None):
            engine = 'Unreal'
        checks.append({'id': 'project', 'title': '게임 프로젝트 · ' + (engine or '엔진 형식 미확인'), 'status': 'DETECTED_NOT_EXECUTED' if engine else 'ACTION_REQUIRED'})
    except (ValueError, OSError):
        checks.append({'id': 'project', 'title': '미션 센터에서 게임 엔진 프로젝트 선택', 'status': 'ACTION_REQUIRED'})
    checks.append({'id': 'engine', 'title': '실제 엔진 실행·플레이 테스트', 'status': 'NOT_VERIFIED'})
    return {'checks': checks, 'engine': engine, 'authentication_verified': False, 'engine_execution_verified': False,
            'starter_brief': dict(STARTER), 'notice': '팀 저장과 개발 실행 준비를 구분합니다. AI 로그인·할당량과 엔진 설치·실행은 실제 PC에서 확인해야 합니다. 계정·키·도구를 자동 설치하거나 AI 작업을 시작하지 않습니다.'}


def bootstrap(expected_revision):
    """One-time persisted company roster initialization; never an AI/engine readiness gate."""
    from core import company
    from core.mission import MissionStore
    state = company.current()
    team = staffing.current()
    if state.get('roster_initialized'):
        return {'team': team, 'initialized': True, 'changed': False}
    if not state.get('company'):
        return {'team': team, 'initialized': False, 'changed': False, 'needs_owner': True}
    if team['revision'] != expected_revision:
        raise staffing.TeamConflict('다른 창에서 직원 구성이 바뀌었습니다. 새로고침 후 다시 확인합니다.')
    if len(team['members']) == staffing.MAX_MEMBERS:
        saved = staffing.save(team, expected_revision, roster_initialized=True)
        return {'team': saved, 'initialized': True, 'changed': False}
    plan = propose(team, MissionStore().all())
    if not plan['team_ready'] or len(plan['prepared_team']['members']) != staffing.MAX_MEMBERS:
        raise ValueError('직원 자동 구성을 저장하지 않았습니다. ' + ' '.join(plan['blocked'] + plan['missing_slots'] + plan['missing_managers']))
    saved = staffing.save(plan['prepared_team'], expected_revision, roster_initialized=True)
    return {'team': saved, 'initialized': True, 'changed': True, 'message': '직원 28명을 실제로 생성해 저장했습니다. 부서별 업무 배정은 1~2명입니다.'}
