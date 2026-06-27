"""Unit tests for the read-only Gremlin safety guard."""
import sys
from pathlib import Path

import allure
import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from src.gremlin_safety import gremlin_safety_violation as violation  # noqa: E402


@allure.feature("Explorer Gremlin safety")
class TestGremlinSafety:
    @pytest.mark.parametrize("query", [
        "g.V().count()",
        "g.V().has('name', 'Borrower').valueMap()",
        "g.V().hasLabel('business_rule').limit(10)",
        "g.E().count()",
        "g.V().has('property', 'x')",          # 'property' as a DATA key — allowed
        "g.V().has('rule_type', 'process')",   # 'process' as a DATA value — allowed
        "g.V().propertyMap()",                  # read step, not the mutating property()
        "g.V().has('content', 'remove the file')",  # blocked words only inside a literal
    ])
    @allure.title("Allows read-only query: {query}")
    def test_allows_reads(self, query):
        assert violation(query) is None

    @pytest.mark.parametrize("query,token", [
        ("g.V().drop()", "drop"),
        ("g.V().has('x',1).drop()", "drop"),
        ("g.addV('rule')", "addv"),
        ("g.V(1).addE('rel').to(__.V(2))", "adde"),
        ("g.V(1).property('name','x')", "property"),
        ("g.V(1).property ( 'k', 'v')", "property"),  # whitespace before (
        ("System.exit(0)", "system"),
        ("Thread.sleep(1000)", "thread"),
        ("new HashMap()", "new"),
        ("read File('/etc/passwd')", "file"),
        ("g.V().map{ Runtime.getRuntime() }", "runtime"),
    ])
    @allure.title("Blocks unsafe query ({token}): {query}")
    def test_blocks_mutations(self, query, token):
        assert violation(query) == token

    @allure.title("Empty / None query is treated as safe")
    def test_empty(self):
        assert violation("") is None
        assert violation(None) is None
