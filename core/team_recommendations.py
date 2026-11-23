"""Explainable, local staffing proposals. Never saves staff or launches AI work."""
import copy
import math
import os
import re
import uuid
from core import staffing

ACTIVE = {'RUNNING', 'BLOCKED', 'INCOMPLETE', 'PAUSED', 'QUEUED', 'PENDING'}
WORDS = {
    'gameplay': ('게임', 'unity', 'godot', 'unreal', 'gameplay', 'collision', '충돌', '전투', '승패'),
    'ui': ('ui', 'ux', 'hud', '메뉴', '화면', '레이아웃', '접근성', '인벤토리', '프론트엔드', 'frontend'),
    'level': ('레벨', '맵', '스테이지', '씬', 'level', 'scene', 'tilemap'),
    'testing': ('테스트', '검증', '재현', '회귀', 'test', 'tests', 'pytest', 'regression'),
    'audio': ('사운드', '효과음', '음악', 'audio', 'sound'),
    'general': ('api', '서버', '데이터', '저장', '로그인', 'backend', 'redis', '설치', '연동'),
}
ROLES = {
    'support': ('경영지원 과장', 'HEAD', 'support', '비서의 고유 업무를 유지하면서 보고 취합·부서 지원·직원 배치를 조율합니다.'),
    'planning': ('기획 담당', 'HEAD', 'planning', '요구사항·우선순위·완료 조건을 정리하고 부서 업무를 조율합니다.'),
    'gameplay': ('게임 로직 개발자', 'BUILDER', 'development', '게임 규칙·입력·충돌·상태·저장 기능을 구현하고 실제 동작을 확인합니다.'),
    'ui': ('UI 개발자', 'BUILDER', 'design', '화면·메뉴·입력 안내와 접근성을 구현하고 반응형 화면을 점검합니다.'),
    'level': ('레벨 디자이너', 'BUILDER', 'level', '씬·맵·스테이지·오브젝트 배치와 이동 경로를 구현하고 점검합니다.'),
    'testing': ('테스트 엔지니어', 'BUILDER', 'testing', '실제 요구사항의 재현·경계 상황·회귀 검사를 작성하고 미검증 범위를 기록합니다.'),
    'quality': ('독립 검수 담당', 'REVIEWER', 'quality', '구현 담당과 분리하여 결과물·실행 증거·결함과 미검증 범위를 검토합니다.'),
    'audio': ('사운드 개발자', 'BUILDER', 'design', '음향 리소스와 재생·볼륨·상태 전환을 연결하고 동작을 점검합니다.'),
    'general': ('개발 담당', 'BUILDER', 'development', 'API·데이터·서버·저장 등 현재 목표의 기능을 구현하고 동작 증거를 남깁니다.'),
}


def classify(text):
    text = text.casefold()
    return {key for key, words in WORDS.items() if any(
        re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', text) if word.isascii() else word in text
        for word in words)}


def recommend(team, missions, goal='', project_path=''):
    """Return a capacity-checked additive plan; caller owns persistence and revision checks."""
    draft = staffing.validate(team, require_ready=False)
    members = copy.deepcopy(draft['members'])
    if not isinstance(goal, str) or len(goal) > 2000:
        raise ValueError('예정 업무는 2,000자 이내로 입력하세요.')
    if not isinstance(project_path, str) or len(project_path) > 4096:
        raise ValueError('추천 대상 프로젝트를 확인하세요.')
    # Paths are only compared as data; recommendations never open a supplied path.
    project_key = os.path.normcase(project_path.replace('\\', '/').rstrip('/'))
    selected = [m for m in missions if m.get('status') in ACTIVE and (
        not project_key or os.path.normcase(str(m.get('project_path', '')).replace('\\', '/').rstrip('/')) == project_key)]
    demand = {key: 0 for key in ROLES}
    examples = {key: [] for key in ROLES}
    pending_by_staff = {}
    for mission in selected:
        text = str(mission.get('goal', ''))[:4000]
        for step in mission.get('steps', []):
            if (step.get('result') or {}).get('final_state') in {'PASS', 'DONE'}:
                continue
            order = step.get('order') or {}
            text += ' ' + str(order.get('goal', ''))[:2000]
            text += ' ' + ' '.join(str(p)[:200] for p in order.get('allowed_paths', [])[:40])
            for field in ('assigned_staff_id', 'assigned_reviewer_id'):
                ident = order.get(field)
                if ident:
                    pending_by_staff[ident] = pending_by_staff.get(ident, 0) + 1
        for key in classify(text) or {'general'}:
            demand[key] += 1
            examples[key].append(str(mission.get('goal', ''))[:140])
    for key in classify(goal) or ({'general'} if goal.strip() else set()):
        demand[key] += 1
        examples[key].append(goal.strip()[:140])
    # An engine/game project benefits from one coherent game team, not just a logic coder.
    if demand['gameplay']:
        for key in ('ui', 'level', 'testing'):
            demand[key] = max(1, demand[key])
            if not examples[key]:
                examples[key] = examples['gameplay'][:1]

    suggestions, blocked = [], []
    dependencies = {}
    unstaffed_managers = []
    used_names = {m['name'] for m in members}

    def department_staff(dept):
        return [m for m in members if staffing.department_for(m) == dept]

    # An existing full department can gain its missing manager without exceeding four people.
    for dept in staffing.DEPARTMENTS:
        staff = department_staff(dept)
        if staff and not any(staffing.position_for(m) == 'manager' for m in staff):
            eligible = [m for m in staff if staffing.position_for(m) != 'secretary']
            if not eligible:
                unstaffed_managers.append(dept)
                continue
            chosen = min(eligible, key=lambda m: (m['slot'] != 'HEAD', pending_by_staff.get(m['id'], 0)))
            chosen['position'] = 'manager'
            action = 'promote_' + chosen['id']
            dependencies[dept] = action
            suggestions.append({'id': action, 'kind': 'promote', 'member': copy.deepcopy(chosen), 'depends_on': [],
                                'reason': staffing.DEPARTMENTS[dept] + '에 과장이 없어 기존 직원을 과장으로 지정하는 제안입니다. 다른 직무·외형은 유지합니다.'})

    def hire(specialty, reason):
        name, slot, dept, duties = ROLES[specialty]
        if len(members) >= staffing.MAX_MEMBERS or len(department_staff(dept)) >= staffing.DEPARTMENT_LIMIT:
            label = staffing.DEPARTMENTS[dept] + ' · ' + staffing.SPECIALTIES.get(specialty, '부서 관리') + ': 정원이 찼습니다. 기존 직원의 배치·직무 조정을 먼저 검토하세요.'
            if label not in blocked:
                blocked.append(label)
            return False
        related = examples[specialty] or ([goal.strip()[:140]] if goal.strip() else [])
        if related:
            duties += ' 우선 검토할 업무: ' + related[0][:120]
        number = 2
        base = name
        while name in used_names:
            name = base + ' ' + str(number)
            number += 1
        used_names.add(name)
        manager = any(staffing.position_for(m) == 'manager' for m in department_staff(dept))
        index = len(members)
        member = {'id': 'staff_' + uuid.uuid4().hex[:20], 'name': name, 'slot': slot, 'specialty': 'planning' if specialty == 'support' else specialty,
                  'department': dept, 'position': 'employee' if manager else 'manager', 'duties': duties,
                  'character': {'gender': 'female' if index % 2 else 'male', 'age': 30,
                                'color': ('mint', 'blue', 'violet', 'coral', 'gold')[index % 5]}}
        action = 'hire_' + member['id']
        suggestions.append({'id': action, 'kind': 'hire', 'member': member,
                            'depends_on': [dependencies[dept]] if manager and dept in dependencies else [], 'reason': reason, 'related_tasks': related[:3]})
        if not manager:
            dependencies[dept] = action
        members.append(copy.deepcopy(member))
        return True

    for dept in unstaffed_managers:
        if dept == 'support':
            hire('support', '비서의 고유 업무를 바꾸지 않고 경영지원과를 조율할 과장을 추가하는 제안입니다.')

    # Preserve every existing person; fill execution gates before workload-driven additions.
    slots = {m['slot'] for m in members}
    if 'HEAD' not in slots:
        hire('planning', '팀에 기획·지휘 담당이 없어 목표와 부서 업무를 조율할 담당을 추천합니다.')
    if 'REVIEWER' not in slots:
        hire('quality', '구현 담당과 분리된 독립 검수 담당이 필요합니다.')
    if 'BUILDER' not in slots:
        specialty = next((key for key in ('gameplay', 'ui', 'general', 'level', 'testing', 'audio') if demand[key]), 'general')
        hire(specialty, '실제 구현·테스트 작성을 담당할 직원이 없어 추천합니다.')
    for key in ('gameplay', 'ui', 'level', 'testing', 'audio', 'general'):
        if not demand[key]:
            continue
        target = min(3, math.ceil(demand[key] / 3))
        candidates = [m for m in members if m['specialty'] == key and m['slot'] == 'BUILDER']
        assigned = sum(pending_by_staff.get(m['id'], 0) for m in candidates)
        target = max(target, min(3, math.ceil(assigned / 3)))
        for _ in range(max(0, target - len(candidates))):
            if not hire(key, f'{staffing.SPECIALTIES[key]} 관련 미완료·예정 업무 {demand[key]}건, 기존 담당의 미완료 단계 {assigned}건을 기준으로 보강합니다. 엔진 프로젝트는 UI·레벨·테스트의 최소 구성을 함께 고려합니다.' if demand['gameplay'] else
                        f'{staffing.SPECIALTIES[key]} 관련 미완료·예정 업무 {demand[key]}건, 기존 담당의 미완료 단계 {assigned}건을 기준으로 추천합니다.'):
                break
    reviewers = [m for m in members if m['slot'] == 'REVIEWER']
    review_pending = sum(pending_by_staff.get(m['id'], 0) for m in reviewers)
    for _ in range(max(0, min(3, math.ceil(review_pending / 3)) - len(reviewers))):
        if not hire('quality', f'독립 검수 담당에게 배정된 미완료 단계 {review_pending}건을 나누기 위해 검수 인원을 보강합니다.'):
            break
    staffing.validate({'members': members}, require_ready=False)
    missing = [label for key, label in staffing.SLOTS.items() if key not in {m['slot'] for m in members}]
    return {'suggestions': suggestions, 'blocked': blocked, 'missing_slots': missing,
            'missing_managers': [staffing.DEPARTMENTS[d] for d in staffing.DEPARTMENTS if department_staff(d) and not any(staffing.position_for(m) == 'manager' for m in department_staff(d))],
            'summary': {'existing_members': len(draft['members']), 'active_missions': len(selected),
                        'proposed_hires': sum(s['kind'] == 'hire' for s in suggestions),
                        'proposed_promotions': sum(s['kind'] == 'promote' for s in suggestions)},
            'workload': [{'specialty': k, 'tasks': n} for k, n in demand.items() if n],
            'basis': '현재 편집 중인 직원과 미완료 미션·예정 업무를 로컬 규칙으로 분석했습니다. 관련 업무 3건 또는 미완료 단계 3건당 담당 1명을 목표로 하며 부서별 최대 4명입니다. 추가 AI 호출·자동 저장은 하지 않습니다.',
            'notice': '추천을 추가한 뒤 이름·외형·직무를 수정하고 팀 설정을 저장하세요. 새 구성은 다음 미션부터 적용되며 AI 계정 수나 동시 실행 수를 늘리지는 않습니다.'}
