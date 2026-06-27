"""Unit tests for the plain-text -> HTML report converter."""
import sys
from pathlib import Path

import allure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.text_to_html_converter import (  # noqa: E402
    convert_text_to_html,
    convert_report_file,
)


@allure.feature("Pipeline reporting")
@allure.story("Text to HTML conversion")
class TestConvertTextToHtml:
    @allure.title("Produces a complete HTML document")
    def test_basic_structure(self):
        html = convert_text_to_html("Hello world.", title="My Report")
        assert html.lstrip().lower().startswith("<!doctype html") or "<html" in html.lower()
        assert "</html>" in html.lower()
        assert "My Report" in html

    @allure.title("HTML-escapes angle brackets in the content")
    def test_escapes_html(self):
        html = convert_text_to_html("danger <script>alert(1)</script> end")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    @allure.title("Source Document header is reflected in the title")
    def test_source_document_from_content(self):
        html = convert_text_to_html("Source Document: My Policy\n\nBody text.")
        assert "My Policy" in html

    @allure.title("Explicit source_document overrides title")
    def test_explicit_source_document(self):
        html = convert_text_to_html("Body.", title="Rpt", source_document="DocX")
        assert "DocX" in html

    @allure.title("Handles empty content without raising")
    def test_empty_content(self):
        html = convert_text_to_html("")
        assert isinstance(html, str) and "<html" in html.lower()


@allure.feature("Pipeline reporting")
@allure.story("File conversion")
class TestConvertReportFile:
    @allure.title("Writes an .html file next to the source by default")
    def test_writes_html_file(self, tmp_path):
        src = tmp_path / "report.txt"
        src.write_text("Source Document: ACME\n\nSome findings.", encoding="utf-8")
        out = convert_report_file(src)
        assert out.exists()
        assert out.suffix == ".html"
        assert "ACME" in out.read_text(encoding="utf-8")

    @allure.title("Honors an explicit output path")
    def test_explicit_output_path(self, tmp_path):
        src = tmp_path / "in.txt"
        src.write_text("hello", encoding="utf-8")
        dest = tmp_path / "out.html"
        out = convert_report_file(src, dest)
        assert out == dest and dest.exists()
