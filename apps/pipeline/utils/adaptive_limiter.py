"""SQLite-backed, process-shared adaptive limiter for pipeline LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any


@dataclass(frozen=True)
class RequestLease:
    token: str
    wait_seconds: float
    concurrency_limit: int


class AdaptiveRequestLimiter:
    """Coordinate subprocesses with additive increase and multiplicative decrease."""

    def __init__(
        self,
        state_file: str | Path,
        *,
        initial_limit: int = 2,
        maximum_limit: int = 8,
        minimum_limit: int = 1,
        success_window: int = 12,
        lease_seconds: float = 900,
        poll_seconds: float = 0.1,
    ) -> None:
        self.state_file = Path(state_file)
        self.initial_limit = max(1, int(initial_limit))
        self.maximum_limit = max(self.initial_limit, int(maximum_limit))
        self.minimum_limit = max(1, min(int(minimum_limit), self.initial_limit))
        self.success_window = max(1, int(success_window))
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.poll_seconds = max(0.01, float(poll_seconds))
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_environment(cls) -> "AdaptiveRequestLimiter | None":
        state_file = os.getenv("KG_GLOBAL_LLM_STATE_FILE")
        if not state_file:
            return None
        return cls(
            state_file,
            initial_limit=int(os.getenv("KG_GLOBAL_LLM_CONCURRENCY_INITIAL", "2")),
            maximum_limit=int(os.getenv("KG_GLOBAL_LLM_CONCURRENCY_MAX", "8")),
            minimum_limit=int(os.getenv("KG_GLOBAL_LLM_CONCURRENCY_MIN", "1")),
            success_window=int(os.getenv("KG_GLOBAL_LLM_SUCCESS_WINDOW", "12")),
            lease_seconds=float(os.getenv("KG_GLOBAL_LLM_LEASE_SECONDS", "900")),
            poll_seconds=float(os.getenv("KG_GLOBAL_LLM_POLL_SECONDS", "0.1")),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.state_file, timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS limiter_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1), current_limit INTEGER NOT NULL,
                    success_streak INTEGER NOT NULL, failure_streak INTEGER NOT NULL,
                    backoff_until REAL NOT NULL, total_success INTEGER NOT NULL,
                    total_failure INTEGER NOT NULL, total_throttled INTEGER NOT NULL,
                    total_wait_seconds REAL NOT NULL, total_request_seconds REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS limiter_leases (
                    token TEXT PRIMARY KEY, process_id INTEGER NOT NULL,
                    acquired_at REAL NOT NULL, expires_at REAL NOT NULL
                )
            """)
            connection.execute(
                "INSERT OR IGNORE INTO limiter_state VALUES (1, ?, 0, 0, 0, 0, 0, 0, 0, 0, ?)",
                (self.initial_limit, time.time()),
            )

    def acquire(self, timeout: float | None = None) -> RequestLease:
        started = time.monotonic()
        deadline = None if timeout is None else started + max(0.0, timeout)
        token = uuid.uuid4().hex
        while True:
            now = time.time()
            wait_for = self.poll_seconds
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM limiter_leases WHERE expires_at <= ?", (now,))
                current_limit, backoff_until = connection.execute(
                    "SELECT current_limit, backoff_until FROM limiter_state WHERE id = 1"
                ).fetchone()
                active = connection.execute("SELECT COUNT(*) FROM limiter_leases").fetchone()[0]
                if now >= backoff_until and active < current_limit:
                    connection.execute(
                        "INSERT INTO limiter_leases VALUES (?, ?, ?, ?)",
                        (token, os.getpid(), now, now + self.lease_seconds),
                    )
                    connection.execute("COMMIT")
                    return RequestLease(token, time.monotonic() - started, int(current_limit))
                connection.execute("COMMIT")
                if backoff_until > now:
                    wait_for = min(1.0, max(self.poll_seconds, backoff_until - now))
            if deadline is not None and time.monotonic() + wait_for > deadline:
                raise TimeoutError("timed out waiting for the shared LLM concurrency limiter")
            time.sleep(wait_for)

    def release(
        self,
        lease: RequestLease,
        *,
        success: bool,
        penalize: bool = False,
        throttled: bool = False,
        request_seconds: float = 0,
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM limiter_leases WHERE token = ?", (lease.token,))
            row = connection.execute(
                "SELECT current_limit, success_streak, failure_streak, total_success, "
                "total_failure, total_throttled, total_wait_seconds, total_request_seconds "
                "FROM limiter_state WHERE id = 1"
            ).fetchone()
            current, successes, failures = map(int, row[:3])
            total_success, total_failure, total_throttled = map(int, row[3:6])
            backoff_until = 0.0
            if success:
                total_success += 1
                successes += 1
                failures = 0
                if successes >= self.success_window and current < self.maximum_limit:
                    current += 1
                    successes = 0
            else:
                total_failure += 1
                failures += 1
                successes = 0
                if throttled:
                    total_throttled += 1
                if penalize:
                    current = max(self.minimum_limit, current // 2)
                    backoff_until = now + min(60.0, float(2 ** min(failures, 5)))
            connection.execute("""
                UPDATE limiter_state SET current_limit=?, success_streak=?, failure_streak=?,
                backoff_until=?, total_success=?, total_failure=?, total_throttled=?,
                total_wait_seconds=?, total_request_seconds=?, updated_at=? WHERE id=1
            """, (
                current, successes, failures, backoff_until, total_success, total_failure,
                total_throttled, float(row[6]) + lease.wait_seconds,
                float(row[7]) + max(0.0, request_seconds), now,
            ))
            connection.execute("COMMIT")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT current_limit, success_streak, failure_streak, backoff_until, "
                "total_success, total_failure, total_throttled, total_wait_seconds, "
                "total_request_seconds, updated_at FROM limiter_state WHERE id=1"
            ).fetchone()
            active = connection.execute("SELECT COUNT(*) FROM limiter_leases").fetchone()[0]
        return {
            "current_limit": int(row[0]), "maximum_limit": self.maximum_limit,
            "active_leases": int(active), "success_streak": int(row[1]),
            "failure_streak": int(row[2]), "backoff_until": float(row[3]),
            "total_success": int(row[4]), "total_failure": int(row[5]),
            "total_throttled": int(row[6]), "total_wait_seconds": round(float(row[7]), 3),
            "total_request_seconds": round(float(row[8]), 3), "updated_at": float(row[9]),
        }

    def write_snapshot(self, destination: str | Path) -> None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2) + "\n", encoding="utf-8")
