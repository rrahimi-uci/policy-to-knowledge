"""Unit tests for the prompts router — path-traversal guard + happy paths."""
import sys
from pathlib import Path

import allure
import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ui.backend.routers import prompts  # noqa: E402


@allure.feature("Pipeline API")
@allure.story("Prompts path-traversal guard")
class TestSafeSegment:
    @pytest.mark.parametrize("bad", ["../etc", "a/b", "..", ".", "", "x\\y", "../../config"])
    @allure.title("Rejects unsafe segment: {bad!r}")
    def test_rejects(self, bad):
        with pytest.raises(HTTPException) as exc:
            prompts._safe_segment(bad, "domain")
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("ok", ["mortgage", "aml", "business_rules_extraction", "default"])
    @allure.title("Allows safe segment: {ok!r}")
    def test_allows(self, ok):
        assert prompts._safe_segment(ok, "domain") == ok


@allure.feature("Pipeline API")
@allure.story("Prompts read/write")
class TestPromptEndpoints:
    @allure.title("get_prompt 400s on a traversal attempt instead of reading a file")
    def test_get_traversal_blocked(self):
        with pytest.raises(HTTPException) as exc:
            prompts.get_prompt("default", "../../config")
        assert exc.value.status_code == 400

    @allure.title("update_prompt 400s on a traversal attempt instead of writing a file")
    def test_put_traversal_blocked(self):
        with pytest.raises(HTTPException) as exc:
            prompts.update_prompt("default", "../../evil", {"content": "x"})
        assert exc.value.status_code == 400

    @allure.title("update_prompt 400s when content is missing")
    def test_put_missing_content(self, tmp_path, monkeypatch):
        # Point at a temp prompts dir with one existing file.
        monkeypatch.setattr(prompts, "PROJECT_ROOT", tmp_path)
        (tmp_path / "prompts").mkdir()
        (tmp_path / "prompts" / "p.txt").write_text("orig")
        with pytest.raises(HTTPException) as exc:
            prompts.update_prompt("default", "p", {})
        assert exc.value.status_code == 400

    @allure.title("get_prompt returns content for an existing default prompt")
    def test_get_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompts, "PROJECT_ROOT", tmp_path)
        (tmp_path / "prompts").mkdir()
        (tmp_path / "prompts" / "p.txt").write_text("hello world", encoding="utf-8")
        result = prompts.get_prompt("default", "p")
        assert result["content"] == "hello world"
        assert result["name"] == "p"


@allure.feature("Pipeline API")
@allure.story("Prompts router via TestClient")
class TestPromptsRoutes:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prompts, "PROJECT_ROOT", tmp_path)
        dom = tmp_path / "domain-prompts" / "mortgage"
        dom.mkdir(parents=True)
        (dom / "rules.txt").write_text("extract the rules")
        default = tmp_path / "prompts"
        default.mkdir()
        (default / "base.txt").write_text("base prompt\nline2")
        from fastapi.testclient import TestClient
        from ui.backend.main import app
        return TestClient(app)

    @allure.title("GET / lists domains + default prompts")
    def test_list(self, client):
        body = client.get("/api/prompts").json()
        assert any(d["name"] == "mortgage" and "rules" in d["prompts"] for d in body["domains"])
        assert "base" in body["default"]["prompts"]

    @allure.title("GET a domain prompt and the default prompt")
    def test_get(self, client):
        r = client.get("/api/prompts/mortgage/rules").json()
        assert r["content"] == "extract the rules" and r["size"] > 0
        assert client.get("/api/prompts/default/base").json()["lines"] == 2

    @allure.title("PUT saves an existing domain prompt; unknown 404s")
    def test_update(self, client):
        ok = client.put("/api/prompts/mortgage/rules", json={"content": "new body"})
        assert ok.json()["status"] == "saved"
        assert client.get("/api/prompts/mortgage/rules").json()["content"] == "new body"
        assert client.put("/api/prompts/mortgage/ghost", json={"content": "x"}).status_code == 404
        assert client.get("/api/prompts/mortgage/missing").status_code == 404
