"""Domain configuration and semantic-assembly contracts.

This package deliberately contains no provider SDK.  It defines the stable boundary
between an agent that may *propose* policy semantics and the deterministic compiler
that owns identifiers, evidence, validation, and projection.
"""

from .profiles import DomainProfile, ProfileError, generic_profile, load_profile

__all__ = ("DomainProfile", "ProfileError", "generic_profile", "load_profile")
