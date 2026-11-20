import http.client
from tests.test_v301_companion_http import http_server


def test_preview_frames_allowed_only_on_web_workspace(http_server):
    from core.device_link import PAGES, ASSETS
    assert '/web-workspace' in PAGES
    assert {'/web-workspace.js','/web-workspace.css'} <= ASSETS
    for path in ('/web-workspace','/office'):
        connection=http.client.HTTPConnection('127.0.0.1',http_server.server_address[1])
        connection.request('GET',path)
        response=connection.getresponse()
        assert response.status==200
        policy=response.getheader('Content-Security-Policy')
        assert "frame-ancestors 'none'" in policy
        assert ('frame-src http: https:' in policy)==(path=='/web-workspace')
        response.read();connection.close()


def test_web_tool_writes_require_local_bridge_auth(http_server):
    from tests.test_v301_companion_http import request
    assert request(http_server,'POST','/ops/web-workspace','{}',{'Content-Type':'application/json'})[0]==403
    assert request(http_server,'POST','/ops/employee-tools','{}',{'Content-Type':'application/json','X-Solomon-Bridge':'test-token','Origin':'https://foreign.example'})[0]==403
    assert request(http_server,'GET','/vendor/monaco/%2e%2e/%2e%2e/settings.js')[0]==404
