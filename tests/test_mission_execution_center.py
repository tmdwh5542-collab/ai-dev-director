"""Execution center: durable launches, concurrency, evidence boundaries, and real resume behavior."""
import copy
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import dashboard_server as d
from core.mission import MissionStore
from core.mission_launch import LaunchStore, LaunchConflict, LaunchBusy, normalize
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "사용자 프로젝트"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    return root


def payload(project, request_id="request-test-001"):
    return {"request_id": request_id, "goal": "기능을 추가하고 테스트해줘", "project_path": str(project), "profile": "standard"}


@pytest.mark.parametrize("changes", [{"request_id": "../x"}, {"request_id": ""}, {"goal": " "}, {"goal": "x" * 8001},
    {"project_path": None}, {"profile": "unlimited"}])
def test_invalid_launch_rejected_without_receipt(project, changes):
    p = {**payload(project), **changes}
    with pytest.raises(ValueError):
        normalize(p)
    assert LaunchStore().get("request-test-001") is None


def test_duplicate_receipt_survives_store_recreation_and_cannot_change_goal(project):
    p = payload(project)
    claimed, receipt = LaunchStore().claim(p)
    assert claimed and receipt["state"] == "planning"
    LaunchStore().finish(p["request_id"], {"status": "started", "mission_id": "MSN-TEST"})
    claimed, duplicate = LaunchStore().claim(p)
    assert not claimed and duplicate["result"]["mission_id"] == "MSN-TEST"
    with pytest.raises(LaunchConflict):
        LaunchStore().claim({**p, "goal": "다른 목표"})


def test_concurrent_duplicate_only_claims_once(project):
    p = payload(project)
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda _: LaunchStore().claim(p)[0], range(6)))
    assert claims.count(True) == 1
    with pytest.raises(LaunchBusy):
        LaunchStore().claim(payload(project, "request-test-002"))


def test_dead_or_reused_owner_is_interrupted_and_never_replayed(project):
    store = LaunchStore(); p = payload(project)
    store.claim(p)
    with store._conn() as conn:
        conn.execute("UPDATE mission_launches SET owner_started=-1 WHERE request_id=?", (p["request_id"],))
    assert LaunchStore().get(p["request_id"])["state"] == "interrupted"
    claimed, receipt = LaunchStore().claim(p)
    assert not claimed and receipt["state"] == "interrupted"
    assert LaunchStore().claim(payload(project, "request-test-002"))[0]


def test_async_launch_locks_head_and_returns_same_receipt_on_retry(env, project, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def launch(path, goal, **kwargs):
        calls.append((path, goal, kwargs))
        started.set()
        assert release.wait(5)
        return {"status": "started", "mission_id": "MSN-ASYNC"}
    monkeypatch.setattr(d, "start_goal_mission", launch)
    # Intercept finish only to know that the worker persisted the terminal result.
    real_finish = LaunchStore.finish
    def finish(self, ident, result):
        real_finish(self, ident, result); finished.set()
    monkeypatch.setattr(LaunchStore, "finish", finish)
    p = payload(project)
    try:
        receipt, code = d.submit_mission_launch(p)
        assert code == 202 and receipt["state"] == "planning" and started.wait(2)
        assert d.submit_mission_launch(p)[1] == 200
        assert d.submit_chat("별도 요청", "other-chat")["status"] == "busy"
        with pytest.raises(LaunchBusy):
            d.submit_mission_launch(payload(project, "request-test-002"))
        with pytest.raises(LaunchConflict):
            d.submit_mission_launch({**p, "goal": "변경된 요청"})
    finally:
        release.set()
    assert finished.wait(3)
    assert LaunchStore().get(p["request_id"])["result"]["mission_id"] == "MSN-ASYNC"
    assert len(calls) == 1 and calls[0][0] == str(project.resolve())
    assert d.submit_mission_launch(p)[1] == 200 and len(calls) == 1


def test_launch_auth_validation_and_read_receipt(env, project, http_server, monkeypatch):
    calls = []
    monkeypatch.setattr(d, "start_goal_mission", lambda *a, **kw: calls.append(a) or {"status": "question", "message": "어떤 화면인가요?"})
    p = payload(project)
    headers = {"Content-Type": "application/json", "X-Solomon-Bridge": "test-token"}
    assert request(http_server, "POST", "/ops/mission-launch", json.dumps(p))[0] == 403
    assert request(http_server, "POST", "/ops/mission-launch", json.dumps(p), {**headers, "Origin": "https://evil.example"})[0] == 403
    assert request(http_server, "POST", "/ops/mission-launch", "[]", headers)[0] == 400
    assert request(http_server, "POST", "/ops/mission-launch", "x" * 64001, headers)[0] == 400
    code, body = request(http_server, "POST", "/ops/mission-launch", json.dumps(p), headers)
    assert code == 202 and json.loads(body)["request_id"] == p["request_id"]
    code, body = request(http_server, "GET", "/ops/mission-launch?request_id=" + p["request_id"])
    assert code == 200 and json.loads(body)["state"] in ("planning", "question")
    assert request(http_server, "GET", "/ops/mission-launch?request_id=unknown")[0] == 404
    assert request(http_server, "POST", "/ops/mission-launch", json.dumps(p), headers)[0] == 200
    assert len(calls) == 1


@pytest.fixture
def evidence(env, tmp_path, monkeypatch):
    root = tmp_path / "director"
    run = root / "runs" / "RUN-EVIDENCE"
    run.mkdir(parents=True)
    record = {"mission_id": "MSN-EVIDENCE", "project_path": "/work/project", "status": "FAILED", "steps": [{"index": 1, "run_id": "RUN-EVIDENCE"}]}
    monkeypatch.setattr(d, "DIRECTOR_ROOT", root)
    monkeypatch.setattr(d, "MissionStore", lambda: type("Store", (), {"all": lambda self: [copy.deepcopy(record)]})())
    return run, record


def test_step_exposes_bounded_real_failure_and_review(evidence, http_server):
    run, _ = evidence
    (run / "verification.json").write_text(json.dumps({"test": {"command": "python -m pytest", "executed": True,
        "passed": False, "exit_code": 1, "output": "x" * 15000 + "assert 12 == 8"}, "git_diff": "+fixed\n" * 4000}))
    (run / "review.json").write_text(json.dumps({"verdict": "changes_required", "p1": ["잘못된 계산"], "p2": [], "summary": "수정 필요"}))
    code, raw = request(http_server, "GET", "/ops/mission-step?mission_id=MSN-EVIDENCE&index=1")
    data = json.loads(raw)
    assert code == 200 and data["available"]
    cmd = data["commands"][0]
    assert not cmd["passed"] and cmd["exit_code"] == 1 and cmd["truncated"]
    assert len(cmd["output"]) == 12000 and cmd["output"].endswith("assert 12 == 8")
    assert data["review"]["p1"] == ["잘못된 계산"] and len(data["diff"]) == 16000
    assert request(http_server, "GET", "/ops/mission-step?mission_id=../../config&index=1")[0] == 404
    assert request(http_server, "GET", "/ops/mission-step?mission_id=MSN-EVIDENCE&index=nan")[0] == 400


def test_evidence_never_follows_outside_symlinks_or_oversized_json(evidence, tmp_path):
    run, record = evidence
    secret = tmp_path / "secret.json"; secret.write_text('{"summary":"DO NOT READ"}')
    try:
        (run / "review.json").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")
    (run / "verification.json").write_bytes(b" " * (512 * 1024 + 1))
    data = d.build_mission_step_payload("MSN-EVIDENCE", 1)
    assert not data["available"] and data["review"] is None
    record["steps"][0]["run_id"] = "../../secret"
    assert not d.build_mission_step_payload("MSN-EVIDENCE", 1)["available"]


def test_resume_stale_running_and_replan_exhausted_budget(env, project, tmp_path, monkeypatch):
    store = MissionStore(tmp_path / "missions")
    m = {"mission_id": "MSN-RESUME", "project_path": str(project), "status": "RUNNING", "owner_pid": None,
         "max_steps": 1, "steps": [{"index": 1, "result": {"final_state": "FAIL"}}]}
    store.save(m)
    calls = []
    monkeypatch.setattr(d, "MissionStore", lambda: store)
    monkeypatch.setattr(d, "_ACTIVE_PROJECTS", {})
    monkeypatch.setattr(d, "_run_mission_thread", lambda *a, **kw: calls.append((a, kw)))
    result = d.decide_mission(m["mission_id"], "resume")
    assert result["status"] == "resumed" and result["max_steps"] == 3 and calls[0][1]["reopen"]
    d._ACTIVE_PROJECTS.clear()
    m.update(status="FAILED", max_steps=1); store.save(m, force=True)
    result = d.decide_mission(m["mission_id"], "replan", reason="먼저 모바일 오류 수정")
    assert result["status"] == "resumed" and result["max_steps"] == 3
    assert store.load(m["mission_id"])["steps"][-1]["operator_replan"] == "먼저 모바일 오류 수정"
    d._ACTIVE_PROJECTS.clear()
    m.update(status="DONE"); store.save(m, force=True)
    assert d.decide_mission(m["mission_id"], "extend")["status"] == "error"


def test_control_needs_token_rejects_running_apply_and_keeps_conflicts(env, project, tmp_path, http_server, monkeypatch):
    store = MissionStore(tmp_path / "missions")
    m = {"mission_id": "MSN-CONTROL", "project_path": str(project), "status": "RUNNING", "owner_pid": os.getpid(), "steps": [{"index": 1}]}
    store.save(m)
    monkeypatch.setattr(d, "MissionStore", lambda: store)
    calls = []
    monkeypatch.setattr(d, "decide_mission", lambda *a, **kw: calls.append((a, kw)) or {"status": "blocked", "blocks": ["user edit"]})
    p = json.dumps({"mission_id": m["mission_id"], "action": "apply"})
    headers = {"Content-Type": "application/json", "X-Solomon-Bridge": "test-token"}
    assert request(http_server, "POST", "/ops/mission-control", p)[0] == 403
    assert request(http_server, "POST", "/ops/mission-control", p, headers)[0] == 409
    assert calls == []
    m["status"] = "FAILED"; store.save(m, force=True)
    assert request(http_server, "POST", "/ops/mission-control", p, headers)[0] == 200
    assert calls[0][1]["on_conflict"] == "block"


def test_project_choices_are_readonly_and_exclude_unprepared_or_director(env, project, tmp_path, monkeypatch):
    from core.chat_manager import ChatManager
    ChatManager().set_project(d.active_session_id(), str(project))
    empty = tmp_path / "untouched"; empty.mkdir()
    monkeypatch.setattr(d, "load_config", lambda: {"projects": {str(empty): {}, str(project): {}, str(d.DIRECTOR_ROOT): {}}})
    result = d.build_project_choices()
    assert result["current"] == str(project)
    assert result["projects"] == [{"path": str(project.resolve()), "name": project.name}]
    assert not (empty / ".git").exists()


def test_thread_start_failure_is_recorded_and_releases_head(env, project, monkeypatch):
    from types import SimpleNamespace
    class BrokenThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError("thread unavailable")
    monkeypatch.setattr(d, "threading", SimpleNamespace(Thread=BrokenThread))
    p = payload(project)
    with pytest.raises(RuntimeError, match="thread unavailable"):
        d.submit_mission_launch(p)
    assert LaunchStore().get(p["request_id"])["state"] == "error"
    assert not d.chat_in_flight()


def test_zombie_owner_does_not_keep_request_planning_forever(project, monkeypatch):
    from types import SimpleNamespace
    from core import mission_launch
    p = payload(project)
    LaunchStore().claim(p)
    monkeypatch.setattr(mission_launch.psutil, "Process", lambda pid: SimpleNamespace(status=lambda: mission_launch.psutil.STATUS_ZOMBIE))
    assert LaunchStore().get(p["request_id"])["state"] == "interrupted"
