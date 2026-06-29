"""Regression tests for a second round of backend review fixes.

  1. publish.py built the docs tarball with tarfile's default recursive add
     while *also* iterating rglob("*"), duplicating every nested file in the
     uploaded archive.
  2. impact_analysis.py ran the synchronous basic-mode engine directly inside
     an async handler, blocking the event loop for the whole analysis.
"""
import asyncio
import io
import sys
import tarfile
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Bug 1: duplicated entries in the publish docs archive ──────────────────
@allure.feature("Backend review fixes (round 2)")
@allure.story("Publish docs archive deduplication")
class TestPublishArchiveNoDuplicates:
    @allure.title("Nested files appear exactly once in the uploaded docs archive")
    def test_no_duplicate_entries(self, tmp_path, monkeypatch):
        import ui.backend.services.run_store as rs
        import ui.backend.routers.publish as publish

        # Isolated DB so run_store writes don't touch the real one.
        db_path = tmp_path / "runs.db"
        monkeypatch.setattr(rs, "_DB_PATH", db_path)
        if hasattr(rs._local, "conn"):
            rs._local.conn = None
        rs.init_db()

        # Build a pipeline-output tree with a NESTED organized-documents folder.
        source = "demo_source"
        base = tmp_path / "pipeline-output" / source
        (base / "agent-5-optimized").mkdir(parents=True)
        (base / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json").write_text("{}")
        docs = base / "agent-1-organized-documents"
        (docs / "sub").mkdir(parents=True)
        (docs / "top.txt").write_text("top")
        (docs / "sub" / "nested.txt").write_text("nested")

        monkeypatch.setattr(publish, "PIPELINE_OUTPUT_DIR", tmp_path / "pipeline-output")

        captured = {}

        class _FakeResp:
            status_code = 200
            text = '{"rules": 1, "entities": 1}'

            def json(self):
                return {"rules": 1, "entities": 1}

        class _FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data=None, files=None):
                # Capture the docs archive bytes for inspection.
                captured["files"] = files
                return _FakeResp()

        monkeypatch.setattr(publish.httpx, "AsyncClient", _FakeClient)
        # Avoid touching the real broadcast machinery.
        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(publish, "broadcast", _noop)

        run_id = "pubtest12345"
        rs.create_run(run_id, run_type="publish", provider="openai")

        asyncio.run(publish._run_publish(run_id, source, "openai", None))

        assert "files" in captured, "publish never POSTed to the assistant"
        archive_field = captured["files"].get("docs_archive")
        assert archive_field is not None, "docs archive was not uploaded"
        _name, archive_bytes, _ctype = archive_field

        with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as tf:
            names = tf.getnames()

        assert "sub/nested.txt" in names
        # The bug duplicated nested files; assert each name is unique.
        assert len(names) == len(set(names)), f"duplicate archive entries: {names}"


# ── Bug 2: basic-mode impact analysis must not block the event loop ────────
@allure.feature("Backend review fixes (round 2)")
@allure.story("Basic impact analysis offloaded to a thread")
class TestImpactBasicNonBlocking:
    @allure.title("start_analysis offloads the synchronous engine off the loop")
    def test_run_analysis_runs_off_event_loop(self, monkeypatch):
        from ui.backend.routers import impact_analysis

        loop_thread_ids = {}

        def _fake_run_analysis(*, analysis_id, old_text, new_text, graph_name, provider):
            import threading
            loop_thread_ids["worker"] = threading.get_ident()
            return {"id": analysis_id, "status": "completed"}

        monkeypatch.setattr(impact_analysis.impact_service, "run_analysis", _fake_run_analysis)
        monkeypatch.setattr(
            impact_analysis.impact_store, "create_analysis",
            lambda **k: {"id": "abc123"},
        )
        monkeypatch.setattr(
            impact_analysis.impact_store, "get_impact_items",
            lambda _id: [],
        )
        monkeypatch.setattr(impact_analysis, "_extract_text", lambda b, n: b.decode())

        class _Up:
            def __init__(self, name, data):
                self.filename = name
                self._data = data

            async def read(self):
                return self._data

        async def _drive():
            import threading
            loop_thread_ids["loop"] = threading.get_ident()
            return await impact_analysis.start_analysis(
                old_doc=_Up("old.txt", b"old text content"),
                new_doc=_Up("new.txt", b"new text content"),
                graph_name="g",
                provider="openai",
                mode="basic",
            )

        result = asyncio.run(_drive())
        assert result["status"] == "completed"
        # The synchronous engine must have executed on a different (worker)
        # thread than the event loop — proving it was offloaded, not run inline.
        assert loop_thread_ids["worker"] != loop_thread_ids["loop"]
