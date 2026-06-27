"""
Global test configuration for pipeline tests.
"""

import os
import sys
from pathlib import Path

import pytest_asyncio

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Canonical committed config the suite ships with. Tests assert against this
# (the gitignored config.json is a developer's local working copy and may drift).
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.json"

# Pin config loading to the committed example so tests are deterministic in CI
# and on a fresh clone regardless of any local config.json.
os.environ.setdefault("P2K_CONFIG_PATH", str(EXAMPLE_CONFIG_PATH))

# Auto-mode for pytest-asyncio: no need for @pytest.mark.asyncio on every test
pytest_plugins = ["pytest_asyncio"]
