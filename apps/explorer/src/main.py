"""
Main entry-point for Explorer.

Usage:
    python -m src.main setup          # Create schema + load data + index embeddings (DESTRUCTIVE)
    python -m src.main setup-if-empty # Only run setup when graphs have no data (preserves IDs)
    python -m src.main force-clean    # Destroy ALL data (graphs, embeddings, SQLite) and rebuild
    python -m src.main consistency    # Run consistency checks and print a report
    python -m src.main queries        # Run example Gremlin queries
    python -m src.main semantic       # Run semantic search demo
    python -m src.main serve          # Start Explorer server
    python -m src.main all            # setup → queries → semantic → serve
"""

import sys
import os

from src.log import log as _log


def cmd_setup() -> None:
    """Clear graphs, recreate schema, load all KG data, and index embeddings."""
    from src.schema import create_schema
    from src.data_loader import clear_all_graphs, load_all_graphs
    from src.semantic_search import SemanticSearchEngine

    _log("INFO", "Step 1/5 – Creating schema")
    create_schema()

    _log("INFO", "Step 2/5 – Clearing existing graph data")
    clear_all_graphs()

    _log("INFO", "Step 3/5 – Loading all knowledge graphs from kgs/")
    load_all_graphs()

    _log("INFO", "Step 4/5 – Rebuilding embeddings index")
    engine = SemanticSearchEngine()
    engine.delete_index()
    engine.index_all_graph_embeddings()

    _log("INFO", "Step 5/5 – Running post-load consistency checks")
    _post_load_consistency()
    _log("INFO", "Setup complete")


def _post_load_consistency() -> None:
    """Run lightweight consistency checks after data load and log results."""
    from src.semantic_search import SemanticSearchEngine
    from src.graph_connection import get_traversal
    from conf.graph_manifest import get_graph_configs, get_docs_folder

    configs = get_graph_configs()
    engine = SemanticSearchEngine()

    for ts, cfg in configs.items():
        # Verify vertex count matches embedding count
        emb_count = engine.embedding_count(ts)
        try:
            with get_traversal(ts) as (g, conn):
                v_count = g.V().count().next()
        except Exception:
            v_count = -1

        if emb_count == v_count:
            _log("INFO", f"  ✓ '{ts}' ({cfg['name']}): {v_count} vertices, {emb_count} embeddings — OK")
        else:
            _log("WARN", f"  ✗ '{ts}' ({cfg['name']}): {v_count} vertices vs {emb_count} embeddings — MISMATCH")

        # Verify reference → chunk resolution
        docs_folder = get_docs_folder(ts)
        if docs_folder and os.path.isdir(docs_folder):
            try:
                with get_traversal(ts) as (g, conn):
                    refs = g.V().has("reference").values("reference").toList()
                total = len(refs)
                # Quick spot-check: sample first 50 refs
                from src.server import _build_chunk_index, _match_reference
                chunk_idx = _build_chunk_index(docs_folder)
                resolved = sum(1 for r in refs[:50] if r and _match_reference(r, chunk_idx))
                checked = min(50, total)
                _log("INFO", f"  ✓ '{ts}' references: {resolved}/{checked} sampled resolved (total: {total})")
            except Exception as exc:
                _log("WARN", f"  ✗ '{ts}' reference check failed: {exc}")
        else:
            _log("INFO", f"  - '{ts}' has no docs folder configured — skipping reference check")


def _get_empty_graphs() -> list[str]:
    """Return traversal sources for graphs that are empty or unreachable.

    Graphs that cannot be contacted (e.g. brand-new entries just added to
    graphs.yaml) are treated as empty so they get loaded on the next startup.
    Graphs that already contain vertices are left untouched.
    """
    from src.graph_connection import get_traversal
    from conf.graph_manifest import get_graph_configs

    empty: list[str] = []
    for graph_name in get_graph_configs():
        try:
            with get_traversal(graph_name) as (g, conn):
                count = g.V().limit(1).count().next()
                if count == 0:
                    _log("INFO", f"Graph '{graph_name}' is empty — will load")
                    empty.append(graph_name)
        except Exception as exc:
            _log("WARN", f"Cannot reach graph '{graph_name}': {exc} — will load")
            empty.append(graph_name)
    return empty


def _get_drifted_graphs() -> list[str]:
    """Return graphs whose live business_rule vertex count does not match the
    business_rules count in their configured KG JSON file.

    JanusGraph storage is persistent across container restarts, so updating a
    baked KG file does not propagate to the live graph unless we explicitly
    detect the drift and reload. Without this check, redeploys silently keep
    stale data (e.g. a doubled fannie_mae from a previous accidental reload).
    """
    import json
    from src.graph_connection import get_traversal
    from conf.graph_manifest import get_graph_configs

    drifted: list[str] = []
    for graph_name, config in get_graph_configs().items():
        kg_file = config.get("file", "")
        if not kg_file or not os.path.isfile(kg_file):
            continue
        try:
            with open(kg_file) as f:
                file_rules = len(json.load(f).get("business_rules", []))
        except Exception as exc:
            _log("WARN", f"Cannot read KG file for '{graph_name}': {exc}")
            continue
        try:
            with get_traversal(graph_name) as (g, conn):
                live_rules = g.V().hasLabel("business_rule").count().next()
        except Exception:
            continue
        if live_rules != file_rules:
            _log(
                "INFO",
                f"Graph '{graph_name}' drift detected — live={live_rules} "
                f"vs file={file_rules}; will reload",
            )
            drifted.append(graph_name)
    return drifted


def cmd_setup_if_empty() -> None:
    """Load empty/new graphs and reload graphs whose KG file has drifted from
    the live JanusGraph state.

    Adding a new graph to graphs.yaml and running ./start.sh will load that
    graph without touching data in graphs that are already populated and in
    sync. Graphs whose baked KG file changed (e.g. after a redeploy with new
    pipeline output) are reloaded so live counts always match the file.
    Vertex IDs are preserved for unchanged graphs so annotations, tasks, and
    reference links remain valid across restarts.
    """
    empty_graphs = _get_empty_graphs()
    drifted_graphs = [g for g in _get_drifted_graphs() if g not in empty_graphs]
    to_load = empty_graphs + drifted_graphs

    if not to_load:
        _log("INFO", "All graphs already contain data and match KG files — skipping setup")
        _log("INFO", "Use './start.sh --fresh' or './start.sh --clean' to force a rebuild")
        from src.semantic_search import SemanticSearchEngine
        engine = SemanticSearchEngine()
        engine.index_all_if_needed()
        return

    if empty_graphs:
        _log("INFO", f"Found {len(empty_graphs)} empty/new graph(s) to load: {empty_graphs}")
    if drifted_graphs:
        _log("INFO", f"Found {len(drifted_graphs)} drifted graph(s) to reload: {drifted_graphs}")

    from src.schema import create_schema
    from src.data_loader import clear_graph, load_data
    from src.semantic_search import SemanticSearchEngine
    from conf.graph_manifest import get_graph_configs

    configs = get_graph_configs()

    # Schema creation checks for existing keys — safe to run on both new and existing graphs
    create_schema()

    for graph_name in to_load:
        config = configs.get(graph_name)
        kg_file = config.get("file", "") if config else ""
        if not kg_file:
            _log("WARN", f"No KG file configured for '{graph_name}' — skipping")
            continue
        if not os.path.isfile(kg_file):
            _log("WARN", f"KG file not found for '{graph_name}': {kg_file} — skipping")
            continue
        _log("INFO", f"Loading graph '{graph_name}' …")
        clear_graph(graph_name)
        load_data(graph_name)
        # Drifted graphs need their embeddings rebuilt too, since vertex IDs changed
        if graph_name in drifted_graphs:
            try:
                engine = SemanticSearchEngine()
                engine.delete_embeddings_for_graph(graph_name)
            except Exception as exc:
                _log("WARN", f"Failed to delete stale embeddings for '{graph_name}': {exc}")

    engine = SemanticSearchEngine()
    engine.index_all_if_needed()
    _post_load_consistency()
    _log("INFO", "Setup complete for new/empty/drifted graphs")


def cmd_force_clean() -> None:
    """DESTRUCTIVE: Clear ALL data stores and rebuild everything from scratch.

    Destroys:
      - All JanusGraph graph data (vertices + edges)
      - OpenSearch embedding index
      - SQLite database (annotations, releases, lock states)

    Then rebuilds:
      - Graph schema
      - All KG data from JSON files
      - Embedding index
      - Task node ID resolution
      - Consistency checks
    """
    from src.schema import create_schema
    from src.data_loader import clear_all_graphs, load_all_graphs
    from src.semantic_search import SemanticSearchEngine
    from src.models import Base, engine as _db_engine

    _log("INFO", "╔══════════════════════════════════════════╗")
    _log("INFO", "║   FORCE CLEAN — Destroying all data      ║")
    _log("INFO", "╚══════════════════════════════════════════╝")

    # Step 1: Destroy SQLite
    _log("INFO", "Step 1/6 – Resetting SQLite database")
    Base.metadata.drop_all(_db_engine)
    Base.metadata.create_all(_db_engine)
    _log("INFO", "SQLite database reset (annotations, releases, lock states)")

    # Step 2: Create/ensure schema
    _log("INFO", "Step 2/6 – Ensuring graph schema")
    create_schema()

    # Step 3: Clear graphs
    _log("INFO", "Step 3/6 – Clearing all graph data")
    clear_all_graphs()

    # Step 4: Reload from KG JSON files
    _log("INFO", "Step 4/6 – Loading all knowledge graphs from kgs/")
    load_all_graphs()

    # Step 5: Rebuild embeddings
    _log("INFO", "Step 5/6 – Rebuilding embedding index")
    engine = SemanticSearchEngine()
    engine.delete_index()
    engine.index_all_graph_embeddings()

    # Step 6: Consistency checks
    _log("INFO", "Step 6/6 – Running consistency checks")
    _post_load_consistency()
    _log("INFO", "Force clean complete — all data rebuilt from scratch")


def cmd_consistency() -> None:
    """Run consistency checks and print a detailed report."""
    from src.semantic_search import SemanticSearchEngine
    from src.graph_connection import get_traversal
    from conf.graph_manifest import get_graph_configs, get_docs_folder

    _log("INFO", "Running consistency checks …")

    configs = get_graph_configs()
    engine = SemanticSearchEngine()
    issues = []

    print("\n" + "=" * 60)
    print("  CONSISTENCY CHECK REPORT")
    print("=" * 60)

    # 1. Graph data
    print("\n── Graph Data ──────────────────────────────────────────")
    for ts, cfg in configs.items():
        try:
            with get_traversal(ts) as (g, conn):
                v = g.V().count().next()
                e = g.E().count().next()
            status = "OK" if v > 0 else "EMPTY"
            print(f"  {cfg['name']:<30} {v:>5} vertices  {e:>5} edges  [{status}]")
            if v == 0:
                issues.append(f"Graph '{ts}' is empty")
        except Exception as exc:
            print(f"  {cfg['name']:<30} ERROR: {exc}")
            issues.append(f"Graph '{ts}' unreachable: {exc}")

    # 2. Embeddings
    print("\n── Embeddings ──────────────────────────────────────────")
    for ts, cfg in configs.items():
        emb = engine.embedding_count(ts)
        try:
            with get_traversal(ts) as (g, conn):
                v = g.V().count().next()
        except Exception:
            v = -1
        match = "OK" if emb == v else "MISMATCH"
        print(f"  {cfg['name']:<30} {emb:>5} indexed / {v:>5} expected  [{match}]")
        if emb != v:
            issues.append(f"Embedding mismatch for '{ts}': {emb} vs {v}")

    # 3. References
    print("\n── Reference → Chunk Resolution ────────────────────────")
    for ts, cfg in configs.items():
        docs_folder = get_docs_folder(ts)
        if not docs_folder or not os.path.isdir(docs_folder):
            print(f"  {cfg['name']:<30} no docs folder configured")
            continue
        try:
            from src.server import _build_chunk_index, _match_reference
            chunk_idx = _build_chunk_index(docs_folder)
            with get_traversal(ts) as (g, conn):
                refs = g.V().has("reference").values("reference").toList()
            total = len(refs)
            resolved = sum(1 for r in refs if r and _match_reference(r, chunk_idx))
            pct = (resolved / total * 100) if total else 100
            status = "OK" if pct >= 80 else "LOW"
            print(f"  {cfg['name']:<30} {resolved:>5}/{total:>5} resolved ({pct:.0f}%)  [{status}]")
            if pct < 80:
                issues.append(f"Low reference resolution for '{ts}': {pct:.0f}%")
        except Exception as exc:
            print(f"  {cfg['name']:<30} ERROR: {exc}")

    # 4. Summary
    print(f"\n{'=' * 60}")
    if issues:
        print(f"  {len(issues)} issue(s) found:")
        for issue in issues:
            print(f"    ✗ {issue}")
    else:
        print("  All checks passed — no issues found")
    print(f"{'=' * 60}\n")


def cmd_queries() -> None:
    from src.gremlin_queries import run_all_queries
    run_all_queries()


def cmd_semantic() -> None:
    from src.semantic_search import run_semantic_search_demo
    run_semantic_search_demo()


def cmd_serve() -> None:
    from src.server import create_app
    from conf.config import SERVER_HOST, SERVER_PORT, FLASK_DEBUG
    app = create_app()
    _log("INFO", f"Starting Explorer server → http://{SERVER_HOST}:{SERVER_PORT}")
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=FLASK_DEBUG)


def cmd_auto_serve() -> None:
    """Load empty graphs, then start the server (default Docker entrypoint)."""
    cmd_setup_if_empty()
    cmd_serve()


COMMANDS = {
    "setup": cmd_setup,
    "setup-if-empty": cmd_setup_if_empty,
    "force-clean": cmd_force_clean,
    "consistency": cmd_consistency,
    "queries": cmd_queries,
    "semantic": cmd_semantic,
    "serve": cmd_serve,
    "auto-serve": cmd_auto_serve,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "all":
        cmd_setup()
        cmd_queries()
        cmd_semantic()
        cmd_serve()
    elif cmd in COMMANDS:
        COMMANDS[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
