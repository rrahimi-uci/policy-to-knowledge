"""The HTML report and the marks it is built from.

Colour correctness was established once, with a validator, and recorded in
:mod:`visualization.palette`; these tests guard the properties that code can regress —
that every categorical slot is filled, that identity is never carried by hue alone,
that a table view exists, that dark mode is declared for both the media query and the
explicit attribute, and that the caps on the graph and the table are stated on the page
rather than applied silently.
"""

from __future__ import annotations

import re

import pytest

from policy_ir.enums import Status
from validation.evidence_gate import run_gate
from visualization import palette as pal
from visualization.charts import Slice, bar_rows, funnel_rows, stacked_bar, stat_tile
from visualization.report import (
    MAX_GRAPH_CLAUSES,
    MAX_TABLE_ROWS,
    ReportData,
    build_report,
    write_report,
)


@pytest.fixture
def report_html(fixtures):
    """A report built over a real fixture IR and a real gate run."""
    fixture = fixtures["eligibility_decision"]
    gate = run_gate(fixture.ir, fixture.texts)
    data = ReportData(
        title="Eligibility Decision",
        ir=fixture.ir,
        gate=gate.to_dict(),
        graph={},
        ingestion={"pages": 3, "chunks": 2, "canonical_chars": 900},
        generated_at="01 January 2026 00:00 UTC",
    )
    return build_report(data)


# ------------------------------------------------------------------- the palette


def test_every_modality_has_a_colour_in_both_modes() -> None:
    """A missing slot would fall through to a default and lose its identity."""
    for name in pal.MODALITY_ORDER:
        assert name in pal.MODALITY_LIGHT
        assert name in pal.MODALITY_DARK


def test_modality_colours_are_distinct_within_a_mode() -> None:
    for mapping in (pal.MODALITY_LIGHT, pal.MODALITY_DARK):
        values = [mapping[name] for name in pal.MODALITY_ORDER]
        assert len(set(values)) == len(values)


def test_dark_mode_is_a_separate_selection_not_a_flip() -> None:
    """Dark steps are chosen against the dark surface; identical values would mean
    the light ramp was reused unchanged."""
    assert pal.MODALITY_LIGHT != pal.MODALITY_DARK
    assert pal.SURFACE_LIGHT != pal.SURFACE_DARK


def test_status_colours_are_not_reused_as_categorical_slots() -> None:
    """Status hues are reserved; reusing one for a series would overload its meaning."""
    categorical = set(pal.MODALITY_LIGHT.values()) | set(pal.NODE_LIGHT.values())
    assert not categorical & set(pal.STATUS.values())


def test_every_coverage_state_ships_an_icon_alongside_its_colour() -> None:
    """State must be readable without colour, so each carries a glyph and a label."""
    for _key, label, colour, icon in pal.COVERAGE_STATES:
        assert label.strip()
        assert colour.startswith("#")
        assert icon.strip()


def test_node_shapes_cover_every_node_colour() -> None:
    for name in pal.NODE_LIGHT:
        assert name in pal.NODE_SHAPES


# --------------------------------------------------------------------- the marks


def test_stat_tile_renders_its_value_and_label() -> None:
    html = stat_tile("Clauses", "1,024", "evidenced")
    assert "1,024" in html and "Clauses" in html and "evidenced" in html


def test_stacked_bar_segments_sum_to_one_hundred_percent() -> None:
    html = stacked_bar([Slice("a", 30, "#111"), Slice("b", 70, "#222")])
    widths = [float(w) for w in re.findall(r"width:\s*([0-9.]+)%", html)]
    assert widths and abs(sum(widths) - 100.0) < 0.5


def test_stacked_bar_survives_an_all_zero_total() -> None:
    """An empty corpus must say so, not divide by zero and not draw a false bar."""
    html = stacked_bar([Slice("a", 0, "#111"), Slice("b", 0, "#222")])
    assert "empty" in html
    assert "%" not in html


def test_stacked_segments_are_separated_by_a_surface_gap(report_html) -> None:
    """Adjacent fills need a 2px surface gap or they read as one continuous mark.

    The gap is a property of the page stylesheet, not of the fragment, so it is
    asserted where it is actually declared.
    """
    css = report_html[report_html.index(".stack{"):]
    assert "gap:2px" in css[:200].replace("gap: 2px", "gap:2px")


def test_stacked_bar_legend_names_every_slice() -> None:
    """Identity is never colour-alone: the legend carries the label too."""
    html = stacked_bar([Slice("obligation", 5, "#111"), Slice("permission", 2, "#222")])
    assert "obligation" in html and "permission" in html


def test_bar_rows_direct_labels_every_bar() -> None:
    html = bar_rows([Slice("alpha", 12, "#111"), Slice("beta", 3, "#111")])
    assert "alpha" in html and "12" in html
    assert "beta" in html and "3" in html


def test_bar_rows_scales_to_the_largest_value() -> None:
    html = bar_rows([Slice("big", 100, "#111"), Slice("small", 50, "#111")])
    widths = [float(w) for w in re.findall(r"width:\s*([0-9.]+)%", html)]
    assert max(widths) == pytest.approx(100.0, abs=0.5)
    assert min(widths) == pytest.approx(50.0, abs=1.0)


def test_bar_rows_handles_an_empty_series() -> None:
    assert isinstance(bar_rows([]), str)


def test_funnel_rows_are_monotonically_descending() -> None:
    """A funnel whose stages grew would be reporting an impossible subset."""
    html = funnel_rows([Slice("all", 100, "#111"), Slice("some", 40, "#111"),
                        Slice("few", 10, "#111")])
    widths = [float(w) for w in re.findall(r"width:\s*([0-9.]+)%", html)]
    assert widths == sorted(widths, reverse=True)


def test_funnel_uses_one_hue_because_order_is_carried_by_length() -> None:
    """An ordinal colour ramp failed the adjacent-pair check; length carries order."""
    html = funnel_rows([Slice(f"s{n}", 100 - n * 10, pal.SERIES_LIGHT) for n in range(6)])
    hues = set(re.findall(r"background:\s*(#[0-9a-fA-F]{6})", html))
    assert len(hues) <= 1


# -------------------------------------------------------------------- the report


def test_report_is_a_complete_html_document(report_html) -> None:
    assert report_html.lstrip().startswith("<!DOCTYPE html>")
    assert report_html.rstrip().endswith("</html>")
    assert "<title>" in report_html


def test_report_declares_dark_mode_for_both_the_query_and_the_attribute(
    report_html,
) -> None:
    """A viewer on system-dark stamps no attribute; a toggle stamps one. Both must work."""
    assert "prefers-color-scheme: dark" in report_html.replace("prefers-color-scheme:dark",
                                                               "prefers-color-scheme: dark")
    assert '[data-theme="dark"]' in report_html


def test_report_never_defines_a_colour_only_in_a_dark_block(report_html) -> None:
    """Every token needs a light definition on bare :root or system-light loses it."""
    assert ":root{" in report_html.replace(":root {", ":root{")


def test_report_contains_a_table_view_of_the_clauses(report_html, fixtures) -> None:
    """The accessibility requirement: the same data readable without any chart."""
    assert "<table" in report_html
    for clause in fixtures["eligibility_decision"].ir.clauses:
        assert clause.clause_id[:26] in report_html


def test_report_quotes_the_exact_cited_text_with_its_offsets(report_html, fixtures) -> None:
    """Provenance is the point; the report shows the bytes, not just a reference."""
    ir = fixtures["eligibility_decision"].ir
    span = ir.evidence_spans[0]
    assert f"{span.char_start:,}" in report_html
    assert span.exact_text[:40] in report_html


def test_report_states_what_this_run_does_not_establish(report_html) -> None:
    """Conformance is not semantic support and neither is governance approval."""
    lowered = report_html.lower()
    assert "governance" in lowered
    assert "not a legal reading" in lowered


def test_report_names_each_modality_present_in_the_ir(report_html, fixtures) -> None:
    for clause in fixtures["eligibility_decision"].ir.clauses:
        assert clause.modality.value in report_html


def test_report_reports_its_caps_rather_than_truncating_silently(fixtures) -> None:
    """A capped view that says nothing reads as "this is everything"."""
    fixture = fixtures["eligibility_decision"]
    gate = run_gate(fixture.ir, fixture.texts)
    data = ReportData(title="T", ir=fixture.ir, gate=gate.to_dict(), graph={})
    html = build_report(data)
    assert "Showing all" in html or "omitted" in html


def test_the_graph_payload_is_embedded_as_json(report_html) -> None:
    assert '"nodes"' in report_html and '"edges"' in report_html


def test_the_graph_carries_shape_as_well_as_colour(report_html) -> None:
    """Two channels for node type, so the view survives a colour-blind reader."""
    assert '"shape"' in report_html
    assert any(shape in report_html for shape in pal.NODE_SHAPES.values())


def test_the_report_degrades_without_the_graph_library(report_html) -> None:
    """Every panel but the graph is inert HTML; say so instead of showing a blank box."""
    assert "typeof vis === 'undefined'" in report_html
    assert "renders offline" in report_html


def test_gate_statuses_reach_the_page(report_html) -> None:
    assert Status.PROVENANCE_EXACT.value.replace("_", " ") in report_html.lower()


def test_write_report_creates_the_file_and_its_parent(tmp_path, fixtures) -> None:
    fixture = fixtures["eligibility_decision"]
    gate = run_gate(fixture.ir, fixture.texts)
    data = ReportData(title="T", ir=fixture.ir, gate=gate.to_dict(), graph={})
    target = tmp_path / "nested" / "report.html"
    written = write_report(data, target)
    assert written == target
    assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_the_caps_are_positive(fixtures) -> None:
    assert MAX_GRAPH_CLAUSES > 0 and MAX_TABLE_ROWS > 0


def test_report_escapes_text_from_the_source_document(fixtures) -> None:
    """Policy text is untrusted input to the page; an unescaped angle bracket is a bug."""
    from dataclasses import replace

    fixture = fixtures["eligibility_decision"]
    ir = fixture.ir
    hostile = '<script>alert("x")</script>'
    clauses = list(ir.clauses)
    clauses[0] = replace(clauses[0], display_text=hostile)
    ir = replace(ir, clauses=tuple(clauses))
    gate = run_gate(ir, fixture.texts)
    html = build_report(ReportData(title="T", ir=ir, gate=gate.to_dict(), graph={}))
    assert hostile not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------- the semantic and governance panels


def _report_with(fixtures, **extra):
    fixture = fixtures["eligibility_decision"]
    gate = run_gate(fixture.ir, fixture.texts)
    return build_report(ReportData(title="T", ir=fixture.ir, gate=gate.to_dict(),
                                   graph={}, **extra))


def test_the_semantic_panel_says_a_graph_only_clause_is_not_a_gap(fixtures) -> None:
    """The number most likely to be misread; the page has to say what it means."""
    html = _report_with(fixtures, semantic={
        "clauses_with_no_declared_projection": 12, "semantic_relations": 3,
        "by_target": {"dmn": {"ready_for_explicit_model": 2, "abstain": 5}},
        "missing_by_field": {"condition_ast": 4},
    })
    assert "Graph-only clauses" in html
    assert "12" in html
    assert "by design" in html


def test_the_semantic_panel_names_what_each_abstention_lacked(fixtures) -> None:
    html = _report_with(fixtures, semantic={
        "clauses_with_no_declared_projection": 0, "semantic_relations": 0,
        "by_target": {"dmn": {"abstain": 7}},
        "missing_by_field": {"condition_ast": 4, "effect_evidence": 3},
    })
    assert "condition ast" in html
    assert "effect evidence" in html


def test_the_governance_panel_frames_refusals_as_a_queue_not_a_bug_list(fixtures) -> None:
    html = _report_with(fixtures, governance={
        "review_items": 9, "review_items_by_kind": {"clause": 6, "synthesis": 3},
    })
    assert "Queued for human review" in html
    assert "not a list of bugs" in html
    assert "9" in html


def test_the_panels_are_omitted_when_their_stage_did_not_run(fixtures) -> None:
    """A partial run must still render, without an empty panel implying zero."""
    html = _report_with(fixtures)
    assert "The semantic layer" not in html
    assert "Queued for human review" not in html


def test_the_report_renders_with_every_stage_absent_but_the_ir(fixtures) -> None:
    """The visualization stage must not require a full pipeline to have run."""
    fixture = fixtures["eligibility_decision"]
    html = build_report(ReportData(title="T", ir=fixture.ir, gate={}, graph={}))
    assert html.lstrip().startswith("<!DOCTYPE html>")
