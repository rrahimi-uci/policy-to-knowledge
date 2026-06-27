import importlib
import json
import sys
from pathlib import Path

from src.docs_sync import copy_docs_tree, docs_folder_rel


def test_docs_folder_rel_uses_graph_key_slug():
    assert docs_folder_rel("fannie_mae") == "kbs/fannie-mae"


def test_copy_docs_tree_preserves_top_level_files_and_nested_chunks(tmp_path):
    source = tmp_path / "agent-1-organized-documents"
    nested = source / "Fannie_Mae"
    nested.mkdir(parents=True)

    (source / "_processing_results.json").write_text("{}", encoding="utf-8")
    (nested / "_metadata.json").write_text(
        '{"structure": [{"title": "Chunk", "path": "Fannie_Mae/chunk.txt", "chunk_id": "chunk-1"}]}',
        encoding="utf-8",
    )
    (nested / "chunk.txt").write_text("chunk body", encoding="utf-8")

    destination = tmp_path / "kbs" / "fannie-mae"
    copy_docs_tree(source, destination)

    assert (destination / "_processing_results.json").read_text(encoding="utf-8") == "{}"
    assert (destination / "Fannie_Mae" / "_metadata.json").is_file()
    assert (destination / "Fannie_Mae" / "chunk.txt").read_text(encoding="utf-8") == "chunk body"


def _load_server(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sys.modules.pop("src.server", None)
    return importlib.import_module("src.server")


def test_publish_graph_rolls_back_manifest_kg_and_docs_on_runtime_open_failure(tmp_path, monkeypatch):
    server = _load_server(monkeypatch)

    app_root = tmp_path / "app"
    pipeline_root = app_root / "pipeline-output" / "openai" / "test_graph"
    optimized_dir = pipeline_root / "agent-5-optimized"
    docs_source = pipeline_root / "agent-1-organized-documents"
    nested_docs = docs_source / "Test_Graph"

    optimized_dir.mkdir(parents=True)
    nested_docs.mkdir(parents=True)

    (optimized_dir / "optimized_compliance_knowledge_graph.json").write_text(
        json.dumps(
            {
                "business_rules": [{"name": "Rule 1", "content": "A fully populated rule body."}],
                "entity_types": {"Entity": [{"name": "Entity 1"}]},
            }
        ),
        encoding="utf-8",
    )
    (docs_source / "_processing_results.json").write_text("{}", encoding="utf-8")
    (nested_docs / "_metadata.json").write_text(
        json.dumps(
            {
                "structure": [
                    {"title": "Chunk", "path": "Test_Graph/chunk.txt", "chunk_id": "chunk-1"}
                ]
            }
        ),
        encoding="utf-8",
    )
    (nested_docs / "chunk.txt").write_text("chunk body", encoding="utf-8")

    real_path = Path

    def fake_path(value):
        if value == "/app":
            return app_root
        if value == "/app/pipeline-output":
            return app_root / "pipeline-output"
        return real_path(value)

    manifest = {}

    def fake_add_graph_to_manifest(**kwargs):
        manifest[kwargs["graph_key"]] = {
            "display_name": kwargs["display_name"],
            "traversal_source": kwargs["traversal_source"],
            "kg_file": kwargs["kg_file"],
            "docs_folder": kwargs.get("docs_folder"),
        }

    def fake_remove_graph_from_manifest(graph_key):
        manifest.pop(graph_key, None)

    monkeypatch.setattr(server, "Path", fake_path)
    monkeypatch.setattr(server, "_publish_callback", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_invalidate_manifest_cache", lambda: None)
    monkeypatch.setattr(server, "get_graphs", lambda: manifest)
    monkeypatch.setattr(server, "add_graph_to_manifest", fake_add_graph_to_manifest)
    monkeypatch.setattr(server, "remove_graph_from_manifest", fake_remove_graph_from_manifest)

    schema = importlib.import_module("src.schema")
    monkeypatch.setattr(schema, "open_graph_runtime", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("runtime open failed")))

    client = server.app.test_client()
    response = client.post(
        "/api/graph/publish",
        json={
            "source_name": "test_graph",
            "provider": "openai",
            "display_name": "Test Graph",
        },
    )

    assert response.status_code == 500
    assert response.get_json()["error"] == "Failed to open graph on JanusGraph: runtime open failed"
    assert manifest == {}
    assert not (app_root / "kgs" / "test_graph-kg.json").exists()
    assert not (app_root / "kbs" / "test-graph").exists()