import pytest
from core import company,staffing
from tests.test_v301_companion_http import http_server,request


def test_illustrated_preferences_survive_without_changing_the_roster():
    staffing.save(staffing.default_team(),staffing.current()['revision'])
    before=staffing.current()['revision'];value={'owner':{'name':'대표','character':{'gender':'female','age':35,'color':'mint'}},'theme':'corporate','visual_mode':'illustrated','room_themes':{'planning':'creative'}}
    saved=company.save(value,company.current()['revision'])
    assert saved['company']['visual_mode']=='illustrated' and saved['company']['room_themes']['planning']=='creative'
    assert staffing.current()['revision']==before
    saved=company.save({**value,'visual_mode':'pixel'},saved['revision']);assert saved['company']['visual_mode']=='pixel'
    with pytest.raises(ValueError):company.save({**value,'visual_mode':'<script>'},saved['revision'])


def test_bundled_artwork_is_served_only_from_fixed_paths(http_server):
    for route in ('/crew-portraits-hd.png','/crew-illustrated.png','/office-corporate-hd.png','/office-creative-hd.png','/office-garden-hd.png',*(f'/furniture-{kind}-hd.png' for kind in ('desk','table','chair','partition','plant'))):
        status,body=request(http_server,'GET',route);assert status==200 and body.startswith(b'\x89PNG\r\n\x1a\n')
    from core.device_link import ASSETS
    assert {'/crew-portraits-hd.png','/crew-illustrated.png','/office-corporate-hd.png','/office-creative-hd.png','/office-garden-hd.png','/game-style.js','/game-style.css'}<=ASSETS
    assert {'/furniture-art.js',*(f'/furniture-{kind}-hd.png' for kind in ('desk','table','chair','partition','plant'))}<=ASSETS
    assert request(http_server,'GET','/assets/../data/director.db')[0]==404
