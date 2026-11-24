"""Disposable UI fixture server. No real CLI calls, credentials, or production DB.

Used by mission_center.cjs, not a production launcher.
"""
import json
import os
import sys
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["DIRECTOR_TESTING"] = "1"
# Caller supplies an isolated temporary directory.
os.environ["TEST_DB_PATH"] = str(Path(sys.argv[1]) / "director.db")

import dashboard_server as d
from companion_server import CompanionHandler
from core.mission import MissionStore
from core import usage

d._ensure_schema()
# Most UI scenarios deliberately edit their own roster; mark those fixtures as initialized.
# The automatic-roster scenario sets DIRECTOR_UI_AUTO_ROSTER=1 and exercises real first-run behavior.
if os.environ.get('DIRECTOR_UI_AUTO_ROSTER') != '1':
    from core import company, staffing
    original_company_save = company.save
    def fixture_company_save(*args, **kwargs):
        original_company_save(*args, **kwargs)
        team = staffing.current()
        staffing.save(team, team['revision'], roster_initialized=True)
        return company.current()
    company.save = fixture_company_save
if os.environ.get('DIRECTOR_UI_LEGACY_COMPANY') == '1':
    from core import staffing, company
    staffing.save(staffing.validate({'members': []},require_ready=False) if os.environ.get('DIRECTOR_UI_EMPTY_COMPANY')=='1' else staffing.default_team(),staffing.current()['revision'])
    company.save({'owner':{'name':'테스트 대표','character':{'gender':'male','age':35,'color':'gold'}},'theme':'corporate','visual_mode':'cozy' if os.environ.get('DIRECTOR_UI_COZY')=='1' else 'illustrated' if os.environ.get('DIRECTOR_UI_ILLUSTRATED')=='1' else 'pixel'},company.current()['revision'])
runtime = Path(sys.argv[1]) / "runtime"
runtime.mkdir()
d.DIRECTOR_ROOT = runtime
projects = [Path(sys.argv[1]) / name for name in ("director-dashboard", "task-manager")]
for project in projects:
    project.mkdir()
    subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
(projects[0] / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.0'\n")
cm = d.ChatManager()
cm.create_session(d.GLOBAL_SESSION_ID, str(projects[0]), "ANTHROPIC")
store = MissionStore()
goals = ["대시보드에 상태별 필터와 검색 추가", "로그인 오류 재현 및 회귀 테스트", "모바일 화면 레이아웃 개선",
         "프로젝트 설정 저장 기능 추가", "사용자 입력 검증 강화", "보고서 내보내기 구현", "알림 화면 접근성 개선",
         "작업 중단 후 재개 동작 점검", "API 오류 메시지 개선", "미션 기록 검색 최적화", "설치 안내 문서 정리",
         "파일 충돌 처리 검증", "<img src=x onerror=window.injected=true>"]
statuses = ["RUNNING", "DONE", "DONE", "BLOCKED", "FAILED", "DONE", "INCOMPLETE", "STOPPED", "DONE", "DONE", "DONE", "FAILED", "DONE"]
for i, (goal, status) in enumerate(zip(goals, statuses)):
    mission = {"mission_id": f"MSN-UI-{i:02}", "goal": goal, "status": status,
               "project_path": str(projects[i % 2]),
               "max_steps": 6, "owner_pid": os.getpid() if status == "RUNNING" else None,
               "steps": [{"index": 1, "order": {"goal": "분석하고 회귀 테스트를 추가합니다"}, "result": {
                   "final_state": "PASS", "tests": {"passed": 12, "failed": 0, "total": 12},
                   "review_verdict": "PASS", "repair_rounds": 1}}],
               "summary": "요구사항에 맞춰 구현하고 테스트를 통과했습니다. 결과물의 적용 상태를 확인하세요.",
               "base_worktree": "/projects/.director_worktrees/verified-result" if status == "DONE" else None,
               "applied": {"status": "applied", "files": ["src/dashboard.py", "tests/test_dashboard.py"]} if status == "DONE" and i != 1 else None,
               "blocked_reason": "외부 서비스의 계정 설정을 확인해야 합니다." if status == "BLOCKED" else None,
               "created_at": "2026-11-01T10:00:00", "updated_at": f"2026-11-{13-i:02}T08:30:00"}
    if i == 4:
        step = mission["steps"][0]
        step["run_id"] = "RUN-UI-04"
        step["result"].update(final_state="FAIL", tests={"passed": 11, "failed": 1, "total": 12}, review_verdict="CHANGES_REQUIRED")
        evidence = runtime / "runs" / step["run_id"]
        evidence.mkdir(parents=True)
        (evidence / "verification.json").write_text(json.dumps({"test": {"executed": True, "command": "python -m pytest tests/", "passed": False, "exit_code": 1,
            "output": "FAILED tests/test_input.py::test_empty_input\nAssertionError: 빈 입력이 허용됨\n<img src=x onerror=window.injected=true>"},
            "git_diff": "--- a/src/input.py\n+++ b/src/input.py\n@@ -1 +1 @@\n-return value\n+return value.strip()\n"}), encoding="utf-8")
        (evidence / "review.json").write_text(json.dumps({"verdict": "changes_required", "summary": "빈 입력 처리에 수정이 필요합니다.", "p1": ["공백 입력도 거부해야 합니다."], "p2": []}), encoding="utf-8")
    # Write explicitly ordered fixture dates; MissionStore.save intentionally updates timestamps.
    store.base.mkdir(parents=True, exist_ok=True)
    (store.base / (mission["mission_id"] + ".json")).write_text(json.dumps(mission, ensure_ascii=False), encoding="utf-8")
    usage.set_context(role="REVIEWER", stage="REVIEWING", mission_id=mission["mission_id"])
    rid = usage.call_started(["codex"], "fixture prompt")
    usage.call_finished(rid, ["codex"], "fixture prompt", SimpleNamespace(stdout="tokens used: 1200", stderr="", duration_sec=8, exit_code=0, timed_out=False))

# Explicit fixture states. No login/health probes or AI jobs are needed for UI checks.
d.cached_status_payload = lambda: {"project_name": Path(cm.get_session(d.active_session_id())["project_path"]).name,
    "project_path": cm.get_session(d.active_session_id())["project_path"],
    "providers": {"ANTHROPIC": {"role": "HEAD", "status": "HEALTHY"},
                  "GOOGLE": {"role": "BUILDER", "status": "UNKNOWN"},
                  "OPENAI": {"role": "REVIEWER", "status": "HEALTHY"}},
    "system_mode_hint": "프로젝트가 선택되어 있습니다. 새 미션을 준비할 수 있습니다."}

def fixture_launch(project_path, goal, profile=None, workflow_id="auto", use_project_memory=True, **kwargs):
    from core import workflows
    selected = workflows.resolve_workflow(workflow_id, goal)
    snapshot = workflows.snapshot(workflows.enrich_context({}, project_path, selected, use_project_memory), use_project_memory)
    if "계획 대기" in goal:
        time.sleep(1.5)
    if "확인 질문" in goal:
        return {"status": "question", "message": "어떤 화면을 먼저 개선할까요?"}
    if "시작 거절" in goal:
        return {"status": "rejected", "error": "테스트용 시작 거절"}
    mission = {"mission_id": "MSN-LAUNCHED-" + uuid.uuid4().hex[:8], "goal": goal,
               "project_path": project_path, "status": "DONE", "profile": profile,
               "max_steps": 2, "steps": [], "summary": "테스트용 실행 결과", "owner_pid": None}
    mission.update(snapshot)
    store.save(mission)
    return {"status": "started", "mission_id": mission["mission_id"], "profile": profile, "project_path": project_path,
            "workflow_id": selected, "memory_sources": snapshot["memory_sources"]}

def fixture_resume(sid, mission_id, key, reopen=False):
    mission = store.load(mission_id)
    mission.update(status="RUNNING", owner_pid=os.getpid())
    store.save(mission, force=True)
    d._ACTIVE_PROJECTS.pop(key, None)

if os.environ.get('DIRECTOR_UI_DEVICE_CHAT') == '1':
    def fixture_device_chat(message):
        sid=d.active_session_id();cm.add_message(sid,'USER',message);time.sleep(.2)
        cm.add_message(sid,'HEAD','검증 응답: '+message)
    d.handle_chat_message=fixture_device_chat

# Explicit test-only Hermes engine shim: exercise the real queue/ledger/approval flow without SDK billing.
if os.environ.get('DIRECTOR_UI_HERMES') == '1':
    from core import hermes_agent as h
    os.environ['DIRECTOR_UI_HERMES_KEY']='fixture-hermes-secret'
    real_hermes_run=h.run
    def fixture_hermes_runner(*args,**kwargs):
        request=Path(args[0][args[0].index('--request')+1])
        payload=json.loads(request.read_text(encoding='utf-8'))
        time.sleep(3 if '중지검수' in payload['prompt'] else .35)
        output={'protocol':'director-hermes-sdk-v1','ok':True,'version':'UI fixture SDK · 모의 응답',
                'text':json.dumps({'summary':'시연용 분석 보고서 <img src=x onerror=window.injected=true>',
                                   'recommendations':['기존 게임 목표 안에서 조작 안내를 보완합니다.'],'questions':['입력 장치를 확인해주세요.']},ensure_ascii=False),
                'usage':{'api_calls':1,'total_tokens':120}}
        return SimpleNamespace(stdout=json.dumps(output),stderr='',exit_code=0,duration_sec=.35,timed_out=False,pid=0)
    h.run=lambda ident:real_hermes_run(ident,fixture_hermes_runner)
    def fixture_hermes_probe():
        h._write(h.settings_path().with_name('hermes_probe.json'),{'python_path':h.settings()['python_path'],'source_root':h.settings()['source_root'],'ok':True,'version':'UI fixture SDK · 모의 점검'})
        return h.public()
    h.probe=fixture_hermes_probe

if os.environ.get('DIRECTOR_UI_AUTOMATION') == '1':
    from core import youtube_channel
    real_youtube_public=youtube_channel.public
    def fixture_youtube_public():
        return {**real_youtube_public(),'connected':True,'channel':{'id':'UC-fixture-channel','title':'UI 전용 모의 채널'},'login_message':'UI fixture · 모의 채널, 실제 Google 연결 없음'}
    youtube_channel.public=fixture_youtube_public

d.start_goal_mission = fixture_launch
d._run_mission_thread = fixture_resume
server = d.DashboardServer(("127.0.0.1", 0), CompanionHandler)
server.bridge_token = "ui-test-token"
server.bridge = SimpleNamespace(list=lambda: [])
print(server.server_address[1], flush=True)
server.serve_forever()
