"""Unit tests for data_loader numeric/string coercion helpers."""
import sys
from pathlib import Path

import allure
import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))

from src.data_loader import _safe_int, _safe_float, _safe_str  # noqa: E402


@allure.feature("Explorer data loader")
@allure.story("Safe coercion helpers")
class TestSafeCoercion:
    @pytest.mark.parametrize("value,expected", [
        (3, 3), ("3", 3), ("3.9", 3), (3.9, 3), (None, 0), ("high", 0), ("", 0), ("N/A", 0),
    ])
    @allure.title("_safe_int({value!r}) == {expected}")
    def test_safe_int(self, value, expected):
        assert _safe_int(value) == expected

    @allure.title("_safe_int honors a custom default")
    def test_safe_int_default(self):
        assert _safe_int("nope", default=5) == 5

    @pytest.mark.parametrize("value,expected", [
        (0.92, 0.92), ("0.92", 0.92), (1, 1.0), (None, 0.0), ("bad", 0.0),
    ])
    @allure.title("_safe_float({value!r}) == {expected}")
    def test_safe_float(self, value, expected):
        assert _safe_float(value) == pytest.approx(expected)

    @allure.title("_safe_str serializes lists/dicts to JSON and None to ''")
    def test_safe_str(self):
        assert _safe_str(None) == ""
        assert _safe_str("x") == "x"
        assert _safe_str([1, 2]) == "[1, 2]"
        assert _safe_str({"a": 1}) == '{"a": 1}'
