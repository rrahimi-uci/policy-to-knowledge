"""Stage 0: immutable ingestion, hashing and canonical offsets."""

from .registry import SourceRegistry, normalize_text  # noqa: F401
from .sections import Heading, find_headings, section_at, segment_by_section  # noqa: F401
