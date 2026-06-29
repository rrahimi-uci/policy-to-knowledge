# Shared Utilities

Infrastructure modules shared across the extraction pipeline: configuration, the OpenAI client, prompt loading, rule-uniqueness enforcement, and HTML report generation. This build is **OpenAI-only**.

## Modules

| Module | Purpose |
|--------|---------|
| `config.py` | Singleton configuration loaded from `config.json` with environment-variable overrides and typed accessors. |
| `llm_client.py` | Thin wrapper over the OpenAI Python SDK for chat completions, including reasoning-model handling. |
| `prompt_manager.py` | Domain-aware prompt loading and formatting with fallback to the shared baseline templates. |
| `rule_uniqueness.py` | Deterministic post-processing that guarantees unique `rule_id` and `rule_name` values. |
| `text_to_html_converter.py` | Converts plain-text optimization reports into styled standalone HTML. |

`__init__.py` re-exports `Config`, `get_config`, `LLMClient`, `create_llm_client`, `PromptManager`, and `enforce_rule_uniqueness`. The LLM symbols are lazily imported so config-only consumers do not pull in the OpenAI SDK.

## `config.py`

Singleton `Config` that loads `config.json` (copy from `config.example.json`; the real file is gitignored). If `config.json` is absent it falls back to `config.example.json`, so a fresh clone, CI, and the test suite work without a manual copy. The config path can be overridden with the `P2K_CONFIG_PATH` environment variable. `${VAR}` placeholders in the JSON are substituted from the environment (and a project-root `.env` is loaded on import).

```python
from utils.config import get_config

config = get_config()

# Models (configurable in the Settings UI)
config.get_reasoning_model()    # "gpt-5.2"
config.get_optimizer_model()    # "gpt-5.2"
config.get_reasoning_effort()   # "medium"
config.get_openai_api_key()     # from config or OPENAI_API_KEY

# Active compliance domain and its prompt directory
config.get_domain()             # "mortgage"
config.get_domain_prompts_dir() # Path("domain-prompts/mortgage")

# Dot-notation access for anything else
config.get("openai.models.embeddings")  # "text-embedding-ada-002"
```

Relevant `config.json` sections:

```json
{
  "openai": {
    "api_key": "${OPENAI_API_KEY}",
    "models": {
      "reasoning": "gpt-5.2",
      "reasoning_effort": "medium",
      "optimizer": "gpt-5.2",
      "embeddings": "text-embedding-ada-002"
    },
    "rate_limiting": { "max_retries": 3, "timeout": 300 }
  },
  "domain": {
    "active": "mortgage",
    "prompts_base_dir": "domain-prompts",
    "available": ["mortgage", "aml", "healthcare", "commercial_lending"]
  }
}
```

`Config` also exposes per-agent accessors (document organizer, entity extractor, rules extractor, optimizer, semantic matcher) and resolves per-run output directories under `pipeline-output/`.

## `llm_client.py`

`LLMClient` wraps the official OpenAI SDK and exposes `chat_completion(...)` and a convenience `get_text_response(...)`. The OpenAI client is built lazily on first request, so an `LLMClient` can be instantiated (e.g. to read its model) without an API key present.

Reasoning models (the `o*` series and `gpt-5.x`) are detected automatically: `temperature` is dropped, `reasoning_effort` is honored, and the token budget is sent as `max_completion_tokens` with generous headroom. Standard chat models receive `temperature` and `max_tokens` directly. Each call emits a structured `[LLM_COST]` line (token usage, cached tokens, best-effort USD estimate) that the UI run aggregator parses.

```python
from utils.llm_client import create_llm_client

llm = create_llm_client(model="gpt-5.2")

text = llm.get_text_response(
    messages=[
        {"role": "system", "content": "You are a compliance expert."},
        {"role": "user", "content": prompt},
    ],
    reasoning_effort="medium",
)
```

## `prompt_manager.py`

Loads prompt templates for the active domain with fallback to the shared baseline. Use the `get_prompt_manager()` singleton, which resolves the active domain from `Config` and rebuilds itself when the domain changes.

```python
from utils.prompt_manager import get_prompt_manager

pm = get_prompt_manager()

template = pm.load_prompt("entity_extraction")          # raw template
prompt   = pm.format_prompt("entity_extraction", **kw)  # substituted
```

Resolution order:

```text
1. domain-prompts/<active_domain>/<name>.txt   (domain-specific)
2. prompts/<name>.txt                          (shared fallback)
```

Templates are cached after first load. `get_prompt_info()` returns a name to first-line summary for every available prompt. See the [Prompts README](../prompts/README.md) for the template catalog.

## `rule_uniqueness.py`

Deterministic pass that guarantees globally unique rule identifiers after parallel LLM batches, which can collide. `enforce_rule_uniqueness(rules)` mutates the list in place and returns it alongside a summary.

- Duplicate `rule_id`s are suffixed `_v2`, `_v3`, … (the original prefix is preserved). Only the later duplicate is renamed, so existing dependency references stay valid.
- Duplicate `rule_name`s are suffixed with `(Variant 2)`, `(Variant 3)`, ….

```python
from utils.rule_uniqueness import enforce_rule_uniqueness

rules, summary = enforce_rule_uniqueness(rules)
print(summary)  # {"id_fixes": 3, "name_fixes": 1}
```

## `text_to_html_converter.py`

Renders plain-text optimization reports as styled, standalone HTML without adding or removing content.

```python
from utils.text_to_html_converter import (
    convert_text_to_html,        # text -> HTML string
    convert_report_file,         # report file -> HTML file
    convert_all_optimization_reports,  # batch-convert a pipeline output dir
)

html = convert_text_to_html(report_text, title="Optimization Report")
```

## Related

- [Prompts README](../prompts/README.md) — prompt templates and domain overrides
- [Agents README](../agents/README.md) — how agents use these utilities
- [Main README](../README.md) — project overview
