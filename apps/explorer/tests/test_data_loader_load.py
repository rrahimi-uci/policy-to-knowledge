"""Cover data_loader.load_data / clear_graph with a chainable fake Gremlin traversal."""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import allure
import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from src import data_loader as dl  # noqa: E402


class _FakeG:
    """Chainable stand-in for a Gremlin GraphTraversalSource.

    Every step returns self; terminal steps return simple values so the loader
    code runs end-to-end without a live JanusGraph.
    """
    def __init__(self):
        self._counter = 0

    def __getattr__(self, name):
        def step(*args, **kwargs):
            if name == "next":
                self._counter += 1
                return self._counter
            if name == "toList":
                return []
            if name == "hasNext":
                return False
            return self
        return step


@pytest.fixture
def fake_traversal(monkeypatch):
    @contextmanager
    def _ctx(graph_name):
        yield _FakeG(), object()
    monkeypatch.setattr(dl, "get_traversal", _ctx)


@allure.feature("Explorer data loader")
@allure.story("Validation")
class TestValidation:
    @allure.title("Unknown graph raises ValueError")
    def test_unknown_graph(self):
        with pytest.raises(ValueError):
            dl.load_data("definitely_not_a_graph")

    @allure.title("Missing KG file raises FileNotFoundError")
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            dl.load_data("sample_guidelines_g", json_file=str(tmp_path / "nope.json"))


@allure.feature("Explorer data loader")
@allure.story("Load")
class TestLoad:
    def _kg(self, tmp_path):
        kg = {
            "business_rules": [
                {"rule_id": "R1", "rule_name": "LTV cap", "rule_type": "constraint",
                 "confidence_score": "92", "entity_or_relationship": "Loan",
                 "dependencies": [{"depends_on_rule": "R2", "strength": "3"}]},
                {"rule_id": "R2", "rule_name": "Income", "rule_type": "eligibility",
                 "confidence_score": 0.8, "entity_or_relationship": "Borrower",
                 "dependencies": []},
            ],
            "entity_types": {"Loan": {"definition": "a loan"}, "Borrower": {"definition": "a person"}},
            "relationships": {"APPLIES_FOR": {"source_entity": "Borrower", "target_entity": "Loan"}},
        }
        f = tmp_path / "kg.json"
        f.write_text(json.dumps(kg))
        return f

    @allure.title("load_data ingests a KG via the fake traversal without error")
    def test_load_data(self, tmp_path, fake_traversal):
        f = self._kg(tmp_path)
        # Should complete; coerces non-numeric/string confidence + strength safely.
        dl.load_data("sample_guidelines_g", json_file=str(f))

    @allure.title("load_data with clear_first also runs the clear path")
    def test_load_clear_first(self, tmp_path, fake_traversal, monkeypatch):
        f = self._kg(tmp_path)
        called = {"clear": 0}
        monkeypatch.setattr(dl, "clear_graph", lambda g: called.__setitem__("clear", called["clear"] + 1))
        dl.load_data("sample_guidelines_g", json_file=str(f), clear_first=True)
        assert called["clear"] == 1

    @allure.title("A rule with an unresolved entity triggers the synthetic _uncategorized_ fallback")
    def test_orphan_rule_fallback(self, tmp_path, fake_traversal):
        kg = {
            "business_rules": [
                {"rule_id": "R9", "rule_name": "Floats free", "rule_type": "constraint",
                 "confidence_score": 0.5, "entity_or_relationship": "UnmappedThing",
                 "dependencies": []},
            ],
            "entity_types": {"Loan": {"definition": "a loan"}},
            "relationships": {},
        }
        f = tmp_path / "orphan.json"; f.write_text(json.dumps(kg))
        dl.load_data("sample_guidelines_g", json_file=str(f))  # must not raise


@allure.feature("Explorer data loader")
@allure.story("Clear + bulk load")
class TestClearAndAll:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        from src import graph_connection as gc_mod
        state = {"counts": [], "submitted": []}

        class _Client:
            def submit(self, query):
                state["submitted"].append(query)
                if "count" in query:
                    return [state["counts"].pop(0)]
                return []

        @contextmanager
        def _ctx(graph_name):
            yield _Client()

        monkeypatch.setattr(gc_mod, "get_client", _ctx)
        return state

    @allure.title("clear_graph short-circuits on an empty graph")
    def test_clear_empty(self, fake_client):
        fake_client["counts"] = [0]
        dl.clear_graph("sample_guidelines_g")
        assert not any("drop" in q for q in fake_client["submitted"])

    @allure.title("clear_graph drops vertices when the graph is non-empty")
    def test_clear_nonempty(self, fake_client):
        fake_client["counts"] = [7]
        dl.clear_graph("sample_guidelines_g")
        assert any("drop" in q for q in fake_client["submitted"])

    @allure.title("load_all_graphs loads present KGs and skips missing ones")
    def test_load_all(self, tmp_path, monkeypatch):
        present = tmp_path / "present.json"; present.write_text("{}")
        monkeypatch.setattr(dl, "GRAPH_CONFIGS", {
            "ok_g": {"file": str(present), "name": "OK"},
            "missing_g": {"file": str(tmp_path / "nope.json"), "name": "Missing"},
        })
        loaded = []
        monkeypatch.setattr(dl, "load_data", lambda name, clear_first=False: loaded.append(name))
        dl.load_all_graphs()
        assert loaded == ["ok_g"]
