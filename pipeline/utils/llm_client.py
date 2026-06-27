"""
LLM Client Abstraction Layer using LiteLLM

This module provides a unified interface for LLM completions using LiteLLM,
which supports multiple providers (OpenAI, Anthropic, Azure, etc.) through
a consistent API.
"""

import copy
import json
import os
import re
import sys
from typing import Dict, Any, List, Optional
import litellm
from litellm import completion, completion_cost

# Lazy config access to avoid circular imports
def _get_config_value(getter_name: str, fallback):
    """Safely get a config value, returning fallback if config is not available."""
    try:
        from utils.config import get_config
        config = get_config()
        return getattr(config, getter_name)()
    except Exception:
        return fallback


class LLMClient:
    """
    Unified LLM client using LiteLLM for multi-provider support.
    
    This client abstracts away provider-specific details and provides
    a consistent interface for chat completions across different LLM providers.
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        model: str = None,
        timeout: int = None,
        max_retries: int = None
    ):
        """
        Initialize LLM client.
        
        Args:
            api_key: API key for OpenAI (defaults to OPENAI_API_KEY env var)
            anthropic_api_key: API key for Anthropic (defaults to ANTHROPIC_API_KEY env var)
            model: Model identifier (e.g., 'gpt-4o', 'o1', 'claude-sonnet-4-20250514')
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.model = model or _get_config_value('get_default_model', 'gpt-4o')
        self.timeout = timeout if timeout is not None else _get_config_value('get_timeout', 300)
        self.max_retries = max_retries if max_retries is not None else _get_config_value('get_max_retries', 3)
        
        # Set API keys in environment for LiteLLM
        if api_key:
            os.environ['OPENAI_API_KEY'] = api_key
        if anthropic_api_key:
            os.environ['ANTHROPIC_API_KEY'] = anthropic_api_key
        
        # Configure LiteLLM settings
        litellm.drop_params = True  # Drop unsupported params instead of failing
        litellm.set_verbose = False  # Disable verbose logging by default
    
    @staticmethod
    def is_reasoning_model(model: str) -> bool:
        """Detect reasoning models that need max_completion_tokens instead of max_tokens.

        Covers current and future OpenAI reasoning series (o1, o3, o4, …)
        as well as gpt-5.x models.
        """
        return bool(
            re.match(r'^o\d', model, re.IGNORECASE)
            or 'gpt-5' in model.lower()
        )

    def _is_anthropic_model(self) -> bool:
        """Check if the configured model is an Anthropic/Claude model."""
        m = self.model.lower()
        return 'claude' in m or 'anthropic' in m

    @staticmethod
    def _add_cache_control(messages: List[Dict]) -> List[Dict]:
        """Add Anthropic cache_control breakpoints to large static message content.

        Marks the last message whose content exceeds ~1 024 characters with
        ``cache_control: {"type": "ephemeral"}``.  Anthropic caches the entire
        prefix up to (and including) the marked block, so later calls with
        the same prefix receive a cache hit and pay only for the new tokens.
        """
        messages = copy.deepcopy(messages)
        # Walk in reverse so we mark only the *last* large block
        for msg in reversed(messages):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 1024:
                msg["content"] = [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                break
            # Already a list of content blocks — mark the last large block
            if isinstance(content, list):
                for block in reversed(content):
                    if block.get("type") == "text" and len(block.get("text", "")) > 1024:
                        block["cache_control"] = {"type": "ephemeral"}
                        break  # inner: found a large block in this message
                else:
                    continue   # no large block in this message; keep scanning
                break          # outer: a large block was marked, stop scanning
        return messages

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Any:
        """
        Create a chat completion using LiteLLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0 to 2.0)
            max_tokens: Maximum tokens to generate
            response_format: Response format specification (e.g., {"type": "json_object"})
            **kwargs: Additional provider-specific parameters
        
        Returns:
            LiteLLM completion response object
        
        Raises:
            Exception: If the completion fails after all retries
        """
        is_reasoning = self.is_reasoning_model(self.model)

        # Anthropic prompt caching: inject cache_control breakpoints so the
        # provider caches the static prompt prefix across batched calls.
        if self._is_anthropic_model():
            messages = self._add_cache_control(messages)

        params = {
            "model": self.model,
            "messages": messages,
            "timeout": self.timeout,
            "num_retries": self.max_retries,
        }
        
        # Reasoning models (o1, o3, o4, gpt-5) don't support temperature
        # parameter but DO support reasoning_effort.
        # litellm.drop_params = True will also silently drop unsupported
        # params, but we explicitly skip temperature for clarity.
        if not is_reasoning:
            params["temperature"] = temperature
        
        # Handle reasoning_effort for reasoning models
        if is_reasoning and 'reasoning_effort' in kwargs:
            params["reasoning_effort"] = kwargs.pop('reasoning_effort')
        
        # ── Token budget strategy ──
        # For reasoning models, set max_completion_tokens to 4× the requested
        # max_tokens (min 32768) to allow sufficient internal reasoning space
        # while preventing indefinite hangs.  Without a cap, reasoning models
        # can run for hours when given complex prompts.
        # For non-reasoning models we honour the caller's max_tokens directly.
        if is_reasoning:
            reasoning_budget = max(max_tokens * 4, 32768) if max_tokens else 32768
            params["max_completion_tokens"] = reasoning_budget
            # Remove caller-supplied max_completion_tokens from kwargs (set above)
            kwargs.pop('max_completion_tokens', None)
        elif max_tokens:
            params["max_tokens"] = max_tokens
        
        if response_format:
            params["response_format"] = response_format
        
        params.update(kwargs)
        
        try:
            response = completion(**params)

            # ── Safety check: warn on unexpected empty or truncated output ──
            content = (response.choices[0].message.content or "").strip()
            finish = getattr(response.choices[0], 'finish_reason', None)

            if not content:
                print(
                    f"  ⚠️  Empty response from model (finish_reason={finish}).",
                    file=sys.stderr, flush=True
                )
            elif finish == 'length':
                print(
                    f"  ⚠️  Response truncated (finish_reason=length, "
                    f"{len(content)} chars). Output may contain incomplete JSON.",
                    file=sys.stderr, flush=True
                )

            # ── Cost & cache tracking ──
            usage = getattr(response, 'usage', None)
            if usage:
                cached = getattr(
                    getattr(usage, 'prompt_tokens_details', None),
                    'cached_tokens', 0
                ) or getattr(usage, 'cache_read_input_tokens', 0)
                if cached:
                    print(
                        f"  💾 Prompt cache hit: {cached} tokens cached "
                        f"(of {usage.prompt_tokens} prompt tokens)",
                        file=sys.stderr, flush=True,
                    )

                # Emit structured cost line for the pipeline runner to aggregate
                try:
                    cost = completion_cost(completion_response=response)
                except Exception:
                    cost = 0.0
                if cost > 0:
                    cost_entry = {
                        "model": self.model,
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                        "cached_tokens": cached or 0,
                        "cost": round(cost, 6),
                    }
                    # Structured line — pipeline_runner parses lines starting with [LLM_COST]
                    print(f"[LLM_COST]{json.dumps(cost_entry)}", flush=True)

            return response
        except Exception as e:
            raise Exception(f"LLM completion failed: {str(e)}")
    
    def get_text_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Get text response from chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters
        
        Returns:
            Text content from the completion
        """
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
    anthropic_api_key: Optional[str] = None,
    model: str = None,
    timeout: int = None,
    max_retries: int = None
) -> LLMClient:
    """
    Factory function to create an LLM client.
    
    Args:
        api_key: API key for OpenAI
        anthropic_api_key: API key for Anthropic
        model: Model identifier (gpt-4o, o1, claude-sonnet-4-20250514, etc.)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts
    
    Returns:
        Configured LLMClient instance
    """
    return LLMClient(
        api_key=api_key,
        anthropic_api_key=anthropic_api_key,
        model=model,
        timeout=timeout,
        max_retries=max_retries
    )
