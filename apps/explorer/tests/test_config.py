"""Unit tests for explorer configuration helpers."""
import sys
from pathlib import Path

import allure
import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from conf import config  # noqa: E402


@allure.feature("Explorer config")
@allure.story("Reasoning-effort support")
class TestSupportsReasoningEffort:
    @pytest.mark.parametrize("model,expected", [
        ("o1", True), ("o1-mini", True), ("o3-mini", True), ("o4-mini", True),
        ("gpt-4o", False), ("gpt-4o-mini", False),
    ])
    @allure.title("supports_reasoning_effort({model}) == {expected}")
    def test_support(self, model, expected):
        assert config.supports_reasoning_effort(model) is expected


@allure.feature("Explorer config")
@allure.story("Configuration constants")
class TestConfigConstants:
    @allure.title("Core server/threshold constants are present and sane")
    def test_constants_present(self):
        # URL prefix default and a couple of numeric thresholds should exist.
        assert isinstance(getattr(config, "URL_PREFIX"), str)
        assert isinstance(getattr(config, "QUERY_DEFAULT_LIMIT"), int)
        assert config.QUERY_DEFAULT_LIMIT > 0
