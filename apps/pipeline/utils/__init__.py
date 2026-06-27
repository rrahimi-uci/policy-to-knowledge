"""
Utilities Package

Contains non-agent utility modules:
- config: Configuration management
- llm_client: LLM abstraction layer
- prompt_manager: Centralized prompt loading
- rule_uniqueness: Deterministic rule_id / rule_name uniqueness enforcement
"""

from .config import Config, get_config
from .rule_uniqueness import enforce_rule_uniqueness

__all__ = [
    'Config',
    'get_config',
    'LLMClient',
    'create_llm_client',
    'PromptManager',
    'enforce_rule_uniqueness',
]


def __getattr__(name):
    """Lazily expose the LLM-dependent symbols.

    ``llm_client`` imports the OpenAI SDK. Resolve these names on first access
    so ``from utils import Config`` stays lightweight for config-only consumers
    (and the test suite) without importing the SDK.
    """
    if name in ('LLMClient', 'create_llm_client'):
        from . import llm_client
        return getattr(llm_client, name)
    if name == 'PromptManager':
        from .prompt_manager import PromptManager
        return PromptManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
