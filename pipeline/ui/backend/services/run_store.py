"""
Run Store — SQLite-backed persistence for pipeline run metadata.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_DB_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", str(Path(__file__).resolve().parent.parent)))
_DB_PATH = _DB_DIR / "runs.db"
_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    """Thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL DEFAULT 'extraction',
            status      TEXT NOT NULL DEFAULT 'pending',
            domain      TEXT,
            provider    TEXT,
            model       TEXT,
            config_json TEXT,
            documents   TEXT,
            result_json TEXT,
            error       TEXT,
            pid         INTEGER,
            log_file    TEXT,
            started_at  TEXT,
            finished_at TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Migrate existing installs that pre-date the pid / log_file columns
    for col, typedef in [("pid", "INTEGER"), ("log_file", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {typedef}")
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_steps (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id   TEXT NOT NULL REFERENCES runs(id),
            step     TEXT NOT NULL,
            status   TEXT NOT NULL DEFAULT 'pending',
            detail   TEXT,
            started_at  TEXT,
            finished_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_logs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id   TEXT NOT NULL REFERENCES runs(id),
            ts       TEXT NOT NULL DEFAULT (datetime('now')),
            level    TEXT NOT NULL DEFAULT 'INFO',
            message  TEXT NOT NULL
        )
    """)
    conn.commit()


# ── CRUD helpers ──

def create_run(run_id: str, *, run_type: str = "extraction", domain: str = None,
               provider: str = None, model: str = None,
               config: dict = None, documents: list = None) -> dict:
    conn = _get_conn()
    now = _now()
    conn.execute(
        """INSERT INTO runs (id, type, status, domain, provider, model, config_json, documents, started_at, created_at)
           VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, run_type, domain, provider, model,
         json.dumps(config or {}), json.dumps(documents or []), now, now),
    )
    conn.commit()
    return get_run(run_id)


def get_run(run_id: str) -> Optional[dict]:
    row = _get_conn().execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.pop("config_json") or "{}")
    d["documents"] = json.loads(d.pop("documents") or "[]")
    d["result"] = json.loads(d.pop("result_json") or "null")
    return d


def list_runs(run_type: str = None, limit: int = 50) -> List[dict]:
    q = "SELECT * FROM runs"
    params: list = []
    if run_type:
        q += " WHERE type = ?"
        params.append(run_type)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = _get_conn().execute(q, params).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["config"] = json.loads(d.pop("config_json") or "{}")
        d["documents"] = json.loads(d.pop("documents") or "[]")
        d["result"] = json.loads(d.pop("result_json") or "null")
        results.append(d)
    return results


def list_running_runs() -> List[dict]:
    """Return all runs currently in 'running' status."""
    rows = _get_conn().execute(
        "SELECT * FROM runs WHERE status = 'running' ORDER BY created_at DESC"
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["config"] = json.loads(d.pop("config_json") or "{}")
        d["documents"] = json.loads(d.pop("documents") or "[]")
        d["result"] = json.loads(d.pop("result_json") or "null")
        results.append(d)
    return results


def update_run(run_id: str, **fields) -> None:
    conn = _get_conn()
    sets = []
    vals = []
    for k, v in fields.items():
        if k == "result":
            sets.append("result_json = ?")
            vals.append(json.dumps(v))
        elif k == "config":
            sets.append("config_json = ?")
            vals.append(json.dumps(v))
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(run_id)
    conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def set_pid(run_id: str, pid: int) -> None:
    """Persist the subprocess PID so it survives server restarts."""
    conn = _get_conn()
    conn.execute("UPDATE runs SET pid = ? WHERE id = ?", (pid, run_id))
    conn.commit()


def set_log_file(run_id: str, path: str) -> None:
    """Persist the log file path for orphan reconnection."""
    conn = _get_conn()
    conn.execute("UPDATE runs SET log_file = ? WHERE id = ?", (path, run_id))
    conn.commit()


def reconcile_stale_runs() -> list:
    """
    Called at server startup. For every run stuck in 'running':
    - If the stored PID is still alive → return it so the caller can attach
      an orphan monitor coroutine (process survived the restart).
    - Otherwise → mark the run 'interrupted' immediately.

    Returns a list of dicts: [{"run_id": ..., "pid": ..., "log_file": ...}, ...]
    for runs whose process is still alive.
    """
    conn = _get_conn()
    now = _now()
    rows = conn.execute(
        "SELECT id, pid, log_file FROM runs WHERE status = 'running'"
    ).fetchall()

    alive: list = []

    for row in rows:
        run_id = row["id"]
        pid = row["pid"]
        log_file = row["log_file"]
        still_alive = False

        if pid:
            try:
                os.kill(pid, 0)   # signal 0 = existence check, no signal sent
                still_alive = True
            except (ProcessLookupError, PermissionError):
                pass

        if still_alive:
            alive.append({"run_id": run_id, "pid": pid, "log_file": log_file})
        else:
            conn.execute(
                "UPDATE runs SET status = 'interrupted', finished_at = ?, error = ? WHERE id = ?",
                (now, "Server restarted while pipeline was running. Re-run from Step 3 to resume.", run_id),
            )
            conn.execute(
                """UPDATE run_steps SET status = 'failed', finished_at = ?, detail = ?
                   WHERE run_id = ? AND status IN ('pending', 'running')""",
                (now, "Interrupted by server restart", run_id),
            )

    conn.commit()
    return alive


# ── Step tracking ──

def upsert_step(run_id: str, step: str, status: str, detail: Optional[str] = None) -> None:
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id, started_at FROM run_steps WHERE run_id = ? AND step = ?", (run_id, step)
    ).fetchone()
    now = _now()
    if existing:
        sets = ["status = ?", "detail = ?"]
        vals: list = [status, detail]
        if status == "running" and not existing["started_at"]:
            # Only set started_at the first time — never overwrite an existing
            # start timestamp (e.g. when "LAUNCHING AGENT" fires repeatedly).
            sets.append("started_at = ?")
            vals.append(now)
        if status in ("completed", "failed", "skipped"):
            sets.append("finished_at = ?")
            vals.append(now)
        vals.append(existing["id"])
        conn.execute(f"UPDATE run_steps SET {', '.join(sets)} WHERE id = ?", vals)
    else:
        started = now if status == "running" else None
        finished = now if status in ("completed", "failed", "skipped") else None
        conn.execute(
            "INSERT INTO run_steps (run_id, step, status, detail, started_at, finished_at) VALUES (?,?,?,?,?,?)",
            (run_id, step, status, detail, started, finished),
        )
    conn.commit()


def get_steps(run_id: str) -> List[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM run_steps WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Log stream ──

def add_log(run_id: str, message: str, level: str = "INFO") -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO run_logs (run_id, level, message) VALUES (?, ?, ?)",
        (run_id, level, message),
    )
    conn.commit()


def get_logs(run_id: str, after_id: int = 0, limit: int = 200) -> List[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM run_logs WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
        (run_id, after_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_run(run_id: str) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM run_logs WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM run_steps WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()
    return True


def delete_all_runs() -> int:
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.execute("DELETE FROM run_logs")
    conn.execute("DELETE FROM run_steps")
    conn.execute("DELETE FROM runs")
    conn.commit()
    return count
