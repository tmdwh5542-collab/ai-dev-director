import copy
import json
import pytest
from core import office_layout as layout, staffing
from tests.test_v301_companion_http import http_server, request


def item(**values):return {'id':'item-example','kind':'table','x':150,'y':500,'rotation':0,'color':'wood',**values}
def room(**values):return {**copy.deepcopy(layout.DEFAULT),**values}
def save(which='ceo',**changes):
    state=layout.public()
    return layout.save({'room':which,'layout':room(**changes),'expected_revision':state['room_revisions'][which]})

def test_independent_rooms_and_conflicting_edits_preserve_records():
    initial=layout.public();saved=save(items=[item()],desk='wood',chair='mint')
    assert saved['rooms']['ceo']['items'][0]['x']==150
    saved=save('planning',desk='graphite')
    assert saved['rooms']['ceo']['desk']=='wood' and saved['rooms']['planning']['desk']=='graphite'
    with pytest.raises(staffing.TeamConflict):layout.save({'room':'ceo','layout':room(),'expected_revision':initial['room_revisions']['ceo']})
    assert layout.current()['rooms']['ceo']['items']

@pytest.mark.parametrize('values',[
    {'x':-10},{'y':700},{'x':500,'y':370},{'x':390,'y':210},{'x':885,'y':430},
    {'rotation':45},{'rotation':True},{'x':float('inf')},{'kind':'script'},{'color':'<script>'},
    {'id':'../../outside'},{'x':True},
])
def test_invalid_and_protected_placements_rejected(values):
    with pytest.raises(ValueError):layout.validate('ceo',room(items=[item(**values)]))

def test_overlap_rotation_bounds_and_item_limit():
    with pytest.raises(ValueError):layout.validate('ceo',room(items=[item(),item(id='item-second',x=170)]))
    with pytest.raises(ValueError):layout.validate('ceo',room(items=[item(),item()]))
    assert layout.validate('ceo',room(items=[item(rotation=90)]))
    with pytest.raises(ValueError):layout.validate('ceo',room(items=[item(x=100,rotation=0)]))
    with pytest.raises(ValueError):layout.validate('ceo',room(items=[item()]*25))
    # A narrow gap between staff stations is not an excuse to put furniture across the aisle.
    with pytest.raises(ValueError):layout.validate('development',room(items=[item(x=390,y=370,kind='partition')]))


def test_cosmetic_save_does_not_change_company_or_roster():
    from core import company
    before=(company.current(),staffing.current())
    save(items=[item()])
    assert before==(company.current(),staffing.current())
    from core.company_backup import FILES
    assert 'office_layouts.json' in FILES


def test_authenticated_endpoint_and_remote_allowlist(http_server):
    assert request(http_server,'GET','/ops/office-layout')[0]==200
    assert request(http_server,'POST','/ops/office-layout')[0]==403
    for url in ('/office-decor.js','/office-view.js','/office-decor.css'):assert request(http_server,'GET',url)[0]==200
    payload={'room':'ceo','layout':room(items=[item()]),'expected_revision':layout.public()['room_revisions']['ceo']}
    headers={'Content-Type':'application/json','X-Solomon-Bridge':'test-token'}
    code,data=request(http_server,'POST','/ops/office-layout',json.dumps(payload),headers)
    assert code==200 and json.loads(data)['rooms']['ceo']['items']
    headers['Origin']='https://evil.example'
    assert request(http_server,'POST','/ops/office-layout',json.dumps(payload),headers)[0]==403
    from core.device_link import READ_API,WRITE_API,ASSETS
    assert '/ops/office-layout' in READ_API&WRITE_API
    assert {'/office-decor.js','/office-view.js','/office-decor.css'}<=ASSETS

def test_cross_department_visitor_workstation_stays_available():
    with pytest.raises(ValueError):layout.validate('development',room(items=[item(kind='chair',x=690,y=500)]))
