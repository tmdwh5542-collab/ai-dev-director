import json
from core import company, staffing
from tests.test_v301_companion_http import http_server, request


def test_old_company_gets_cozy_presentation_without_writing_or_losing_staff(tmp_path, monkeypatch):
    file = tmp_path / 'team_settings.json'
    monkeypatch.setattr(staffing, 'settings_path', lambda: file)
    owner = {'name':'대표','character':{'gender':'female','age':35,'color':'mint'}}
    stored = {**staffing.default_team(), 'company':{'owner':owner,'theme':'garden','visual_mode':'illustrated'}}
    file.write_text(json.dumps(stored))
    before = file.read_bytes()
    current = company.current()
    assert current['company']['visual_mode'] == 'cozy'
    assert current['company']['owner'] == owner
    assert file.read_bytes() == before
    selected = company.save({**current['company'], 'visual_mode':'illustrated'}, current['revision'])
    assert selected['company']['visual_mode'] == 'illustrated'
    assert json.loads(file.read_text())['members'] == stored['members']
    staffing.save(staffing.current(), staffing.current()['revision'])
    assert company.current()['company']['visual_mode'] == 'illustrated'


def test_cozy_assets_are_available_locally_and_to_paired_devices(http_server):
    from core.device_link import ASSETS
    for path in ('/cozy-office.js', '/cozy-office.css', '/crew-portraits-cozy-hd.png'):
        assert path in ASSETS
        status, body = request(http_server, 'GET', path)
        assert status == 200 and body
