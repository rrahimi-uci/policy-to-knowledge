"""BPMN compiler tests.

Every assertion here is a refusal to invent. A BPMN diagram is persuasive — it
looks like a process whether or not the source described one — so the tests focus
on what must *not* appear.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from compilers.bpmn import BPMN_MODEL_NS, TRACE_NS, compile_bpmn
from compilers.dmn import compile_dmn
from compilers.verify import validate_bpmn
from fixtures import all_fixtures
from policy_ir.enums import CompilerProfile
from policy_ir.models import ProcessFragmentCandidate, TriggerEvent
from validation import blockers as codes
from validation import run_gate

NS = {"bpmn": BPMN_MODEL_NS, "p2c": TRACE_NS}
EXECUTABLE = CompilerProfile.EXECUTABLE_SUBSET
REVIEW = CompilerProfile.REVIEW


def compiled(name: str, profile: CompilerProfile = EXECUTABLE):
    item = all_fixtures()[name]
    report = run_gate(item.ir, item.texts)
    return item, report, compile_bpmn(item.ir, report, profile=profile)


def test_the_emitted_document_targets_bpmn_202() -> None:
    _, _, artifact = compiled("notice_process")
    assert f'xmlns="{BPMN_MODEL_NS}"' in artifact.xml
    assert "20100524" in artifact.xml


def test_emitted_bpmn_is_structurally_clean() -> None:
    item, report, artifact = compiled("notice_process")
    decisions = compile_dmn(item.ir, report)
    assert validate_bpmn(artifact.xml, emitted_decision_ids=frozenset(decisions.emitted_ids)) == ()


def test_every_sequence_flow_connects_two_real_nodes() -> None:
    _, _, artifact = compiled("notice_process")
    root = ET.fromstring(artifact.xml)
    process = root.find("bpmn:process", NS)
    assert process is not None
    node_ids = {
        child.get("id")
        for child in process
        if child.tag.split("}")[-1] not in ("laneSet", "sequenceFlow", "documentation")
    }
    flows = process.findall("bpmn:sequenceFlow", NS)
    assert flows
    for flow in flows:
        assert flow.get("sourceRef") in node_ids
        assert flow.get("targetRef") in node_ids


def test_executable_process_has_one_start_and_a_reachable_end() -> None:
    _, _, artifact = compiled("notice_process")
    root = ET.fromstring(artifact.xml)
    process = root.find("bpmn:process", NS)
    assert process is not None
    assert process.get("isExecutable") == "true"
    assert len(process.findall("bpmn:startEvent", NS)) == 1
    assert len(process.findall("bpmn:endEvent", NS)) == 1


def test_business_rule_task_binds_a_decision_without_vendor_attributes() -> None:
    item, report, artifact = compiled("notice_process")
    decisions = compile_dmn(item.ir, report)
    root = ET.fromstring(artifact.xml)
    task = root.find(".//bpmn:businessRuleTask", NS)
    assert task is not None
    binding = task.find("bpmn:extensionElements/p2c:decisionRef", NS)
    assert binding is not None
    assert binding.get("decisionId") in decisions.emitted_ids
    # The binding lives in extensionElements, so the canonical file stays portable.
    assert "camunda" not in artifact.xml.lower()
    assert "decisionRef=" not in artifact.xml


def test_lanes_come_from_stated_responsibility() -> None:
    _, _, artifact = compiled("notice_process")
    root = ET.fromstring(artifact.xml)
    lanes = root.findall(".//bpmn:lane", NS)
    assert [lane.get("name") for lane in lanes] == ["Lender"]
    participants = root.findall(".//bpmn:participant", NS)
    assert [p.get("name") for p in participants] == ["Lender"]


def test_a_retention_deadline_does_not_become_a_timer_process() -> None:
    """The plan's sharpest example: an obligation is not a five-year timer."""
    item, report, artifact = compiled("retention_obligation")
    assert item.ir.processes == ()
    assert artifact.emitted_ids == ()
    assert "timerEventDefinition" not in artifact.xml
    assert "startEvent" not in artifact.xml
    assert "sequenceFlow" not in artifact.xml


def test_a_temporal_constraint_alone_never_produces_a_timer_event() -> None:
    """The fragment has a 30-day constraint, but its trigger is a message."""
    item, _, artifact = compiled("notice_process")
    fragment = item.ir.processes[0]
    assert fragment.temporal_constraint is not None
    assert fragment.trigger_event is not None and fragment.trigger_event.kind == "message"
    assert "timerEventDefinition" not in artifact.xml
    assert "messageEventDefinition" in artifact.xml


def test_a_timer_trigger_does_produce_a_timer_event() -> None:
    """A timer appears only when the trigger itself is stated to be one."""
    item = all_fixtures()["notice_process"]
    fragment = item.ir.processes[0]
    timed = ProcessFragmentCandidate(
        **{
            **{f: getattr(fragment, f) for f in fragment.__dataclass_fields__},
            "trigger_event": TriggerEvent(
                event_id=fragment.trigger_event.event_id,
                name=fragment.trigger_event.name,
                kind="timer",
                evidence_ids=fragment.trigger_event.evidence_ids,
            ),
        }
    )
    ir = type(item.ir)(
        **{
            **{f: getattr(item.ir, f) for f in item.ir.__dataclass_fields__},
            "processes": (timed,),
        }
    )
    report = run_gate(ir, item.texts)
    artifact = compile_bpmn(ir, report)
    assert "timerEventDefinition" in artifact.xml
    assert "<timeDuration" in artifact.xml


def test_a_missing_actor_blocks_the_executable_subset() -> None:
    item, report, executable = compiled("missing_actor_process")
    assert codes.MISSING_RESPONSIBLE_ACTOR in set(report.counts_by_code())
    assert executable.emitted_ids == ()


def test_a_missing_actor_still_produces_a_review_fragment() -> None:
    item, report, review = compiled("missing_actor_process", REVIEW)
    assert review.emitted_ids == ("fragment_adverse_action_notice",)
    assert "REVIEW ONLY" in review.xml
    assert 'isExecutable="false"' in review.xml
    assert validate_bpmn(review.xml) == ()
    root = ET.fromstring(review.xml)
    # The activities still state who performs them, so a lane is drawn from that
    # evidence. What is missing is fragment-level responsibility, so no pool
    # (participant) is asserted — a lane without a pool is valid BPMN and is the
    # honest picture of "we know who does each step, not who owns the process".
    assert [lane.get("name") for lane in root.findall(".//bpmn:lane", NS)] == ["Lender"]
    assert root.findall(".//bpmn:participant", NS) == []


def test_an_unevidenced_order_guess_is_not_a_sequence_flow() -> None:
    """Two rules sharing an entity do not imply an order."""
    item, report, artifact = compiled("inferred_sequence")
    all_codes = set(report.counts_by_code())
    assert codes.ORDERING_NOT_VALIDATED in all_codes
    assert codes.UNVALIDATED_EXECUTABLE_DEPENDENCY in all_codes
    assert artifact.emitted_ids == ()


def test_branching_is_refused_rather_than_guessed_as_a_gateway() -> None:
    item = all_fixtures()["notice_process"]
    fragment = item.ir.processes[0]
    branched = ProcessFragmentCandidate(
        **{
            **{f: getattr(fragment, f) for f in fragment.__dataclass_fields__},
            "ordering": (
                ("activity_evaluate_eligibility", "activity_send_notice"),
                ("activity_evaluate_eligibility", "activity_evaluate_eligibility"),
            ),
        }
    )
    ir = type(item.ir)(
        **{
            **{f: getattr(item.ir, f) for f in item.ir.__dataclass_fields__},
            "processes": (branched,),
        }
    )
    report = run_gate(ir, item.texts)
    assert codes.BRANCHING_NOT_SUPPORTED in report.processes[fragment.fragment_id].codes()
    artifact = compile_bpmn(ir, report)
    assert artifact.emitted_ids == ()
    assert "Gateway" not in artifact.xml


def test_identical_input_compiles_to_identical_bytes() -> None:
    item = all_fixtures()["notice_process"]
    first = compile_bpmn(item.ir, run_gate(item.ir, item.texts))
    second = compile_bpmn(item.ir, run_gate(item.ir, item.texts))
    assert first.xml == second.xml
