"""
Prompt Manager - Centralized prompt loading utility

Loads prompts from domain-prompts/{domain}/ with fallback to prompts/ for shared prompts.

Domain precedence:
  1. domain-prompts/{active_domain}/{prompt}.txt  (domain-specific)
  2. prompts/{prompt}.txt                          (shared / domain-agnostic fallback)
"""

from pathlib import Path
from typing import Dict, Optional


_PROJECT_ROOT = Path(__file__).parent.parent


class PromptManager:
    """Manages loading and formatting of prompts from domain-specific and shared directories."""

    def __init__(
        self,
        domain_prompts_dir: Optional[str] = None,
        fallback_dir: Optional[str] = None,
    ):
        """
        Initialize prompt manager.

        Args:
            domain_prompts_dir: Path to the active domain's prompts directory
                (e.g., 'domain-prompts/mortgage'). If None, resolved from Config.
            fallback_dir: Path to the shared/generic prompts directory used when
                a prompt is not found in the domain directory. Defaults to 'prompts/'.
        """
        if domain_prompts_dir is None:
            try:
                from utils.config import Config
                config = Config()
                domain_prompts_dir = _PROJECT_ROOT / config.get_domain_prompts_dir()
            except Exception:
                # Graceful degradation if Config is unavailable
                domain_prompts_dir = _PROJECT_ROOT / "domain-prompts" / "mortgage"

        self.prompts_dir = Path(domain_prompts_dir)

        if fallback_dir is None:
            self.fallback_dir = _PROJECT_ROOT / "prompts"
        else:
            self.fallback_dir = Path(fallback_dir)

        self._cache: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Core loading
    # ------------------------------------------------------------------

    def load_prompt(self, prompt_name: str) -> str:
        """
        Load a prompt by name.

        Resolution order:
          1. domain_prompts_dir/{prompt_name}.txt
          2. fallback_dir/{prompt_name}.txt

        Args:
            prompt_name: Prompt file stem (without .txt extension).

        Returns:
            Prompt template as a string.

        Raises:
            FileNotFoundError: If the prompt is found in neither location.
        """
        if prompt_name in self._cache:
            return self._cache[prompt_name]

        # Try domain-specific first
        prompt_file = self.prompts_dir / f"{prompt_name}.txt"
        if not prompt_file.exists():
            # Fall back to shared prompts directory
            prompt_file = self.fallback_dir / f"{prompt_name}.txt"

        if not prompt_file.exists():
            raise FileNotFoundError(
                f"Prompt '{prompt_name}' not found in '{self.prompts_dir}' "
                f"or fallback '{self.fallback_dir}'"
            )

        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()

        self._cache[prompt_name] = prompt
        return prompt

    def format_prompt(self, prompt_name: str, **kwargs) -> str:
        """
        Load and format a prompt with keyword substitutions.

        Args:
            prompt_name: Prompt file stem.
            **kwargs: Variables to substitute in the template.

        Returns:
            Formatted prompt string.
        """
        return self.load_prompt(prompt_name).format(**kwargs)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_prompt_info(self) -> Dict[str, str]:
        """
        Return a summary of available prompts (name → first line).

        Merges prompts from the fallback directory and the domain directory,
        with domain-specific prompts taking precedence.
        """
        info: Dict[str, str] = {}

        # Load shared prompts first
        if self.fallback_dir.exists():
            for prompt_file in sorted(self.fallback_dir.glob("*.txt")):
                with open(prompt_file, "r", encoding="utf-8") as f:
                    info[prompt_file.stem] = f.readline().strip()

        # Domain prompts override shared ones
        if self.prompts_dir.exists():
            for prompt_file in sorted(self.prompts_dir.glob("*.txt")):
                with open(prompt_file, "r", encoding="utf-8") as f:
                    info[prompt_file.stem] = f.readline().strip()

        return info

    @property
    def active_domain_dir(self) -> Path:
        """Return the active domain prompts directory."""
        return self.prompts_dir


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_prompt_manager: Optional[PromptManager] = None
_prompt_manager_domain: Optional[str] = None


def get_prompt_manager() -> PromptManager:
    """
    Return the singleton PromptManager, re-creating it if the active domain has changed.
    """
    global _prompt_manager, _prompt_manager_domain

    try:
        from utils.config import Config
        current_domain = Config().get_domain()
    except Exception:
        current_domain = "mortgage"

    if _prompt_manager is None or _prompt_manager_domain != current_domain:
        _prompt_manager = PromptManager()
        _prompt_manager_domain = current_domain

    return _prompt_manager


if __name__ == "__main__":
    pm = get_prompt_manager()
    print(f"Active domain directory: {pm.active_domain_dir}")
    print("Available prompts:")
    for name, desc in pm.get_prompt_info().items():
        print(f"  - {name}: {desc}")
