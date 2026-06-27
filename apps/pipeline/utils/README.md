# Utils Directory

This directory contains **utility modules and helper functions** that support the knowledge extraction pipeline. These provide core infrastructure for configuration management, LLM communication, prompt loading, and data processing.

## 📦 Utility Modules

| Module | Lines | Purpose | Used By |
|--------|-------|---------|---------|
| config.py | ~150 | Configuration management | All agents, main.py |
| llm_client.py | ~200 | LLM API abstraction | All agents |
| prompt_manager.py | ~100 | Domain-aware prompt loading/formatting | All agents |
| rule_uniqueness.py | ~80 | Rule ID/name uniqueness enforcement | Agents 3, 5 |
| text_to_html_converter.py | ~250 | HTML report generation | Agent 6, 10 |

**Total**: ~780 lines of infrastructure code

---

## 🔧 Module Details

### 1. **config.py** - Configuration Management

**Purpose**: Centralized configuration loading from environment variables and config.json

**Key Features**:
- Environment variable parsing (API keys, model selection)
- JSON config file loading and validation
- Default values for optional settings
- Configuration validation with helpful error messages

**Configuration Structure**:
```python
{
    "llm_provider": "openai",
    "primary_model": "gpt-5.2",
    "fallback_model": "gpt-4o",
    "document_organizer": {
        "chunk_size": 2000,
        "max_workers": 4
    },
    "entity_extractor": {
        "temperature": 0.7,
        "max_iterations": 3
    },
    "rules_extractor": {
        "rules_per_batch": 10,  # OpenAI
        "max_workers": 5,
        "temperature": 0.7
    },
    "rules_validator": {
        "enabled": true,
        "temperature": 0.7
    },
    "rules_with_entities_merger": {
        "temperature": 0.7
    },
    "knowledge_graph_optimizer": {
        "rules_per_batch": 50,
        "max_workers": 5,
        "temperature": 0.7
    },
    "visualization_and_report": {
        "temperature": 0.7
    }
}
```

**Usage Example**:
```python
from utils.config import load_config

# Load configuration
config = load_config()

# Access settings
provider = config["llm_provider"]
model = config["primary_model"]
chunk_size = config["document_organizer"]["chunk_size"]
```

**Environment Variables**:
```bash
# Required
export OPENAI_API_KEY="sk-proj-..."

# Optional (overrides config.json)
export LLM_PROVIDER="openai"
export PRIMARY_MODEL="gpt-5.2"
```

**Recent Enhancements** (Dec 2025):
- ✅ OpenAI-only LLM client
- ✅ Agent-specific configuration sections
- ✅ Validation step configuration (enabled/disabled)

---

### 2. **llm_client.py** - LLM API Abstraction

**Purpose**: OpenAI chat-completion client

**Key Features**:
- **Provider abstraction**: OpenAI chat completions
- **Automatic retries**: Exponential backoff for rate limits and transient errors
- **Error handling**: Graceful degradation and informative error messages
- **Token usage tracking**: Monitor API costs
- **Streaming support**: For real-time response generation (not currently used)

**Supported Providers**:
```python
SUPPORTED_PROVIDERS = {
    "openai": ["gpt-5.2", "gpt-4o", "gpt-4", "gpt-3.5-turbo"],
    "azure": ["gpt-4-turbo-azure"],
    "together": ["mixtral-8x7b-instruct"],
}
```

**Usage Example**:
```python
from utils.llm_client import LLMClient

# Initialize client
llm = LLMClient(
    provider="openai",
    model="gpt-5.2",
    temperature=0.7,
    max_tokens=16000
)

# Chat completion
response = llm.chat_completion(
    messages=[
        {"role": "system", "content": "You are a compliance expert."},
        {"role": "user", "content": prompt}
    ]
)

# Extract response
content = response.choices[0].message.content
tokens_used = response.usage.total_tokens
```

**Retry Logic**:
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((RateLimitError, APIError))
)
def _make_request(self, messages):
    return client.chat.completions.create(...)
```

**Recent Enhancements** (Dec 2025):
- ✅ OpenAI SDK integration
- ✅ Multi-provider fallback support
- ✅ Improved error messages with retry guidance

---

### 3. **prompt_manager.py** - Prompt Loading & Formatting

**Purpose**: Load prompts from domain-specific and shared directories with fallback

**Key Features**:
- **Domain-first precedence**: Loads from `domain-prompts/{domain}/` first, falls back to `prompts/`
- Parameter substitution with validation
- Template caching for performance
- Missing parameter detection
- 4 domain prompt sets (mortgage, aml, commercial_lending, healthcare)

**Usage Example**:
```python
from utils.prompt_manager import PromptManager

# Initialize (auto-resolves domain from Config)
pm = PromptManager()

# Or specify domain explicitly
pm = PromptManager(domain_prompts_dir="domain-prompts/aml")

# Load and format prompt — checks domain-prompts/ first, falls back to prompts/
prompt = pm.get_prompt(
    "business_rules_extraction",
    entity_context=entity_definitions,
    rules_per_batch=10,
    batch_num=1,
    sample_content=document_chunks
)
```

**Prompt Resolution Order**:
```
1. domain-prompts/{active_domain}/{prompt}.txt  (domain-specific)
2. prompts/{prompt}.txt                          (shared fallback)
```

**Prompt File Structure**:
```
prompts/                          # Shared baseline (11 templates)
├── business_rules_extraction.txt
├── dependency_analysis.txt
├── document_structure_analysis.txt
├── entity_extraction.txt
├── entity_refinement.txt
├── entity_resolution.txt
├── rule_deduplication.txt
├── rule_resolution.txt
├── rule_matcher.txt
├── rule_matcher_batch.txt
└── validation_report.txt

domain-prompts/                   # Domain overrides (same 11 templates each)
├── mortgage/
├── aml/
├── commercial_lending/
└── healthcare/
```

**Parameter Substitution**:
```python
# Template (in .txt file)
"""
Extract {rules_per_batch} rules from batch {batch_num}.

Entity Context:
{entity_context}

Document Content:
{sample_content}
"""

# Code
prompt = pm.get_prompt(
    "business_rules_extraction",
    rules_per_batch=10,
    batch_num=1,
    entity_context=json.dumps(entities),
    sample_content=chunks[0]
)
```

**Recent Enhancements** (Dec 2025):
- ✅ Support for nested parameter substitution
- ✅ Automatic prompt file discovery

---

### 4. **rule_uniqueness.py** - Rule ID/Name Deduplication

**Purpose**: Deterministic post-processing to guarantee unique rule IDs and names

**Key Features**:
- Resolves collisions from parallel LLM batches
- Appends `_v2`, `_v3` etc. to duplicate rule_ids
- Appends `(Variant 2)` etc. to duplicate rule_names
- Patches dependency references after renames

**Usage Example**:
```python
from utils.rule_uniqueness import enforce_rule_uniqueness

rules, summary = enforce_rule_uniqueness(rules_list)
print(summary)  # {"id_fixes": 3, "name_fixes": 1}
```

---

### 5. **text_to_html_converter.py** - HTML Report Generation

**Purpose**: Generate styled HTML reports from knowledge graph data

**Key Features**:
- Converts KG JSON to interactive HTML reports
- Styled tables and visual formatting
- Rule and entity summaries with dependency graphs
- Used by Agent 6 (Visualization) and Agent 10 (Set Visualization)

**Usage Example**:
```python
from utils.text_to_html_converter import convert_to_html

html = convert_to_html(kg_data, title="Compliance Report")
with open("report.html", "w") as f:
    f.write(html)
```

---

## 📊 Performance Characteristics

| Module | Initialization Time | Typical Call Time | Memory Usage |
|--------|---------------------|-------------------|--------------|
| config.py | ~5ms | ~1ms | ~50KB |
| llm_client.py | ~50ms | 2-30s (LLM latency) | ~100KB |
| prompt_manager.py | ~10ms | ~5ms | ~200KB (cached) |
| rule_uniqueness.py | ~1ms | ~10ms (250 rules) | ~1MB |
| text_to_html_converter.py | ~5ms | 100-500ms | ~5MB |

---

## 📚 Related Documentation

- [Main README](../README.md) - Project overview
- [Agents README](../agents/README.md) - How agents use utilities
- [Prompts README](../prompts/README.md) - Prompt engineering details
- [SETUP.md](../docs/SETUP.md) - Configuration and security setup

---

## 🔄 Recent Changes

| Date | Module | Change | Reason |
|------|--------|--------|--------|
| Feb 2026 | rule_uniqueness.py | New module | Deterministic rule ID dedup |
| Feb 2026 | prompt_manager.py | Domain-first precedence | Multi-domain prompt support |
| Dec 21, 2025 | llm_client.py | OpenAI SDK integration | Chat completions |
| Dec 15, 2025 | config.py | Validation step config | Agent 3.5 toggle |
| Dec 10, 2025 | prompt_manager.py | Nested substitution | Complex prompt parameters |

---

**Last Updated**: February 2026
**Status**: ✅ Production-ready
**Dependencies**: openai, json
