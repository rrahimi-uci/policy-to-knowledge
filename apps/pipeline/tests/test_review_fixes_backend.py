"""Regression tests for the confirmed backend review fixes.

One test (or small group) per bug:
  1. Concurrency guard read the wrong dict key (`run_type` vs `type`).
  2. Path traversal in the graphs / compare routers.
  3. impact_store / obligation_store ignored PIPELINE_DATA_DIR.
  4. _advance_step conflated "Step 3" with "Step 3.5".

Bugs 5 (_kill_pid SIGKILL escalation) and 6 (WS dict-key leak) are covered
by lightweight unit checks below.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point all three stores at one temp DB (mirrors test_routers_more.py)."""
    db_path = tmp_path / "runs.db"
    import ui.backend.services.run_store as rs
    import ui.backend.services.impact_store as is_
    import ui.backend.services.obligation_store as os_
    for mod in (rs, is_, os_):
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        if hasattr(mod._local, "conn"):
            mod._local.conn = None
    rs.init_db()
    is_.init_tables()
    os_.init_tables()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from ui.backend.main import app
    return TestClient(app)


@pytest.fixture
def fake_output(tmp_path, monkeypatch):
    from ui.backend.services import graph_service as gs
    monkeypatch.setattr(gs, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "pipeline-output"
    out.mkdir()
    return out


# ── Bug 1: concurrency guard wrong dict key ────────────────────────────────
@allure.feature("Backend review fixes")
@allure.story("Concurrency guard")
class TestConcurrencyGuard:
    @allure.title("_conflicting_running_run finds a running extraction for the same batch")
    def test_conflict_detected(self):
        import ui.backend.services.run_store as rs
        from ui.backend.services import pipeline_runner

        rs.create_run(
            "run-a",
            run_type="extraction",
            provider="openai",
            config={"batch_name": "Mortgage-Batch"},
        )
        # Before the fix this returned None because the guard read run["run_type"]
        # while run_store stores the column as "type".
        conflict = pipeline_runner._conflicting_running_run("openai", "mortgage-batch")
        assert conflict is not None
        assert conflict["id"] == "run-a"

    @allure.title("No conflict for a different batch")
    def test_no_conflict_other_batch(self):
        import ui.backend.services.run_store as rs
        from ui.backend.services import pipeline_runner

        rs.create_run("run-b", run_type="extraction", provider="openai",
                      config={"batch_name": "AML-Batch"})
        assert pipeline_runner._conflicting_running_run("openai", "mortgage-batch") is None


# ── Bug 2: path traversal in graphs / compare routers ──────────────────────
@allure.feature("Backend review fixes")
@allure.story("Path traversal")
class TestPathTraversal:
    @allure.title("DELETE with a traversal name does not escape pipeline-output")
    def test_delete_traversal_blocked(self, client, fake_output, tmp_path):
        # Sentinel directory OUTSIDE pipeline-output that must survive.
        sentinel = tmp_path / "sentinel"
        sentinel.mkdir()
        (sentinel / "keep.txt").write_text("important")

        # A crafted traversal name must never delete anything outside the tree.
        # 405 = path-normalized to /api/graphs (no name); 400 = guard rejected;
        # 404 = not found. All three mean "nothing escaped / was deleted".
        for bad in ("..", "../sentinel", "..%2Fsentinel", "%2e%2e%2fsentinel"):
            r = client.delete(f"/api/graphs/{bad}")
            assert r.status_code in (400, 404, 405), (bad, r.status_code)

        assert sentinel.exists(), "sentinel outside pipeline-output was deleted"
        assert (sentinel / "keep.txt").exists()

    @allure.title("delete_graph raises UnsafeNameError for traversal names")
    def test_service_rejects_traversal(self, fake_output, tmp_path):
        from ui.backend.services import graph_service as gs
        sentinel = tmp_path / "sentinel2"
        sentinel.mkdir()
        with pytest.raises(gs.UnsafeNameError):
            gs.delete_graph("../sentinel2")
        with pytest.raises(gs.UnsafeNameError):
            gs.get_graph_data("../../etc")
        assert sentinel.exists()

    @allure.title("comparison name/operation traversal is rejected")
    def test_comparison_traversal(self, fake_output):
        from ui.backend.services import graph_service as gs
        with pytest.raises(gs.UnsafeNameError):
            gs.get_comparison_data("../foo")
        # _joined exists so _find_comparison_dir is reachable, then operation guarded
        (fake_output / "_joined" / "cmp").mkdir(parents=True)
        with pytest.raises(gs.UnsafeNameError):
            gs.get_comparison_html("cmp", "../../secret")


# ── Bug 3: stores honour PIPELINE_DATA_DIR ─────────────────────────────────
@allure.feature("Backend review fixes")
@allure.story("PIPELINE_DATA_DIR")
class TestDataDirEnv:
    @allure.title("all three stores resolve _DB_PATH under PIPELINE_DATA_DIR")
    def test_shared_data_dir(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "shared-data"
        data_dir.mkdir()
        monkeypatch.setenv("PIPELINE_DATA_DIR", str(data_dir))

        import ui.backend.services.run_store as rs
        import ui.backend.services.impact_store as is_
        import ui.backend.services.obligation_store as os_
        # Re-import so module-level _DB_PATH is recomputed against the env var.
        rs = importlib.reload(rs)
        is_ = importlib.reload(is_)
        os_ = importlib.reload(os_)
        try:
            for mod in (rs, is_, os_):
                assert Path(mod._DB_PATH).parent == data_dir, mod.__name__
                assert Path(mod._DB_PATH) == data_dir / "runs.db", mod.__name__
        finally:
            # Restore default-resolved modules for the rest of the suite.
            monkeypatch.delenv("PIPELINE_DATA_DIR", raising=False)
            importlib.reload(rs)
            importlib.reload(is_)
            importlib.reload(os_)


# ── Bug 4: _advance_step "Step 3" vs "Step 3.5" ────────────────────────────
@allure.feature("Backend review fixes")
@allure.story("Step boundary matching")
class TestAdvanceStep:
    @allure.title("'Step 3.5 ... completed' must NOT complete step 3")
    def test_step35_does_not_complete_step3(self):
        import ui.backend.services.run_store as rs
        from ui.backend.services import pipeline_runner

        rs.create_run("run-c", run_type="extraction", provider="openai")
        steps = ["1", "2", "3", "3.5", "4", "5", "6"]
        idx = 2  # current step is "3"

        new_idx = pipeline_runner._advance_step(
            "run-c", "Step 3.5 Rule Quality Validation completed", steps, idx
        )
        assert new_idx == idx, "Step 3.5 line wrongly advanced past step 3"
        step3 = [s for s in rs.get_steps("run-c") if s["step"] == "3"]
        assert not step3 or step3[0]["status"] != "completed"

    @allure.title("'Step 3 completed' DOES complete step 3")
    def test_step3_completes(self):
        import ui.backend.services.run_store as rs
        from ui.backend.services import pipeline_runner

        rs.create_run("run-d", run_type="extraction", provider="openai")
        steps = ["1", "2", "3", "3.5", "4", "5", "6"]
        idx = 2

        new_idx = pipeline_runner._advance_step(
            "run-d", "Step 3 Business Rules Extraction completed", steps, idx
        )
        assert new_idx == idx + 1
        step3 = [s for s in rs.get_steps("run-d") if s["step"] == "3"]
        assert step3 and step3[0]["status"] == "completed"


# ── Bug 5: _kill_pid escalates to SIGKILL ──────────────────────────────────
@allure.feature("Backend review fixes")
@allure.story("Kill escalation")
class TestKillEscalation:
    @allure.title("_kill_pid sends SIGKILL when the process ignores SIGTERM")
    def test_sigkill_escalation(self, monkeypatch):
        import signal
        from ui.backend.services import pipeline_runner

        sent = []
        # Pretend the process group lookup fails so it falls back to os.kill.
        monkeypatch.setattr(pipeline_runner.os, "getpgid",
                            lambda pid: (_ for _ in ()).throw(ProcessLookupError()))

        # Process stays alive through every existence check (ignores SIGTERM).
        monkeypatch.setattr(pipeline_runner, "_pid_alive", lambda pid: True)

        def fake_kill(pid, sig):
            sent.append(sig)
        monkeypatch.setattr(pipeline_runner.os, "kill", fake_kill)

        pipeline_runner._kill_pid(4242)
        assert signal.SIGTERM in sent
        assert signal.SIGKILL in sent, "SIGKILL never sent to a SIGTERM-ignoring process"


# ── Bug 6: WS broadcast does not recreate dict keys ────────────────────────
@allure.feature("Backend review fixes")
@allure.story("WS subscriber leak")
class TestWsBroadcastLeak:
    @allure.title("broadcast to an unknown run_id does not create an empty subscriber set")
    def test_no_key_recreation(self):
        import asyncio
        from ui.backend.ws import pipeline_ws

        pipeline_ws._subscribers.clear()
        asyncio.run(pipeline_ws.broadcast("ghost-run", {"type": "log"}))
        assert "ghost-run" not in pipeline_ws._subscribers
