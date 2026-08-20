"""The staged pipeline runner.

Each stage reads the previous stage's artefacts from disk and writes its own, so the
expensive steps happen once and can be re-run independently. PDF extraction of a
1,200-page guide costs minutes; a model pass costs money. Neither should be repeated
because a later stage needs fixing.
"""

from .stages import RUNNERS, STAGES, StageResult, run_stage, stage_dir  # noqa: F401
from . import runner  # noqa: F401,E402  - registers every stage runner in RUNNERS
