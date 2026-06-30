"""Regression: the joins CLI must report the SAME output folder the agents write.

Agents 7-10 write their artifacts under ``pipeline-output/_merged/<subfolder>/``
(see agent_10 ``SetOperationsVisualizer``). cli/compare.py used to print and
build its summary path under ``_joined/`` instead, pointing users (and the
``file://.../index.html`` link) at a directory that is never created.
"""
import re
import sys
from pathlib import Path

import allure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

COMPARE_SRC = (PROJECT_ROOT / "cli" / "compare.py").read_text()
AGENT10_SRC = (PROJECT_ROOT / "agents" / "agent_10_set_visualization.py").read_text()


@allure.feature("Joins CLI")
@allure.story("Reported output path matches the agents")
class TestCompareOutputPath:
    @allure.title("agent_10 writes the visualizations under _merged/")
    def test_agent10_writes_under_merged(self):
        # Establishes the ground truth the CLI must agree with.
        assert '"_merged"' in AGENT10_SRC and "agent-10-visualizations" in AGENT10_SRC
        assert '"_joined"' not in AGENT10_SRC

    @allure.title("compare.py builds its summary output_dir under _merged/, not _joined/")
    def test_compare_summary_path_uses_merged(self):
        # The summary output_dir line must use _merged (matching agent_10).
        m = re.search(r'output_dir\s*=\s*Path\(__file__\).*?agent-10-visualizations"', COMPARE_SRC)
        assert m, "could not find the summary output_dir construction in compare.py"
        line = m.group(0)
        assert '"_merged"' in line, "summary output_dir must point under _merged/"
        assert '"_joined"' not in line, "stale _joined/ path must be gone"

    @allure.title("compare.py no longer prints a _joined/ output folder")
    def test_compare_banner_uses_merged(self):
        assert "_merged/{joins_subfolder}/" in COMPARE_SRC
        assert "_joined/{joins_subfolder}/" not in COMPARE_SRC
