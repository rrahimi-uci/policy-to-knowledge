"""An independent DMN reader and evaluator.

The point of this module is *not* to be a production DMN engine. It is to give the
test suite a second route to a decision's meaning that shares no code with the
serialiser: read the emitted XML, parse its FEEL unary tests, evaluate the table.
When this agrees with :mod:`evaluation.evaluator` on the conformance fixtures, the
agreement means something. A round-trip through the same AST would not.

Only the subset :mod:`compilers.dmn` emits is supported, and anything outside it
raises rather than being approximated.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .dmn import DMN_MODEL_NS
from policy_ir.feel import FeelError, parse_feel_value, parse_unary_test

_NS = {"dmn": DMN_MODEL_NS}


def _tag(element: ET.Element) -> str:
    return element.tag.split("}", 1)[-1]


def _text_of(parent: ET.Element | None) -> str:
    if parent is None:
        return ""
    node = parent.find("dmn:text", _NS)
    return (node.text or "").strip() if node is not None else ""


@dataclass(frozen=True)
class ReferenceRule:
    """One decision-table row as read back from XML."""

    rule_id: str
    input_entries: tuple[str, ...]
    output_entry: str
    annotation: str = ""


@dataclass(frozen=True)
class ReferenceDecision:
    """One decision table as read back from XML."""

    decision_id: str
    name: str
    hit_policy: str
    input_names: tuple[str, ...]
    rules: tuple[ReferenceRule, ...]

    def evaluate(self, values: Mapping[str, Any]) -> tuple[str, ...]:
        """Return the matching rows' output values, in table order.

        Inputs absent from ``values`` are treated as ``None``, which no unary test
        this compiler emits will match. That mirrors the Policy IR evaluator's
        refusal to let a missing value satisfy a threshold.
        """
        matches: list[str] = []
        for rule in self.rules:
            if len(rule.input_entries) != len(self.input_names):
                raise FeelError(
                    f"rule {rule.rule_id!r} has {len(rule.input_entries)} entries for "
                    f"{len(self.input_names)} inputs"
                )
            hit = True
            for name, entry in zip(self.input_names, rule.input_entries):
                if not parse_unary_test(entry).matches(values.get(name)):
                    hit = False
                    break
            if hit:
                matches.append(rule.output_entry)
                if self.hit_policy in ("UNIQUE", "FIRST", "PRIORITY"):
                    break
        return tuple(matches)

    def evaluate_value(self, values: Mapping[str, Any]) -> Any:
        """Evaluate and return the single output value, or ``None`` if no row hit."""
        matches = self.evaluate(values)
        if not matches:
            return None
        return parse_feel_value(matches[0])


def read_decisions(xml: str) -> dict[str, ReferenceDecision]:
    """Parse every decision table in a DMN document."""
    root = ET.fromstring(xml)
    out: dict[str, ReferenceDecision] = {}
    for decision in root.findall("dmn:decision", _NS):
        table = decision.find("dmn:decisionTable", _NS)
        if table is None:
            continue
        input_names = tuple(
            _text_of(clause.find("dmn:inputExpression", _NS))
            for clause in table.findall("dmn:input", _NS)
        )
        rules: list[ReferenceRule] = []
        for rule in table.findall("dmn:rule", _NS):
            entries = tuple(
                _text_of(entry) for entry in rule.findall("dmn:inputEntry", _NS)
            )
            output = rule.find("dmn:outputEntry", _NS)
            annotation = rule.find("dmn:annotationEntry", _NS)
            rules.append(
                ReferenceRule(
                    rule_id=rule.get("id", ""),
                    input_entries=entries,
                    output_entry=_text_of(output),
                    annotation=_text_of(annotation),
                )
            )
        decision_id = decision.get("id", "")
        out[decision_id] = ReferenceDecision(
            decision_id=decision_id,
            name=decision.get("name", ""),
            hit_policy=table.get("hitPolicy", "UNIQUE"),
            input_names=input_names,
            rules=tuple(rules),
        )
    return out


def input_variable_names(xml: str) -> dict[str, str]:
    """Map ``inputData`` element IDs to their FEEL variable names."""
    root = ET.fromstring(xml)
    out: dict[str, str] = {}
    for node in root.findall("dmn:inputData", _NS):
        variable = node.find("dmn:variable", _NS)
        if variable is not None:
            out[node.get("id", "")] = variable.get("name", "")
    return out
