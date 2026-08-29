"""Regression test: Agent 5's rule-merge dedup must not drop a duplicate's
field_evidence.

Context: `_deduplicate_rules_single` already collects `source_reference`
from every rule in a duplicate group (primary + duplicates) into the
surviving primary rule, but never did the same for `field_evidence`. A
removed duplicate's per-field citations (scope_basis, outcomes, exceptions,
...) are real evidence for the merged rule, not just its source_reference —
dropping them silently loses a section's only citation whenever that
section was cited exclusively through a duplicate's field_evidence.

Real case found on a full OPP-115 benchmark run: rule
`batch40_lodgemfg_do_not_track_honored_no_cookies_or_ads_v1` was merged as a
duplicate into `batch63_r4_dnt_honor_...`, and its `field_evidence.scope_basis`
and `field_evidence.outcomes` citations (two distinct sections, cited
nowhere else in the corpus) vanished — kg_readiness.corpus_manifest's "every
corpus change needs an explicit reason" check correctly flagged both as
unexplained removals and failed the whole pipeline's corpus_integrity
invariant.
"""

from unittest.mock import patch

from agents.agent_5_knowledge_graph_optimizer import KnowledgeGraphOptimizer


def _optimizer() -> KnowledgeGraphOptimizer:
    return KnowledgeGraphOptimizer(api_key="sk-dummy")


def _dedup_result(primary_id: str, duplicate_id: str) -> dict:
    return {
        "duplicate_groups": [
            {
                "primary_rule_id": primary_id,
                "duplicate_rule_ids": [duplicate_id],
                "merged_description": "Merged description.",
                "rationale": "Same practice, same trigger, same consequences.",
                "confidence": "high",
                "similarity_score": 0.96,
            }
        ],
        "statistics": {},
    }


def test_duplicates_field_evidence_is_merged_into_the_surviving_primary_rule():
    optimizer = _optimizer()
    primary = {
        "rule_id": "primary-001",
        "source_reference": {"chunk_path": "a.txt", "section_id": "A", "source_text": "quote a"},
        "field_evidence": {
            "outcomes": [{"chunk_path": "a.txt", "section_id": "A", "source_text": "quote a"}],
        },
    }
    duplicate = {
        "rule_id": "duplicate-002",
        "source_reference": {"chunk_path": "b.txt", "section_id": "B", "source_text": "quote b"},
        "field_evidence": {
            # A field the primary has nothing for — must be added, not dropped.
            "scope_basis": [{"chunk_path": "c.txt", "section_id": "C — cited nowhere else", "source_text": "quote c"}],
            # A field the primary already has an entry for — must be extended, not replaced.
            "outcomes": [{"chunk_path": "d.txt", "section_id": "D", "source_text": "quote d"}],
        },
    }

    with patch.object(optimizer, "_json_request", return_value=_dedup_result("primary-001", "duplicate-002")):
        deduplicated, _metadata = optimizer._deduplicate_rules_single([primary, duplicate])

    assert len(deduplicated) == 1
    merged = deduplicated[0]
    assert merged["rule_id"] == "primary-001"

    scope_sections = {e["section_id"] for e in merged["field_evidence"]["scope_basis"]}
    assert "C — cited nowhere else" in scope_sections, "duplicate's only citation for this field was dropped"

    outcome_sections = {e["section_id"] for e in merged["field_evidence"]["outcomes"]}
    assert outcome_sections == {"A", "D"}, "primary's own outcomes evidence must survive alongside the duplicate's"


def test_no_field_evidence_on_either_rule_does_not_crash():
    optimizer = _optimizer()
    primary = {"rule_id": "primary-001", "source_reference": {"chunk_path": "a.txt", "section_id": "A", "source_text": "quote a"}}
    duplicate = {"rule_id": "duplicate-002", "source_reference": {"chunk_path": "b.txt", "section_id": "B", "source_text": "quote b"}}

    with patch.object(optimizer, "_json_request", return_value=_dedup_result("primary-001", "duplicate-002")):
        deduplicated, _metadata = optimizer._deduplicate_rules_single([primary, duplicate])

    assert len(deduplicated) == 1
    assert deduplicated[0]["rule_id"] == "primary-001"


def test_duplicate_and_primary_citing_the_same_section_is_not_duplicated():
    optimizer = _optimizer()
    shared_entry = {"chunk_path": "a.txt", "section_id": "A", "source_text": "quote a"}
    primary = {
        "rule_id": "primary-001",
        "source_reference": shared_entry,
        "field_evidence": {"outcomes": [dict(shared_entry)]},
    }
    duplicate = {
        "rule_id": "duplicate-002",
        "source_reference": {"chunk_path": "b.txt", "section_id": "B", "source_text": "quote b"},
        "field_evidence": {"outcomes": [dict(shared_entry)]},
    }

    with patch.object(optimizer, "_json_request", return_value=_dedup_result("primary-001", "duplicate-002")):
        deduplicated, _metadata = optimizer._deduplicate_rules_single([primary, duplicate])

    assert len(deduplicated[0]["field_evidence"]["outcomes"]) == 1
