"""
Impact Store — SQLite persistence for regulatory change impact analyses.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "runs.db"
_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def init_tables() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS impact_analyses (
            id            TEXT PRIMARY KEY,
            graph_name    TEXT NOT NULL,
            provider      TEXT NOT NULL DEFAULT 'openai',
            old_doc_name  TEXT,
            new_doc_name  TEXT,
            status        TEXT NOT NULL DEFAULT 'pending',
            summary_json  TEXT,
            stats_json    TEXT,
            error         TEXT,
            created_at    TEXT NOT NULL,
            finished_at   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS impact_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id     TEXT NOT NULL REFERENCES impact_analyses(id) ON DELETE CASCADE,
            change_type     TEXT NOT NULL,
            provision_text  TEXT NOT NULL,
            severity        TEXT NOT NULL DEFAULT 'cosmetic',
            affected_rules  TEXT NOT NULL DEFAULT '[]',
            description     TEXT,
            recommendation  TEXT
        )
    """)
    conn.commit()


def create_analysis(
    graph_name: str,
    provider: str,
    old_doc_name: str,
    new_doc_name: str,
) -> dict:
    analysis_id = uuid.uuid4().hex[:12]
    now = _now()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO impact_analyses
           (id, graph_name, provider, old_doc_name, new_doc_name, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
        (analysis_id, graph_name, provider, old_doc_name, new_doc_name, now),
    )
    conn.commit()
    return get_analysis(analysis_id)


def update_analysis(analysis_id: str, **fields) -> None:
    if not fields:
        return
    conn = _get_conn()
    sets, vals = [], []
    for k, v in fields.items():
        if k in ("summary", "stats"):
            sets.append(f"{k}_json = ?")
            vals.append(json.dumps(v) if v is not None else None)
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(analysis_id)
    conn.execute(f"UPDATE impact_analyses SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def get_analysis(analysis_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT * FROM impact_analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["summary"] = json.loads(d.pop("summary_json") or "null")
    d["stats"] = json.loads(d.pop("stats_json") or "null")
    return d


def list_analyses(graph_name: str = None, limit: int = 50) -> List[dict]:
    q = "SELECT * FROM impact_analyses"
    params: list = []
    if graph_name:
        q += " WHERE graph_name = ?"
        params.append(graph_name)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = _get_conn().execute(q, params).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["summary"] = json.loads(d.pop("summary_json") or "null")
        d["stats"] = json.loads(d.pop("stats_json") or "null")
        results.append(d)
    return results


def delete_analysis(analysis_id: str) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM impact_items WHERE analysis_id = ?", (analysis_id,))
    cur = conn.execute("DELETE FROM impact_analyses WHERE id = ?", (analysis_id,))
    conn.commit()
    return cur.rowcount > 0


def add_impact_item(
    analysis_id: str,
    change_type: str,
    provision_text: str,
    severity: str,
    affected_rules: list,
    description: str = "",
    recommendation: str = "",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO impact_items
           (analysis_id, change_type, provision_text, severity, affected_rules, description, recommendation)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            analysis_id,
            change_type,
            provision_text,
            severity,
            json.dumps(affected_rules),
            description,
            recommendation,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_impact_items(analysis_id: str) -> List[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM impact_items WHERE analysis_id = ? ORDER BY id", (analysis_id,)
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["affected_rules"] = json.loads(d.get("affected_rules") or "[]")
        results.append(d)
    return results
