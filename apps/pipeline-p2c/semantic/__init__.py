"""Domain configuration and semantic-assembly contracts.

This package deliberately contains no provider SDK.  It defines the stable boundary
between an agent that may *propose* policy semantics and the deterministic compiler
that owns identifiers, evidence, validation, and projection.
"""

from .profiles import DomainProfile, ProfileError, generic_profile, load_profile
from .assembly import AssemblyError, assemble_proposal, proposal_schema
from .synthesis import SynthesisOpportunity, synthesis_report
from .governance import review_queue, semantic_metrics

__all__ = (
    "AssemblyError", "DomainProfile", "ProfileError", "assemble_proposal", "generic_profile",
    "load_profile", "proposal_schema",
    "SynthesisOpportunity", "synthesis_report",
    "review_queue", "semantic_metrics",
)
