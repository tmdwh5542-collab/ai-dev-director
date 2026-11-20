"""Bounded cosmetic layouts; no employee assignments or execution settings."""
import hashlib
import json
import threading
from core.db_path import get_db_path
from core import staffing

LOCK=threading.RLock()
KINDS={'desk':{'name':'추가 책상','width':120,'height':64},'table':{'name':'협업 테이블','width':120,'height':60},'chair':{'name':'의자','width':40,'height':40},'partition':{'name':'파티션','width':120,'height':20},'plant':{'name':'화분','width':36,'height':36}}
PALETTES={'white':{'name':'화이트','surface':'#f7fafc','frame':'#9aaebc'},'wood':{'name':'모던 우드','surface':'#d8b48d','frame':'#947654'},'graphite':{'name':'그라파이트','surface':'#627585','frame':'#344b5a'}}
CHAIRS={'blue':'#536d80','mint':'#65a58d','coral':'#c67e77'}
DEFAULT={'desk':'white','chair':'blue','items':[]}

def path():return get_db_path().parent/'office_layouts.json'
def revision(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]
def bounds(item):
    kind=KINDS[item['kind']];w,h=kind['width'],kind['height']
    if item['rotation']==90:w,h=h,w
    return [item['x']-w/2,item['y']-h/2,item['x']+w/2,item['y']+h/2]
def overlap(a,b):return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]
def reserved(room):
    zones=[[70,338,1010,402],[750,200,1020,600],[70,294,130,356]]
    anchors=[(390,210,95,85),(390,485,85,75)] if room=='ceo' else [(245,235,85,85),(550,235,85,85),(245,445,85,85),(550,445,85,85),(690,175,90,90)]
    if room!='ceo':zones.append([615,405,745,580])  # Temporary cross-department collaboration workstation.
    if room=='testing':anchors.append((670,490,60,75))
    return zones+[[x-w,y-h,x+w,y+h] for x,y,w,h in anchors]
def validate(room,value):
    import re
    if room not in {'ceo',*staffing.DEPARTMENTS}:raise ValueError('사무실을 선택하세요.')
    if not isinstance(value,dict) or set(value)!={'desk','chair','items'} or value.get('desk') not in PALETTES or value.get('chair') not in CHAIRS or not isinstance(value.get('items'),list) or len(value['items'])>24:raise ValueError('책상·의자 색상과 가구 목록(최대 24개)을 확인하세요.')
    result={'desk':value['desk'],'chair':value['chair'],'items':[]};ids=set()
    for item in value['items']:
        if not isinstance(item,dict) or set(item)!={'id','kind','x','y','rotation','color'}:raise ValueError('가구 형식을 확인하세요.')
        if not isinstance(item['id'],str) or not re.fullmatch(r'item-[a-zA-Z0-9_-]{6,40}',item['id']) or item['id'] in ids:raise ValueError('중복되거나 잘못된 가구 ID입니다.')
        if item['kind'] not in KINDS or item['color'] not in PALETTES or type(item['rotation']) is not int or item['rotation'] not in (0,90) or any(type(item[k]) is not int for k in ('x','y')):raise ValueError('가구 종류·색상·좌표·회전을 확인하세요.')
        box=bounds(item)
        if box[0]<70 or box[1]<160 or box[2]>1010 or box[3]>600 or any(overlap(box,b) for b in reserved(room)):raise ValueError('가구는 바닥 안에 놓고 출입구·통로·업무 책상·회의 공간은 비워주세요.')
        if any(overlap(box,bounds(other)) for other in result['items']):raise ValueError('가구가 서로 겹칩니다. 간격을 두어 배치하세요.')
        ids.add(item['id']);result['items'].append(dict(item))
    return result

def current():
    from core.read_projection import CACHE
    def build():
        with LOCK:
            state=json.loads(path().read_text(encoding='utf-8')) if path().exists() else {'rooms':{}}
            return ({'rooms':state['rooms'],'revision':revision(state)},False)
    return CACHE.get(path(),build)
def public():
    state=current()
    return {**state,'room_revisions':{room:revision(state['rooms'].get(room,DEFAULT)) for room in ['ceo',*staffing.DEPARTMENTS]},'default':DEFAULT,'kinds':KINDS,'palettes':PALETTES,'chairs':CHAIRS,'reserved':{r:reserved(r) for r in ['ceo',*staffing.DEPARTMENTS]}}
def save(payload):
    if not isinstance(payload,dict):raise ValueError('JSON 객체가 필요합니다.')
    room=payload.get('room');layout=validate(room,payload.get('layout'))
    with LOCK:
        state=current()
        if payload.get('expected_revision')!=revision(state['rooms'].get(room,DEFAULT)):raise staffing.TeamConflict('이 사무실 배치가 다른 기기에서 변경됐습니다. 작성 중인 배치는 유지됩니다. 취소로 최신 배치를 불러온 뒤 다시 편집하세요.')
        value={'rooms':{**state['rooms'],room:layout}};p=path();p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
        return public()
