"""Stage 3: turning source text into Policy IR clause candidates.

Two paths share one contract:

* :mod:`extraction.deterministic` finds normative sentences and emits evidenced
  clauses with **no** typed expressions. It needs no model, runs over the whole
  corpus, and is the baseline any smarter extractor has to beat.
* :mod:`extraction.candidates` defines the contract a model-driven extractor must
  satisfy, and the strict parser that admits its output. A proposal may only choose
  from closed vocabularies and cite span IDs the application handed it; it can never
  name its own clause ID, invent a span, or assert a field it has also declared
  unstated.

Neither path may fabricate an expression. A prose sentence is not an AST, and
inventing one would put unsupported logic exactly where it is most dangerous.
"""

from .candidates import (  # noqa: F401
    CandidateClause,
    CandidateRejected,
    candidate_from_dict,
    candidates_to_clauses,
)
from .sentences import Sentence, split_sentences  # noqa: F401
