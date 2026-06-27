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

    ``llm_client`` imports litellm (a heavy dependency). Importing it eagerly
    forced every config-only consumer (and the test suite) to install litellm.
    Resolve those names on first access instead so ``from utils import Config``
    stays lightweight.
    """
    if name in ('LLMClient', 'create_llm_client'):
        from . import llm_client
        return getattr(llm_client, name)
    if name == 'PromptManager':
        from .prompt_manager import PromptManager
        return PromptManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
