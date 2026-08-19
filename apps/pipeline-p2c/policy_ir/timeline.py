"""Temporal queries: what was in force, and what superseded what.

``Lifecycle.SUPERSEDED`` on its own records a status without recording the
replacement, which makes "what applied on 3 March 2026" unanswerable. Supersession
is therefore a typed edge (``DependencyKind.SUPERSEDES``, source replaces target)
paired with the superseding clause's effective period.

Every function here takes the date explicitly. Nothing reads the clock, because a
compiler whose output depends on when it ran cannot produce byte-stable artefacts —
the caller passes ``--as-of`` and the answer is reproducible forever.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable

from .enums import DependencyKind, Lifecycle
from .models import AtomicPolicyClause, PolicyIR

#: Three-valued, like scope: ``None`` means the record does not say.
InForce = bool | None


def parse_date(value: str) -> _dt.date:
    """Parse an ISO date, raising a clear error rather than a ValueError."""
    try:
        return _dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not an ISO 8601 date: {value!r}") from exc


def clause_in_force_on(clause: AtomicPolicyClause, on_date: _dt.date) -> InForce:
    """Is this clause in force on ``on_date``, judged from the clause alone?

    Supersession is *not* considered here — that needs the graph, so use
    :func:`in_force_on`. This function answers only what the clause's own lifecycle
    and effective period state.
    """
    period = clause.effective_period
    if period.start:
        try:
            if on_date < parse_date(period.start):
                return False
        except ValueError:
            return None
    if period.end:
        try:
            if on_date > parse_date(period.end):
                return False
        except ValueError:
            return None

    if clause.lifecycle is Lifecycle.EXPIRED:
        # Expired with an end date already handled above; expired without one is a
        # contradiction the gate reports, and here it simply is not in force.
        return False
    # Lifecycle.SUPERSEDED describes the clause *now*; it must not veto a historical
    # query. Whether a replacement had taken effect on a given date is decided by the
    # supersedes edge in :func:`in_force_on`.
    if clause.lifecycle is Lifecycle.ACTIVE:
        # An author asserting ACTIVE and stating no bounds means "in force now".
        return True
    if clause.lifecycle is Lifecycle.FUTURE and not period.start:
        return None
    if clause.lifecycle is Lifecycle.UNKNOWN and not (period.start or period.end):
        return None
    return True


def superseded_by(ir: PolicyIR, clause_id: str) -> tuple[str, ...]:
    """Clause IDs that directly supersede ``clause_id``."""
    return tuple(
        sorted(
            edge.source_id
            for edge in ir.dependencies
            if edge.kind is DependencyKind.SUPERSEDES and edge.target_id == clause_id
        )
    )


def supersedes(ir: PolicyIR, clause_id: str) -> tuple[str, ...]:
    """Clause IDs that ``clause_id`` directly supersedes."""
    return tuple(
        sorted(
            edge.target_id
            for edge in ir.dependencies
            if edge.kind is DependencyKind.SUPERSEDES and edge.source_id == clause_id
        )
    )


def supersession_chain(ir: PolicyIR, clause_id: str) -> tuple[str, ...]:
    """Walk forward from ``clause_id`` through its replacements, oldest first.

    Stops on a repeat rather than looping, so a malformed cycle yields a finite
    answer here and a blocker from the gate.
    """
    chain = [clause_id]
    seen = {clause_id}
    while True:
        successors = [s for s in superseded_by(ir, chain[-1]) if s not in seen]
        if not successors:
            return tuple(chain)
        chain.append(successors[0])
        seen.add(successors[0])


def supersession_cycles(ir: PolicyIR) -> tuple[tuple[str, ...], ...]:
    """Return every supersession cycle. A clause cannot replace its own replacement."""
    successors: dict[str, list[str]] = {}
    for edge in ir.dependencies:
        if edge.kind is DependencyKind.SUPERSEDES:
            successors.setdefault(edge.target_id, []).append(edge.source_id)

    found: list[tuple[str, ...]] = []
    visiting: set[str] = set()
    done: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            found.append(tuple(stack[stack.index(node) :]) + (node,))
            return
        visiting.add(node)
        stack.append(node)
        for successor in sorted(successors.get(node, ())):
            visit(successor)
        stack.pop()
        visiting.discard(node)
        done.add(node)

    for node in sorted(successors):
        visit(node)
    return tuple(found)


def in_force_on(ir: PolicyIR, clause_id: str, on_date: _dt.date) -> InForce:
    """Is this clause in force on ``on_date``, accounting for supersession?

    A clause is out of force once a replacement has itself taken effect. A
    replacement whose start date is still in the future does not yet displace the
    clause it supersedes, which is what lets a corpus hold both the current and the
    forthcoming version of a rule.
    """
    clauses = ir.clause_index()
    clause = clauses.get(clause_id)
    if clause is None:
        raise KeyError(f"unknown clause {clause_id!r}")

    own = clause_in_force_on(clause, on_date)
    if own is False:
        return False

    for replacement_id in superseded_by(ir, clause_id):
        replacement = clauses.get(replacement_id)
        if replacement is None:
            continue
        start = replacement.effective_period.start
        if not start:
            # A replacement with no start date displaces immediately: the corpus
            # says this clause was replaced and gives no later date.
            return False
        try:
            if on_date >= parse_date(start):
                return False
        except ValueError:
            return None
    return own


def in_force_clause_ids(ir: PolicyIR, on_date: _dt.date) -> frozenset[str]:
    """Clause IDs definitely in force on ``on_date``.

    Clauses whose status is unknown are excluded. Under an explicit ``--as-of`` the
    caller asked what applied on a date, and "we cannot tell" is not an answer that
    should reach an executable projection.
    """
    return frozenset(
        clause.clause_id
        for clause in ir.clauses
        if in_force_on(ir, clause.clause_id, on_date) is True
    )


def unknown_in_force_clause_ids(ir: PolicyIR, on_date: _dt.date) -> frozenset[str]:
    """Clause IDs whose in-force status on ``on_date`` cannot be determined."""
    return frozenset(
        clause.clause_id
        for clause in ir.clauses
        if in_force_on(ir, clause.clause_id, on_date) is None
    )


def latest_in_force(
    ir: PolicyIR, clause_ids: Iterable[str], on_date: _dt.date
) -> tuple[str, ...]:
    """Filter ``clause_ids`` to those definitely in force, preserving order."""
    live = in_force_clause_ids(ir, on_date)
    return tuple(clause_id for clause_id in clause_ids if clause_id in live)
