"""Stage 3: turning source text into Policy IR clause candidates.

Two paths share one contract:

* :mod:`extraction.deterministic` finds normative sentences and emits evidenced
  clauses with **no** typed expressions. It needs no model, runs over the whole
  corpus, and is the baseline any smarter extractor has to beat.
* :mod:`extraction.offer`, :mod:`extraction.proposals` and :mod:`extraction.contract`
  are the seam for a model-driven extractor. It is handed numbered text units and a
  generated JSON Schema that enumerates exactly those indices, so a citation to unseen
  text cannot be produced at all; the application then builds every evidence span
  itself from offsets it already holds.
* :mod:`extraction.candidates` is the strict parser both paths share. Nothing may name
  its own clause ID, invent a span, or assert a field it has also declared absent.

Neither path may fabricate an expression. A prose sentence is not an AST, and
inventing one would put unsupported logic exactly where it is most dangerous.
"""

from .contract import proposal_schema, render_instructions  # noqa: F401
from .offer import (  # noqa: F401
    ExtractionRequest,
    TextUnit,
    build_request,
    build_requests,
)
from .proposals import (  # noqa: F401
    CandidateProposal,
    RoleCitation,
    admit_proposals,
    proposal_from_dict,
    resolve_proposal,
)
from .candidates import (  # noqa: F401
    CandidateClause,
    CandidateRejected,
    candidate_from_dict,
    candidates_to_clauses,
)
from .sentences import Sentence, split_sentences  # noqa: F401
