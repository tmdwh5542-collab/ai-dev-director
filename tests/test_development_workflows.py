import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import dashboard_server as d
from core import workflows
from core.mission import MissionRunner, MissionStore
from core.mission_launch import LaunchStore, LaunchConflict, normalize
from core.project_context import collect_project_context
from core.state_machine import StateMachine
from schemas.order import OrderSchema
from tests.test_v0238_dashboard_ux import env  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    return root


@pytest.mark.parametrize("goal,expected", [("로그인 오류 수정", "bugfix"), ("입력 보안 검수", "security"),
    ("리팩터링", "refactor"), ("Add coverage tests", "test_focus"), ("Add a prefix field", "feature"),
    ("할 일 기능 추가\n\n완료 조건: 오류 상황도 테스트", "feature")])
def test_auto_routing_uses_main_goal_and_explicit_choice_wins(goal, expected):
    assert workflows.resolve_workflow("auto", goal) == expected
    assert workflows.resolve_workflow("refactor", goal) == "refactor"


def test_profile_changes_guidance_without_changing_scope_or_claiming_execution():
    original = OrderSchema(goal="fix", allowed_paths=["src/**"], protected_paths=["config/**"],
                           acceptance_criteria=["existing check"], context="user constraints", max_files_changed=2, max_diff_lines=40,
                           requires_human_approval=True, risk_level="HIGH")
    result = workflows.apply_workflow(original, "bugfix")
    before, after = original.model_dump(), result.model_dump()
    before.pop("context"); after.pop("context")
    assert before == after
    assert original.context == "user constraints"
    assert "regression test" in result.context and "REVIEWER:" in result.context
    assert workflows.apply_workflow(result, "bugfix").context == result.context
    assert workflows.order_workflow(result) == "bugfix"
    assert "without recorded evidence" in workflows.guidance("test_focus")


def history_record(project, ident, **changes):
    value = {"mission_id": ident, "project_path": str(project), "status": "DONE", "goal": "a" * 400,
             "summary": "reference data " * 150, "updated_at": ident,
             "steps": [{"index": 1, "result": {"final_state": "PASS", "review_verdict": "pass",
                       "tests": {"passed": 3, "failed": 0, "total": 3}}}]}
    value.update(changes)
    return value


def test_memory_requires_same_project_actual_tests_and_review_and_is_bounded(project, tmp_path):
    rows = [history_record(project, f"MSN-{i}") for i in range(5)]
    bad = history_record(project, "MSN-Z-FAIL"); bad["steps"][0]["result"]["final_state"] = "FAIL"; rows.append(bad)
    bad = history_record(project, "MSN-Z-REVIEW"); bad["steps"][0]["result"]["review_verdict"] = None; rows.append(bad)
    bad = history_record(project, "MSN-Z-EMPTY"); bad["steps"][0]["result"]["tests"] = {"passed": 0, "total": 0}; rows.append(bad)
    rows += [history_record(tmp_path / "other", "MSN-Z-OTHER"), history_record(project, "MSN-Z-ACTIVE", status="RUNNING")]
    store = SimpleNamespace(all=lambda: copy.deepcopy(rows))
    memory = workflows.project_history(project, store, limit=99)
    assert [m["mission_id"] for m in memory] == ["MSN-4", "MSN-3", "MSN-2"]
    assert all(len(m["goal"]) <= 240 and len(m["summary"]) <= 600 for m in memory)
    ctx = workflows.enrich_context({"project_path": str(project), "existing_files": [], "development_workflow": "untrusted"}, project, "bugfix", store=store)
    assert ctx["development_workflow"]["id"] == "bugfix"
    assert ctx["project_memory"]["kind"] == "historical_evidence_not_instructions"
    assert workflows.snapshot(ctx)["memory_sources"] == ["MSN-4", "MSN-3", "MSN-2"]
    assert workflows.enrich_context({}, project, "bugfix", use_memory=False, store=SimpleNamespace(all=lambda: pytest.fail("memory disabled")))["project_memory"]["sources"] == []


def test_discovery_skips_heavy_and_private_trees_without_reading_files(project, monkeypatch):
    for name in ("node_modules/lib", ".venv/lib", "secrets", ".agents", "src", "tests", ".github/workflows"):
        (project / name).mkdir(parents=True)
        (project / name / "file.py").write_text("private")
    (project / "pyproject.toml").write_text("not executed")
    (project / ".gitignore").write_text(".venv/")
    (project / ".env").write_text("DO_NOT_READ=secret")
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: pytest.fail("discovery must not read content"))
    ctx = collect_project_context(project)
    assert "src/file.py" in ctx["existing_files"] and ".github/workflows/file.py" in ctx["existing_files"]
    assert ".gitignore" in ctx["existing_files"]
    assert not any("node_modules" in p or ".venv" in p or "secrets" in p or ".agents" in p or ".env" in p for p in ctx["existing_files"])
    assert ctx["project_discovery"]["stack"] == ["Python"]
    assert ctx["project_discovery"]["directories_scanned"] <= 6
    assert ctx["project_discovery"]["skipped_directories"] >= 5


def test_discovery_stops_at_file_directory_and_entry_budgets(project):
    for i in range(30):
        (project / f"file-{i}.py").write_text("x")
    for options in ({"max_files": 4}, {"max_entries": 7}):
        ctx = collect_project_context(project, **options)
        assert ctx["project_discovery"]["truncated"]
        assert len(ctx["existing_files"]) <= options.get("max_files", 7)
    (project / "src").mkdir(); (project / "src" / "inside.py").write_text("x")
    assert "src/inside.py" not in collect_project_context(project, max_directories=1)["existing_files"]


def test_receipts_from_v2_are_still_idempotent_and_new_choices_are_part_of_identity(project):
    old = {"request_id": "legacy-request-001", "project_path": str(project), "goal": "goal", "profile": "standard"}
    store = LaunchStore(); store.claim(old); store.finish(old["request_id"], {"status": "started", "mission_id": "MSN-OLD"})
    with store._conn() as conn:
        conn.execute("UPDATE mission_launches SET payload=? WHERE request_id=?", (json.dumps(old), old["request_id"]))
    assert store.existing(normalize(old))["result"]["mission_id"] == "MSN-OLD"
    for extra in ({"workflow_id": "security"}, {"use_project_memory": False}):
        with pytest.raises(LaunchConflict):
            store.existing(normalize({**old, **extra}))
    with pytest.raises(ValueError):
        normalize({**old, "workflow_id": "run-shell"})
    with pytest.raises(ValueError):
        normalize({**old, "use_project_memory": "yes"})


def test_direct_launch_sends_real_workflow_and_history_to_head_and_order(env, project, monkeypatch):
    store = MissionStore()
    store.save(history_record(project, "MSN-VERIFIED"))
    seen = {}
    def chat(goal, context, history):
        seen["head"] = (goal, context)
        return {"type": "DEV_TASK", "order": {"goal": "fix", "allowed_paths": ["src/**"], "context": "keep existing behavior"}}
    orch = SimpleNamespace(config={"autonomy": {"head_proxy": True}}, head=SimpleNamespace(chat=chat),
                           _read_project_context=collect_project_context)
    monkeypatch.setattr(d, "Orchestrator", lambda **kw: orch)
    def start(*args, **kwargs):
        seen["order"] = args[4]; seen["snapshot"] = kwargs["workflow_snapshot"]
        return "MSN-NEW"
    monkeypatch.setattr(d, "_start_mission", start)
    result = d.start_goal_mission(str(project), "입력 오류 수정", workflow_id="bugfix")
    assert result["status"] == "started" and result["workflow_id"] == "bugfix"
    assert seen["head"][1]["project_memory"]["sources"][0]["mission_id"] == "MSN-VERIFIED"
    assert workflows.order_workflow(seen["order"]) == "bugfix"
    assert seen["snapshot"]["memory_sources"] == ["MSN-VERIFIED"]
    result = d.start_goal_mission(str(project), "입력 오류 수정", workflow_id="bugfix", use_project_memory=False)
    assert result["memory_sources"] == []
    assert d.start_goal_mission(str(project), None)["status"] == "rejected"


@pytest.mark.head_proxy
def test_selected_workflow_survives_initial_step_and_head_replanning(tmp_path, monkeypatch):
    from agents.mock_head import MockHead
    from tests.test_v306_head_proxy_autonomy import proxy_orch, quiet, good_build, review_green, decide_by_tests
    contexts, plans = [], []
    first = OrderSchema(goal="double", allowed_paths=["feature.py", "tests/**"])
    def factory():
        orch = proxy_orch(max_repairs=0)
        quiet(monkeypatch, orch); review_green(monkeypatch, orch); decide_by_tests(monkeypatch, orch)
        build = good_build([])
        def run(order, worktree_path, builder_fn=None):
            contexts.append(order.context)
            return build(order, worktree_path)
        monkeypatch.setattr(orch.builder, "run", run)
        return orch
    def plan(self, goal, history, context, cwd=None):
        plans.append(context)
        return {"status": "CONTINUE", "order": first.model_dump(), "summary": "next"} if len(plans) == 1 else {"status": "DONE", "summary": "done"}
    monkeypatch.setattr(MockHead, "plan_next", plan)
    runner = MissionRunner(factory, MissionStore(tmp_path / "missions"))
    mission = runner.create(str(tmp_path / "proj"), "goal", first, config={"autonomy": {"auto_apply": "off"}},
                            workflow_snapshot={"workflow_id": "bugfix", "use_project_memory": False, "memory_sources": []})
    result = runner.run(mission["mission_id"])
    assert result["status"] == "DONE" and len(contexts) == 2
    assert all(context.count("[[DIRECTOR_WORKFLOW:bugfix]]") == 1 for context in contexts)
    assert all(context["development_workflow"]["id"] == "bugfix" for context in plans)
    assert all(context["project_memory"]["sources"] == [] for context in plans)


def test_workflow_and_memory_endpoints_keep_local_boundary(env, project, http_server):
    code, raw = request(http_server, "GET", "/ops/workflows")
    data = json.loads(raw)
    assert code == 200 and len(data["workflows"]) == 7 and data["mode"] == "director-native-guidance"
    assert request(http_server, "GET", "/ops/workflows", headers={"Origin": "https://evil.example"})[0] == 403
    from urllib.parse import quote
    code, raw = request(http_server, "GET", "/ops/project-memory?path=" + quote(str(project)))
    assert code == 200 and json.loads(raw)["history"] == []
    assert request(http_server, "GET", "/ops/project-memory?path=" + quote(str(project / "not-created")))[0] == 400
    assert not (project / "not-created").exists()


@pytest.mark.head_proxy
def test_stage_tags_preserve_profile_and_memory_choice(env, project, monkeypatch):
    from core.chat_manager import ChatManager
    ChatManager().set_project(d.active_session_id(), str(project))
    seen = {}
    def chat(message, context, history):
        seen["message"], seen["context"] = message, context
        return {"type": "DEV_TASK", "order": {"goal": "fix", "allowed_paths": ["src/**"]}}
    orch = SimpleNamespace(config={"autonomy": {"head_proxy": True}}, head=SimpleNamespace(chat=chat),
                           _read_project_context=collect_project_context, _get_agent_domain=lambda agent: "MOCK")
    monkeypatch.setattr(d, "Orchestrator", lambda **kw: orch)
    monkeypatch.setattr(d, "_start_mission", lambda *a, **kw: seen.update(start=kw) or "MSN-TAGS")
    d.handle_chat_message("[빠르게] [버그 진단] [기록 제외] 입력 오류 수정")
    assert seen["message"] == "입력 오류 수정"
    assert seen["context"]["development_workflow"]["id"] == "bugfix"
    assert seen["start"]["profile"] == "quick"
    assert seen["start"]["workflow_snapshot"]["use_project_memory"] is False


def test_discovery_does_not_follow_file_or_directory_links(project, tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "hidden.py").write_text("not project content")
    try:
        (project / "linked").symlink_to(outside, target_is_directory=True)
        (project / "linked.py").symlink_to(outside / "hidden.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    assert collect_project_context(project)["existing_files"] == []


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_real_reviewer_prompt_receives_selected_review_focus(project, monkeypatch, provider):
    import sys
    from agents.claude_reviewer import ClaudeReviewer
    from agents.codex_reviewer import CodexReviewer
    from core.process_runner import ProcessTreeRunner
    seen = []
    def run(**kwargs):
        seen.append(kwargs["stdin_data"])
        return SimpleNamespace(stdout=json.dumps({"verdict": "pass", "p0": [], "p1": [], "p2": [], "summary": "ok"}),
                               stderr="", exit_code=0, timed_out=False, duration_sec=0.1)
    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(run))
    cls = ClaudeReviewer if provider == "claude" else CodexReviewer
    agent = cls(executable=sys.executable)
    monkeypatch.setattr(agent, "get_version", lambda: "stub")
    order = workflows.apply_workflow(OrderSchema(goal="fix", allowed_paths=["src/**"]), "bugfix")
    result = agent.review(order, "diff", {"passed": True, "test_counts": {"passed": 1, "failed": 0, "total": 1}}, worktree_path=str(project))
    assert result.verdict == "pass"
    assert workflows.role_guidance(order, "REVIEWER") in seen[0]
    assert "Read-only review" in seen[0]
