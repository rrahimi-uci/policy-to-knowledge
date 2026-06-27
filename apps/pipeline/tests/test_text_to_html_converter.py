"""Unit tests for the plain-text -> HTML report converter."""
import sys
from pathlib import Path

import allure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.text_to_html_converter import (  # noqa: E402
    convert_text_to_html,
    convert_report_file,
    convert_all_optimization_reports,
)


RICH_REPORT = """\
========================================
COMPLIANCE KNOWLEDGE GRAPH OPTIMIZATION REPORT
========================================
Source Document: Fancy <Policy> & Co
Generated: 2026-06-27
Model: gpt-4o-mini

Optimization Summary:
  Total Rules: 197
  Duplicates Removed: 12

EXECUTIVE OVERVIEW
----------------------------------------
This is a sentence. Another sentence follows here.

Strategy:
- first bullet item
- second bullet item

Duplicate Group 1
  Rationale: These rules overlap heavily. They were merged into one.
  Enhanced Description: A combined rule covering both cases.
  Severity: high

Duplicate Group 2
  Note: trivial

A trailing paragraph.
"""


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

    @allure.title("Raises FileNotFoundError for a missing input file")
    def test_missing_input(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            convert_report_file(tmp_path / "ghost.txt")

    @allure.title("Derives the source document from a pipeline-output path")
    def test_source_from_pipeline_path(self, tmp_path):
        d = tmp_path / "pipeline-output" / "bank_a" / "agent-5-optimized"
        d.mkdir(parents=True)
        infile = d / "optimization_report.txt"
        infile.write_text(RICH_REPORT, encoding="utf-8")
        out = convert_report_file(infile)
        assert out.exists()
        assert "bank_a -" in out.read_text(encoding="utf-8")


@allure.feature("Pipeline reporting")
@allure.story("Rich section rendering")
class TestRichRendering:
    @allure.title("All section types render and HTML is escaped")
    def test_full_report(self):
        html = convert_text_to_html(RICH_REPORT, title="Demo", source_document="Bank A")
        assert 'class="metadata source-document"' in html
        assert 'class="summary-item"' in html and "Total Rules" in html
        assert 'class="section-title"' in html and "EXECUTIVE OVERVIEW" in html
        assert 'class="subsection-title"' in html        # "Strategy:"
        assert 'class="list-item"' in html               # bullet points
        assert 'class="duplicate-group"' in html
        # The source-document header line is rendered as metadata
        assert "Fancy" in html
        assert "&lt;Policy&gt;" in html and "&amp;" in html
        assert "<Policy>" not in html


@allure.feature("Pipeline reporting")
@allure.story("Batch conversion")
class TestConvertAll:
    @allure.title("Returns [] when no optimization reports are present")
    def test_none_found(self, tmp_path):
        assert convert_all_optimization_reports(tmp_path) == []

    @allure.title("Converts every matching optimization report")
    def test_converts_matches(self, tmp_path):
        d = tmp_path / "g" / "agent-5-optimized"
        d.mkdir(parents=True)
        (d / "x_optimization_report.txt").write_text(RICH_REPORT, encoding="utf-8")
        out = convert_all_optimization_reports(tmp_path)
        assert len(out) == 1 and out[0].exists()
