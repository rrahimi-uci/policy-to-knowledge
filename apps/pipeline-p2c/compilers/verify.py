"""Offline structural validation of emitted DMN and BPMN.

CI must stay deterministic and offline, so it cannot download the OMG XSDs. These
checks cover what actually breaks in practice — duplicate IDs, hrefs that resolve
to nothing, rows with the wrong number of entries, sequence flows pointing at
absent nodes, business rule tasks bound to decisions that were never emitted — and
they run with no network and no third-party dependency.

They are a complement to XSD validation, not a replacement, and the README says so:
``scripts/fetch_schemas.py`` pulls the pinned normative schemas for the full check.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter

from .bpmn import BPMN_MODEL_NS, TRACE_NS
from .dmn import DMN_MODEL_NS

_DMN_NS = {"dmn": DMN_MODEL_NS}
_BPMN_NS = {"bpmn": BPMN_MODEL_NS, "p2c": TRACE_NS}

_FEEL_BUILTINS = frozenset(
    {
        "string",
        "number",
        "boolean",
        "date",
        "time",
        "date and time",
        "days and time duration",
        "years and months duration",
        "Any",
    }
)

_ALLOWED_HIT_POLICIES = frozenset({"UNIQUE", "FIRST", "PRIORITY", "COLLECT"})

_FLOW_NODE_TAGS = frozenset(
    {
        "startEvent",
        "endEvent",
        "task",
        "businessRuleTask",
        "subProcess",
        "userTask",
        "serviceTask",
        "exclusiveGateway",
        "inclusiveGateway",
        "parallelGateway",
        "boundaryEvent",
        "intermediateCatchEvent",
        "intermediateThrowEvent",
    }
)


def _all_ids(root: ET.Element) -> list[str]:
    return [element.get("id") for element in root.iter() if element.get("id")]  # type: ignore[misc]


def _duplicate_ids(root: ET.Element) -> list[str]:
    counts = Counter(_all_ids(root))
    return sorted(value for value, count in counts.items() if count > 1)


def validate_dmn(xml: str) -> tuple[str, ...]:
    """Return structural problems in a DMN document; empty means clean."""
    problems: list[str] = []
    root = ET.fromstring(xml)
    for duplicate in _duplicate_ids(root):
        problems.append(f"duplicate id {duplicate!r}")
    known_ids = set(_all_ids(root))
    for element in root.iter():
        href = element.get("href")
        if href and href.startswith("#") and href[1:] not in known_ids:
            problems.append(f"href {href!r} resolves to nothing")

    item_names = {
        item.get("name")
        for item in root.findall("dmn:itemDefinition", _DMN_NS)
        if item.get("name")
    }
    for element in root.iter():
        type_ref = element.get("typeRef")
        if type_ref and type_ref not in _FEEL_BUILTINS and type_ref not in item_names:
            problems.append(f"typeRef {type_ref!r} is neither a FEEL type nor an itemDefinition")

    variable_names = set()
    for node in root.findall("dmn:inputData", _DMN_NS):
        variable = node.find("dmn:variable", _DMN_NS)
        if variable is not None and variable.get("name"):
            variable_names.add(variable.get("name"))

    for decision in root.findall("dmn:decision", _DMN_NS):
        decision_id = decision.get("id", "?")
        table = decision.find("dmn:decisionTable", _DMN_NS)
        if table is None:
            problems.append(f"decision {decision_id!r} has no decision table")
            continue
        hit_policy = table.get("hitPolicy", "UNIQUE")
        if hit_policy not in _ALLOWED_HIT_POLICIES:
            problems.append(f"decision {decision_id!r} uses hit policy {hit_policy!r}")
        if hit_policy == "COLLECT" and not table.get("aggregation"):
            problems.append(f"decision {decision_id!r} uses COLLECT with no aggregation")
        inputs = table.findall("dmn:input", _DMN_NS)
        outputs = table.findall("dmn:output", _DMN_NS)
        if not outputs:
            problems.append(f"decision {decision_id!r} declares no output clause")
        for clause in inputs:
            expression = clause.find("dmn:inputExpression", _DMN_NS)
            text_node = expression.find("dmn:text", _DMN_NS) if expression is not None else None
            text = (text_node.text or "").strip() if text_node is not None else ""
            if text not in variable_names:
                problems.append(
                    f"decision {decision_id!r} reads {text!r}, which is not an inputData "
                    "variable"
                )
        for rule in table.findall("dmn:rule", _DMN_NS):
            rule_id = rule.get("id", "?")
            entries = rule.findall("dmn:inputEntry", _DMN_NS)
            if len(entries) != len(inputs):
                problems.append(
                    f"rule {rule_id!r} has {len(entries)} input entries for {len(inputs)} inputs"
                )
            if len(rule.findall("dmn:outputEntry", _DMN_NS)) != len(outputs):
                problems.append(f"rule {rule_id!r} does not have one entry per output")
    return tuple(problems)


def validate_bpmn(xml: str, *, emitted_decision_ids: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Return structural problems in a BPMN document; empty means clean."""
    problems: list[str] = []
    root = ET.fromstring(xml)
    for duplicate in _duplicate_ids(root):
        problems.append(f"duplicate id {duplicate!r}")

    process_ids = {
        process.get("id") for process in root.findall("bpmn:process", _BPMN_NS) if process.get("id")
    }
    for collaboration in root.findall("bpmn:collaboration", _BPMN_NS):
        for participant in collaboration.findall("bpmn:participant", _BPMN_NS):
            process_ref = participant.get("processRef")
            if process_ref and process_ref not in process_ids:
                problems.append(f"participant references unknown process {process_ref!r}")

    for process in root.findall("bpmn:process", _BPMN_NS):
        process_id = process.get("id", "?")
        node_ids: set[str] = set()
        for child in process:
            if _tag_of(child) in _FLOW_NODE_TAGS and child.get("id"):
                node_ids.add(child.get("id"))  # type: ignore[arg-type]
        referenced: set[str] = set()
        for flow in process.findall("bpmn:sequenceFlow", _BPMN_NS):
            flow_id = flow.get("id", "?")
            for attribute in ("sourceRef", "targetRef"):
                target = flow.get(attribute)
                if target not in node_ids:
                    problems.append(
                        f"sequence flow {flow_id!r} {attribute}={target!r} is not a flow "
                        f"node of process {process_id!r}"
                    )
                else:
                    referenced.add(target)
        if len(node_ids) > 1:
            dangling = sorted(node_ids - referenced)
            if dangling:
                problems.append(
                    f"process {process_id!r} has flow nodes with no sequence flow: {dangling}"
                )
        for lane_set in process.findall("bpmn:laneSet", _BPMN_NS):
            for lane in lane_set.findall("bpmn:lane", _BPMN_NS):
                for reference in lane.findall("bpmn:flowNodeRef", _BPMN_NS):
                    value = (reference.text or "").strip()
                    if value not in node_ids:
                        problems.append(
                            f"lane {lane.get('id')!r} references unknown flow node {value!r}"
                        )
        if process.get("isExecutable") == "true":
            starts = process.findall("bpmn:startEvent", _BPMN_NS)
            ends = process.findall("bpmn:endEvent", _BPMN_NS)
            if len(starts) != 1:
                problems.append(
                    f"executable process {process_id!r} has {len(starts)} start events"
                )
            if not ends:
                problems.append(f"executable process {process_id!r} has no end event")
        for task in process.findall("bpmn:businessRuleTask", _BPMN_NS):
            references = task.findall(
                "bpmn:extensionElements/p2c:decisionRef", _BPMN_NS
            )
            if not references:
                problems.append(
                    f"business rule task {task.get('id')!r} carries no decision binding"
                )
            for reference in references:
                decision_id = reference.get("decisionId", "")
                if emitted_decision_ids and decision_id not in emitted_decision_ids:
                    problems.append(
                        f"business rule task {task.get('id')!r} binds decision "
                        f"{decision_id!r}, which was not emitted"
                    )
    return tuple(problems)


def _tag_of(element: ET.Element) -> str:
    return element.tag.split("}", 1)[-1]
