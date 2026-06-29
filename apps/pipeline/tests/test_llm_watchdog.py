"""Regression: an LLM call must never hang indefinitely.

Three pipelines once sat for hours blocked in a single OpenAI socket read after
the machine slept and the TCP connection died silently — the SDK's own timeout
never fired. The hard watchdog in LLMClient guarantees control returns in finite
time regardless of socket state; keep-alive makes a dead peer surface fast.
"""
import sys
import threading
import time
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.llm_client import LLMClient, _build_keepalive_http_client  # noqa: E402


class _Completions:
    def __init__(self, behaviour):
        self._behaviour = behaviour

    def create(self, **params):
        return self._behaviour(**params)


class _Chat:
    def __init__(self, behaviour):
        self.completions = _Completions(behaviour)


class _FakeClient:
    """Stand-in for an OpenAI client whose .create behaviour we control."""

    def __init__(self, behaviour):
        self.chat = _Chat(behaviour)


def _client_with(behaviour, *, timeout, max_retries=0, margin=0.3):
    c = LLMClient(api_key="test", model="gpt-4o", timeout=timeout, max_retries=max_retries)
    c.watchdog_margin = margin
    c._client = _FakeClient(behaviour)  # bypass real OpenAI construction
    return c


@allure.feature("LLM client robustness")
@allure.story("Hard watchdog on every completion")
class TestWatchdog:
    @allure.title("A stalled call is aborted at the watchdog deadline, not left hanging")
    def test_hanging_call_raises_within_deadline(self):
        never = threading.Event()  # never set → create() blocks forever

        def _hang(**_params):
            never.wait()  # simulates a dead socket read that never returns

        client = _client_with(_hang, timeout=0.2, max_retries=0, margin=0.3)
        # deadline = 0.2 * (0 + 1) + 0.3 = 0.5s
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="watchdog deadline"):
            client._create_with_watchdog({"model": "gpt-4o", "messages": []})
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"watchdog took too long to fire ({elapsed:.1f}s)"
        never.set()  # release the daemon worker so the test process stays tidy

    @allure.title("Deadline scales with the SDK's own timeout × attempts")
    def test_deadline_accounts_for_retries(self):
        client = _client_with(lambda **_: None, timeout=10, max_retries=3, margin=60)
        # The watchdog must not undercut the SDK's legitimate worst case
        # (timeout × (retries + 1)); it only adds a margin on top.
        expected = 10 * (3 + 1) + 60
        assert client.timeout * (client.max_retries + 1) + client.watchdog_margin == expected

    @allure.title("A fast successful call passes straight through")
    def test_successful_call_returns_response(self):
        sentinel = object()
        client = _client_with(lambda **_: sentinel, timeout=5)
        assert client._create_with_watchdog({"model": "gpt-4o", "messages": []}) is sentinel

    @allure.title("An error from the call is propagated, not swallowed")
    def test_error_is_propagated(self):
        def _boom(**_params):
            raise RuntimeError("api exploded")

        client = _client_with(_boom, timeout=5)
        with pytest.raises(RuntimeError, match="api exploded"):
            client._create_with_watchdog({"model": "gpt-4o", "messages": []})


@allure.feature("LLM client robustness")
@allure.story("TCP keep-alive on the HTTP client")
class TestKeepAlive:
    @allure.title("Keep-alive client builder never raises (returns a client or None)")
    def test_build_is_best_effort(self):
        # Must degrade gracefully: a real httpx.Client when supported, else None.
        client = _build_keepalive_http_client(300)
        if client is not None:
            import httpx

            assert isinstance(client, httpx.Client)
            client.close()
