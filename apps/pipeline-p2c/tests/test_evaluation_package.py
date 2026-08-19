"""Package import behaviour for executable evaluation modules."""

from __future__ import annotations

import subprocess
import sys


def test_benchmark_module_entrypoint_does_not_preimport_itself() -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-m", "evaluation.benchmarks", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "open_benchmark_eval" in result.stdout
