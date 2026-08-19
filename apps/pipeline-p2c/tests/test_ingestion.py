"""Stage 0/1 ingestion: canonical text, offsets, sections and coverage.

The PDF tests run against the corpus committed under ``apps/pipeline/compliance-files``
and skip cleanly when it or ``pypdf`` is absent. They read those files but never write
to that app.

The property that matters most is determinism: ingesting the same bytes twice must
produce the same hashes, the same chunk boundaries and the same coverage, because
every citation downstream is anchored to them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestion import SourceRegistry, find_headings, section_at, segment_by_section
from policy_ir.enums import SemanticRole
from policy_ir.ids import sha256_text
from policy_ir.models import PolicyIR
from validation import run_gate

pypdf = pytest.importorskip("pypdf", reason="PDF ingestion needs the optional pypdf extra")

from ingestion.pdf import (  # noqa: E402  (after importorskip by design)
    canonicalise,
    extract_pages,
    ingest_pdf,
    parser_version,
    section_for_offset,
)

#: The committed source corpus, read-only. It lives in the sibling pipeline app; these
#: tests never write there.
COMPLIANCE = Path(__file__).resolve().parents[2] / "pipeline" / "compliance-files"
SMALL_PDF = COMPLIANCE / "comercial_lending" / "bulletin_2013_9a.pdf"
#: 59 pages, one of which is a scanned image — the corpus's own coverage gap.
GAPPED_PDF = COMPLIANCE / "healthcare" / "nursing_facility_icpg.pdf"

requires_corpus = pytest.mark.skipif(
    not SMALL_PDF.exists(), reason="the committed compliance PDFs are not present"
)


# -- section detection (no PDF needed) --------------------------------------


def test_every_drafting_convention_is_recognised() -> None:
    text = "\n".join(
        [
            "§ 1016.5(a) Annual notice",
            "Section 4.2 Purchase eligibility",
            "Chapter 3 Underwriting",
            "Ch. 12 Servicing",
            "Part II Investigative procedures",
            "Appendix V Emergency cases",
            "Subpart C3 Securitising",
            "7.1 Adverse action",
        ]
    )
    kinds = {heading.kind for heading in find_headings(text)}
    assert kinds == {
        "section_symbol",
        "section_word",
        "chapter",
        "chapter_short",
        "part",
        "appendix",
        "subpart",
        "numbered",
    }


def test_a_mid_sentence_cross_reference_is_not_a_heading() -> None:
    """Headings anchor at line starts, so "see § 1016.8" stays prose."""
    text = "The lender must comply; see § 1016.8 for the revised notice rules.\n"
    assert find_headings(text) == ()


def test_front_matter_is_not_attributed_to_the_first_section() -> None:
    text = "Cover page text\nSection 1.1 Scope\nbody\n"
    headings = find_headings(text)
    assert section_at(headings, 0) == ""
    assert section_at(headings, text.index("body")) == "Section 1.1"


def test_segments_tile_the_text_without_gaps_or_overlaps() -> None:
    text = "preamble\nSection 1.1 A\n" + ("x" * 500) + "\nSection 1.2 B\n" + ("y" * 500)
    segments = segment_by_section(text)
    assert segments[0].char_start == 0
    assert segments[-1].char_end == len(text)
    for earlier, later in zip(segments, segments[1:]):
        assert earlier.char_end == later.char_start


def test_a_long_section_splits_but_keeps_its_label() -> None:
    text = "Section 9.9 Long\n" + ("z" * 5_000)
    segments = segment_by_section(text, max_length=1_000)
    assert len(segments) > 1
    assert {segment.section_path for segment in segments} == {"Section 9.9"}
    assert sum(segment.length for segment in segments) == len(text)


# -- canonicalisation -------------------------------------------------------


def test_a_wrapped_sentence_becomes_citable() -> None:
    """This is the reason canonical text is normalised at all."""
    raw = "The Lender must   pay\n  the fee within\n10 business days.\n"
    canonical, _ = canonicalise(raw)
    assert canonical == "The Lender must pay the fee within 10 business days."
    assert "must pay the fee within 10 business days." in canonical
    # The phrase does not occur in the raw extraction, which is the whole problem.
    assert "must pay the fee within 10 business days." not in raw


def test_offsets_are_translated_into_canonical_coordinates() -> None:
    raw = "A\n\nSection 2.1\n\nbody"
    marker = raw.index("Section 2.1")
    canonical, mapped = canonicalise(raw, [0, marker])
    assert mapped[0] == 0
    assert canonical[mapped[marker] :].startswith("Section 2.1")


def test_an_offset_inside_collapsed_whitespace_maps_to_the_next_word() -> None:
    raw = "one    two"
    canonical, mapped = canonicalise(raw, [4])
    assert canonical == "one two"
    assert canonical[mapped[4] :].startswith(" two") or canonical[mapped[4] :].startswith("two")


def test_canonicalisation_is_idempotent() -> None:
    raw = "  a\n\n  b   c \n"
    once, _ = canonicalise(raw)
    twice, _ = canonicalise(once)
    assert once == twice


# -- PDF ingestion ----------------------------------------------------------


@requires_corpus
def test_the_parser_version_names_the_extractor_and_the_normaliser() -> None:
    """A different extractor is a different canonical text, so it is recorded."""
    version = parser_version()
    assert version.startswith("pypdf-")
    assert version.endswith("+normalize-1")


@requires_corpus
def test_extraction_is_deterministic() -> None:
    first = "".join(page.text for page in extract_pages(SMALL_PDF))
    second = "".join(page.text for page in extract_pages(SMALL_PDF))
    assert sha256_text(first) == sha256_text(second)


@requires_corpus
def test_ingesting_twice_produces_identical_hashes_and_chunks() -> None:
    one = ingest_pdf(SourceRegistry(), SMALL_PDF)
    two = ingest_pdf(SourceRegistry(), SMALL_PDF)
    assert one.document.source_sha256 == two.document.source_sha256
    assert one.document.canonical_text_sha256 == two.document.canonical_text_sha256
    assert [c.chunk_id for c in one.chunks] == [c.chunk_id for c in two.chunks]
    assert [(c.status, c.chunk_id) for c in one.coverage] == [
        (c.status, c.chunk_id) for c in two.coverage
    ]


@requires_corpus
def test_the_canonical_text_hash_covers_what_offsets_index() -> None:
    registry = SourceRegistry()
    result = ingest_pdf(registry, SMALL_PDF)
    assert result.document.canonical_text_sha256 == sha256_text(result.canonical_text)
    assert registry.text(result.document.document_id) == result.canonical_text


@requires_corpus
def test_every_chunk_hashes_to_the_text_at_its_offsets() -> None:
    registry = SourceRegistry()
    result = ingest_pdf(registry, SMALL_PDF)
    for chunk in result.chunks:
        body = result.canonical_text[chunk.char_start : chunk.char_end]
        assert sha256_text(body) == chunk.chunk_sha256


@requires_corpus
def test_content_chunks_tile_the_document() -> None:
    result = ingest_pdf(SourceRegistry(), SMALL_PDF)
    content = [c for c in result.chunks if c.char_end > c.char_start]
    assert content[0].char_start == 0
    assert content[-1].char_end == len(result.canonical_text)
    for earlier, later in zip(content, content[1:]):
        assert earlier.char_end == later.char_start


@requires_corpus
def test_chunks_carry_the_section_they_fall_in() -> None:
    result = ingest_pdf(SourceRegistry(), SMALL_PDF)
    labelled = [c for c in result.chunks if c.section_path.startswith("§")]
    assert labelled, "this document is organised by section symbols"
    for chunk in labelled:
        assert section_for_offset(result, chunk.char_start) == chunk.section_path


@requires_corpus
def test_the_chunk_cap_is_respected() -> None:
    result = ingest_pdf(SourceRegistry(), SMALL_PDF, max_chunk_chars=2_000)
    content = [c for c in result.chunks if c.char_end > c.char_start]
    assert content and all(c.char_end - c.char_start <= 2_000 for c in content)


@requires_corpus
def test_a_real_obligation_can_be_cited_and_round_trips() -> None:
    registry = SourceRegistry()
    result = ingest_pdf(registry, SMALL_PDF)
    needle = "must provide a clear and conspicuous notice to customers"
    holder = next(
        (c for c in result.chunks if needle in registry.chunk_text(c.chunk_id)), None
    )
    assert holder is not None, "expected this notice obligation in the bulletin"
    span = registry.make_span(holder.chunk_id, needle, SemanticRole.EFFECT)
    assert result.canonical_text[span.char_start : span.char_end] == span.exact_text
    assert span.section_path


@pytest.mark.skipif(not GAPPED_PDF.exists(), reason="gapped corpus PDF not present")
def test_a_page_with_no_extractable_text_is_recorded_not_dropped() -> None:
    """A silently dropped page makes a corpus look complete when it is not."""
    result = ingest_pdf(SourceRegistry(), GAPPED_PDF)
    assert result.pages_without_text, "this document contains a scanned page"
    failed = [entry for entry in result.coverage if entry.status == "extraction_failed"]
    assert len(failed) == len(result.pages_without_text)
    for entry in failed:
        assert "OCR" in entry.note
    placeholders = {c.chunk_id for c in result.chunks if c.char_end == c.char_start}
    assert {entry.chunk_id for entry in failed} <= placeholders
    assert 0 < result.extraction_gap < 1


@pytest.mark.skipif(not GAPPED_PDF.exists(), reason="gapped corpus PDF not present")
def test_the_coverage_ledger_accounts_for_every_chunk() -> None:
    result = ingest_pdf(SourceRegistry(), GAPPED_PDF)
    assert {entry.chunk_id for entry in result.coverage} == {
        chunk.chunk_id for chunk in result.chunks
    }


@requires_corpus
def test_the_skeleton_is_valid_policy_ir_that_the_gate_accepts() -> None:
    registry = SourceRegistry()
    result = ingest_pdf(registry, SMALL_PDF)
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        coverage=result.coverage,
    )
    assert PolicyIR.from_dict(json.loads(json.dumps(ir.to_dict()))) == ir
    report = run_gate(ir, {result.document.document_id: result.canonical_text})
    # No clauses yet, so there is nothing to refuse and nothing malformed.
    assert not report.fatal
    assert report.counts_by_code() == {}


@requires_corpus
def test_the_skeleton_validates_against_the_committed_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    registry = SourceRegistry()
    result = ingest_pdf(registry, SMALL_PDF)
    ir = PolicyIR(
        documents=registry.document_tuple(),
        chunks=registry.chunk_tuple(),
        coverage=result.coverage,
    )
    schema_path = (
        Path(__file__).resolve().parent.parent / "policy_ir" / "schema" / "policy-ir-v2.schema.json"
    )
    jsonschema.validate(ir.to_dict(), json.loads(schema_path.read_text(encoding="utf-8")))


# -- CLI --------------------------------------------------------------------


@requires_corpus
def test_the_cli_writes_a_reusable_skeleton(tmp_path: Path) -> None:
    from cli.compile_policy import EXIT_OK, main

    code = main(["--ingest", str(SMALL_PDF), "--out", str(tmp_path), "--quiet"])
    assert code == EXIT_OK
    skeleton = tmp_path / "policy-ir-v2.json"
    assert skeleton.exists()
    ir = PolicyIR.from_dict(json.loads(skeleton.read_text(encoding="utf-8")))
    assert ir.documents and ir.chunks and ir.coverage
    assert ir.metadata["artifact_role"] == "ingestion_skeleton"


@pytest.mark.skipif(not GAPPED_PDF.exists(), reason="gapped corpus PDF not present")
def test_the_cli_reports_the_extraction_gap(capsys: pytest.CaptureFixture[str]) -> None:
    from cli.compile_policy import main

    main(["--ingest", str(GAPPED_PDF), "--dry-run"])
    output = capsys.readouterr().out
    assert "no extractable text" in output
    assert "extraction_failed" in output


@requires_corpus
def test_ingesting_several_documents_keeps_them_distinct(tmp_path: Path) -> None:
    from cli.compile_policy import EXIT_OK, main

    assert (
        main(
            ["--ingest", str(SMALL_PDF), str(GAPPED_PDF), "--out", str(tmp_path), "--quiet"]
        )
        == EXIT_OK
    )
    ir = PolicyIR.from_dict(
        json.loads((tmp_path / "policy-ir-v2.json").read_text(encoding="utf-8"))
    )
    assert len({d.document_id for d in ir.documents}) == 2
    assert len({d.source_sha256 for d in ir.documents}) == 2
    by_document = {d.document_id for d in ir.documents}
    assert {c.document_id for c in ir.chunks} == by_document
