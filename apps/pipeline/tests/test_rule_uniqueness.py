"""Unit tests for deterministic rule_id / rule_name uniqueness enforcement."""
import sys
from pathlib import Path

import allure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.rule_uniqueness import enforce_rule_uniqueness  # noqa: E402


@allure.feature("Pipeline rule uniqueness")
class TestRuleUniqueness:
    @allure.title("Duplicate rule_ids get _v2/_v3 suffixes; first keeps its id")
    def test_duplicate_ids(self):
        rules = [
            {"rule_id": "R1", "rule_name": "A"},
            {"rule_id": "R1", "rule_name": "B"},
            {"rule_id": "R1", "rule_name": "C"},
        ]
        out, summary = enforce_rule_uniqueness(rules)
        assert [r["rule_id"] for r in out] == ["R1", "R1_v2", "R1_v3"]
        assert summary["id_fixes"] == 2

    @allure.title("Duplicate rule_names get (Variant N); first stays plain")
    def test_duplicate_names(self):
        rules = [
            {"rule_id": "R1", "rule_name": "Same Name"},
            {"rule_id": "R2", "rule_name": "same name"},  # case-insensitive
        ]
        out, summary = enforce_rule_uniqueness(rules)
        assert out[0]["rule_name"] == "Same Name"
        assert out[1]["rule_name"] == "same name (Variant 2)"
        assert summary["name_fixes"] == 1

    @allure.title("Dependencies on a duplicated id keep pointing at the first rule")
    @allure.description(
        "Regression: a previous version rewrote references to R1 onto the renamed "
        "duplicate R1_v2, silently pointing dependencies at the wrong rule."
    )
    def test_dependencies_not_corrupted(self):
        rules = [
            {"rule_id": "R1", "rule_name": "First"},
            {"rule_id": "R1", "rule_name": "Dup"},
            {"rule_id": "R9", "rule_name": "Dependent",
             "dependencies": [{"depends_on_rule": "R1"}]},
        ]
        out, _ = enforce_rule_uniqueness(rules)
        # The dependency must still resolve to the surviving first rule "R1".
        assert out[2]["dependencies"][0]["depends_on_rule"] == "R1"

    @allure.title("No collisions → list unchanged, zero fixes")
    def test_no_collisions(self):
        rules = [{"rule_id": "A", "rule_name": "x"}, {"rule_id": "B", "rule_name": "y"}]
        out, summary = enforce_rule_uniqueness(rules)
        assert summary == {"id_fixes": 0, "name_fixes": 0}
        assert [r["rule_id"] for r in out] == ["A", "B"]

    @allure.title("Empty / missing ids and names are tolerated")
    def test_missing_fields(self):
        rules = [{}, {"rule_id": "", "rule_name": ""}]
        out, summary = enforce_rule_uniqueness(rules)
        assert summary == {"id_fixes": 0, "name_fixes": 0}
        assert len(out) == 2
