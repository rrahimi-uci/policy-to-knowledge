"""
LLM Client — thin wrapper over the official OpenAI Python SDK.

Provides a consistent chat-completion interface for the pipeline, with support
for both standard chat models (gpt-4o, gpt-4o-mini, …) and reasoning models
(o1/o3/o4, gpt-5.x), plus token/cost accounting emitted for the UI runner.
"""

import json
import re
import sys
import threading
from typing import Dict, Any, List, Optional

from openai import OpenAI


def _build_keepalive_http_client(timeout):
    """Build an httpx client with TCP keep-alive enabled.

    Without keep-alive, a connection that dies silently — the machine sleeps,
    a NAT/router drops the flow, the peer vanishes — leaves a blocking socket
    read parked in ``poll()`` indefinitely, well past the SDK's own timeout.
    With keep-alive the OS probes the idle connection and surfaces the dead
    peer (here within ~2 min: idle 60s, then 4 probes 15s apart), so the read
    fails fast and the SDK can retry or error instead of hanging forever.

    Returns ``None`` (so the SDK uses its default client) if httpx or the
    needed socket options aren't available — keeping this strictly best-effort.
    """
    try:
        import socket
        import httpx
    except Exception:
        return None

    opts = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    # macOS uses TCP_KEEPALIVE for the idle time; Linux uses TCP_KEEPIDLE.
    # Whichever exists is applied; absent constants are simply skipped.
    for const, value in (
        ("TCP_KEEPALIVE", 60),
        ("TCP_KEEPIDLE", 60),
        ("TCP_KEEPINTVL", 15),
        ("TCP_KEEPCNT", 4),
    ):
        num = getattr(socket, const, None)
        if num is not None:
            opts.append((socket.IPPROTO_TCP, num, value))

    try:
        connect = min(30, timeout) if timeout else 30
        return httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect),
            transport=httpx.HTTPTransport(retries=0, socket_options=opts),
        )
    except Exception:
        # Older httpx without socket_options support, etc. — fall back cleanly.
        return None


# Approximate OpenAI pricing in USD per 1M tokens (input, output). Used only to
# emit a best-effort cost estimate for the UI; unknown models report cost 0 but
# still report token usage. Update as pricing changes.
_PRICING_PER_1M = {
    "gpt-4o":       (2.50, 10.00),
    "gpt-4o-mini":  (0.15, 0.60),
    "gpt-4.1":      (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "o1":           (15.00, 60.00),
    "o1-mini":      (1.10, 4.40),
    "o3":           (2.00, 8.00),
    "o3-mini":      (1.10, 4.40),
    "o4-mini":      (1.10, 4.40),
}


def _get_config_value(getter_name: str, fallback):
    """Safely get a config value, returning fallback if config is not available."""
    try:
        from utils.config import get_config
        config = get_config()
        return getattr(config, getter_name)()
    except Exception:
        return fallback


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Best-effort USD cost estimate; 0.0 when the model's pricing is unknown."""
    key = (model or "").lower()
    rates = _PRICING_PER_1M.get(key)
    if not rates:
        # Try a prefix match (e.g. "gpt-4o-2024-08-06" -> "gpt-4o"). Match the
        # LONGEST prefix first so "gpt-4o-mini-..." resolves to "gpt-4o-mini",
        # not the pricier "gpt-4o".
        for name, r in sorted(_PRICING_PER_1M.items(), key=lambda kv: -len(kv[0])):
            if key.startswith(name):
                rates = r
                break
    if not rates:
        return 0.0
    in_rate, out_rate = rates
    return (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000


class LLMClient:
    """Unified chat-completion client backed by the OpenAI SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = None,
        timeout: int = None,
        max_retries: int = None,
    ):
        """
        Initialize the client.

        Args:
            api_key: OpenAI API key (defaults to config / OPENAI_API_KEY env var).
            model: Model identifier (e.g. 'gpt-4o', 'o3-mini', 'gpt-5.2').
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts (handled by the SDK).
        """
        self.model = model or _get_config_value('get_default_model', 'gpt-4o')
        self.timeout = timeout if timeout is not None else _get_config_value('get_timeout', 300)
        self.max_retries = max_retries if max_retries is not None else _get_config_value('get_max_retries', 3)

        # Hard watchdog margin (seconds) added on top of the SDK's own worst-case
        # (timeout × attempts). The watchdog only ever fires when the socket-level
        # timeout fails to — e.g. a connection killed mid-flight by a machine sleep.
        self.watchdog_margin = 60

        self._api_key = api_key
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Lazily build the OpenAI client on first use.

        Deferring construction means simply instantiating an LLMClient (e.g. to
        read its configured model) does not require an API key to be present.
        """
        if self._client is None:
            api_key = self._api_key or _get_config_value('get_openai_api_key', None)
            # The SDK falls back to OPENAI_API_KEY in the env when api_key is None;
            # pass it explicitly when we have it (without mutating the environment).
            client_kwargs: Dict[str, Any] = dict(
                api_key=api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
            http_client = _build_keepalive_http_client(self.timeout)
            if http_client is not None:
                client_kwargs["http_client"] = http_client
            self._client = OpenAI(**client_kwargs)
        return self._client

    def _create_with_watchdog(self, params: Dict[str, Any]) -> Any:
        """Run the SDK call under a hard wall-clock deadline.

        The OpenAI SDK's per-request timeout normally bounds a call, but a
        connection that dies silently can leave the underlying blocking socket
        read parked indefinitely past that timeout (observed: a call hung for
        hours after the machine slept). This backstop runs the request on a
        daemon thread and refuses to wait past ``timeout × attempts + margin``,
        so control always returns in finite time. A stranded thread (still
        blocked on the dead socket) is a daemon and never blocks process exit;
        TCP keep-alive tears its socket down shortly after.
        """
        client = self._get_client()
        box: Dict[str, Any] = {}

        def _call():
            try:
                box["resp"] = client.chat.completions.create(**params)
            except BaseException as e:  # propagate any failure to the caller
                box["err"] = e

        worker = threading.Thread(target=_call, name="llm-call", daemon=True)
        worker.start()
        deadline = self.timeout * (self.max_retries + 1) + self.watchdog_margin
        worker.join(deadline)

        if worker.is_alive():
            raise TimeoutError(
                f"LLM call exceeded the hard watchdog deadline ({deadline:.0f}s) — "
                f"the connection is likely stalled or dead; aborting so the pipeline "
                f"fails fast instead of hanging indefinitely."
            )
        if "err" in box:
            raise box["err"]
        return box["resp"]

    @staticmethod
    def is_reasoning_model(model: str) -> bool:
        """Detect reasoning models that need max_completion_tokens instead of max_tokens.

        Covers current and future OpenAI reasoning series (o1, o3, o4, …)
        as well as gpt-5.x models.
        """
        model = model or ""
        return bool(
            re.match(r'^o\d', model, re.IGNORECASE)
            or 'gpt-5' in model.lower()
        )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Any:
        """
        Create a chat completion.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Sampling temperature (ignored for reasoning models).
            max_tokens: Maximum tokens to generate.
            response_format: e.g. {"type": "json_object"} for JSON mode.
            **kwargs: Additional OpenAI parameters (e.g. reasoning_effort).

        Returns:
            The OpenAI ChatCompletion response object.
        """
        is_reasoning = self.is_reasoning_model(self.model)

        params: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        # Reasoning models reject `temperature` but accept `reasoning_effort`.
        if not is_reasoning:
            params["temperature"] = temperature
            kwargs.pop('reasoning_effort', None)
        elif 'reasoning_effort' in kwargs:
            params["reasoning_effort"] = kwargs.pop('reasoning_effort')

        # ── Token budget strategy ──
        # Reasoning models need generous headroom for internal reasoning; give
        # them 4× the requested budget (min 32768) so they don't truncate, while
        # still capping runaway generations. Non-reasoning models honour the
        # caller's max_tokens directly.
        if is_reasoning:
            params["max_completion_tokens"] = max(max_tokens * 4, 32768) if max_tokens else 32768
            kwargs.pop('max_completion_tokens', None)
            kwargs.pop('max_tokens', None)
        elif max_tokens:
            params["max_tokens"] = max_tokens

        if response_format:
            params["response_format"] = response_format

        params.update(kwargs)

        try:
            response = self._create_with_watchdog(params)
        except Exception as e:
            raise Exception(f"LLM completion failed: {str(e)}")

        # ── Safety check: warn on unexpected empty or truncated output ──
        content = (response.choices[0].message.content or "").strip()
        finish = getattr(response.choices[0], 'finish_reason', None)
        if not content:
            print(
                f"  ⚠️  Empty response from model (finish_reason={finish}).",
                file=sys.stderr, flush=True,
            )
        elif finish == 'length':
            print(
                f"  ⚠️  Response truncated (finish_reason=length, "
                f"{len(content)} chars). Output may contain incomplete JSON.",
                file=sys.stderr, flush=True,
            )

        # ── Cost & cache tracking (emitted for the UI run aggregator) ──
        usage = getattr(response, 'usage', None)
        if usage:
            cached = getattr(
                getattr(usage, 'prompt_tokens_details', None),
                'cached_tokens', 0,
            ) or 0
            if cached:
                print(
                    f"  💾 Prompt cache hit: {cached} tokens cached "
                    f"(of {usage.prompt_tokens} prompt tokens)",
                    file=sys.stderr, flush=True,
                )
            cost = _estimate_cost(self.model, usage.prompt_tokens, usage.completion_tokens)
            cost_entry = {
                "model": self.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "cached_tokens": cached,
                "cost": round(cost, 6),
            }
            # Structured line — pipeline_runner parses lines starting with [LLM_COST]
            print(f"[LLM_COST]{json.dumps(cost_entry)}", flush=True)

        return response

    def get_text_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """Return just the text content from a chat completion."""
        response = self.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("Empty response from model (content is None)")
        return content


def create_llm_client(
    api_key: Optional[str] = None,
    model: str = None,
    timeout: int = None,
    max_retries: int = None,
) -> LLMClient:
    """Factory for an OpenAI-backed LLMClient."""
    return LLMClient(
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
    )
