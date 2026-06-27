"""Documents router: preview format branches, listing, raw, and delete endpoints."""
import sys
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ui.backend.routers import documents as d  # noqa: E402


def _make_xlsx(path: Path, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(path))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "PROJECT_ROOT", tmp_path)
    src = tmp_path / "compliance-files" / "docs"
    src.mkdir(parents=True)
    from fastapi.testclient import TestClient
    from ui.backend.main import app
    return TestClient(app), src


@allure.feature("Pipeline API")
@allure.story("Documents preview formats")
class TestPreviewFormats:
    @allure.title("CSV preview returns csv type")
    def test_csv(self, env):
        c, src = env
        (src / "a.csv").write_text("rule,risk\nLTV,high\n")
        r = c.get("/api/documents/preview/docs/a.csv").json()
        assert r["type"] == "csv" and "LTV" in r["content"]

    @allure.title("Markdown preview returns markdown type")
    def test_md(self, env):
        c, src = env
        (src / "a.md").write_text("# Heading\n\nbody")
        r = c.get("/api/documents/preview/docs/a.md").json()
        assert r["type"] == "markdown" and "Heading" in r["content"]

    @allure.title("XLSX preview renders sheet rows")
    def test_xlsx(self, env):
        c, src = env
        _make_xlsx(src / "a.xlsx", [["Rule", "Risk"], ["LTV", "high"]])
        r = c.get("/api/documents/preview/docs/a.xlsx").json()
        assert r["type"] == "xlsx_sheets" and "Rule" in r["content"]

    @allure.title("Corrupt PPTX falls back to 'preview not available'")
    def test_pptx_fallback(self, env):
        c, src = env
        (src / "a.pptx").write_bytes(b"not a real pptx")
        r = c.get("/api/documents/preview/docs/a.pptx").json()
        assert "not available" in r["content"]

    @allure.title("Unknown extension returns the generic fallback")
    def test_unknown_ext(self, env):
        c, src = env
        (src / "a.bin").write_bytes(b"\x00\x01binary")
        r = c.get("/api/documents/preview/docs/a.bin").json()
        assert "not available" in r["content"]

    @allure.title("Empty/invalid PDF signature file → pdf_embed marker")
    def test_pdf_embed(self, env):
        c, src = env
        (src / "a.pdf").write_bytes(b"%PDF-1.7\n%%EOF")   # valid signature, no extractable text
        r = c.get("/api/documents/preview/docs/a.pdf").json()
        assert r["type"] in ("pdf_embed", "pdf_text")

    @allure.title("Preview of a missing file 404s")
    def test_missing(self, env):
        c, _ = env
        assert c.get("/api/documents/preview/docs/ghost.txt").status_code == 404


@allure.feature("Pipeline API")
@allure.story("Documents listing / raw / delete")
class TestListingRawDelete:
    @allure.title("GET /{subdir}/files lists supported files; 404 for unknown subdir")
    def test_list_files(self, env):
        c, src = env
        (src / "a.txt").write_text("hi")
        body = c.get("/api/documents/docs/files").json()
        assert body["subdirectory"] == "docs"
        assert any(doc["name"] == "a.txt" for doc in body["documents"])
        assert c.get("/api/documents/nope/files").status_code == 404

    @allure.title("GET / with subdir param lists nested documents")
    def test_list_with_subdir(self, env):
        c, src = env
        (src / "a.txt").write_text("hi")
        body = c.get("/api/documents?subdir=docs").json()
        assert any(doc["name"] == "a.txt" for doc in body["documents"])

    @allure.title("Raw rejects unsupported extensions with 400")
    def test_raw_unsupported(self, env):
        c, src = env
        (src / "a.bin").write_bytes(b"x")
        assert c.get("/api/documents/raw/docs/a.bin").status_code == 400

    @allure.title("DELETE /file removes a file; 404 when absent")
    def test_delete_file(self, env):
        c, src = env
        (src / "a.txt").write_text("hi")
        assert c.delete("/api/documents/file/docs/a.txt").json() == {"deleted": "a.txt"}
        assert not (src / "a.txt").exists()
        assert c.delete("/api/documents/file/docs/a.txt").status_code == 404
