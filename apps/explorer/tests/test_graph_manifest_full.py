"""Cover conf/graph_manifest.py against a temporary graphs.yaml manifest.

Complements test_graph_manifest.py (which runs against the committed manifest)
by exercising the config builders, loaded-graph filtering, and mutation paths
with controlled fixture data.
"""
import sys
import textwrap
from pathlib import Path

import allure
import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from conf import graph_manifest as gm  # noqa: E402


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    """Point the loader at a temp manifest with one loaded + one empty graph."""
    conf = tmp_path / "conf"
    conf.mkdir()
    (tmp_path / "kgs").mkdir()
    (tmp_path / "kgs" / "sample.json").write_text("{}")          # exists → "loaded"
    (tmp_path / "docs" / "sample").mkdir(parents=True)
    (conf / "graphs.yaml").write_text(textwrap.dedent("""
        graphs:
          sample_guidelines:
            display_name: Sample Guidelines
            graph_ref: sample_ref
            traversal_source: sample_guidelines_g
            cassandra_keyspace: ks_sample
            opensearch_index: idx_sample
            kg_file: kgs/sample.json
            docs_folder: docs/sample
          empty_graph:
            display_name: Empty Graph
            graph_ref: empty_ref
            traversal_source: empty_g
            cassandra_keyspace: ks_empty
            opensearch_index: idx_empty
            kg_file: kgs/missing.json
        aliases:
          sample: sample_guidelines
          bogus: nonexistent_target
    """))
    monkeypatch.setattr(gm, "_MANIFEST_PATH", conf / "graphs.yaml")
    gm.load_manifest.cache_clear()
    yield tmp_path
    gm.load_manifest.cache_clear()


@allure.feature("Explorer graph manifest")
@allure.story("Resolution")
class TestResolution:
    @allure.title("aliases drop entries whose target is unknown")
    def test_aliases(self, manifest):
        assert gm.get_graph_aliases() == {"sample": "sample_guidelines"}

    @allure.title("resolve_graph_key handles key, alias, traversal source, unknown, empty")
    def test_resolve_key(self, manifest):
        assert gm.resolve_graph_key("sample_guidelines") == "sample_guidelines"
        assert gm.resolve_graph_key("sample") == "sample_guidelines"
        assert gm.resolve_graph_key("sample_guidelines_g") == "sample_guidelines"
        assert gm.resolve_graph_key("totally_unknown") == "totally_unknown"
        assert gm.resolve_graph_key("") == ""

    @allure.title("resolve_traversal_source handles ts, key, unknown, empty")
    def test_resolve_ts(self, manifest):
        assert gm.resolve_traversal_source("empty_g") == "empty_g"
        assert gm.resolve_traversal_source("sample_guidelines") == "sample_guidelines_g"
        assert gm.resolve_traversal_source("nope") == "nope"
        assert gm.resolve_traversal_source("") == ""


@allure.feature("Explorer graph manifest")
@allure.story("Config builders")
class TestConfigs:
    @allure.title("get_graph_configs keys by traversal source with abs file paths")
    def test_graph_configs(self, manifest):
        cfg = gm.get_graph_configs()
        assert set(cfg) == {"sample_guidelines_g", "empty_g"}
        assert cfg["sample_guidelines_g"]["file"].endswith("kgs/sample.json")
        assert cfg["sample_guidelines_g"]["name"] == "Sample Guidelines"

    @allure.title("traversal source + available-name listings")
    def test_listings(self, manifest):
        assert gm.get_traversal_sources() == ["sample_guidelines_g", "empty_g"]
        names = gm.get_available_graph_names()
        assert "sample_guidelines" in names and "sample_guidelines_g" in names

    @allure.title("loaded graphs only include those with KG files present")
    def test_loaded(self, manifest):
        assert set(gm.get_loaded_graphs()) == {"sample_guidelines"}
        assert gm.get_loaded_traversal_sources() == ["sample_guidelines_g"]

    @allure.title("enum description + default source reflect loaded graphs")
    def test_enum_default(self, manifest):
        assert "Sample Guidelines" in gm.get_graph_enum_description()
        assert gm.get_default_traversal_source() == "sample_guidelines_g"

    @allure.title("graph_ref + docs_folder maps")
    def test_ref_docs_maps(self, manifest):
        assert gm.get_graph_ref_map()["sample_guidelines_g"] == "sample_ref"
        assert gm.get_docs_folder("sample_guidelines_g").endswith("docs/sample")
        assert gm.get_docs_folder("empty_g") is None
        assert "sample_guidelines_g" in gm.get_docs_folder_map()


@allure.feature("Explorer graph manifest")
@allure.story("Errors & mutation")
class TestMutation:
    @allure.title("load_manifest raises FileNotFoundError for a missing manifest")
    def test_missing_manifest(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            gm.load_manifest(str(tmp_path / "absent.yaml"))

    @allure.title("add_graph_to_manifest persists a new entry; duplicate raises")
    def test_add(self, manifest, monkeypatch):
        monkeypatch.setattr(gm, "_regenerate_jg_configs", lambda: None)
        entry = gm.add_graph_to_manifest(
            "new_graph", "New Graph", "new_g", "ks_new", "idx_new",
            "kgs/new.json", docs_folder="docs/new",
        )
        assert entry["traversal_source"] == "new_g"
        assert "new_graph" in gm.get_graphs()
        with pytest.raises(ValueError):
            gm.add_graph_to_manifest("new_graph", "x", "x_g", "k", "i", "f.json")

    @allure.title("remove_graph_from_manifest deletes an entry; unknown is a no-op")
    def test_remove(self, manifest, monkeypatch):
        monkeypatch.setattr(gm, "_regenerate_jg_configs", lambda: None)
        gm.remove_graph_from_manifest("empty_graph")
        assert "empty_graph" not in gm.get_graphs()
        gm.remove_graph_from_manifest("does_not_exist")  # no raise
