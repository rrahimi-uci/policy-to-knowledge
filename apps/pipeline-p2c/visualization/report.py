"""Build the HTML report over a compiled policy knowledge graph.

The page answers four questions in order, because that is the order a reader needs them:
how much of the source was read, what was found in it, what can be executed, and where
any single clause came from. Colour carries meaning throughout — never decoration — and
every palette was validated against both surfaces before a line of chart code was
written (see :mod:`visualization.palette`).

Two honest constraints are surfaced in the page itself rather than hidden:

* the graph and the table are **capped**, and the caps say what they dropped;
* ``conformance_verified`` is not ``semantically_supported`` and neither is
  ``governance_approved`` — the footer states which of the three this run establishes.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from policy_ir.enums import Status
from policy_ir.models import PolicyIR

from . import palette as pal
from .charts import Slice, bar_rows, stacked_bar, stat_tile

#: vis-network renders the node-link view. Loaded from a CDN, exactly as the existing
#: pipeline report does, which means the file needs network to draw the graph; every
#: other panel is inert HTML and renders offline.
VIS_NETWORK_CDN = "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"

MAX_GRAPH_CLAUSES = 350
MAX_TABLE_ROWS = 250


@dataclass
class ReportData:
    """Everything the page needs, gathered from the stage artefacts."""

    title: str
    ir: PolicyIR
    gate: Mapping[str, Any]
    graph: Mapping[str, Any]
    stages: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    model: Mapping[str, Any] = field(default_factory=dict)
    ingestion: Mapping[str, Any] = field(default_factory=dict)
    semantic: Mapping[str, Any] = field(default_factory=dict)
    governance: Mapping[str, Any] = field(default_factory=dict)
    dmn_ids: Sequence[str] = field(default_factory=tuple)
    bpmn_ids: Sequence[str] = field(default_factory=tuple)
    generated_at: str = ""


def _clause_statuses(data: ReportData) -> dict[str, set[str]]:
    """Map clause id to the set of statuses the gate granted it."""
    return {
        clause_id: set(entry.get("statuses", ()))
        for clause_id, entry in (data.gate.get("clauses") or {}).items()
    }


def _coverage_slices(data: ReportData) -> list[Slice]:
    counts: dict[str, int] = {}
    for entry in data.ir.coverage:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return [
        Slice(label=label, value=counts.get(key, 0), colour=colour, icon=icon)
        for key, label, colour, icon in pal.COVERAGE_STATES
    ]


def _modality_slices(data: ReportData) -> list[Slice]:
    counts: dict[str, int] = {}
    for clause in data.ir.clauses:
        counts[clause.modality.value] = counts.get(clause.modality.value, 0) + 1
    return [
        Slice(
            label=name.replace("_", " "),
            value=counts.get(name, 0),
            colour=pal.MODALITY_LIGHT[name],
            note=f"{name}: {counts.get(name, 0):,} clauses",
        )
        for name in pal.MODALITY_ORDER
    ]


def _status_slices(data: ReportData) -> list[Slice]:
    """The six statuses, as independent proportions of all clauses.

    They are deliberately *not* a funnel. The app grants each status on its own
    evidence, so a clause can have exact provenance and still be ineligible for DMN, and
    ``provenance_exact`` at 100% sitting below ``schema_valid`` at 54% is not an anomaly.
    Drawing them as a funnel asserted a nesting that does not exist.
    """
    statuses = _clause_statuses(data)
    total = len(data.ir.clauses)

    def having(status: Status) -> int:
        return sum(1 for granted in statuses.values() if status.value in granted)

    stages = (
        ("Clauses admitted", total, "every clause the extractor proposed and the app admitted"),
        ("Schema valid", having(Status.SCHEMA_VALID), "required fields present, vocabularies known"),
        ("Provenance exact", having(Status.PROVENANCE_EXACT),
         "every cited span matches its document hash at its offsets"),
        ("Semantically supported", having(Status.SEMANTIC_SUPPORTED),
         "types check, values and modality attested, references resolve"),
        ("DMN eligible", having(Status.DMN_ELIGIBLE), "may become a decision-table row"),
        ("BPMN eligible", having(Status.BPMN_ELIGIBLE), "may become a flow node"),
    )
    return [
        Slice(label, float(value), pal.SERIES_LIGHT, note=note)
        for label, value, note in stages
    ]


def _blocker_slices(data: ReportData) -> list[Slice]:
    counts = data.gate.get("blocker_counts") or {}
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    return [
        Slice(label=code.replace("_", " "), value=float(count), colour=pal.SERIES_LIGHT,
              note=f"{code}: {count:,}")
        for code, count in ordered
    ]


def _graph_payload(data: ReportData) -> tuple[dict[str, Any], dict[str, int]]:
    """Nodes and edges for the node-link view, capped and reported.

    Structure is document → section → clause, which is the graph the IR actually has.
    Node *shape* carries type alongside colour, so identity never rests on hue alone.
    """
    spans = data.ir.evidence_index()
    statuses = _clause_statuses(data)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_sections: dict[str, str] = {}

    for document in data.ir.documents:
        node_id = f"doc::{document.document_id}"
        nodes.append({
            "id": node_id,
            "label": Path(document.source_uri).name or document.document_id,
            "title": (f"Document\n{document.source_uri}\n"
                      f"bytes sha256 {document.source_sha256[:16]}…\n"
                      f"text sha256 {document.canonical_text_sha256[:16]}…\n"
                      f"parser {document.parser_version}"),
            "shape": pal.NODE_SHAPES["document"],
            "color": pal.NODE_LIGHT["document"], "size": 26, "font": {"size": 18},
        })

    clauses = list(data.ir.clauses)
    shown = clauses[:MAX_GRAPH_CLAUSES]
    for clause in shown:
        section = ""
        for evidence_id in clause.all_evidence_ids():
            span = spans.get(evidence_id)
            if span is not None and span.section_path:
                section = span.section_path
                break
        if section and section not in seen_sections:
            section_id = f"sec::{section}"
            seen_sections[section] = section_id
            nodes.append({
                "id": section_id, "label": section,
                "title": f"Section\n{section}",
                "shape": pal.NODE_SHAPES["section"],
                "color": pal.NODE_LIGHT["section"], "size": 16,
            })
            for document in data.ir.documents:
                edges.append({"from": f"doc::{document.document_id}", "to": section_id,
                              "length": 260})
        granted = statuses.get(clause.clause_id, set())
        badge = ("DMN" if Status.DMN_ELIGIBLE.value in granted
                 else "graph only" if Status.GRAPH_ELIGIBLE.value in granted else "blocked")
        nodes.append({
            "id": f"cl::{clause.clause_id}",
            "label": clause.display_text[:44] + ("…" if len(clause.display_text) > 44 else ""),
            "title": (f"{clause.modality.value} · {clause.semantic_kind.value}\n"
                      f"{clause.display_text[:400]}\n\nstatus: {badge}\n"
                      f"clause {clause.clause_id}"),
            "shape": pal.NODE_SHAPES["clause"],
            "color": pal.NODE_LIGHT["clause"], "size": 10, "font": {"size": 11},
        })
        if section:
            edges.append({"from": seen_sections[section], "to": f"cl::{clause.clause_id}"})

    caps = {"clauses_total": len(clauses), "clauses_shown": len(shown),
            "clauses_omitted": max(0, len(clauses) - len(shown)),
            "sections": len(seen_sections), "nodes": len(nodes), "edges": len(edges)}
    return {"nodes": nodes, "edges": edges}, caps


def _clause_rows(data: ReportData) -> tuple[str, int]:
    """The table view: a clause, its verdict, and the exact bytes it cites."""
    spans = data.ir.evidence_index()
    statuses = _clause_statuses(data)
    rows = []
    for clause in data.ir.clauses[:MAX_TABLE_ROWS]:
        granted = statuses.get(clause.clause_id, set())
        badge_class = ("ok" if Status.DMN_ELIGIBLE.value in granted
                       else "warn" if Status.GRAPH_ELIGIBLE.value in granted else "bad")
        badge = ("DMN eligible" if Status.DMN_ELIGIBLE.value in granted
                 else "graph only" if Status.GRAPH_ELIGIBLE.value in granted else "blocked")
        cited = []
        for role in sorted(clause.evidence):
            for evidence_id in clause.evidence[role]:
                span = spans.get(evidence_id)
                if span is None:
                    continue
                cited.append(
                    f'<div class="cite"><span class="role">{escape(role)}</span>'
                    f'<span class="offsets">[{span.char_start:,}–{span.char_end:,}]</span>'
                    f'<span class="quote">{escape(span.exact_text[:190])}</span></div>'
                )
        rows.append(
            "<tr>"
            f'<td class="mono">{escape(clause.clause_id[:26])}</td>'
            f'<td><span class="pill mod-{escape(clause.modality.value)}">'
            f'{escape(clause.modality.value)}</span></td>'
            f"<td>{escape(clause.semantic_kind.value.replace('_',' '))}</td>"
            f'<td class="statement">{escape(clause.display_text[:260])}</td>'
            f'<td><span class="badge {badge_class}">{escape(badge)}</span></td>'
            f'<td class="cites">{"".join(cited) or "<em>none</em>"}</td>'
            "</tr>"
        )
    return "".join(rows), len(data.ir.clauses)


def _stage_table(data: ReportData) -> str:
    if not data.stages:
        return ""
    rows = "".join(
        "<tr>"
        f'<td class="mono">{escape(str(stage.get("stage","")))}</td>'
        f'<td>{stage.get("files_written", 0):,}</td>'
        f'<td>{stage.get("elapsed_seconds", 0):,.1f}s</td>'
        f'<td class="mono small">{escape(json.dumps(stage.get("summary", {}))[:220])}</td>'
        "</tr>"
        for stage in data.stages
    )
    return (
        '<table class="grid"><thead><tr><th>Stage</th><th>Files</th><th>Elapsed</th>'
        f"<th>Summary</th></tr></thead><tbody>{rows}</tbody></table>"
    )



def _stage_path(name: str) -> str:
    """``NN_stage`` for a stage, read from the stage table rather than written by hand."""
    from pipeline.stages import STAGE_BY_NAME

    number, _ = STAGE_BY_NAME[name]
    return f"{number:02d}_{name}"


def _semantic_panel(data: ReportData) -> str:
    """What the semantic layer found, including what it deliberately did not claim.

    The important number here is the one that is easy to misread as a failure:
    clauses with no declared projection. A definition, an entity or a constraint
    belongs in the knowledge graph and nowhere else. It is not a missing workflow.
    """
    semantic = data.semantic or {}
    if not semantic:
        return ""
    missing = semantic.get("missing_by_field") or {}
    by_target = semantic.get("by_target") or {}
    ready = sum(counts.get("ready_for_explicit_model", 0) for counts in by_target.values())
    abstained = sum(counts.get("abstain", 0) for counts in by_target.values())
    tiles = "".join([
        stat_tile("Graph-only clauses",
                  f"{semantic.get('clauses_with_no_declared_projection', 0):,}",
                  "no projection declared — by design, not a gap"),
        stat_tile("Ready to project", f"{ready:,}", "every required field is present"),
        stat_tile("Abstained", f"{abstained:,}", "intent declared, a field still missing"),
        stat_tile("Semantic relations", f"{semantic.get('semantic_relations', 0):,}",
                  "typed edges between clauses"),
    ])
    gaps = bar_rows(
        [Slice(label=name.replace("_", " "), value=float(count), colour=pal.SERIES_LIGHT,
               note=f"{name}: {count:,}")
         for name, count in sorted(missing.items(), key=lambda item: -item[1])]
    ) if missing else '<p class="empty">Nothing missing.</p>'
    return (
        '<section class="panel"><h2>The semantic layer</h2>'
        '<p class="lede">The knowledge graph is the representation; DMN and BPMN are '
        'projections of the subset that qualifies for them. A clause that projects to '
        'neither is still a full member of the graph.</p>'
        f'<div class="tiles">{tiles}</div>'
        '<h3>What an abstention was waiting for</h3>'
        f'{gaps}</section>'
    )


def _governance_panel(data: ReportData) -> str:
    """The reviewer queue. A refusal that is only a log line is not actionable."""
    governance = data.governance or {}
    if not governance:
        return ""
    by_kind = governance.get("review_items_by_kind") or {}
    rows = bar_rows(
        [Slice(label=kind.replace("_", " "), value=float(count), colour=pal.SERIES_LIGHT,
               note=f"{kind}: {count:,}")
         for kind, count in sorted(by_kind.items(), key=lambda item: -item[1])]
    ) if by_kind else '<p class="empty">Nothing queued for review.</p>'
    return (
        '<section class="panel"><h2>Queued for human review</h2>'
        f'<p class="lede">{governance.get("review_items", 0):,} items a reviewer can act '
        'on, each carrying its own named reason. This is the output of a fail-closed '
        'gate, not a list of bugs.</p>'
        f'{rows}</section>'
    )


def build_report(data: ReportData) -> str:
    """Render the complete page."""
    graph_payload, caps = _graph_payload(data)
    table_rows, clause_total = _clause_rows(data)
    coverage = _coverage_slices(data)
    modality = _modality_slices(data)
    statuses = _status_slices(data)
    blockers = _blocker_slices(data)
    generated = data.generated_at or _dt.datetime.now(_dt.timezone.utc).strftime(
        "%d %B %Y %H:%M UTC"
    )
    ingestion = data.ingestion or {}
    model = data.model or {}
    usage = model.get("usage") or {}

    tiles = "".join([
        stat_tile("Pages read", f"{ingestion.get('pages', 0):,}",
                  f"{ingestion.get('canonical_chars', 0):,} canonical characters"),
        stat_tile("Chunks", f"{ingestion.get('chunks', 0):,}", "section-aligned"),
        stat_tile("Clauses", f"{len(data.ir.clauses):,}", "evidenced and admitted"),
        stat_tile("Evidence spans", f"{len(data.ir.evidence_spans):,}",
                  "hash-anchored citations"),
        stat_tile("DMN decisions", f"{len(data.dmn_ids):,}", "executable subset"),
        stat_tile("BPMN processes", f"{len(data.bpmn_ids):,}", "executable subset"),
    ])
    model_tiles = "".join([
        stat_tile("Model", str(model.get("model", "—")),
                  f"reasoning effort: {model.get('reasoning_effort', '—')}"),
        stat_tile("Chunks sent", f"{model.get('requests_attempted', 0):,}",
                  f"of {model.get('requests_available', 0):,} available"),
        stat_tile("Input tokens", f"{usage.get('input_tokens', 0):,}",
                  f"{usage.get('calls', 0):,} calls"),
        stat_tile("Output tokens", f"{usage.get('output_tokens', 0):,}",
                  f"{usage.get('reasoning_tokens', 0):,} reasoning"),
    ]) if model else ""

    # Paths are derived from the stage table, never written out by hand: renumbering the
    # stages once left this caption pointing at a directory that no longer existed.
    clauses_path = f"{_stage_path('admission')}/clauses.json"
    graph_path = f"{_stage_path('projection')}/graph-v2.json"
    omitted_note = (
        f'<p class="cap">Showing {caps["clauses_shown"]:,} of {caps["clauses_total"]:,} '
        f'clauses ({caps["clauses_omitted"]:,} omitted to keep the graph legible). '
        f"The full set is in <code>{escape(clauses_path)}</code> and "
        f"<code>{escape(graph_path)}</code>.</p>"
        if caps["clauses_omitted"] else
        f'<p class="cap">Showing all {caps["clauses_shown"]:,} clauses.</p>'
    )
    table_note = (
        f'<p class="cap">First {MAX_TABLE_ROWS:,} of {clause_total:,} clauses. '
        f"The complete table is <code>{escape(clauses_path)}</code>.</p>"
        if clause_total > MAX_TABLE_ROWS else ""
    )

    return _PAGE.format(
        title=escape(data.title),
        generated=escape(generated),
        source=escape(", ".join(Path(d.source_uri).name for d in data.ir.documents) or "—"),
        parser=escape(data.ir.documents[0].parser_version if data.ir.documents else "—"),
        text_hash=escape(data.ir.documents[0].canonical_text_sha256[:24] + "…"
                         if data.ir.documents else "—"),
        tiles=tiles,
        model_section=(
            f'<section class="panel"><h2>Model extraction</h2>'
            f'<div class="tiles">{model_tiles}</div></section>' if model_tiles else ""
        ),
        coverage=stacked_bar(coverage),
        modality=bar_rows(modality),
        statuses=bar_rows(
            statuses, max_value=float(len(data.ir.clauses)) or None, keep_zeros=True
        ),
        semantic_panel=_semantic_panel(data),
        governance_panel=_governance_panel(data),
        blockers=(
            f'<section class="panel"><h2>Why clauses were refused</h2>'
            f'<p class="lede">Every refusal is a named, machine-readable reason. An '
            f'abstention is a designed outcome, not a gap.</p>{bar_rows(blockers)}</section>'
            if blockers else
            '<section class="panel"><h2>Why clauses were refused</h2>'
            '<p class="empty">No blockers — every admitted clause passed every check.</p></section>'
        ),
        graph_json=json.dumps(graph_payload),
        graph_caps=omitted_note,
        node_legend="".join(
            f'<li><span class="chip" style="background:{colour}" aria-hidden="true"></span>'
            f'<span class="chip-shape" aria-hidden="true">{shape}</span>'
            f'<span class="chip-label">{escape(name)}</span></li>'
            for name, colour, shape in (
                ("Document", pal.NODE_LIGHT["document"], "◆"),
                ("Section", pal.NODE_LIGHT["section"], "■"),
                ("Clause", pal.NODE_LIGHT["clause"], "●"),
            )
        ),
        table_rows=table_rows,
        table_note=table_note,
        stage_table=_stage_table(data),
        vis_cdn=VIS_NETWORK_CDN,
        surface_light=pal.SURFACE_LIGHT, surface_dark=pal.SURFACE_DARK,
        ink_light=pal.INK_LIGHT, ink_dark=pal.INK_DARK,
        muted_light=pal.MUTED_LIGHT, muted_dark=pal.MUTED_DARK,
        grid_light=pal.GRID_LIGHT, grid_dark=pal.GRID_DARK,
        series_light=pal.SERIES_LIGHT, series_dark=pal.SERIES_DARK,
        mod_css="".join(
            f".pill.mod-{name}{{background:{pal.MODALITY_LIGHT[name]}22;"
            f"color:{pal.MODALITY_LIGHT[name]};border-color:{pal.MODALITY_LIGHT[name]}55}}"
            for name in pal.MODALITY_ORDER
        ),
    )


def write_report(data: ReportData, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(data), encoding="utf-8")
    return path


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Policy Knowledge Graph</title>
<script src="{vis_cdn}"></script>
<style>
  *,*::before,*::after{{box-sizing:border-box}}
  :root{{
    --surface:{surface_light}; --panel:#ffffff; --ink:{ink_light}; --muted:{muted_light};
    --grid:{grid_light}; --series:{series_light}; --shadow:0 1px 2px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.05);
    color-scheme:light;
  }}
  @media (prefers-color-scheme:dark){{
    :root:not([data-theme="light"]){{
      --surface:{surface_dark}; --panel:#232321; --ink:{ink_dark}; --muted:{muted_dark};
      --grid:{grid_dark}; --series:{series_dark}; --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
      color-scheme:dark;
    }}
  }}
  :root[data-theme="dark"]{{
    --surface:{surface_dark}; --panel:#232321; --ink:{ink_dark}; --muted:{muted_dark};
    --grid:{grid_dark}; --series:{series_dark}; color-scheme:dark;
  }}
  body{{margin:0;background:var(--surface);color:var(--ink);
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:1240px;margin:0 auto;padding:32px 24px 72px}}
  header.top{{margin-bottom:28px}}
  .eyebrow{{font-size:12px;letter-spacing:.10em;text-transform:uppercase;color:var(--muted);
    font-weight:650}}
  h1{{margin:.25rem 0 .5rem;font-size:clamp(26px,3.6vw,40px);line-height:1.12;letter-spacing:-.02em}}
  .sub{{color:var(--muted);max-width:76ch}}
  .meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}}
  .meta span{{font:12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);
    border:1px solid var(--grid);border-radius:999px;padding:6px 10px;background:var(--panel)}}
  .panel{{background:var(--panel);border:1px solid var(--grid);border-radius:14px;
    padding:22px 24px;margin:18px 0;box-shadow:var(--shadow)}}
  h2{{margin:0 0 4px;font-size:17px;letter-spacing:-.01em}}
  h3{{margin:22px 0 10px;font-size:13px;letter-spacing:.04em;text-transform:uppercase;
    color:var(--muted);font-weight:650}}
  .lede{{margin:0 0 16px;color:var(--muted);font-size:13.5px;max-width:80ch}}
  .two{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}}
  .two>.panel{{margin:0}}
  .tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px}}
  .tile{{border:1px solid var(--grid);border-radius:12px;padding:14px 16px;background:var(--panel)}}
  .tile-value{{font-size:26px;font-weight:680;letter-spacing:-.02em;
    font-variant-numeric:tabular-nums}}
  .tile-label{{font-size:12.5px;color:var(--muted);margin-top:2px}}
  .tile-note{{font-size:11.5px;color:var(--muted);opacity:.8;margin-top:6px}}
  .stack{{display:flex;height:26px;border-radius:6px;overflow:hidden;background:var(--grid);
    gap:2px}}
  .stack .seg:first-child{{border-radius:6px 0 0 6px}}
  .stack .seg:last-child{{border-radius:0 6px 6px 0}}
  .legend{{list-style:none;display:flex;flex-wrap:wrap;gap:6px 22px;margin:14px 0 0;padding:0}}
  .legend li{{display:flex;align-items:center;gap:8px;font-size:13px}}
  .chip{{width:11px;height:11px;border-radius:3px;flex:0 0 auto}}
  .chip-icon,.chip-shape{{color:var(--muted);font-size:11px;width:1em;text-align:center}}
  .chip-label{{color:var(--ink)}}
  .chip-value{{color:var(--muted);font-variant-numeric:tabular-nums}}
  .chip-pct{{opacity:.7}}
  .bars{{display:grid;gap:8px}}
  .row{{display:grid;grid-template-columns:minmax(120px,190px) 1fr auto;align-items:center;gap:12px}}
  .row-label{{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}}
  .row-track{{background:var(--grid);border-radius:4px;height:14px;overflow:hidden}}
  .row-fill{{height:100%;border-radius:0 4px 4px 0;transition:width .2s ease}}
  .row-value{{font:13px/1 ui-monospace,Menlo,monospace;color:var(--muted);
    font-variant-numeric:tabular-nums;min-width:5ch;text-align:right}}
  .row-pct{{display:inline-block;margin-left:8px;opacity:.65}}
  .funnel .row-fill{{opacity:1}}
  #graph{{height:620px;border:1px solid var(--grid);border-radius:12px;background:var(--surface)}}
  .cap{{font-size:12.5px;color:var(--muted);margin:12px 0 0}}
  .tablewrap{{overflow-x:auto;border:1px solid var(--grid);border-radius:12px;margin-top:14px}}
  table{{border-collapse:collapse;width:100%;font-size:13px}}
  th{{text-align:left;font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;
    color:var(--muted);padding:10px 12px;border-bottom:1px solid var(--grid);
    background:var(--panel);position:sticky;top:0}}
  td{{padding:10px 12px;border-bottom:1px solid var(--grid);vertical-align:top}}
  tr:last-child td{{border-bottom:0}}
  .mono{{font:12px/1.45 ui-monospace,Menlo,monospace;color:var(--muted)}}
  .small{{font-size:11px}}
  .statement{{max-width:400px}}
  .cites{{max-width:430px}}
  .cite{{display:grid;grid-template-columns:auto auto 1fr;gap:8px;align-items:baseline;
    padding:3px 0;font-size:12px}}
  .role{{color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.05em}}
  .offsets{{font:11px/1 ui-monospace,Menlo,monospace;color:var(--muted);opacity:.8}}
  .quote{{color:var(--ink);opacity:.9}}
  .pill{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;
    border:1px solid transparent;white-space:nowrap}}
  {mod_css}
  .badge{{display:inline-block;padding:2px 9px;border-radius:6px;font-size:11.5px;
    white-space:nowrap;border:1px solid}}
  .badge.ok{{color:#0ca30c;border-color:#0ca30c55;background:#0ca30c14}}
  .badge.warn{{color:#8a8984;border-color:var(--grid);background:transparent}}
  .badge.bad{{color:#d03b3b;border-color:#d03b3b55;background:#d03b3b14}}
  .empty{{color:var(--muted);font-size:13px;margin:0}}
  footer{{margin-top:26px;color:var(--muted);font-size:12.5px;max-width:84ch}}
  footer h2{{color:var(--ink)}}
  footer code,p code{{font:11.5px/1 ui-monospace,Menlo,monospace;background:var(--grid);
    padding:2px 5px;border-radius:4px}}
  .assurance{{display:grid;gap:8px;margin:12px 0 0;padding:0;list-style:none}}
  .assurance li{{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:baseline}}
  .assurance .mark{{font-size:13px}}
</style>
</head>
<body>
<div class="wrap viz-root">
  <header class="top">
    <div class="eyebrow">Evidence-bound policy compilation</div>
    <h1>{title}</h1>
    <p class="sub">Every clause below is anchored to exact character offsets in a hashed
    source document. Nothing reaches an executable projection without passing a
    fail-closed gate, and every refusal is recorded with a named reason.</p>
    <div class="meta">
      <span>source: {source}</span><span>parser: {parser}</span>
      <span>canonical text sha256: {text_hash}</span><span>generated: {generated}</span>
    </div>
  </header>

  <section class="panel">
    <h2>At a glance</h2>
    <p class="lede">What was read, what was found, and how much of it can be executed.</p>
    <div class="tiles">{tiles}</div>
  </section>

  {model_section}

  <section class="panel">
    <h2>Source coverage</h2>
    <p class="lede">Every chunk is accounted for. A chunk that stated no requirement is
    recorded as such rather than dropped, and a page with no extractable text is a
    reported gap, not a silent one.</p>
    {coverage}
  </section>

  <div class="two">
    <section class="panel">
      <h2>Normative force</h2>
      <p class="lede">What kind of statement each clause makes — read from the cited text,
      not assumed.</p>
      {modality}
    </section>
    <section class="panel">
      <h2>What each clause qualifies for</h2>
      <p class="lede">Six statuses, each granted on its own evidence and
      <strong>independent of the others</strong> — not a funnel. A clause can cite its
      source exactly and still be ineligible for DMN. Bars are shares of all admitted
      clauses.</p>
      {statuses}
    </section>
  </div>

  {semantic_panel}

  {blockers}

  {governance_panel}

  <section class="panel">
    <h2>Knowledge graph</h2>
    <p class="lede">Document → section → clause. Colour and shape both carry node type, so
    the view stays readable without relying on hue. Drag to explore; hover any node for its
    provenance.</p>
    <div id="graph"></div>
    <ul class="legend">{node_legend}</ul>
    {graph_caps}
  </section>

  <section class="panel">
    <h2>Clauses and their evidence</h2>
    <p class="lede">The table view of the same data, with the exact quoted span and its
    character offsets for every field a clause asserts.</p>
    <div class="tablewrap">
      <table>
        <thead><tr><th>Clause</th><th>Modality</th><th>Kind</th><th>Statement</th>
        <th>Verdict</th><th>Cited evidence</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    {table_note}
  </section>

  <section class="panel">
    <h2>Pipeline stages</h2>
    <p class="lede">Each stage persisted its own output, so any stage can be inspected or
    re-run without repeating the ones before it.</p>
    <div class="tablewrap">{stage_table}</div>
  </section>

  <footer>
    <h2>What this run does and does not establish</h2>
    <ul class="assurance">
      <li><span class="mark">✓</span><span><strong>Conformance verified.</strong> Schema,
      hashes, character offsets, types, references and XML structure passed deterministic
      checks.</span></li>
      <li><span class="mark">—</span><span><strong>Semantic support is bounded.</strong>
      Values and modality are checked against the cited text by surface match. Finding
      "620" in a span does not prove the span means "credit score at least 620".</span></li>
      <li><span class="mark">✗</span><span><strong>Governance approval is not claimed.</strong>
      An executable subset means technically executable under a restricted compiler
      profile. It is not a legal reading and not approved for production.</span></li>
    </ul>
  </footer>
</div>
<script>
(function () {{
  var data = {graph_json};
  var el = document.getElementById('graph');
  if (!el || typeof vis === 'undefined') {{
    if (el) el.innerHTML = '<p style="padding:24px;color:#8a8984;font:14px system-ui">' +
      'The graph needs the vis-network library, which loads from a CDN. ' +
      'Every other panel on this page renders offline.</p>';
    return;
  }}
  var network = new vis.Network(el, {{
    nodes: new vis.DataSet(data.nodes),
    edges: new vis.DataSet(data.edges)
  }}, {{
    nodes: {{borderWidth: 0, shadow: false,
             font: {{color: getComputedStyle(document.body).color, face: 'ui-sans-serif'}}}},
    edges: {{color: {{color: 'rgba(130,130,125,.42)', highlight: '#2a78d6'}},
             width: 1, smooth: {{type: 'continuous'}}, arrows: {{to: {{enabled: false}}}}}},
    physics: {{stabilization: {{iterations: 220}},
               barnesHut: {{gravitationalConstant: -9000, springLength: 150,
                            springConstant: 0.02, damping: 0.5}}}},
    interaction: {{hover: true, tooltipDelay: 120, navigationButtons: true, keyboard: false}}
  }});
  network.once('stabilizationIterationsDone', function () {{
    network.setOptions({{physics: false}});
  }});
}})();
</script>
</body>
</html>
"""
