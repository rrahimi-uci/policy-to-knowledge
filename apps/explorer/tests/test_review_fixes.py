"""Regression tests for three review fixes (2026-06):

1. `_run_consistency_checks` crashed with AttributeError when semantic search
   is disabled (`_engine is None`) because the embeddings loop called
   `_engine.embedding_count(...)` with no None guard.
2. `force_reset` / `rebuild-embeddings` called `_engine.*` unguarded, raising
   a raw AttributeError instead of degrading cleanly when `_engine is None`.
3. Arbitrary-path read in the JSON publish branch: `provider` / `source_name`
   from the request body were used unsanitized to build a filesystem path,
   allowing `../` traversal outside pipeline-output.

These are fast, OFFLINE unit tests — no live JanusGraph / OpenSearch.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent  # apps/explorer/


def _import_server():
    """Lazy-import server.py; skip if heavy deps are unavailable."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src import server  # noqa: F401
        return server
    except Exception as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"server.py not importable in this env: {exc}")


# ────────────────────────────────────────────────────────────────────
# Bug 1: consistency check must not crash when _engine is None
# ────────────────────────────────────────────────────────────────────

def test_consistency_checks_no_crash_without_engine(monkeypatch):
    """`_run_consistency_checks()` must degrade gracefully (not raise) when
    semantic search is unavailable (`_engine is None`)."""
    server = _import_server()

    # Force the no-semantic-search condition regardless of installed deps.
    monkeypatch.setattr(server, "_engine", None, raising=False)

    # Stub graph access so the test stays fully offline.
    monkeypatch.setattr(
        server, "get_graph_configs", lambda: {"demo_g": {"name": "Demo"}}
    )

    class _StubG:
        def V(self, *a, **k):
            return self

        def E(self, *a, **k):
            return self

        def count(self):
            return self

        def next(self):
            return 3  # pretend 3 vertices/edges

    @contextmanager
    def _fake_traversal(ts):
        yield (_StubG(), None)

    monkeypatch.setattr(server, "get_traversal", _fake_traversal)
    # No tasks / no annotations to keep the rest of the report offline.
    monkeypatch.setattr(server, "_TASKS", [])

    class _StubSession:
        def query(self, *a, **k):
            return self

        def all(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr(server, "SessionLocal", lambda: _StubSession())

    # Must NOT raise.
    report = server._run_consistency_checks()

    assert isinstance(report, dict)
    emb = report["embeddings"]["demo_g"]
    assert emb["status"] == "unavailable"
    assert emb["indexed"] == 0
    assert any("Semantic search unavailable" in i for i in report["issues"])


# ────────────────────────────────────────────────────────────────────
# Bug 3: provider / source_name path sanitization
# ────────────────────────────────────────────────────────────────────

def test_safe_pipeline_base_rejects_traversal():
    """The publish path helper must reject traversal / unsafe segments and
    must contain the resolved path under pipeline-output."""
    server = _import_server()

    root = (server.APP_ROOT / "pipeline-output").resolve()

    # Valid input resolves under pipeline-output.
    base = server._safe_pipeline_base("openai", "my-source")
    assert root in base.parents or base == root
    assert base == (root / "openai" / "my-source")

    # Traversal / unsafe inputs must raise (mapped to HTTP 400 by the caller).
    bad_inputs = [
        ("..", "src"),
        ("openai", "../../etc"),
        ("openai", ".."),
        ("openai", "a/b"),
        ("openai", ""),
        ("", "src"),
        ("openai", "."),
        ("openai", "with space"),
    ]
    for provider, source_name in bad_inputs:
        with pytest.raises(ValueError):
            server._safe_pipeline_base(provider, source_name)


# ────────────────────────────────────────────────────────────────────
# Bug 2: rebuild-embeddings endpoint degrades cleanly without _engine
# ────────────────────────────────────────────────────────────────────

def test_rebuild_embeddings_503_without_engine(monkeypatch):
    """The rebuild-embeddings endpoint returns a clean 503 (not a raw
    AttributeError) when semantic search is unavailable."""
    server = _import_server()
    monkeypatch.setattr(server, "_engine", None, raising=False)

    client = server.app.test_client()
    resp = client.post("/api/admin/rebuild-embeddings", json={})
    assert resp.status_code == 503
    body = resp.get_json()
    assert "unavailable" in body["error"].lower()
