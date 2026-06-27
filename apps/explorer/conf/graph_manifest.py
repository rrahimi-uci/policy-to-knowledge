"""
Runtime loader for conf/graphs.yaml manifest.

Provides a single source of truth for graph configuration used by:
  - conf/config.py       (AVAILABLE_GRAPHS)
  - src/data_loader.py   (GRAPH_CONFIGS)
  - src/graph_connection.py (list_available_graphs)
  - src/server.py        (tool definitions)
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

_MANIFEST_PATH = Path(__file__).resolve().parent / "graphs.yaml"


@lru_cache(maxsize=1)
def load_manifest(path: Optional[str] = None) -> dict:
    """Load and cache the graphs.yaml manifest."""
    p = Path(path) if path else _MANIFEST_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"graphs.yaml not found at {p}. "
            "Run: python scripts/generate_graph_config.py"
        )
    with open(p) as f:
        return yaml.safe_load(f)


def get_graphs() -> Dict[str, dict]:
    """Return the graphs section from the manifest."""
    return load_manifest()["graphs"]


def normalize_graph_name(name: Optional[str]) -> str:
    """Normalize graph identifiers from keys, slugs, or traversal sources."""
    if not name:
        return ""
    normalized = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    return re.sub(r"_+", "_", normalized)


def get_graph_aliases() -> Dict[str, str]:
    """Return normalized alias -> canonical graph key mappings."""
    manifest = load_manifest()
    graphs = manifest.get("graphs", {})
    aliases: Dict[str, str] = {}
    for alias, target in manifest.get("aliases", {}).items():
        normalized_alias = normalize_graph_name(alias)
        normalized_target = normalize_graph_name(target)
        if not normalized_alias or normalized_target not in graphs:
            continue
        aliases[normalized_alias] = normalized_target
    return aliases


def resolve_graph_key(name: Optional[str]) -> str:
    """Resolve a graph key, alias, slug, or traversal source to its canonical key."""
    normalized = normalize_graph_name(name)
    if not normalized:
        return ""

    graphs = get_graphs()
    if normalized in graphs:
        return normalized

    alias_target = get_graph_aliases().get(normalized)
    if alias_target:
        return alias_target

    for key, graph in graphs.items():
        if normalize_graph_name(graph["traversal_source"]) == normalized:
            return key

    return normalized


def resolve_traversal_source(name: Optional[str]) -> str:
    """Resolve a graph identifier or alias to the canonical traversal source."""
    normalized = normalize_graph_name(name)
    if not normalized:
        return ""

    graphs = get_graphs()
    for graph in graphs.values():
        if normalize_graph_name(graph["traversal_source"]) == normalized:
            return graph["traversal_source"]

    graph_key = resolve_graph_key(normalized)
    graph = graphs.get(graph_key)
    if graph:
        return graph["traversal_source"]

    return normalized


def get_graph_configs() -> Dict[str, dict]:
    """
    Build the runtime GRAPH_CONFIGS dict keyed by traversal_source.

    Returns a dict like:
        {
            "compliance_g":        {"file": "/abs/path/kgs/fama-kg.json",       "name": "compliance (FAMA)"},
            "overlays_g":          {"file": "/abs/path/kgs/example-overlays-kg.json", "name": "overlays (example)"},
        }
    """
    root = _MANIFEST_PATH.parent.parent   # project root (one level up from conf/)
    result = {}
    for _key, graph in get_graphs().items():
        ts = graph["traversal_source"]
        kg_path = graph.get("kg_file", "")
        result[ts] = {
            "file": str(root / kg_path) if kg_path else "",
            "name": graph.get("display_name", _key),
        }
    return result


def get_traversal_sources() -> List[str]:
    """Return ordered list of traversal source names (e.g. ['compliance_g', 'overlays_g'])."""
    return [g["traversal_source"] for g in get_graphs().values()]


def get_available_graph_names() -> List[str]:
    """Return graph keys + traversal sources for backward-compatible lookup."""
    names: List[str] = []
    for key, graph in get_graphs().items():
        names.append(key)
        ts = graph["traversal_source"]
        if ts not in names:
            names.append(ts)
    return names


def get_loaded_graphs() -> Dict[str, dict]:
    """Return only graphs whose KG file exists on disk.

    This filters out configured-but-not-yet-populated graphs so the
    chat system prompt, tool enums, and statistics only expose graphs
    that actually have data.
    """
    root = _MANIFEST_PATH.parent.parent
    loaded: Dict[str, dict] = {}
    for key, graph in get_graphs().items():
        kg_file = graph.get("kg_file", "")
        if kg_file and (root / kg_file).is_file():
            loaded[key] = graph
    return loaded


def get_loaded_traversal_sources() -> List[str]:
    """Return traversal sources for graphs whose KG files exist."""
    return [g["traversal_source"] for g in get_loaded_graphs().values()]


def get_graph_enum_description() -> str:
    """Build a human-readable description of available graphs for tool definitions."""
    parts = []
    for _key, graph in get_loaded_graphs().items():
        ts = graph["traversal_source"]
        name = graph.get("display_name", _key)
        parts.append(f"'{ts}' for {name}")
    return "The graph to query: " + ", ".join(parts) + f" (default: '{get_default_traversal_source()}')"


def get_default_traversal_source() -> str:
    """Return the first loaded traversal source as the default.

    Prefers graphs that actually have KG files on disk.  Falls back
    to the first configured source (or 'g') when nothing is loaded.
    """
    loaded = get_loaded_traversal_sources()
    if loaded:
        return loaded[0]
    sources = get_traversal_sources()
    return sources[0] if sources else "g"


def get_graph_ref_map() -> Dict[str, str]:
    """Return mapping of traversal_source → graph_ref for each graph.

    The graph_ref is the variable name bound by JanusGraphManager
    (from gremlin-server.yaml ``graphs:`` map) and can be used in
    Groovy scripts for ``graph_ref.openManagement()`` etc.
    """
    return {
        graph["traversal_source"]: graph["graph_ref"]
        for graph in get_graphs().values()
    }


def get_docs_folder(traversal_source: str) -> Optional[str]:
    """Return the absolute docs_folder path for a given traversal source, or None."""
    root = _MANIFEST_PATH.parent.parent
    for graph in get_graphs().values():
        if graph["traversal_source"] == traversal_source:
            folder = graph.get("docs_folder", "")
            if folder:
                return str(root / folder)
    return None


def get_docs_folder_map() -> Dict[str, str]:
    """Return mapping of traversal_source → absolute docs_folder path."""
    root = _MANIFEST_PATH.parent.parent
    result = {}
    for graph in get_graphs().values():
        ts = graph["traversal_source"]
        folder = graph.get("docs_folder", "")
        if folder:
            result[ts] = str(root / folder)
    return result


# ── Dynamic graph registration ────────────────────────────────────

def invalidate_cache() -> None:
    """Clear the cached manifest so changes to graphs.yaml are picked up."""
    load_manifest.cache_clear()


def add_graph_to_manifest(
    graph_key: str,
    display_name: str,
    traversal_source: str,
    cassandra_keyspace: str,
    opensearch_index: str,
    kg_file: str,
    docs_folder: Optional[str] = None,
) -> dict:
    """Add a new graph entry to graphs.yaml and regenerate JanusGraph configs.

    Returns the new graph entry dict.
    Raises ValueError if graph_key already exists.
    """
    invalidate_cache()
    manifest = load_manifest()

    if graph_key in manifest.get("graphs", {}):
        raise ValueError(f"Graph '{graph_key}' already exists in manifest")

    entry: Dict[str, str] = {
        "display_name": display_name,
        "graph_ref": graph_key,
        "traversal_source": traversal_source,
        "cassandra_keyspace": cassandra_keyspace,
        "opensearch_index": opensearch_index,
        "kg_file": kg_file,
    }
    if docs_folder:
        entry["docs_folder"] = docs_folder

    manifest["graphs"][graph_key] = entry

    with open(_MANIFEST_PATH, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

    invalidate_cache()
    _regenerate_jg_configs()
    return entry


def remove_graph_from_manifest(graph_key: str) -> None:
    """Remove a graph entry from graphs.yaml and regenerate JanusGraph configs."""
    invalidate_cache()
    manifest = load_manifest()
    if graph_key not in manifest.get("graphs", {}):
        return
    del manifest["graphs"][graph_key]
    with open(_MANIFEST_PATH, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
    invalidate_cache()
    _regenerate_jg_configs()


def _regenerate_jg_configs() -> None:
    """Regenerate JanusGraph configuration files from current manifest."""
    import subprocess
    import sys
    script = Path(__file__).resolve().parent.parent / "scripts" / "generate_graph_config.py"
    subprocess.run(
        [sys.executable, str(script)],
        cwd=str(Path(__file__).resolve().parent.parent),
        check=True,
        capture_output=True,
    )
