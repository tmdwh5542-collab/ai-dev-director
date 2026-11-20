"""Durable receipts for mission launch requests; a reconnect must never submit the same goal twice."""
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import psutil

from core.db_path import get_db_path


class LaunchConflict(ValueError):
    pass


class LaunchBusy(RuntimeError):
    pass


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError("요청은 JSON 객체여야 합니다")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
        raise ValueError("올바른 요청 ID가 필요합니다")
    project = payload.get("project_path")
    goal = payload.get("goal")
    profile = payload.get("profile", "standard")
    from core.workflows import validate_workflow
    workflow_id = validate_workflow(payload.get("workflow_id", "auto"))
    use_memory = payload.get("use_project_memory", True)
    if not isinstance(use_memory, bool):
        raise ValueError("프로젝트 기록 사용 여부가 올바르지 않습니다")
    if not isinstance(project, str) or not project.strip() or len(project) > 4096:
        raise ValueError("프로젝트 경로가 필요합니다")
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 8000:
        raise ValueError("작업 목표는 1~8000자여야 합니다")
    if profile not in ("quick", "standard", "deep"):
        raise ValueError("올바른 작업 규모를 선택하세요")
    return {"request_id": request_id, "project_path": project.strip(), "goal": goal.strip(), "profile": profile,
            "workflow_id": workflow_id, "use_project_memory": use_memory}


class LaunchStore:
    @contextmanager
    def _conn(self):
        path = get_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS mission_launches (
            request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
            owner_pid INTEGER, owner_started REAL, result TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS mission_launch_one_planner
                        ON mission_launches ((1)) WHERE state='planning'""")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _recover(conn):
        for row in conn.execute("SELECT request_id, owner_pid, owner_started FROM mission_launches WHERE state='planning'").fetchall():
            try:
                owner = psutil.Process(row["owner_pid"])
                alive = owner.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD) and owner.create_time() == row["owner_started"]
            except (psutil.Error, TypeError, ValueError):
                alive = False
            if not alive:
                conn.execute("UPDATE mission_launches SET state='interrupted', updated_at=? WHERE request_id=?",
                             (datetime.utcnow().isoformat(), row["request_id"]))

    @staticmethod
    def _view(row):
        if row is None:
            return None
        payload = json.loads(row["payload"])
        return {"request_id": row["request_id"], "state": row["state"],
                "project_path": payload["project_path"], "profile": payload["profile"],
                "workflow_id": payload.get("workflow_id", "auto"), "use_project_memory": payload.get("use_project_memory", True),
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "result": json.loads(row["result"]) if row["result"] else None}

    def get(self, request_id):
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._recover(conn)
            return self._view(conn.execute("SELECT * FROM mission_launches WHERE request_id=?", (request_id,)).fetchone())

    def existing(self, payload):
        """Check identity even when HEAD is busy. A reused ID with a different goal is a conflict."""
        encoded = json.dumps(normalize(payload), ensure_ascii=False, sort_keys=True)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._recover(conn)
            row = conn.execute("SELECT * FROM mission_launches WHERE request_id=?", (payload["request_id"],)).fetchone()
            if row and json.dumps(normalize(json.loads(row["payload"])), ensure_ascii=False, sort_keys=True) != encoded:
                raise LaunchConflict("같은 요청 ID로 다른 작업을 제출할 수 없습니다")
            return self._view(row)

    def claim(self, payload):
        encoded = json.dumps(normalize(payload), ensure_ascii=False, sort_keys=True)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._recover(conn)
            row = conn.execute("SELECT * FROM mission_launches WHERE request_id=?", (payload["request_id"],)).fetchone()
            if row:
                if json.dumps(normalize(json.loads(row["payload"])), ensure_ascii=False, sort_keys=True) != encoded:
                    raise LaunchConflict("같은 요청 ID로 다른 작업을 제출할 수 없습니다")
                return False, self._view(row)
            if conn.execute("SELECT 1 FROM mission_launches WHERE state='planning'").fetchone():
                raise LaunchBusy("다른 미션의 요청을 처리하고 있습니다")
            now = datetime.utcnow().isoformat()
            conn.execute("INSERT INTO mission_launches VALUES (?, ?, 'planning', ?, ?, NULL, ?, ?)",
                         (payload["request_id"], encoded, os.getpid(), psutil.Process().create_time(), now, now))
            return True, self._view(conn.execute("SELECT * FROM mission_launches WHERE request_id=?", (payload["request_id"],)).fetchone())

    def finish(self, request_id, result):
        state = result.get("status", "error")
        if state not in ("started", "question", "escalated", "rejected", "busy", "error"):
            result = {"status": "error", "error": "작업 시작 결과를 확인할 수 없습니다"}
            state = "error"
        with self._conn() as conn:
            conn.execute("UPDATE mission_launches SET state=?, result=?, updated_at=? WHERE request_id=? AND state='planning'",
                         (state, json.dumps(result, ensure_ascii=False), datetime.utcnow().isoformat(), request_id))
