"""
Global test configuration for pipeline tests.
"""

import sys
from pathlib import Path

import pytest_asyncio

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Auto-mode for pytest-asyncio: no need for @pytest.mark.asyncio on every test
pytest_plugins = ["pytest_asyncio"]
