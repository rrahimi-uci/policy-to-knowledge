"""
Unit tests for conf/graph_manifest.py — the single source of truth for graph
configuration. Runs offline against the committed conf/graphs.yaml.
"""
import base64
import sys
from pathlib import Path

import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from conf import graph_manifest as gm


def _legacy_brand_markers() -> list[str]:
    encoded = (
        "amF6eng=",
        "Y29ydGV4",
        "ZmFubmll",
        "ZnJlZGRpZQ==",
        "YmFyY2xheXM=",
        "YWJzYQ==",
    )
    return [base64.b64decode(item).decode("utf-8") for item in encoded]


@pytest.fixture(autouse=True)
def _clear_cache():
    gm.invalidate_cache()
    yield
    gm.invalidate_cache()


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("Sample Guidelines", "sample_guidelines"),
        ("sample_guidelines_g", "sample_guidelines_g"),
        ("  Example-Policies  ", "example_policies"),
        ("A//B__C", "a_b_c"),
        (None, ""),
        ("", ""),
    ])
    def test_normalize(self, raw, expected):
        assert gm.normalize_graph_name(raw) == expected


class TestManifest:
    def test_graphs_loaded(self):
        graphs = gm.get_graphs()
        assert "sample_guidelines" in graphs
        assert graphs["sample_guidelines"]["traversal_source"] == "sample_guidelines_g"

    def test_no_proprietary_or_brand_names(self):
        # The public manifest must not reference removed brands or proprietary graphs.
        blob = " ".join(gm.get_graphs().keys()).lower()
        for bad in _legacy_brand_markers():
            assert bad not in blob

    def test_resolve_by_traversal_source(self):
        assert gm.resolve_graph_key("sample_guidelines_g") == "sample_guidelines"

    def test_resolve_traversal_source_from_key(self):
        assert gm.resolve_traversal_source("sample_guidelines") == "sample_guidelines_g"

    def test_resolve_unknown_passthrough(self):
        # Unknown names normalize and pass through rather than raising.
        assert gm.resolve_graph_key("does not exist") == "does_not_exist"

    def test_default_traversal_source_is_known(self):
        default = gm.get_default_traversal_source()
        assert default in gm.get_traversal_sources()

    def test_docs_folder_lookup(self):
        folder = gm.get_docs_folder("sample_guidelines_g")
        assert folder and "sample-guidelines" in folder
