"""Regression: the embedded logo data URI must declare a MIME matching its bytes.

A previous version read logo.svg but always emitted `data:image/png;base64,...`,
so browsers couldn't render it (the "Policy to Knowledge" image showed broken).
"""
import base64
import sys
from pathlib import Path

import allure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _decode(uri: str):
    assert uri.startswith("data:"), f"not a data URI: {uri[:40]}"
    header, b64 = uri.split(",", 1)
    return header, base64.b64decode(b64)


def _assert_mime_matches_bytes(uri: str):
    header, raw = _decode(uri)
    if "image/png" in header:
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", "declared image/png but bytes are not a PNG"
    elif "image/svg+xml" in header:
        head = raw[:400].lower()
        assert b"<svg" in head or b"<?xml" in head, "declared svg but bytes are not SVG"
    else:
        raise AssertionError(f"unexpected logo MIME type: {header}")


@allure.feature("Pipeline visualization")
@allure.story("Logo embedding")
class TestLogoDataUri:
    @allure.title("agent_6 logo data URI MIME matches its bytes")
    def test_agent6_logo_mime(self):
        from agents.agent_6_visualization_and_report import _get_logo_base64
        uri = _get_logo_base64()
        assert uri, "expected a bundled logo (logo.png/logo.svg)"
        _assert_mime_matches_bytes(uri)

    @allure.title("agent_10 logo data URI MIME matches its bytes")
    def test_agent10_logo_mime(self):
        from agents.agent_10_set_visualization import SetOperationsVisualizer as V
        V._logo_cache = None  # bypass any cached value from earlier tests
        uri = V._get_logo_base64()
        assert uri, "expected a bundled logo (logo.png/logo.svg)"
        _assert_mime_matches_bytes(uri)

    @allure.title("agent_10 _logo_img_tag yields a real <img> (never an empty src)")
    def test_agent10_img_tag_non_empty(self):
        from agents.agent_10_set_visualization import SetOperationsVisualizer as V
        tag = V._logo_img_tag()
        assert tag.startswith("<img") and 'src="data:image/' in tag
        assert 'src=""' not in tag
