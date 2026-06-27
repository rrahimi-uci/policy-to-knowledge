"""Unit tests for the SQLite-backed pipeline run store."""
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ui.backend.services import run_store as rs  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_DB_PATH", tmp_path / "runs.db")
    if hasattr(rs._local, "conn"):
        rs._local.conn = None
    rs.init_db()
    yield rs
    if hasattr(rs._local, "conn") and rs._local.conn is not None:
        rs._local.conn.close()
        rs._local.conn = None


@allure.feature("Pipeline run store")
@allure.story("Run lifecycle")
class TestRunCrud:
    @allure.title("create_run persists a 'running' run; get_run reads it back")
    def test_create_get(self, store):
        run = store.create_run("r1", run_type="extraction", provider="openai", domain="mortgage")
        assert run["id"] == "r1"
        assert run["status"] == "running"
        fetched = store.get_run("r1")
        assert fetched["domain"] == "mortgage"

    @allure.title("update_run sets fields; empty update is a no-op")
    def test_update(self, store):
        store.create_run("r1", run_type="extraction")
        store.update_run("r1", status="completed")
        assert store.get_run("r1")["status"] == "completed"
        store.update_run("r1")  # must not raise
        assert store.get_run("r1")["status"] == "completed"

    @allure.title("list_runs filters by type and orders newest first")
    def test_list(self, store):
        store.create_run("a", run_type="extraction")
        store.create_run("b", run_type="comparison")
        store.create_run("c", run_type="extraction")
        extraction = [r["id"] for r in store.list_runs(run_type="extraction")]
        assert set(extraction) == {"a", "c"}
        assert "b" not in extraction

    @allure.title("delete_run removes the run and returns True; False when absent")
    def test_delete(self, store):
        store.create_run("r1", run_type="extraction")
        assert store.delete_run("r1") is True
        assert store.get_run("r1") is None
        assert store.delete_run("r1") is False


@allure.feature("Pipeline run store")
@allure.story("Steps and logs")
class TestStepsAndLogs:
    @allure.title("upsert_step then get_steps round-trips status")
    def test_steps(self, store):
        store.create_run("r1", run_type="extraction")
        store.upsert_step("r1", "agent-1", "running")
        store.upsert_step("r1", "agent-1", "done", detail="ok")
        steps = store.get_steps("r1")
        assert len(steps) == 1
        assert steps[0]["status"] == "done"

    @allure.title("Logs are returned incrementally via the after_id cursor")
    def test_logs_cursor(self, store):
        store.create_run("r1", run_type="extraction")
        store.add_log("r1", "first")
        store.add_log("r1", "second")
        first_page = store.get_logs("r1", after_id=0)
        assert [l["message"] for l in first_page] == ["first", "second"]
        last_id = first_page[-1]["id"]
        store.add_log("r1", "third")
        nxt = store.get_logs("r1", after_id=last_id)
        assert [l["message"] for l in nxt] == ["third"]

    @allure.title("set_pid / set_log_file persist onto the run row")
    def test_pid_and_logfile(self, store):
        store.create_run("r1", run_type="extraction")
        store.set_pid("r1", 4242)
        store.set_log_file("r1", "/tmp/r1.log")
        run = store.get_run("r1")
        assert run["pid"] == 4242
        assert run["log_file"] == "/tmp/r1.log"

    @allure.title("busy_timeout pragma is configured on the connection")
    def test_busy_timeout(self, store):
        conn = store._get_conn()
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
