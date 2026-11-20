"""Mission library uses persisted evidence and never starts/changes a mission."""
import copy
import json

import pytest

import dashboard_server as d
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


@pytest.fixture
def library(env, monkeypatch):
    rows = []
    for i in range(26):
        rows.append({"mission_id": f"MSN-{i:03}", "goal": f"검색 개선 {i}" if i % 2 else f"로그인 수정 {i}",
                     "project_path": "/work/한글프로젝트" if i % 2 else "/work/Other", "status": "DONE" if i % 2 else "FAILED",
                     "updated_at": f"2026-11-{i + 1:02}T10:00:00", "created_at": "2026-10-01T00:00:00",
                     "max_steps": 6, "steps": [{"index": 1, "order": {"goal": "회귀 테스트 추가"},
                     "result": {"final_state": "PASS", "tests": {"passed": 4, "failed": 0, "total": 4}, "review_verdict": "PASS"}}]})
    class ReadOnlyStore:
        def all(self):
            return copy.deepcopy(rows)
        def load(self, *args):
            pytest.fail("Untrusted mission IDs must never be used as file paths")
        def save(self, *args, **kwargs):
            pytest.fail("The library must not mutate mission records")
    monkeypatch.setattr(d, "MissionStore", ReadOnlyStore)
    return rows


def test_pages_are_stable_and_counts_are_global(library):
    first = d.build_missions_payload(limit=10)
    second = d.build_missions_payload(limit=10, page=2)
    assert first["total"] == 26 and first["pages"] == 3
    ids = [m["mission_id"] for m in first["missions"] + second["missions"]]
    assert len(set(ids)) == 20
    assert ids[:2] == ["MSN-025", "MSN-024"]
    assert first["counts"] == {"all": 26, "DONE": 13, "FAILED": 13}
    assert d.build_missions_payload(page=999, limit=10)["page"] == 3
    assert d.build_missions_payload(limit=999)["limit"] == 50


@pytest.mark.parametrize("query,status,total", [("한글프로젝트", "", 13), ("other", "FAILED", 13),
    ("검색 개선", "FAILED", 0), ("MSN-001", "DONE", 1), ("없는 기록", "", 0)])
def test_combined_search_and_status(library, query, status, total):
    result = d.build_missions_payload(query=query, status=status)
    assert result["total"] == total and result["counts"]["all"] == 26


def test_detail_preserves_goal_and_evidence_without_writes(library, monkeypatch):
    library[0].update(goal="목표" * 500, summary="검증한 내용\n" * 300, base_worktree="/work/result",
                      applied={"status": "blocked", "blocks": ["사용자가 수정한 파일"], "files": []})
    from core import usage
    monkeypatch.setattr(usage, "mission_calls", lambda mid: [{"role": "HEAD", "mission_id": mid}])
    snapshot = copy.deepcopy(library)
    data = d.build_missions_payload(mission_id="MSN-000")
    m = data["mission"]
    assert m["goal"] == library[0]["goal"] and m["summary"] == library[0]["summary"]
    assert m["steps"][0]["tests"] == {"passed": 4, "failed": 0, "total": 4}
    assert m["steps"][0]["review"] == "PASS" and m["apply_state"] == "blocked"
    assert data["calls"][0]["mission_id"] == "MSN-000" and library == snapshot
    assert d.build_missions_payload(mission_id="../../config") == {"mission": None}


def test_http_library_and_invalid_inputs(library, http_server):
    code, raw = request(http_server, "GET", "/ops/missions?q=other&status=FAILED&limit=2")
    data = json.loads(raw)
    assert code == 200 and len(data["missions"]) == 2 and data["total"] == 13
    for query in ("page=nan", "limit=abc", "status=INVALID"):
        assert request(http_server, "GET", "/ops/missions?" + query)[0] == 400
    assert request(http_server, "GET", "/ops/missions?mission_id=missing")[0] == 404
    assert request(http_server, "GET", "/ops/missions", headers={"Origin": "https://evil.example"})[0] == 403


def test_new_assets_keep_static_allowlist_and_csp(http_server):
    for path, marker in (("/missions", "MISSION CONTROL"), ("/missions.js", "openDetail"), ("/missions.css", ".sidebar")):
        code, raw = request(http_server, "GET", path)
        assert code == 200 and marker.encode() in raw
    for path in ("/missions.html", "/missions.js.bak", "/console/missions.html"):
        assert request(http_server, "GET", path)[0] == 404
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", http_server.server_address[1])
    conn.request("GET", "/missions")
    response = conn.getresponse()
    assert "default-src 'self'" in response.getheader("Content-Security-Policy")
    html = response.read().decode()
    assert "style=" not in html and '<script src="/missions.js" defer>' in html
    conn.close()
