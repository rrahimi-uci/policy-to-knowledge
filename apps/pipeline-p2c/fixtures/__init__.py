"""Conformance fixtures: small, hand-written Policy IR cases with known outcomes.

These are engineering fixtures, not a benchmark. They test software semantics —
does the gate refuse an unsupported threshold, does the compiler decline to invent
a timer — and they are author-written on purpose. They are never a new
human-labelled dataset and must not be reported as one.
"""

from .library import Fixture, all_fixtures, fixture, fixture_names  # noqa: F401
