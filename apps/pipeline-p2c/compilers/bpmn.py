"""The conservative BPMN 2.0.2 compiler.

Target: OMG BPMN 2.0.2, ``formal/13-12-09``, namespace
``http://www.omg.org/spec/BPMN/20100524/MODEL`` — still the latest formal BPMN
release.

The subset is deliberately narrow, and every narrowing is a refusal to invent:

* **One chain per fragment.** No gateways are emitted. A gateway needs branch
  conditions and a declared default path; the gate refuses branching outright
  rather than letting this compiler guess a split.
* **A timer only from a timer trigger.** A ``temporal_constraint`` never becomes a
  ``timerEventDefinition``. "Records must be retained for five years" is an
  obligation, not a five-year timer, and the retention fixture asserts that.
* **Lanes only from stated responsibility.** A lane appears when an actor is
  declared and categorised as something that can own work.
* **Vendor-neutral DMN binding.** The link from a business rule task to its
  decision goes in ``extensionElements`` under this project's own namespace, so
  the canonical file carries no engine-specific attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from policy_ir.enums import CompilerProfile, Status
from policy_ir.ids import SCHEMA_VERSION, ncname
from policy_ir.models import PolicyIR, ProcessFragmentCandidate
from validation import blockers as codes
from validation.evidence_gate import Blocker, GateReport

from .dmn import REVIEWABLE_CODES, CompiledArtifact
from .xmlwriter import Element, serialize

BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMN_DI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
TRACE_NS = "urn:p2c:trace"
BPMN_SPEC = "OMG BPMN 2.0.2 (formal/13-12-09)"

EXPORTER = "pipeline-p2c"
EXPORTER_VERSION = SCHEMA_VERSION

_EVENT_DEFINITIONS = {
    "message": "messageEventDefinition",
    "timer": "timerEventDefinition",
    "condition": "conditionalEventDefinition",
}


@dataclass(frozen=True)
class _Chain:
    """A fragment's flow nodes in emission order."""

    start_id: str
    activity_ids: tuple[str, ...]
    end_id: str

    def node_ids(self) -> tuple[str, ...]:
        return (self.start_id, *self.activity_ids, self.end_id)


def _ordered_activities(fragment: ProcessFragmentCandidate) -> tuple[str, ...]:
    """Return activity IDs in validated order.

    The gate has already refused fragments whose ordering branches or cycles, so a
    single chain is all that can arrive here. Activities with no ordering at all
    keep declaration order, which is stable because the IR is.
    """
    successors = {source: target for source, target in fragment.ordering}
    targets = set(successors.values())
    declared = [activity.activity_id for activity in fragment.activities]
    roots = [activity_id for activity_id in declared if activity_id not in targets]
    if not roots:
        return tuple(declared)
    chain: list[str] = []
    current: str | None = roots[0]
    seen: set[str] = set()
    while current is not None and current not in seen:
        chain.append(current)
        seen.add(current)
        current = successors.get(current)
    for activity_id in declared:
        if activity_id not in seen:
            chain.append(activity_id)
    return tuple(chain)


def _fragment_is_emittable(
    fragment: ProcessFragmentCandidate,
    report: GateReport,
    profile: CompilerProfile,
) -> tuple[bool, tuple[Blocker, ...]]:
    element_report = report.processes.get(fragment.fragment_id)
    if element_report is None:
        return False, (Blocker(codes.NO_ACTIVITY, fragment.fragment_id, "no gate report"),)
    if element_report.has(Status.BPMN_ELIGIBLE):
        return True, ()
    if profile is CompilerProfile.EXECUTABLE_SUBSET:
        return False, element_report.blockers
    # The review profile still needs something to draw: an activity, and an
    # ordering that is a chain rather than an invented graph.
    reviewable = REVIEWABLE_CODES | {
        codes.MISSING_RESPONSIBLE_ACTOR,
        codes.MISSING_TRIGGER,
        codes.MISSING_END_STATE,
        codes.ORDERING_NOT_VALIDATED,
        codes.MISSING_ACTIVITY_EVIDENCE,
        codes.BUSINESS_RULE_TASK_WITHOUT_DECISION,
    }
    hard = [b for b in element_report.blockers if b.code not in reviewable]
    if hard or not fragment.activities:
        return False, tuple(hard) or (
            Blocker(codes.NO_ACTIVITY, fragment.fragment_id, "nothing to draw"),
        )
    return True, ()


def compile_bpmn(
    ir: PolicyIR,
    report: GateReport,
    *,
    profile: CompilerProfile = CompilerProfile.EXECUTABLE_SUBSET,
    model_name: str = "PolicyProcesses",
    target_namespace: str = "urn:p2c:processes",
    filename: str | None = None,
    decision_file: str = "decisions.dmn",
) -> CompiledArtifact:
    """Compile admitted process fragments into one BPMN 2.0.2 definitions document."""
    if filename is None:
        filename = (
            "processes-executable.bpmn"
            if profile is CompilerProfile.EXECUTABLE_SUBSET
            else "processes-review.bpmn"
        )
    entities = ir.entity_index()

    emitted: list[ProcessFragmentCandidate] = []
    skipped: list[Blocker] = []
    for fragment in sorted(ir.processes, key=lambda p: p.fragment_id):
        allowed, why = _fragment_is_emittable(fragment, report, profile)
        if allowed:
            emitted.append(fragment)
        else:
            skipped.extend(why)

    root = Element(
        "definitions",
        {
            "xmlns": BPMN_MODEL_NS,
            "xmlns:bpmndi": BPMN_DI_NS,
            "xmlns:xsi": XSI_NS,
            "xmlns:p2c": TRACE_NS,
            "id": ncname(f"definitions_{model_name}"),
            "name": model_name,
            "targetNamespace": target_namespace,
            "exporter": EXPORTER,
            "exporterVersion": EXPORTER_VERSION,
        },
    )

    trace: dict[str, object] = {
        "specification": BPMN_SPEC,
        "profile": profile.value,
        "processes": {},
    }

    participants: list[tuple[str, str, str]] = []
    processes: list[Element] = []

    for fragment in emitted:
        element_report = report.processes.get(fragment.fragment_id)
        executable = bool(element_report and element_report.has(Status.BPMN_ELIGIBLE))
        process_id = ncname(f"process_{fragment.fragment_id}")
        activity_order = _ordered_activities(fragment)
        activities = {a.activity_id: a for a in fragment.activities}

        start_id = ncname(
            f"start_{fragment.trigger_event.event_id}"
            if fragment.trigger_event
            else f"start_{fragment.fragment_id}"
        )
        end_id = ncname(f"end_{fragment.fragment_id}")
        chain = _Chain(start_id, activity_order, end_id)

        process = Element(
            "process",
            {
                "id": process_id,
                "name": fragment.name,
                "isExecutable": "true" if executable else "false",
            },
        )
        if not executable:
            reasons = ", ".join(
                sorted({b.code for b in (element_report.blockers if element_report else ())})
            )
            process.child(
                "documentation",
                None,
                "REVIEW ONLY - not admitted for execution"
                + (f" ({reasons})" if reasons else ""),
            )

        # Lanes come before flow elements in tProcess.
        actor_ids = [
            activity.actor_ref
            for activity in (activities[a] for a in activity_order)
            if activity.actor_ref
        ]
        if fragment.responsible_actor_ref:
            actor_ids.insert(0, fragment.responsible_actor_ref)
        lane_actors: list[str] = []
        for actor_id in actor_ids:
            if actor_id not in lane_actors and actor_id in entities:
                lane_actors.append(actor_id)
        if lane_actors:
            lane_set = process.child("laneSet", {"id": ncname(f"laneset_{fragment.fragment_id}")})
            for actor_id in lane_actors:
                lane = lane_set.child(
                    "lane",
                    {
                        "id": ncname(f"lane_{fragment.fragment_id}_{actor_id}"),
                        "name": entities[actor_id].name,
                    },
                )
                owned = [
                    activity_id
                    for activity_id in activity_order
                    if (activities[activity_id].actor_ref or fragment.responsible_actor_ref)
                    == actor_id
                ]
                if actor_id == lane_actors[0]:
                    owned = [start_id, *owned, end_id]
                for node_id in owned:
                    lane.child("flowNodeRef", None, node_id)

        start = process.child(
            "startEvent",
            {
                "id": start_id,
                "name": fragment.trigger_event.name if fragment.trigger_event else "Start",
            },
        )
        if fragment.trigger_event is not None:
            definition = _EVENT_DEFINITIONS.get(fragment.trigger_event.kind)
            if definition == "timerEventDefinition":
                timer = start.child(
                    "timerEventDefinition",
                    {"id": ncname(f"timerdef_{fragment.trigger_event.event_id}")},
                )
                if fragment.temporal_constraint is not None:
                    timer.child(
                        "timeDuration",
                        {"xsi:type": "tFormalExpression"},
                        fragment.temporal_constraint.duration.value,
                    )
            elif definition is not None:
                start.child(
                    definition,
                    {"id": ncname(f"eventdef_{fragment.trigger_event.event_id}")},
                )

        for activity_id in activity_order:
            activity = activities[activity_id]
            tag = {
                "task": "task",
                "business_rule_task": "businessRuleTask",
                "subprocess": "subProcess",
            }[activity.kind]
            attributes = {"id": ncname(activity_id), "name": activity.name}
            if tag == "businessRuleTask":
                attributes["implementation"] = "##unspecified"
            node = process.child(tag, attributes)
            if activity.decision_ref:
                extension = node.child("extensionElements")
                extension.child(
                    "p2c:decisionRef",
                    {
                        "href": f"{decision_file}#{activity.decision_ref}",
                        "decisionId": activity.decision_ref,
                    },
                )

        process.child("endEvent", {"id": end_id, "name": fragment.end_state or "End"})

        node_ids = chain.node_ids()
        for index in range(len(node_ids) - 1):
            process.child(
                "sequenceFlow",
                {
                    "id": ncname(f"flow_{fragment.fragment_id}_{index}"),
                    "sourceRef": node_ids[index],
                    "targetRef": node_ids[index + 1],
                },
            )

        processes.append(process)
        if fragment.responsible_actor_ref and fragment.responsible_actor_ref in entities:
            participants.append(
                (
                    ncname(f"participant_{fragment.fragment_id}"),
                    entities[fragment.responsible_actor_ref].name,
                    process_id,
                )
            )

        trace["processes"][fragment.fragment_id] = {  # type: ignore[index]
            "executable": executable,
            "process_id": process_id,
            "flow_nodes": list(node_ids),
            "clause_refs": list(fragment.clause_refs),
            "decision_refs": sorted(
                {a.decision_ref for a in fragment.activities if a.decision_ref}
            ),
            "evidence_ids": list(fragment.evidence_ids),
        }

    if participants:
        collaboration = Element(
            "collaboration", {"id": ncname(f"collaboration_{model_name}")}
        )
        for participant_id, name, process_ref in participants:
            collaboration.child(
                "participant",
                {"id": participant_id, "name": name, "processRef": process_ref},
            )
        root.append(collaboration)
    for process in processes:
        root.append(process)

    return CompiledArtifact(
        filename=filename,
        xml=serialize(root),
        emitted_ids=tuple(fragment.fragment_id for fragment in emitted),
        skipped=tuple(skipped),
        trace=trace,
    )
