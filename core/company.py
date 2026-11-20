"""Company identity/preferences stored atomically with the roster.
Demographics are visual data and never determine capability or assignments.
"""
import hashlib
import json
from core import staffing

THEMES = {
 'corporate': {'name': '대기업 본사', 'description': '도시 전망 · 통유리 · 화이트 데스크'},
 'creative': {'name': '자유로운 스튜디오', 'description': '모던 우드 · 협업 보드 · 라운지'},
 'garden': {'name': '그린 오피스', 'description': '밝은 바닥 · 플랜트 월 · 유리 회의실'},
}
COLORS = {'mint': '#89dfca', 'blue': '#89bfff', 'violet': '#c5b1ff', 'coral': '#f4a49a', 'gold': '#e5c58e'}


def validate_character(value):
    if not isinstance(value, dict) or set(value) != {'gender', 'age', 'color'}:
        raise ValueError('캐릭터의 성별·나이·의상 색상을 선택하세요.')
    if not isinstance(value['gender'], str) or value['gender'] not in ('male', 'female') or isinstance(value['age'], bool) or not isinstance(value['age'], int) or not 18 <= value['age'] <= 100:
        raise ValueError('성별은 남성·여성, 나이는 18~100세로 입력하세요.')
    if not isinstance(value['color'], str) or value['color'] not in COLORS:
        raise ValueError('의상 색상을 선택하세요.')
    return dict(value)


def validate(value):
    if not isinstance(value, dict) or not {'owner','theme'} <= set(value) or set(value)-{'owner','theme','auto_meetings','room_themes','visual_mode'}:
        raise ValueError('대표 캐릭터와 사무실을 설정하세요.')
    owner = value['owner']
    if not isinstance(owner, dict) or set(owner) != {'name', 'character'}:
        raise ValueError('대표 이름과 캐릭터를 입력하세요.')
    name = owner['name']
    if not isinstance(name, str) or not name.strip() or len(name) > 24 or any(ord(c) < 32 for c in name):
        raise ValueError('대표 이름은 1~24자로 입력하세요.')
    if not isinstance(value['theme'], str) or value['theme'] not in THEMES:
        raise ValueError('사무실 배경을 선택하세요.')
    if 'auto_meetings' in value and type(value['auto_meetings']) is not bool:
        raise ValueError('자동 회의 설정을 확인하세요.')
    if 'visual_mode' in value and value['visual_mode'] not in ('illustrated','pixel'):raise ValueError('고해상도 2D 또는 픽셀 그래픽을 선택하세요.')
    rooms = value.get('room_themes', {})
    if not isinstance(rooms, dict) or any(k not in {'ceo', *staffing.DEPARTMENTS} or v not in THEMES for k,v in rooms.items()):
        raise ValueError('사무실별 배경 설정을 확인하세요.')
    extra = {'room_themes': dict(rooms)} if rooms else {}
    if 'visual_mode' in value:extra['visual_mode']=value['visual_mode']
    return {**extra, 'auto_meetings':value.get('auto_meetings',False),'owner': {'name': name.strip(), 'character': validate_character(owner['character'])}, 'theme': value['theme']}


def current():
    path = staffing.settings_path()
    stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    company = validate(stored['company']) if stored.get('company') is not None else None
    revision = hashlib.sha256(json.dumps(company, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    return {'company': company, 'revision': revision, 'existing_team': bool(stored.get('members')), 'themes': THEMES, 'colors': COLORS}


def save(value, expected_revision):
    company = validate(value)
    with staffing.LOCK:
        if expected_revision != current()['revision']:
            raise staffing.TeamConflict('다른 창에서 회사 설정이 변경됐습니다. 다시 불러온 뒤 저장하세요.')
        path = staffing.settings_path()
        stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() else staffing.validate({'members': []}, require_ready=False)
        stored['company'] = company
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    return current()
