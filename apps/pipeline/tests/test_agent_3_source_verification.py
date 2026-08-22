"""Tests for Agent 3's source_reference verification and exact-span bridging.

Context: `_verify_source_references` accepts an LLM-quoted `source_text` as
"verified" whenever it scores >= 0.5 on a fuzzy SequenceMatcher ratio against
the text at its claimed word position — a threshold deliberately loose because
LLMs often quote verbatim but get word offsets slightly wrong (see that
method's own docstring). The gap this leaves: a quote that silently elides
real intervening content (a worked example, a footnote) can still score well
above 0.5 even though it is not a genuine substring of the document. Agent
5.7's independent grounding verifier requires an exact substring, so such
rules pass Agent 3's check and then fail certification later.

`bridge_exact_span` closes that gap: when the fuzzy ratio isn't already near
1.0, it looks for where the genuinely-matching words actually sit in the
chunk and returns the span from the first matching run to the last — which,
by construction, is always an exact substring, even if it ends up longer than
the original quote (it will include whatever real content the LLM dropped
from the middle).
"""

from difflib import SequenceMatcher
from types import SimpleNamespace

from agents.agent_3_rules_extractor import BusinessRulesExtractor, bridge_exact_span


# ─────────────────────────────────────────────────────────────────────────
# bridge_exact_span — isolated unit tests
# ─────────────────────────────────────────────────────────────────────────

REAL_CHUNK = (
    "Designated Threshold Amount and Minimum Transfer Amount\n"
    "The designated threshold amount represents a level of unsecured exposure an "
    "in the money party will accept before making a margin call on the "
    "out of the money party. Fannie Maes designated threshold amount and "
    "a lenders designated threshold amount shall each be $3,000,000, unless "
    "otherwise agreed to by the parties in writing and/or subject to the occurrence "
    "of a triggering event as discussed below.\nExample\nIf there is a positive "
    "price differential and a lender is in the money by $3,100,000, the lender may "
    "make a\nmargin call to Fannie Mae for $100,000. ($3,100,000 minus Fannie Maes "
    "designated threshold amount of\n$3,000,000).\nA minimum transfer is a specified "
    "amount of money that must be exceeded before a margin call can be made. "
    "Fannie Maes minimum transfer amount and a lenders minimum transfer amount "
    "shall each be $50,000"
)


def test_bridges_over_an_elided_example_paragraph():
    """The exact reproduction of the real BATCH1-FM-TRADING-THRESHOLD-MINTRANSFER-001
    failure: the LLM's quote is real on both ends but skips the worked "Example"
    paragraph the source document places between them."""
    words = REAL_CHUNK.split()
    llm_quote = (
        "Fannie Maes designated threshold amount and a lenders designated threshold "
        "amount shall each be $3,000,000, unless otherwise agreed to by the parties in "
        "writing and/or subject to the occurrence of a triggering event as discussed below.\n"
        "A minimum transfer is a specified amount of money that must be exceeded before a "
        "margin call can be made. Fannie Maes minimum transfer amount and a lenders "
        "minimum transfer amount shall each be $50,000"
    )
    start_hint = len(REAL_CHUNK.split("Fannie Maes designated")[0].split())
    end_hint = start_hint + len(llm_quote.split())

    result = bridge_exact_span(llm_quote, words, start_hint, end_hint)

    assert result is not None
    start, end, exact_text = result
    assert exact_text == " ".join(words[start:end])
    assert exact_text in " ".join(words), "bridged text must be an exact substring of the chunk"
    assert "Example" in exact_text, "the bridge must span across the elided paragraph, not around it"


def test_already_exact_quote_still_bridges_to_itself():
    words = "The quick brown fox jumps over the lazy dog".split()
    quote = "quick brown fox jumps over the lazy"

    result = bridge_exact_span(quote, words, 1, 8)

    assert result is not None
    start, end, exact_text = result
    assert exact_text == "quick brown fox jumps over the lazy"


def test_unrelated_quote_returns_none():
    """A quote with no real relationship to the chunk must not be bridged into
    something that only superficially overlaps — that would fabricate evidence
    rather than recover it."""
    words = "The quick brown fox jumps over the lazy dog".split()
    quote = "Completely different sentence about mortgage servicing obligations"

    assert bridge_exact_span(quote, words, 0, 5) is None


def test_too_little_coverage_returns_none():
    """A tiny incidental overlap (e.g. one common word) is not enough evidence
    to justify rewriting the rule's citation."""
    words = ("Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet "
              "Kilo Lima Mike November Oscar the Papa Quebec").split()
    quote = "the requirement applies only when a triggering event has occurred"

    assert bridge_exact_span(quote, words, 0, len(words)) is None


def test_short_quote_below_minimum_block_words_returns_none():
    words = "some short chunk of text here".split()
    assert bridge_exact_span("hi there", words, 0, 5) is None


def test_empty_inputs_return_none():
    assert bridge_exact_span("", ["a", "b"], 0, 1) is None
    assert bridge_exact_span("quote text here now", [], 0, 1) is None


def test_search_margin_bounds_the_search():
    """A genuine match far outside the search margin should not be found —
    this keeps the repair scoped to the LLM's claimed neighbourhood rather
    than searching the whole document for a coincidental match elsewhere."""
    filler = ["filler"] * 500
    target = "a very specific and unusual phrase indeed".split()
    words = filler + target + filler
    quote = "a very specific and unusual phrase indeed"

    # The claimed position is far from where the real match sits.
    result = bridge_exact_span(quote, words, 0, 5, search_margin=10)
    assert result is None

    # With a wide-enough margin, the same call succeeds.
    result = bridge_exact_span(quote, words, 0, 5, search_margin=600)
    assert result is not None


# ─────────────────────────────────────────────────────────────────────────
# _verify_source_references — integration through the real verification path
# ─────────────────────────────────────────────────────────────────────────

def _extractor() -> BusinessRulesExtractor:
    """A BusinessRulesExtractor with no API key, no entity file, no client —
    _verify_source_references only reads self.all_entity_types /
    self.all_relationships, so those are all it needs."""
    extractor = object.__new__(BusinessRulesExtractor)
    extractor.all_entity_types = {}
    extractor.all_relationships = {}
    return extractor


def _rule_with_reference(rule_id, source_text, start, end, chunk_path="doc.txt"):
    return {
        "rule_id": rule_id,
        "description": "irrelevant for this test",
        "source_reference": {
            "chunk_path": chunk_path,
            "section_id": "S1",
            "start_word_position": start,
            "end_word_position": end,
            "source_text": source_text,
        },
    }


def test_fuzzy_match_with_elided_content_is_bridged_to_an_exact_quote(tmp_path):
    (tmp_path / "doc.txt").write_text(REAL_CHUNK, encoding="utf-8")
    llm_quote = (
        "Fannie Maes designated threshold amount and a lenders designated threshold "
        "amount shall each be $3,000,000, unless otherwise agreed to by the parties in "
        "writing and/or subject to the occurrence of a triggering event as discussed below.\n"
        "A minimum transfer is a specified amount of money that must be exceeded before a "
        "margin call can be made. Fannie Maes minimum transfer amount and a lenders "
        "minimum transfer amount shall each be $50,000"
    )
    words = REAL_CHUNK.split()
    start = len(REAL_CHUNK.split("Fannie Maes designated")[0].split())
    end = start + len(llm_quote.split())
    # Sanity: this reproduces the real bug's precondition — a fuzzy ratio well
    # above 0.5 (the old acceptance threshold) but well below an exact match.
    actual_slice = " ".join(words[start:end])
    precondition_ratio = SequenceMatcher(None, llm_quote.lower(), actual_slice.lower()).ratio()
    assert 0.5 < precondition_ratio < 0.995

    rule = _rule_with_reference("R1", llm_quote, start, end)
    extractor = _extractor()
    extractor.all_entity_types = {"E": {"business_rules": [rule]}}

    extractor._verify_source_references(str(tmp_path))

    ref = rule["source_reference"]
    assert rule["reference_verified"] is True
    assert rule["reference_verification_note"] == "ok_bridged_exact_span"
    assert ref["text_match_score"] == 1.0
    assert ref["source_text_bridged"] is True
    # The chunk on disk is whitespace-normalised into `words` (as the rest of
    # this verifier already does), so "is a real substring" means a substring
    # of the space-joined words, not of the original newline-preserving text.
    assert ref["source_text"] in " ".join(words)
    assert "Example" in ref["source_text"], "bridged quote must include the real elided content"


def test_already_exact_quote_is_verified_without_bridging(tmp_path):
    (tmp_path / "doc.txt").write_text(REAL_CHUNK, encoding="utf-8")
    words = REAL_CHUNK.split()
    exact = "shall each be $3,000,000, unless otherwise agreed to by the parties"
    start = " ".join(words).index(exact.split()[0])  # placeholder, recomputed below
    # Find the true word-index span for this exact substring.
    joined = " ".join(words)
    char_idx = joined.index(exact)
    start = len(joined[:char_idx].split())
    end = start + len(exact.split())

    rule = _rule_with_reference("R2", exact, start, end)
    extractor = _extractor()
    extractor.all_relationships = {"REL": {"business_rules": [rule]}}

    extractor._verify_source_references(str(tmp_path))

    ref = rule["source_reference"]
    assert rule["reference_verified"] is True
    assert rule["reference_verification_note"] == "ok"
    assert "source_text_bridged" not in ref, "an already-exact quote must not be rewritten"
    assert ref["source_text"] == exact, "an already-exact quote's text must be left untouched"


def test_unbridgeable_fuzzy_match_falls_back_to_existing_lenient_acceptance(tmp_path):
    """When bridging can't find a reliable exact span, behaviour must not
    regress below what the pipeline already did: still accept a >=0.5 fuzzy
    match rather than newly rejecting rules that previously passed.

    This needs a quote with decent CHARACTER-level similarity (what the
    existing >=0.5 threshold measures) but no genuine contiguous WORD-level
    run (what bridging requires) — e.g. the same vocabulary, scrambled.
    """
    chunk = "The seller must deliver the loan file within ten business days of closing"
    (tmp_path / "doc.txt").write_text(chunk, encoding="utf-8")
    quote = "days closing seller ten must file the loan of within business deliver"
    start, end = 0, len(quote.split())
    actual_slice = " ".join(chunk.split()[start:end])
    precondition_ratio = SequenceMatcher(None, quote.lower(), actual_slice.lower()).ratio()
    assert 0.5 <= precondition_ratio < 0.995, "fixture must land in the fuzzy-acceptance band"
    assert bridge_exact_span(quote, chunk.split(), start, end) is None, (
        "fixture must be genuinely unbridgeable for this test to exercise the fallback"
    )

    rule = _rule_with_reference("R3", quote, start, end)
    extractor = _extractor()
    extractor.all_entity_types = {"E": {"business_rules": [rule]}}

    extractor._verify_source_references(str(tmp_path))

    assert rule["reference_verified"] is True
    assert rule["reference_verification_note"] == "ok"
    assert "source_text_bridged" not in rule["source_reference"]
    assert rule["source_reference"]["source_text"] == quote, "unbridged text must be left as-is"


def test_recovery_path_also_bridges_elided_content(tmp_path):
    """Step 3 (positions wrong, but source_text found elsewhere in the chunk)
    must get the same exact-span tightening as step 1.

    The claimed position (0,3) has to be far enough from the real content
    that step 1's own bridging attempt — which searches only a margin around
    the claimed position — genuinely can't reach it, forcing a fall-through
    to step 3's unbounded anywhere-in-chunk search.
    """
    filler = " ".join(f"filler{i}" for i in range(400))
    (tmp_path / "doc.txt").write_text(f"{filler} {REAL_CHUNK}", encoding="utf-8")
    llm_quote = (
        "Fannie Maes designated threshold amount and a lenders designated threshold "
        "amount shall each be $3,000,000, unless otherwise agreed to by the parties in "
        "writing and/or subject to the occurrence of a triggering event as discussed below.\n"
        "A minimum transfer is a specified amount of money that must be exceeded before a "
        "margin call can be made. Fannie Maes minimum transfer amount and a lenders "
        "minimum transfer amount shall each be $50,000"
    )
    rule = _rule_with_reference("R4", llm_quote, 0, 3)
    extractor = _extractor()
    extractor.all_entity_types = {"E": {"business_rules": [rule]}}

    extractor._verify_source_references(str(tmp_path))

    ref = rule["source_reference"]
    full_words = f"{filler} {REAL_CHUNK}".split()
    assert rule["reference_verified"] is True
    assert rule["reference_verification_note"] == "ok_recovered_and_bridged_exact_span"
    assert ref["source_text"] in " ".join(full_words)
    assert "Example" in ref["source_text"]


def test_bridging_never_produces_text_outside_the_chunk(tmp_path):
    """Defence in depth: whatever bridge_exact_span returns, the verifier must
    never persist a source_text that isn't a real substring of the chunk it
    claims to cite."""
    (tmp_path / "doc.txt").write_text(REAL_CHUNK, encoding="utf-8")
    words = REAL_CHUNK.split()
    llm_quote = (
        "Fannie Maes designated threshold amount and a lenders designated threshold "
        "amount shall each be $3,000,000, unless otherwise agreed to by the parties in "
        "writing and/or subject to the occurrence of a triggering event as discussed below.\n"
        "A minimum transfer is a specified amount of money that must be exceeded before a "
        "margin call can be made. Fannie Maes minimum transfer amount and a lenders "
        "minimum transfer amount shall each be $50,000"
    )
    start = len(REAL_CHUNK.split("Fannie Maes designated")[0].split())
    end = start + len(llm_quote.split())
    rule = _rule_with_reference("R5", llm_quote, start, end)
    extractor = _extractor()
    extractor.all_entity_types = {"E": {"business_rules": [rule]}}

    extractor._verify_source_references(str(tmp_path))

    ref = rule["source_reference"]
    assert ref["source_text"] in " ".join(words)
    assert " ".join(words[ref["start_word_position"]:ref["end_word_position"]]) == ref["source_text"]
