"""
Graph Service — reads pipeline-output/ artifacts and returns structured data.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # policy-to-knowledge/

# Keep these in sync with routers/documents.py — the user-facing taxonomy on
# the Documents page. Graphs inherit the domain of their source folder so the
# Graph Comparison view groups them under the same labels (e.g. a folder
# uploaded under the Mortgage tab appears under "Mortgage", not "Other").
SUPPORTED_DOMAINS = {"mortgage", "aml", "healthcare", "commercial_lending"}

# Keyword fallback used when the folder hasn't been explicitly assigned a
# domain via the Documents UI (i.e. missing from .folder_domains.json).
# Order matters: more specific domains first so e.g. "commercial-lending" is not
# captured by the generic mortgage keyword ("lend").
_DOMAIN_KEYWORDS: list[tuple[str, list[str]]] = [
    ("commercial_lending", ["commercial", "comercial", "lending"]),
    ("aml", ["anti-money", "anti_money", "money-laundry", "money_laundering", "aml", "kyc", "sanctions"]),
    ("healthcare", ["healthcare", "health-care", "hipaa"]),
    ("mortgage", [
        "mortgage", "loan", "sample_guidelines", "example_policies", "underwriting", "servicing", "lend",
    ]),
]


def _pipeline_output() -> Path:
    return PROJECT_ROOT / "pipeline-output"


class UnsafeNameError(ValueError):
    """Raised when a graph/comparison/operation name would escape the
    pipeline-output tree (path traversal)."""


def _safe_subpath(name: str, *parts: str) -> Path:
    """Resolve `pipeline-output / name [/ *parts]` and guarantee the result
    stays inside the pipeline-output tree. Rejects empty names, names
    containing path separators or '..', and any resolved path that escapes
    the base directory. Returns the validated (resolved) Path."""
    if not name or not isinstance(name, str):
        raise UnsafeNameError("empty name")
    # Reject separators / parent refs in any user-supplied component.
    for component in (name, *parts):
        if not component or component in (".", "..") \
                or "/" in component or "\\" in component:
            raise UnsafeNameError(f"unsafe path component: {component!r}")
    base = _pipeline_output().resolve()
    target = base.joinpath(name, *parts).resolve()
    if target != base and not target.is_relative_to(base):
        raise UnsafeNameError(f"path escapes pipeline-output: {name!r}")
    return target


def _compliance_files_dir() -> Path:
    return PROJECT_ROOT / "compliance-files"


def _load_folder_domains() -> dict[str, str]:
    """Read the same .folder_domains.json that the Documents router maintains."""
    path = _compliance_files_dir() / ".folder_domains.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, str) and v in SUPPORTED_DOMAINS
    }


def _infer_domain_from_name(name: str) -> str:
    lower = (name or "").lower()
    for domain, keywords in _DOMAIN_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return domain
    return ""


def _resolve_graph_domain(graph_name: str, folder_domains: dict[str, str]) -> str:
    """Match graph → source folder domain.

    Graph names mirror the folder name (with hyphens or underscores). Try
    exact match first, then a normalized match, then keyword inference so the
    Graph Comparison page lines up with the Documents page categorization.
    """
    if not graph_name:
        return ""
    if graph_name in folder_domains:
        return folder_domains[graph_name]
    norm = graph_name.replace("_", "-").lower()
    for folder, domain in folder_domains.items():
        if folder.replace("_", "-").lower() == norm:
            return domain
    return _infer_domain_from_name(graph_name)


def delete_graph(name: str, provider: str = "openai") -> bool:
    """Delete all pipeline output files for a knowledge graph. Returns True if deleted.

    `provider` is accepted for backward compatibility but ignored — outputs are
    no longer namespaced by provider.
    """
    import shutil
    graph_dir = _safe_subpath(name)
    if not graph_dir.exists() or not graph_dir.is_dir():
        return False
    shutil.rmtree(graph_dir)
    return True


def list_graphs(provider: str = None) -> List[dict]:
    """Return metadata for every generated knowledge graph.

    Each source subdirectory directly under ``pipeline-output/`` (excluding
    internal ``_``-prefixed folders such as ``_merged`` / ``_joined``) is a graph.
    """
    base = _pipeline_output()
    if not base.exists():
        return []

    graphs: list[dict] = []
    folder_domains = _load_folder_domains()

    for sub in sorted(base.iterdir()):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue

        optimized = sub / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
        merged = sub / "agent-4-rules-with-entities" / "compliance_knowledge_graph.json"
        kg_file = optimized if optimized.exists() else merged if merged.exists() else None

        info: dict[str, Any] = {
            "name": sub.name,
            "provider": "openai",
            "path": str(sub),
            "has_optimized": optimized.exists(),
            "has_visualization": False,
            "rules": 0,
            "entities": 0,
            # Inherit categorization from the source folder so the
            # Graph Comparison view matches the Documents view.
            "domain": _resolve_graph_domain(sub.name, folder_domains) or None,
        }

        # Count rules and entities from the KG JSON. Only root-level
        # business_rules are loaded into JanusGraph by data_loader.py, so we
        # count only those here for consistency.
        if kg_file and kg_file.exists():
            try:
                data = json.loads(kg_file.read_text())
                info["entities"] = len(data.get("entity_types", {}))
                info["rules"] = sum(
                    1 for r in data.get("business_rules", []) if isinstance(r, dict)
                )
            except Exception:
                pass

        # Check for visualization HTML
        viz_dir = sub / "agent-6-visualization-and-report"
        if viz_dir.exists():
            html_files = list(viz_dir.glob("*.html"))
            info["has_visualization"] = len(html_files) > 0
            if html_files:
                info["visualization_file"] = str(html_files[0])

        graphs.append(info)

    return graphs


def get_graph_data(name: str, provider: str = "openai") -> Optional[dict]:
    """Load full knowledge graph JSON. `provider` is ignored (kept for compat)."""
    base = _safe_subpath(name)
    optimized = base / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
    merged = base / "agent-4-rules-with-entities" / "compliance_knowledge_graph.json"
    kg_file = optimized if optimized.exists() else merged if merged.exists() else None
    if not kg_file:
        return None
    return json.loads(kg_file.read_text())


def get_visualization_html(name: str, provider: str = "openai") -> Optional[str]:
    """Return the HTML content of the visualization file. `provider` ignored."""
    viz_dir = _safe_subpath(name, "agent-6-visualization-and-report")
    if not viz_dir.exists():
        return None
    html_files = list(viz_dir.glob("*.html"))
    if not html_files:
        return None
    return html_files[0].read_text()


_DARK_CSS = """<style id="p2k-dark-theme">
/* ── Policy to Knowledge Dark Theme — Midnight Studio ── */
body{background:#0b0b18!important;color:#e0e0ec!important}
.container{max-width:100%!important;padding:10px!important}
header,.graph-container,.entity-definitions-container,
.rules-container,.dependency-container,.summary-container{
  background:#14142b!important;border:1px solid #1e1e3f!important;
  box-shadow:0 2px 8px rgba(0,0,0,.35)!important;color:#e0e0ec!important}
h1,h2,h3,h4,.section-title{color:#f1f1f7!important;
  -webkit-text-fill-color:#f1f1f7!important;background:none!important}
.subtitle,.legend-label{color:#9090a8!important}
.stat-card{background:linear-gradient(135deg,#06b6d4 0%,#8b5cf6 100%)!important;color:#fff!important}
#network{background:#0b0b18!important;border-color:#1e1e3f!important}
.legend{background:#0b0b18!important;border:1px solid #1e1e3f!important}
.search-container input,.filter-btn,select{
  background:#0b0b18!important;color:#e0e0ec!important;
  border-color:#2a2a55!important}
.filter-btn.active{background:#06b6d4!important;color:#0b0b18!important}
table{color:#e0e0ec!important}
table th{background:#14142b!important;color:#9090a8!important;
  border-color:#1e1e3f!important}
table td{border-color:#14142b!important}
table tr:nth-child(even){background:#14142b!important}
table tr:nth-child(odd){background:#0b0b18!important}
table tr:hover{background:#1e1e3f!important}
.entity-card{background:#0b0b18!important;border-color:#1e1e3f!important;
  color:#e0e0ec!important}
.entity-card:hover{box-shadow:0 4px 12px rgba(6,182,212,.18)!important;
  border-color:#06b6d4!important}
.entity-card-header{border-color:#1e1e3f!important}
.entity-card-header h3{color:#f1f1f7!important}
.attr-name{color:#9090a8!important}
.rule-tag{background:#1e1e3f!important;color:#a78bfa!important}
.modal-content{background:#14142b!important;color:#e0e0ec!important;
  border:1px solid #1e1e3f!important}
.modal-overlay{background:rgba(0,0,0,.75)!important}
.close-btn{color:#9090a8!important}
.badge,.tag{background:#1e1e3f!important;color:#e0e0ec!important}
a{color:#22d3ee!important}
.pagination-btn,.page-btn{background:#14142b!important;color:#e0e0ec!important;
  border-color:#1e1e3f!important}
.pagination-btn:hover,.page-btn:hover{background:#1e1e3f!important;color:#22d3ee!important}
.vis-navigation .vis-button{filter:invert(0.85)!important}
pre,code{background:#0b0b18!important;color:#a5f3fc!important}
.source-logo{background:#14142b!important;box-shadow:0 4px 12px rgba(0,0,0,.3)!important}
.logo-text{color:#22d3ee!important}
*::-webkit-scrollbar{width:8px;height:8px}
*::-webkit-scrollbar-track{background:#0b0b18}
*::-webkit-scrollbar-thumb{background:#2a2a55;border-radius:4px}
*::-webkit-scrollbar-thumb:hover{background:#3f3f7a}
*:focus-visible{outline:2px solid rgba(6,182,212,.6)!important;outline-offset:2px!important}
</style>"""


_LIGHT_CSS = """<style id="p2k-light-theme">
/* ── Policy to Knowledge Light Theme — Warm Linen ── */
body{background:#f7f5f0!important;color:#1f1810!important}
.container{max-width:100%!important;padding:10px!important}
header,.graph-container,.entity-definitions-container,
.rules-container,.dependency-container,.summary-container{
  background:#fffdf8!important;border:1px solid #ddd5c4!important;
  box-shadow:0 1px 3px rgba(60,38,22,.06),0 1px 2px rgba(60,38,22,.04)!important;
  color:#1f1810!important}
h1,h2,h3,h4,.section-title{color:#1f1810!important;
  -webkit-text-fill-color:#1f1810!important;background:none!important}
.subtitle,.legend-label{color:#6b5d48!important}
.stat-card{background:linear-gradient(135deg,#0e7490 0%,#7e22ce 100%)!important;color:#fff!important}
#network{background:#fffdf8!important;border-color:#ddd5c4!important}
.legend{background:#fffdf8!important;border:1px solid #ddd5c4!important;color:#1f1810!important}
.search-container input,.filter-btn,select{
  background:#fffdf8!important;color:#1f1810!important;
  border-color:#c8bfae!important}
.filter-btn.active{background:#0e7490!important;color:#fff!important;border-color:#0e7490!important}
table{color:#1f1810!important}
table th{background:#f1ede4!important;color:#463a2a!important;
  border-color:#ddd5c4!important}
table td{border-color:#ddd5c4!important}
table tr:nth-child(even){background:#fffdf8!important}
table tr:nth-child(odd){background:#f7f5f0!important}
table tr:hover{background:#f1ede4!important}
.entity-card{background:#fffdf8!important;border-color:#ddd5c4!important;
  color:#1f1810!important}
.entity-card:hover{box-shadow:0 4px 12px rgba(14,116,144,.12)!important;
  border-color:#0e7490!important}
.entity-card-header{border-color:#ddd5c4!important}
.entity-card-header h3{color:#1f1810!important}
.attr-name{color:#6b5d48!important}
.rule-tag{background:#f1ede4!important;color:#7e22ce!important}
.modal-content{background:#fffdf8!important;color:#1f1810!important;
  border:1px solid #ddd5c4!important}
.modal-overlay{background:rgba(60,38,22,.35)!important}
.close-btn{color:#6b5d48!important}
.badge,.tag{background:#f1ede4!important;color:#1f1810!important}
a{color:#0e7490!important}
.pagination-btn,.page-btn{background:#fffdf8!important;color:#1f1810!important;
  border-color:#ddd5c4!important}
.pagination-btn:hover,.page-btn:hover{background:#f1ede4!important;color:#0e7490!important}
pre,code{background:#f1ede4!important;color:#155e75!important}
.source-logo{background:#fffdf8!important;box-shadow:0 1px 3px rgba(60,38,22,.08)!important}
.logo-text{color:#0e7490!important}
*::-webkit-scrollbar{width:8px;height:8px}
*::-webkit-scrollbar-track{background:#f7f5f0}
*::-webkit-scrollbar-thumb{background:#c8bfae;border-radius:4px}
*::-webkit-scrollbar-thumb:hover{background:#a89c85}
*:focus-visible{outline:2px solid rgba(14,116,144,.55)!important;outline-offset:2px!important}
</style>"""


def inject_dark_theme(html: str) -> str:
    """Inject dark theme CSS overrides before </head>."""
    if "</head>" in html:
        return html.replace("</head>", _DARK_CSS + "\n</head>", 1)
    return _DARK_CSS + html


def inject_light_theme(html: str) -> str:
    """Inject light theme CSS overrides before </head>."""
    if "</head>" in html:
        return html.replace("</head>", _LIGHT_CSS + "\n</head>", 1)
    return _LIGHT_CSS + html


def apply_theme(html: str, theme: str) -> str:
    """Apply named theme overrides; defaults to light."""
    if (theme or "").lower() == "dark":
        return inject_dark_theme(html)
    return inject_light_theme(html)


def _comparison_base_dirs(provider: str = "openai") -> List[Path]:
    """Return all directories that may contain comparison subfolders.

    `provider` is accepted for backward compatibility but ignored — outputs are
    no longer namespaced by provider (they live directly under pipeline-output/).
    """
    base = _pipeline_output()
    return [base / d for d in ("_joined", "_merged") if (base / d).exists()]


def _safe_comparison_name(comparison_name: str) -> str:
    """Reject comparison names that contain path separators or parent refs."""
    if not comparison_name or comparison_name in (".", "..") \
            or "/" in comparison_name or "\\" in comparison_name:
        raise UnsafeNameError(f"unsafe comparison name: {comparison_name!r}")
    return comparison_name


def _find_comparison_dir(comparison_name: str, provider: str = "openai") -> Optional[Path]:
    """Locate the directory for a named comparison across all base dirs."""
    _safe_comparison_name(comparison_name)
    for base in _comparison_base_dirs(provider):
        base_resolved = base.resolve()
        p = (base / comparison_name).resolve()
        if p != base_resolved and not p.is_relative_to(base_resolved):
            continue
        if p.exists():
            return p
    return None


def _extract_g1_g2(comparison_dir: Path) -> tuple:
    """Read g1/g2 graph names from set-operation metadata JSON."""
    ops_dir = comparison_dir / "agent-9-set-operations"
    if ops_dir.exists():
        for f in ops_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                meta = data.get("metadata", {})
                g1 = meta.get("g1_name", "")
                g2 = meta.get("g2_name", "")
                if g1 and g2:
                    return g1, g2
            except Exception:
                continue
    return ("", "")


def list_comparisons(provider: str = "openai") -> List[dict]:
    """List available graph comparisons across _joined and _merged directories."""
    seen: set = set()
    results = []

    for base in _comparison_base_dirs(provider):
        for sub in sorted(base.iterdir()):
            if not sub.is_dir() or sub.name in seen:
                continue
            seen.add(sub.name)

            g1, g2 = _extract_g1_g2(sub)

            info: Dict[str, Any] = {
                "name": sub.name,
                "g1": g1,
                "g2": g2,
                "provider": provider,
                "path": str(sub),
                "has_visualizations": (sub / "agent-10-visualizations").exists(),
            }

            ops_dir = sub / "agent-9-set-operations"
            if ops_dir.exists():
                for op_file in ops_dir.glob("*.json"):
                    try:
                        data = json.loads(op_file.read_text())
                        if op_file.stem == "contradictions":
                            count = len(data.get("contradictions", []))
                        else:
                            br = data.get("business_rules", [])
                            count = len(br) if isinstance(br, list) else 0
                    except Exception:
                        count = 0
                    info[op_file.stem + "_count"] = count

            results.append(info)

    return results


def get_comparison_html(comparison_name: str, operation: str, provider: str = "openai") -> Optional[str]:
    """Get a specific comparison visualization HTML."""
    comp_dir = _find_comparison_dir(comparison_name, provider)
    if not comp_dir:
        return None
    if not operation or operation in (".", "..") \
            or "/" in operation or "\\" in operation:
        raise UnsafeNameError(f"unsafe operation name: {operation!r}")
    html_file = comp_dir / "agent-10-visualizations" / f"{operation}.html"
    return html_file.read_text() if html_file.exists() else None


def get_comparison_data(comparison_name: str, provider: str = "openai") -> Optional[dict]:
    """Get all set operation data for a comparison."""
    comp_dir = _find_comparison_dir(comparison_name, provider)
    if not comp_dir:
        return None
    ops_dir = comp_dir / "agent-9-set-operations"
    if not ops_dir.exists():
        return None

    result = {}
    for f in ops_dir.glob("*.json"):
        try:
            result[f.stem] = json.loads(f.read_text())
        except Exception:
            result[f.stem] = None
    return result
