# Prompts Directory

This directory contains the **active, production prompts** used by all agents in the knowledge extraction pipeline. These are the actual prompts that execute during pipeline runs.

## 📄 Active Prompts (Production)

| Prompt | Lines | Agent | Last Updated |
|--------|-------|-------|--------------|
| business_rules_extraction.txt | 343 | Agent 3 | Dec 21, 2025 |
| dependency_analysis.txt | 401 | Agent 5 | Dec 21, 2025 |
| document_structure_analysis.txt | 94 | Agent 1 | Dec 21, 2025 |
| entity_extraction.txt | 245 | Agent 2 | Dec 21, 2025 |
| entity_refinement.txt | 266 | Agent 2 (meta) | Dec 21, 2025 |
| entity_resolution.txt | - | Agent 2 (resolution) | Feb 2026 |
| rule_deduplication.txt | 280 | Agent 5 | Dec 21, 2025 |
| rule_resolution.txt | - | Agent 4 | Feb 2026 |
| rule_matcher.txt | - | Agent 8 | Feb 2026 |
| rule_matcher_batch.txt | - | Agent 8 (batch) | Feb 2026 |
| validation_report.txt | 401 | Agent 3.5 | Dec 21, 2025 |

**Total**: 11 prompt templates across 4 compliance domains

## 🎯 Purpose

These prompts are the **shared baseline** templates. Each compliance domain has its own domain-specific override set under `domain-prompts/`:

| Directory | Domain | Description |
|-----------|--------|-------------|
| `prompts/` | Shared (fallback) | Domain-agnostic baseline templates |
| `domain-prompts/mortgage/` | Mortgage Lending | Agency/investor guidelines and lender overlays — mortgage-specific terminology |
| `domain-prompts/aml/` | Anti-Money Laundering | AML/BSA compliance — SAR, CTR, CDD, KYC entities |
| `domain-prompts/commercial_lending/` | Commercial Lending | Commercial loan origination — collateral, covenants |
| `domain-prompts/healthcare/` | Healthcare | HIPAA, patient entities, provider relationships |

The `PromptManager` uses **domain-first precedence**: it checks `domain-prompts/{active_domain}/` first, then falls back to `prompts/`.

### Domain-Specific Prompt Loading

```python
from utils.prompt_manager import PromptManager

# PromptManager resolves domain from Config automatically
pm = PromptManager()
# Or specify explicitly:
pm = PromptManager(domain_prompts_dir="domain-prompts/aml")

# Resolution order:
# 1. domain-prompts/{active_domain}/{prompt}.txt (domain-specific)
# 2. prompts/{prompt}.txt (shared fallback)
template = pm.load_prompt("business_rules_extraction")
```

Each domain directory contains the full set of 11 prompt templates. Domain-specific versions inject specialized terminology, entity vocabularies, rule taxonomies, and worked examples while keeping the same pipeline integration structure.

## 🔄 How Prompts Are Used

### Agent Execution Flow

```python
# 1. Load prompt from file
prompt_manager = PromptManager()
template = prompt_manager.get_prompt("business_rules_extraction")

# 2. Substitute parameters
prompt = template.format(
    entity_context=entity_definitions,
    rules_per_batch=10,
    batch_num=1,
    sample_content=document_chunks
)

# 3. Send to LLM
response = llm_client.chat_completion(
    messages=[{"role": "user", "content": prompt}],
    temperature=0.7
)

# 4. Parse and validate response
rules = json.loads(response.choices[0].message.content)
```

## 📋 Prompt Descriptions

### 1. **business_rules_extraction.txt** (343 lines)
**Agent**: 3 (Rules Extractor)  
**Purpose**: Extract detailed business rules from document chunks

**Key Features**:
- **Batch size adaptation**: 10 rules/batch for OpenAI, 2-3 for Anthropic
- **7 rule types**: eligibility, compliance, constraint, calculation, validation, process, documentation
- **Complete metadata**: conditions, consequences, exceptions, source references, examples
- **Confidence scoring**: 5-factor algorithm guidance
- **Quality standards**: Specificity, traceability, quantification

**Recent Enhancements** (Dec 21, 2025):
- ✅ Updated batch size strategies for different providers
- ✅ Enhanced rule type definitions with mortgage-specific examples
- ✅ Added "quality over quantity" principles
- ✅ Comprehensive JSON schema with all required fields

---

### 2. **dependency_analysis.txt** (401 lines)
**Agent**: 5 (Knowledge Graph Optimizer)  
**Purpose**: Identify dependencies between business rules

**Key Features**:
- **7 dependency types**: prerequisite, sequential, conditional, complementary, contradictory, override, validation
- **Strength ratings**: 1-5 scale (5 = critical dependency)
- **Evidence requirements**: Detailed rationale for each dependency
- **Impact analysis**: Consequence if dependency fails
- **Batched processing**: 50 rules/batch for efficiency

**Dependency Output Schema**:
```json
{
  "depends_on_rule": "BR_ENTITY_042",
  "dependency_type": "prerequisite",
  "rationale": "Credit report must be obtained before score validation",
  "strength": 5,
  "impact_if_fails": "Cannot validate borrower credit score"
}
```

**Recent Enhancements** (Dec 21, 2025):
- ✅ Enhanced rationale requirements with specific examples
- ✅ Added impact_if_fails field for risk assessment
- ✅ Improved strength rating criteria

---

### 3. **document_structure_analysis.txt** (94 lines)
**Agent**: 1 (Document Organizer)  
**Purpose**: Analyze document structure when TOC is unavailable

**Key Features**:
- Section identification patterns
- Hierarchical heading detection
- Chunking strategies (target: 2000 chars)
- Metadata extraction

**Use Case**: Fallback when PDF has no table of contents

---

### 4. **entity_extraction.txt** (245 lines)
**Agent**: 2 (Entity Extractor)  
**Purpose**: Extract domain entities and relationships

**Key Features**:
- Entity definition guidelines (what qualifies as an entity)
- Attribute identification rules
- Relationship directionality and cardinality
- Quality criteria (completeness, clarity, consistency)

**Example Output**:
- 44 entity types (BORROWER, LOAN, PROPERTY, etc.)
- 40 relationships (BORROWER_APPLIES_FOR_LOAN, etc.)

---

### 5. **entity_refinement.txt** (266 lines)
**Agent**: 2 (Entity Extractor - Meta-Agent)  
**Purpose**: Iteratively refine entity extraction quality

**Key Features**:
- **5-dimensional quality scoring**: completeness, relationship quality, attribute coverage, clarity, consistency
- **Prompt optimization**: Analyzes weak areas and generates improved prompts
- **Iterative process**: 3 iterations of extraction → analysis → refinement

**Quality Threshold**: Min 70/100 score to proceed

---

### 6. **rule_deduplication.txt** (280 lines)
**Agent**: 5 (Knowledge Graph Optimizer)  
**Purpose**: Identify and merge duplicate rules

**Key Features**:
- **Conservative approach**: Preserves meaningful variations
- **Deduplication criteria**: Exact vs semantic duplicates
- **Merge decisions**: Keep both, merge, or remove
- **Context preservation**: Maintains entity-specific variations

**Example**:
- Input: 248 rules (Agent 3)
- Output: 244 rules (4 exact duplicates removed)

---

### 7. **validation_report.txt** (401 lines)
**Agent**: 3.5 (Rule Validator)  
**Purpose**: Validate extracted rules for quality

**Key Features**:
- **6 validation dimensions**: completeness, specificity, consistency, confidence scores, cross-references, duplicates
- **Actionable recommendations**: Specific fixes for quality issues
- **Non-blocking**: Pipeline continues even if validation fails

**Output**: validation_summary.txt with findings and recommendations

---

## 🔧 Prompt Management

### Loading Prompts
```python
from utils.prompt_manager import PromptManager

pm = PromptManager()
prompt = pm.get_prompt("business_rules_extraction")
```

### Customizing for New Domain

1. **Create a new domain-prompts directory**:
   ```bash
   mkdir -p domain-prompts/insurance
   ```

2. **Copy the shared baseline prompts**:
   ```bash
   cp prompts/*.txt domain-prompts/insurance/
   ```

3. **Customize domain-specific content** (entity vocabularies, rule taxonomies, worked examples):
   ```txt
   # Replace domain terminology in each prompt:
   "mortgage lending" → "insurance underwriting"
   # Update entity types, rule categories, etc.
   ```

4. **Run the pipeline with the new domain**:
   ```bash
   python3 knowledge_graph_generation.py --provider openai
   ```
   The `PromptManager` will automatically load prompts from the new domain directory.

## 📊 Prompt Engineering Metrics

| Metric | Value |
|--------|-------|
| Total prompt templates | 11 |
| Domain-specific sets | 4 (mortgage, aml, commercial_lending, healthcare) |
| Total prompt instances | 55 (11 templates × 5 directories) |
| Largest prompt | dependency_analysis.txt (401 lines) |
| Parameters per prompt | 3-5 |
| LLM providers | 2 (OpenAI GPT-5.2, Anthropic Claude Sonnet 4) |

## 🎯 Key Prompt Engineering Principles

### 1. **Batch Size Adaptation**
Prompts automatically adjust extraction strategy based on LLM provider:
- **OpenAI GPT-5.2**: 10 rules/batch (comprehensive)
- **Anthropic Claude Sonnet 4**: 2-3 rules/batch (focused on critical rules)

### 2. **Quality Over Quantity**
All prompts emphasize complete, detailed extraction over rule count:
- Better to extract 10 perfect rules than 20 incomplete ones
- Each rule must have all required fields
- No placeholders or "TBD" values

### 3. **Domain Context**
Prompts include:
- Pipeline role explanation (upstream/downstream agents)
- Entity context from previous steps
- Domain terminology and examples
- Regulatory framework references

### 4. **Structured Output**
All prompts specify exact JSON schema:
```json
{
  "field_name": "type and description",
  "required": true,
  "example": "sample value"
}
```

### 5. **Traceability**
Every extraction requires source references:
- Document section (e.g., "B3-2-01")
- Page numbers
- Clause identifiers

## 🐛 Troubleshooting Prompts

### Issue: Low-quality extractions
**Solution**: Check prompt parameters are being substituted correctly
```python
print(prompt)  # Verify no {placeholders} remain
```

### Issue: JSON parsing errors
**Solution**: Prompts explicitly instruct "Return ONLY valid JSON, no markdown"

### Issue: Provider-specific failures
**Solution**: Batch size may be too large for provider
```json
// config.json
"rules_extractor": {
  "rules_per_batch": 3  // Reduce for Anthropic
}
```

## 📚 Related Documentation


- [Agents README](../agents/README.md) - How agents use prompts
- [Main README](../README.md) - Project overview

## 🔄 Update History

| Date | Changes | Reason |
|------|---------|--------|
| Dec 21, 2025 | Synced all 7 prompts from templates | Standardize production prompts |
| Dec 20, 2025 | Enhanced dependency_analysis rationale | Add dependency evidence to HTML |
| Dec 15, 2025 | Added validation_report prompt | New Agent 3.5 validator |
| Dec 10, 2025 | Batch size adaptation in rules extraction | Multi-provider optimization |

---

**Last Updated**: February 2026
**Domains**: Mortgage, AML, Commercial Lending, Healthcare
**Status**: ✅ Production-ready, 4 domain prompt sets deployed
