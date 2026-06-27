"""Tests for the documents router — pure helpers + folder lifecycle endpoints."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import allure
import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ui.backend.routers import documents as d  # noqa: E402


@allure.feature("Pipeline API")
@allure.story("Documents helpers")
class TestHelpers:
    @allure.title("_safe_path allows in-base paths and blocks traversal")
    def test_safe_path(self, tmp_path):
        assert d._safe_path(tmp_path, "a", "b").is_relative_to(tmp_path.resolve())
        with pytest.raises(HTTPException) as e:
            d._safe_path(tmp_path, "../escape")
        assert e.value.status_code == 400

    @allure.title("_truncate_preview truncates and flags overflow")
    def test_truncate(self):
        assert d._truncate_preview("hello", 10) == ("hello", False)
        assert d._truncate_preview("hello world", 5) == ("hello", True)

    @allure.title("_has_pdf_signature detects the %PDF- magic header")
    def test_pdf_signature(self, tmp_path):
        pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF-1.7\n...")
        notpdf = tmp_path / "b.pdf"; notpdf.write_bytes(b"not a pdf")
        assert d._has_pdf_signature(pdf) is True
        assert d._has_pdf_signature(notpdf) is False
        assert d._has_pdf_signature(tmp_path / "missing.pdf") is False

    @allure.title("_raw_media_type prefers the PDF signature, then extension")
    def test_raw_media_type(self, tmp_path):
        real_pdf = tmp_path / "x.bin"; real_pdf.write_bytes(b"%PDF-1.4")
        assert d._raw_media_type(real_pdf) == "application/pdf"
        txt = tmp_path / "x.txt"; txt.write_text("hi")
        assert "text" in d._raw_media_type(txt)

    @allure.title("_extract_xml_text_nodes pulls OOXML <t> text runs (namespaced)")
    def test_xml_text_nodes(self):
        # Mimics Word/PPTX: only <...}t> run elements carry text.
        xml = '<doc xmlns:a="urn:x"><a:t>one</a:t><a:p>skip</a:p><a:t> two </a:t></doc>'
        nodes = d._extract_xml_text_nodes(ET.fromstring(xml))
        assert nodes == ["one", "two"]


@allure.feature("Pipeline API")
@allure.story("Documents folder lifecycle")
class TestFolderEndpoints:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(d, "PROJECT_ROOT", tmp_path)
        (tmp_path / "compliance-files").mkdir()
        from fastapi.testclient import TestClient
        from ui.backend.main import app
        return TestClient(app)

    @allure.title("GET /api/documents on an empty tree returns no subdirectories")
    def test_list_empty(self, client):
        body = client.get("/api/documents").json()
        assert body["subdirectories"] == [] and body["documents"] == []

    @allure.title("Create → list → delete folder round-trip")
    def test_folder_crud(self, client):
        created = client.post("/api/documents/folder", json={"name": "mortgage_docs", "domain": "mortgage"})
        assert created.status_code == 200
        subs = client.get("/api/documents").json()["subdirectories"]
        assert any(s["name"] == "mortgage_docs" for s in subs)
        # duplicate → 409
        assert client.post("/api/documents/folder", json={"name": "mortgage_docs"}).status_code == 409
        # delete
        assert client.delete("/api/documents/folder/mortgage_docs").status_code == 200
        assert client.delete("/api/documents/folder/mortgage_docs").status_code == 404

    @allure.title("Rejects invalid folder names and unknown domains")
    def test_invalid_inputs(self, client):
        assert client.post("/api/documents/folder", json={"name": "../evil"}).status_code == 400
        assert client.post("/api/documents/folder", json={"name": "ok", "domain": "nonsense"}).status_code == 400
