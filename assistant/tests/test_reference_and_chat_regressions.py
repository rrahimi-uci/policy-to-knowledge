"""Regression tests for the two production bugs reported on 2026-04-28:

1. Reference resolution returning "source not in KB" because the assistant
   Docker image did not COPY the kbs/ folder, so docs_folder was empty in prod.
2. Chat producing canned hallucinated text like
   "The p2k (guidelines) graph has been loaded for visualization.
    It contains 750 nodes and 555 links."
   when the LLM was never given real graph statistics.

These are fast unit tests — no live server, no JanusGraph required.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent  # assistant/


# ────────────────────────────────────────────────────────────────────
# Bug 1: Dockerfile must ship the KB folder so reference resolution works
# ────────────────────────────────────────────────────────────────────

def test_dockerfile_copies_kbs_folder():
    """The assistant Docker image must include the kbs/ KB folder.

    Without this, /api/reference/resolve returns no matches in production
    and every reference renders the "source not in KB" badge.
    """
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert re.search(r"^\s*COPY\s+kbs/\s+kbs/\s*$", dockerfile, re.MULTILINE), (
        "assistant/Dockerfile must contain `COPY kbs/ kbs/` so the "
        "knowledge base ships with the image. Without it, reference resolve "
        "returns 'source not in KB' in production."
    )
    # The old image created an empty /app/kbs in the same RUN useradd line —
    # make sure that pre-create is gone (otherwise it shadows the COPY).
    assert "mkdir -p /app/data /app/kbs" not in dockerfile, (
        "Old `mkdir -p /app/data /app/kbs` line must be removed; it can race "
        "with the COPY and leave the directory empty."
    )


def test_dockerignore_does_not_exclude_kbs():
    """The .dockerignore must NOT exclude kbs/ — otherwise COPY kbs/ kbs/
    silently produces an empty directory (or fails the build)."""
    dockerignore = (REPO_ROOT / ".dockerignore").read_text()
    for line in dockerignore.splitlines():
        stripped = line.split("#", 1)[0].strip()
        assert stripped not in ("kbs", "kbs/", "/kbs", "/kbs/", "**/kbs", "**/kbs/"), (
            f".dockerignore line {line!r} excludes the KB folder. Remove it "
            "or the assistant image will ship without its KB and "
            "reference resolution will return 'source not in KB' in production."
        )


# ────────────────────────────────────────────────────────────────────
# Bug 1b: repeated graph loads must replace data, not append duplicates
# ────────────────────────────────────────────────────────────────────

def _import_data_loader():
    try:
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from src import data_loader  # noqa: F401
        return data_loader
    except Exception as exc:
        pytest.skip(f"data_loader.py not importable in this env: {exc}")


class _FakeCountTraversal:
    def V(self):
        return self

    def E(self):
        return self

    def count(self):
        return self

    def next(self):
        return 0


class _FakeTraversalContext:
    def __enter__(self):
        return _FakeCountTraversal(), object()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_load_data_can_clear_graph_before_reload(tmp_path, monkeypatch):
    """Repeated graph loads must be able to replace existing data.

    Without an explicit clear-first path, republishing or reactivating a graph
    appends a second copy of the same rule IDs, which is how sample_guidelines_g
    ended up with 718 business_rule vertices from a 377-rule JSON file.
    """
    data_loader = _import_data_loader()

    kg_path = tmp_path / "minimal-kg.json"
    kg_path.write_text(json.dumps({"business_rules": [], "entity_types": {}}))

    cleared = []
    monkeypatch.setattr(data_loader, "clear_graph", lambda graph_name: cleared.append(graph_name))
    monkeypatch.setattr(data_loader, "get_traversal", lambda graph_name: _FakeTraversalContext())

    data_loader.load_data("sample_guidelines_g", json_file=str(kg_path), clear_first=True)

    assert cleared == ["sample_guidelines_g"], (
        "load_data(..., clear_first=True) must clear the target graph before "
        "loading, or repeated publishes will duplicate every business_rule."
    )


def test_publish_graph_clears_target_graph_before_loading():
    """Publishing a KG over an existing traversal source must replace it,
    not append a second copy of the same rules."""
    server_src = (REPO_ROOT / "src" / "server.py").read_text()
    assert re.search(
        r"load_data\(\s*traversal_source\s*,\s*json_file=str\(dest_path\)\s*,\s*clear_first=True\s*\)",
        server_src,
    ), (
        "publish_graph must call load_data(..., clear_first=True) so a "
        "republish replaces the graph instead of doubling the rule count."
    )


def test_publish_graph_allows_refresh_of_existing_manifest_entry():
    """Republishing an existing graph must refresh the current manifest entry
    instead of rejecting the update and leaving Explorer / Graph DB drift."""
    server_src = (REPO_ROOT / "src" / "server.py").read_text()
    start = server_src.index("def _do_publish_graph")
    end = server_src.index('@app.route("/api/graph/activate", methods=["POST"])')
    publish_impl = server_src[start:end]

    assert "refreshing existing graph" in publish_impl, (
        "_do_publish_graph should refresh an existing manifest entry when the "
        "same graph is published again, so Graph DB can be resynced to the "
        "latest pipeline artifact."
    )
    assert "is already published" not in publish_impl, (
        "_do_publish_graph must not reject duplicate publishes with an "
        "'already published' early return, or Explorer and chat can drift "
        "forever after a graph is regenerated."
    )


def test_activate_graph_clears_target_graph_before_loading():
    """Graph activation must also replace stale data if the traversal source
    already contains vertices from a prior failed/incomplete load."""
    server_src = (REPO_ROOT / "src" / "server.py").read_text()
    assert re.search(
        r"load_data\(\s*traversal_source\s*,\s*json_file=str\(kg_path\)\s*,\s*clear_first=True\s*\)",
        server_src,
    ), (
        "activate_graph must call load_data(..., clear_first=True) so it "
        "cannot append duplicate business_rule vertices on reload."
    )


def test_load_all_graphs_clears_before_load():
    """Container restarts re-run startup load_all_graphs against persistent
    JanusGraph storage. Without clear_first=True every restart doubles the
    business_rule vertex count (observed: fannie_mae 392 file rules → 784
    live nodes after a redeploy)."""
    src = (REPO_ROOT / "src" / "data_loader.py").read_text()
    start = src.index("def load_all_graphs")
    rest = src[start:]
    # body ends at the next top-level "def " / "class " / "if __name__", or EOF
    candidates = [rest.find(f"\n{kw}") for kw in ("def ", "class ", "if __name__")]
    candidates = [c for c in candidates if c > 0]
    end = start + (min(candidates) if candidates else len(rest))
    body = src[start:end]
    assert "load_data(graph_name, clear_first=True)" in body, (
        "load_all_graphs must invoke load_data with clear_first=True so "
        "container restarts cannot accumulate duplicate vertices in the "
        "persistent JanusGraph store."
    )


def test_setup_if_empty_reloads_drifted_graphs():
    """Persistent JanusGraph state means a baked KG file change does NOT
    propagate on container restart unless setup-if-empty also reloads graphs
    whose live business_rule count differs from the file. Without this, a
    stale fannie_mae (e.g. doubled to 784) survives indefinite redeploys."""
    src = (REPO_ROOT / "src" / "main.py").read_text()
    assert "_get_drifted_graphs" in src, (
        "main.py must define _get_drifted_graphs() so cmd_setup_if_empty can "
        "reload graphs whose baked KG file no longer matches the live store."
    )
    # cmd_setup_if_empty body must reference both empty and drifted lists
    start = src.index("def cmd_setup_if_empty")
    rest = src[start:]
    candidates = [rest.find(f"\n{kw}") for kw in ("def ", "class ", "if __name__")]
    candidates = [c for c in candidates if c > 0]
    end = start + (min(candidates) if candidates else len(rest))
    body = src[start:end]
    assert "_get_drifted_graphs" in body and "drifted" in body, (
        "cmd_setup_if_empty must consult _get_drifted_graphs() and reload the "
        "drifted graphs, otherwise stale persistent JanusGraph state will "
        "never refresh from updated baked KG files."
    )


def test_baked_kgs_match_optimized_pipeline_output():
    """The KG JSON files baked into the assistant image must match the
    canonical optimized pipeline output. Drift here is what produced the
    user-visible mismatches (assistant said 850/723 for fannie_mae while
    Explorer correctly showed 352 rules)."""
    pipeline_root = REPO_ROOT.parent / "pipeline" / "pipeline-output" / "openai"
    if not pipeline_root.is_dir():
        pytest.skip("pipeline-output not present in this checkout")
    pairs = [
        ("anti_money_laundry-kg.json",   "anti-money-laundry"),
        ("comercial_lending-kg.json",    "comercial-lending"),
        ("fannie_mae-kg.json",           "fannie-mae"),
        ("freddies_mac-kg.json",         "freddies-mac"),
        ("healthcare-kg.json",           "healthcare"),
        ("sample-guidelines-kg.json",     "sample-guidelines"),
        ("example-overlays-kg.json",           "overlay"),
    ]
    import json as _json
    mismatches = []
    for kg_name, provider in pairs:
        baked = REPO_ROOT / "kgs" / kg_name
        opt = pipeline_root / provider / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
        if not baked.is_file() or not opt.is_file():
            continue
        baked_count = len(_json.loads(baked.read_text()).get("business_rules", []))
        opt_count = len(_json.loads(opt.read_text()).get("business_rules", []))
        if baked_count != opt_count:
            mismatches.append(f"{kg_name}: baked={baked_count} optimized={opt_count}")
    assert not mismatches, (
        "Baked-in assistant KGs are out of sync with optimized pipeline "
        "output — re-run the kg sync step before deploying:\n  "
        + "\n  ".join(mismatches)
    )


# ────────────────────────────────────────────────────────────────────
# Bug 1 (functional): the actual resolve logic must find the chunk on disk
# ────────────────────────────────────────────────────────────────────

# Lazy-import server.py only when needed — it pulls heavy deps (gremlin etc.)
# Tests that use it are skipped if those deps aren't installed locally.
def _import_server():
    try:
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from src import server  # noqa: F401
        return server
    except Exception as exc:
        pytest.skip(f"server.py not importable in this env: {exc}")


@pytest.fixture(scope="module")
def sample_docs_folder():
    folder = REPO_ROOT / "kbs" / "sample-guidelines"
    if not folder.is_dir():
        pytest.skip(f"KB folder missing: {folder}")
    return str(folder)


def test_reference_resolve_finds_freddie_mac_chunk(sample_docs_folder):
    """The exact reference reported by the user must resolve to a real chunk.

    User-reported reference (from a node in sample_guidelines_g):
       Freddie Mac Single-Family Seller_Servicer Guide PDF Sep 2025/
         Chapter 6301 Documentation Delivery/
         Chapter 6302 Mortgage Delivery Instructions/
         6302.7 Loan data required for ARMs (100121)/
         (a) General requirements + (b) Data delivery instructions.txt
    """
    server = _import_server()

    expected_rel = (
        "Freddie Mac Single-Family Seller_Servicer Guide PDF Sep 2025/"
        "Chapter 6301 Documentation Delivery/"
        "Chapter 6302 Mortgage Delivery Instructions/"
        "6302.7 Loan data required for ARMs (100121)/"
        "(a) General requirements + (b) Data delivery instructions.txt"
    )
    expected_abs = Path(sample_docs_folder) / expected_rel
    assert expected_abs.is_file(), (
        f"Test fixture missing on disk: {expected_abs}. "
        "If this is missing, the KB has changed and the test must be updated."
    )

    chunk_index = server._build_chunk_index(sample_docs_folder)
    assert chunk_index, "_build_chunk_index returned no entries — _metadata.json missing?"

    # Simulate the resolve endpoint's structured-source-reference path
    chunk_path = expected_rel
    matched = None
    for entry in chunk_index:
        if entry["path"].endswith(chunk_path) or chunk_path.endswith(entry["path"]):
            matched = entry
            break
    assert matched is not None, (
        f"Reference resolution failed to match chunk_path={chunk_path!r}. "
        f"Chunk index has {len(chunk_index)} entries; sample first 3: "
        f"{[e['path'] for e in chunk_index[:3]]}"
    )


# ────────────────────────────────────────────────────────────────────
# Bug 2: Chat system prompt must forbid inventing graph statistics
# ────────────────────────────────────────────────────────────────────

def test_chat_system_prompt_forbids_invented_stats():
    """The chat system prompt must explicitly forbid the LLM from inventing
    node/edge counts (the "750 nodes and 555 links" hallucination)."""
    server = _import_server()
    prompt = server._build_chat_system_prompt(active_graph=None)

    # Anti-hallucination clause must mention forbidden phrases
    p = prompt.lower()
    assert "never invent graph statistics" in p, (
        "System prompt must contain 'NEVER invent graph statistics' clause."
    )
    assert "loaded for visualization" in p, (
        "System prompt must explicitly call out the forbidden template "
        "'loaded for visualization' so the LLM avoids it."
    )
    assert "get_graph_statistics" in prompt or "get_graph_overview" in prompt, (
        "System prompt must direct the LLM to call get_graph_statistics / "
        "get_graph_overview before quoting any graph counts."
    )


def test_chat_system_prompt_threads_active_graph():
    """When an active_graph is supplied AND it's loaded, the prompt must
    instruct the LLM to default to that graph."""
    server = _import_server()
    loaded = list(server.get_loaded_traversal_sources())
    if not loaded:
        pytest.skip("No graphs loaded in this env — cannot exercise active-graph path")
    target = loaded[0]
    prompt = server._build_chat_system_prompt(active_graph=target)
    assert f'graph_name="{target}"' in prompt, (
        f"Prompt must instruct LLM to use graph_name=\"{target}\" when that "
        f"graph is the active one in the UI."
    )
