"""
Obligation Store — SQLite persistence for the Obligation Register.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DB_PATH = Path(__file__).resolve().parent.parent / "runs.db"
_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_tables() -> None:
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS obligations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            graph_name  TEXT NOT NULL,
            provider    TEXT NOT NULL DEFAULT 'openai',
            rule_id     TEXT NOT NULL,
            rule_name   TEXT,
            rule_type   TEXT,
            risk_level  TEXT,
            status      TEXT NOT NULL DEFAULT 'unmapped',
            notes       TEXT DEFAULT '',
            description         TEXT DEFAULT '',
            source_reference    TEXT DEFAULT '',
            jurisdiction        TEXT DEFAULT '',
            mandatory           INTEGER DEFAULT 1,
            effective_date      TEXT DEFAULT '',
            conditions          TEXT DEFAULT '',
            consequences        TEXT DEFAULT '',
            exceptions          TEXT DEFAULT '',
            applicability_scope TEXT DEFAULT '',
            audit_frequency     TEXT DEFAULT '',
            enforcement_action  TEXT DEFAULT '',
            updated_at  TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            UNIQUE(graph_name, provider, rule_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS obligation_controls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            obligation_id   INTEGER NOT NULL REFERENCES obligations(id) ON DELETE CASCADE,
            control_name    TEXT NOT NULL,
            control_type    TEXT NOT NULL DEFAULT 'policy',
            description     TEXT DEFAULT '',
            evidence_url    TEXT DEFAULT '',
            owner           TEXT DEFAULT '',
            created_at      TEXT NOT NULL
        )
    """)
    conn.commit()

    # Migrate existing databases: add new columns if they don't exist
    _ENRICH_COLS = [
        ("description", "TEXT DEFAULT ''"),
        ("source_reference", "TEXT DEFAULT ''"),
        ("jurisdiction", "TEXT DEFAULT ''"),
        ("mandatory", "INTEGER DEFAULT 1"),
        ("effective_date", "TEXT DEFAULT ''"),
        ("conditions", "TEXT DEFAULT ''"),
        ("consequences", "TEXT DEFAULT ''"),
        ("exceptions", "TEXT DEFAULT ''"),
        ("applicability_scope", "TEXT DEFAULT ''"),
        ("audit_frequency", "TEXT DEFAULT ''"),
        ("enforcement_action", "TEXT DEFAULT ''"),
    ]
    existing = {r[1] for r in conn.execute("PRAGMA table_info(obligations)").fetchall()}
    for col_name, col_def in _ENRICH_COLS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE obligations ADD COLUMN {col_name} {col_def}")
    conn.commit()


# ── Obligation CRUD ────────────────────────────────────────────────────────

def upsert_obligation(
    graph_name: str,
    provider: str,
    rule_id: str,
    rule_name: str = "",
    rule_type: str = "",
    risk_level: str = "",
    status: str = "unmapped",
    notes: str = "",
    *,
    description: str = "",
    source_reference: str = "",
    jurisdiction: str = "",
    mandatory: int = 1,
    effective_date: str = "",
    conditions: str = "",
    consequences: str = "",
    exceptions: str = "",
    applicability_scope: str = "",
    audit_frequency: str = "",
    enforcement_action: str = "",
) -> dict:
    """Create or update an obligation entry."""
    conn = _get_conn()
    now = _now()
    conn.execute(
        """INSERT INTO obligations
           (graph_name, provider, rule_id, rule_name, rule_type, risk_level,
            status, notes, description, source_reference, jurisdiction, mandatory,
            effective_date, conditions, consequences, exceptions,
            applicability_scope, audit_frequency, enforcement_action,
            updated_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(graph_name, provider, rule_id)
           DO UPDATE SET rule_name=excluded.rule_name, rule_type=excluded.rule_type,
                         risk_level=excluded.risk_level,
                         description=excluded.description,
                         source_reference=excluded.source_reference,
                         jurisdiction=excluded.jurisdiction,
                         mandatory=excluded.mandatory,
                         effective_date=excluded.effective_date,
                         conditions=excluded.conditions,
                         consequences=excluded.consequences,
                         exceptions=excluded.exceptions,
                         applicability_scope=excluded.applicability_scope,
                         audit_frequency=excluded.audit_frequency,
                         enforcement_action=excluded.enforcement_action,
                         updated_at=excluded.updated_at""",
        (graph_name, provider, rule_id, rule_name, rule_type, risk_level,
         status, notes, description, source_reference, jurisdiction, mandatory,
         effective_date, conditions, consequences, exceptions,
         applicability_scope, audit_frequency, enforcement_action,
         now, now),
    )
    conn.commit()
    return get_obligation(graph_name, provider, rule_id)


def get_obligation(graph_name: str, provider: str, rule_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT * FROM obligations WHERE graph_name=? AND provider=? AND rule_id=?",
        (graph_name, provider, rule_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["controls"] = get_controls(d["id"])
    return d


def list_obligations(graph_name: str, provider: str = "openai") -> List[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM obligations WHERE graph_name=? AND provider=? ORDER BY rule_id",
        (graph_name, provider),
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["controls"] = get_controls(d["id"])
        results.append(d)
    return results


def update_obligation_status(
    graph_name: str, provider: str, rule_id: str, status: str, notes: str = None
) -> Optional[dict]:
    conn = _get_conn()
    now = _now()
    sets = ["status = ?", "updated_at = ?"]
    vals = [status, now]
    if notes is not None:
        sets.append("notes = ?")
        vals.append(notes)
    vals.extend([graph_name, provider, rule_id])
    cur = conn.execute(
        f"UPDATE obligations SET {', '.join(sets)} WHERE graph_name=? AND provider=? AND rule_id=?",
        vals,
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return get_obligation(graph_name, provider, rule_id)


def delete_obligations(graph_name: str, provider: str = "openai") -> int:
    conn = _get_conn()
    # Get obligation IDs first to cascade controls
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM obligations WHERE graph_name=? AND provider=?",
            (graph_name, provider),
        ).fetchall()
    ]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM obligation_controls WHERE obligation_id IN ({placeholders})", ids)
    cur = conn.execute(
        "DELETE FROM obligations WHERE graph_name=? AND provider=?",
        (graph_name, provider),
    )
    conn.commit()
    return cur.rowcount


# ── Control mapping CRUD ──────────────────────────────────────────────────

def add_control(
    obligation_id: int,
    control_name: str,
    control_type: str = "policy",
    description: str = "",
    evidence_url: str = "",
    owner: str = "",
) -> dict:
    conn = _get_conn()
    now = _now()
    cur = conn.execute(
        """INSERT INTO obligation_controls
           (obligation_id, control_name, control_type, description, evidence_url, owner, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (obligation_id, control_name, control_type, description, evidence_url, owner, now),
    )
    conn.commit()
    return dict(
        _get_conn()
        .execute("SELECT * FROM obligation_controls WHERE id=?", (cur.lastrowid,))
        .fetchone()
    )


def get_controls(obligation_id: int) -> List[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM obligation_controls WHERE obligation_id=? ORDER BY id",
        (obligation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_control(control_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM obligation_controls WHERE id=?", (control_id,))
    conn.commit()
    return cur.rowcount > 0


# ── Heatmap aggregation ──────────────────────────────────────────────────

def get_heatmap(graph_name: str, provider: str = "openai") -> dict:
    """Compliance heatmap: counts by status, by rule_type, by risk_level."""
    conn = _get_conn()

    # Overall counts
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM obligations WHERE graph_name=? AND provider=? GROUP BY status",
        (graph_name, provider),
    ).fetchall()
    by_status = {r["status"]: r["cnt"] for r in rows}

    # By rule_type × status
    rows = conn.execute(
        """SELECT rule_type, status, COUNT(*) as cnt
           FROM obligations WHERE graph_name=? AND provider=?
           GROUP BY rule_type, status""",
        (graph_name, provider),
    ).fetchall()
    by_type = {}
    for r in rows:
        rt = r["rule_type"] or "unknown"
        if rt not in by_type:
            by_type[rt] = {}
        by_type[rt][r["status"]] = r["cnt"]

    # By risk_level × status
    rows = conn.execute(
        """SELECT risk_level, status, COUNT(*) as cnt
           FROM obligations WHERE graph_name=? AND provider=?
           GROUP BY risk_level, status""",
        (graph_name, provider),
    ).fetchall()
    by_risk = {}
    for r in rows:
        rl = r["risk_level"] or "unknown"
        if rl not in by_risk:
            by_risk[rl] = {}
        by_risk[rl][r["status"]] = r["cnt"]

    total = sum(by_status.values())
    mapped = by_status.get("mapped", 0)
    partial = by_status.get("partially-mapped", 0)

    return {
        "total_obligations": total,
        "by_status": by_status,
        "by_rule_type": by_type,
        "by_risk_level": by_risk,
        "compliance_score": round((mapped + partial * 0.5) / max(total, 1) * 100, 1),
    }
