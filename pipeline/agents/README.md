# Policy to Knowledge Agents

**Policy to Knowledge** (COmpliance Rules Transformation & EXtraction System) uses a 10-agent pipeline to transform compliance documents into structured knowledge graphs.

```
PDF → [1] → [2] → [3] → [3.5] → [4] → [5] → [6] → Knowledge Graph
                                                          ↓
                              KG₁ + KG₂ → [7] → [8] → [9] → [10] → Comparison Reports
```

---

## Agent 1: Document Organizer

**File**: `agent_1_document_organizer.py`  
**Class**: `DocumentChunkingAgent`  
**LLM**: ✅ GPT-5.2 / Claude (for TOC detection and structure analysis)

**Purpose**: Chunk and organize compliance documents using table of contents structure.

| Input | Output |
|-------|--------|
| Raw PDF files from `compliance-files/` | Text chunks in `pipeline-output/{provider}/agent-1-organized-documents/` |

**Features**:
- Extracts PDF table of contents (TOC) using PyPDF2 bookmarks
- **LLM-assisted TOC detection** when no bookmarks exist (analyzes first 5 pages)
- **LLM-based document structure analysis** for files without clear TOC
- Format-specific chunkers: PDF, Markdown, CSV, Excel, DOCX
- Preserves section references, page numbers, metadata
- Handles large PDFs (500+ pages)

**Chunker Tools**:
| Format | Chunker | Method |
|--------|---------|--------|
| PDF | PDFChunker | TOC-based or AI reasoning |
| Markdown | MarkdownChunker | Header-based (langchain) |
| CSV/TSV | CSVChunker | Row-based (pandas) |
| Excel | ExcelChunker | Sheet-aware (pandas) |
| DOCX | DocxChunker | Heading-based (python-docx) |
| TXT | TextChunker | AI structure analysis |

**Config** (`config.json`):
```json
{
  "document_organizer": {
    "chunk_size_target": 2000,
    "max_chunk_size": 3000,
    "min_chunk_size": 500,
    "supported_formats": [".pdf", ".txt", ".docx", ".md", ".csv", ".xlsx"]
  }
}
```

**Run**: `python knowledge_graph_generation.py --step 1`

---

## Agent 2: Entity Extractor

**File**: `agent_2_entity_extractor.py`  
**Class**: `ComplianceEntityRelationshipAgent`  
**LLM**: ✅ GPT-5.2 / Claude Sonnet 4

**Purpose**: Extract entity types and relationships using meta-agent prompt optimization.

| Input | Output |
|-------|--------|
| Organized chunks from Agent 1 | `agent-2-entities/entity_types_and_relationships.json` |

**Features**:
- Meta-agent prompt optimization (iterative refinement)
- Extracts entities with: name, definition, attributes, examples
- Identifies relationships with: cardinality, directionality, constraints
- Quality scoring (5 factors × 20 points = 100 max)

**Config** (`config.json`):
```json
{
  "entity_extractor": {
    "n_iterations": 3,
    "min_score_threshold": 70,
    "scoring_weights": {
      "completeness": 20,
      "relationship_quality": 20,
      "attribute_coverage": 20,
      "clarity": 20,
      "consistency": 20
    }
  }
}
```

**Run**: `python knowledge_graph_generation.py --step 2`

---

## Agent 3: Rules Extractor

**File**: `agent_3_rules_extractor.py`  
**Class**: `BusinessRulesExtractor`  
**LLM**: ✅ GPT-5.2 / Claude Sonnet 4  
**Workers**: 10 (parallel)

**Purpose**: Extract business rules with parallel batch processing.

| Input | Output |
|-------|--------|
| Organized chunks + entity definitions | `compliance_rules_with_entities.json`, `.csv` |

**Features**:
- Parallel batch processing with `ThreadPoolExecutor`
- 11 rule categories: Eligibility, Compliance, Documentation, Process, Calculation, Validation, Notification, Timing, Audit, Exception Handling, Reporting
- 5-factor confidence scoring (source specificity, metric clarity, condition completeness, example quality, consequence clarity)

**Config** (`config.json`):
```json
{
  "rules_extractor": {
    "target_rules": 240,
    "rules_per_batch": 10,
    "rules_per_batch_anthropic": 4,
    "rules_per_batch_openai": 10
  }
}
```

**Run**: `python knowledge_graph_generation.py --step 3`

---

## Agent 3.5: Rule Validator

**File**: `agent_3_5_rule_validator.py`  
**Class**: `RuleValidationAgent`  
**LLM**: ✅ GPT-5.2 / Claude Sonnet 4  
**Blocking**: ❌ No (pipeline continues on failure)

**Purpose**: Validate extracted rules for quality, consistency, and completeness.

| Input | Output |
|-------|--------|
| Rules from Agent 3 | `agent-3-5-validation/validation_summary.txt` |

**Features**:
- Rule quality assessment (completeness, specificity, consistency)
- Duplicate detection
- Cross-reference validation
- Confidence score analysis
- Generates recommendations

**Run**: `python knowledge_graph_generation.py --step 3` (runs automatically after Agent 3)

---

## Agent 4: Rules with Entities Merger

**File**: `agent_4_rules_with_entities_merger.py`  
**Class**: `RulesEntitiesMerger`  
**LLM**: ❌ Not required

**Purpose**: Merge business rules with entity definitions to create complete knowledge graph.

| Input | Output |
|-------|--------|
| Agent 3 rules + Agent 2 entities | `business_rules_complete.json`, `.csv` |

**Features**:
- Combines rules with entity context
- Maintains referential integrity
- Creates unified knowledge graph structure
- Exports to JSON and CSV (18 columns)

**Run**: `python knowledge_graph_generation.py --step 4`

---

## Agent 5: Knowledge Graph Optimizer

**File**: `agent_5_knowledge_graph_optimizer.py`  
**Class**: `KnowledgeGraphOptimizer`  
**LLM**: ✅ GPT-5.2 / Claude (configured reasoning model)  
**Parallel**: ✅ Sequential deduplication then dependency analysis

**Purpose**: Optimize knowledge graph through deduplication and dependency analysis.

| Input | Output |
|-------|--------|
| Complete KG from Agent 4 | `optimized_compliance_knowledge_graph.json`, `optimized-dependency_graph.json`, `optimized-optimization_report.txt` |

**Features**:
- Uses configured reasoning model (gpt-5.2 with medium reasoning by default)
- Conservative deduplication (preserves meaningful variations)
- Batched processing for large rule sets (50 rules/batch)
- 7 dependency types:

| Type | Description |
|------|-------------|
| `prerequisite` | Rule A must be satisfied before Rule B |
| `sequential` | Rules must be executed in order |
| `conditional` | Rule B applies only if Rule A is met |
| `complementary` | Rules work together |
| `contradictory` | Rules conflict |
| `override` | Rule B supersedes Rule A |
| `validation` | Rule B validates Rule A's outcome |

**Run**: `python knowledge_graph_generation.py --step 5`

---

## Agent 6: Visualization and Report Generator

**File**: `agent_6_visualization_and_report.py`  
**Class**: `KnowledgeGraphVisualizer`  
**LLM**: ❌ Not required

**Purpose**: Generate interactive HTML visualization and reports.

| Input | Output |
|-------|--------|
| Optimized KG from Agent 5 | `{source_name}_knowledge_graph.html`, `extraction_metadata.json` |

**Features**:
- Interactive network graph (vis.js)
- 9-column rules table with search/filter/sort
- Dependency evidence column (rationale, strength, impact)
- Color-coded visualization by rule type
- Self-contained HTML (no external dependencies)
- Statistics dashboard

**Run**: `python knowledge_graph_generation.py --step 6`

---

## Agent 7: Rule Behavior Clusterer

**File**: `agent_7_rule_type_clusterer.py`  
**Class**: `RuleBehaviorClusterer`  
**LLM**: ❌ Not required

**Purpose**: Group rules from two knowledge graphs by behavior (HOW dimension) for comparison.

| Input | Output |
|-------|--------|
| Two optimized KGs (G1, G2) | `_merged/{G1}_{G2}/agent-7-rule-clusters/rule_clusters.json` |

**8 Rule Behaviors**:

| Behavior | Description | Example |
|----------|-------------|---------|
| `formula` | Defines a calculation | DTI = Total Debt / Income |
| `classification` | Defines a category | Property Type: SFR, Condo |
| `threshold` | Numeric min/max limit | LTV ≤ 97% |
| `prohibition` | Forbids something | No prepayment penalties |
| `timing` | Deadline/time window | Appraisal valid 120 days |
| `sequence` | Specific order | Inspect → Appraise → Underwrite |
| `method` | How to verify/execute | Use DU for underwriting |
| `mandate` | Requires existence | Flood insurance required |

**10 Rule Domains**: borrower, income, property, loan, appraisal, underwriting, documentation, closing, servicing, compliance

**Run**: `python join_graphs.py --g1 FMNA --g2 Revolution-Overlay`

---

## Agent 8: Semantic Rule Matcher

**File**: `agent_8_semantic_rule_matcher.py`  
**Class**: `SemanticRuleMatcher`  
**LLM**: ✅ GPT-5.2 / Claude Sonnet 4  
**Workers**: 15 (default, configurable via `--workers`)  
**Batch Size**: 10 pairs/call (configurable via `--batch-size`)

**Purpose**: Compare rules within each behavior cluster using LLM semantic matching.

| Input | Output |
|-------|--------|
| Rule clusters from Agent 7 | `agent-8-rule-matches/match_results.json` |

**4 Match Classifications**:

| Classification | Description | Action |
|----------------|-------------|--------|
| `IDENTICAL` | Same rule, same thresholds | Merge (keep one) |
| `EQUIVALENT` | Same practical effect | Merge with note |
| `CONTRADICTORY` | Conflicting requirements | Flag for review |
| `UNRELATED` | No meaningful connection | Keep separate |

**Features**:
- BATCH parallel processing (10 pairs per LLM call = 10x speedup)
- ThreadPoolExecutor with configurable workers
- Confidence scores for each match
- Thread-safe progress tracking

**Run**: `python join_graphs.py --g1 FMNA --g2 Revolution --workers 15 --batch-size 10`

---

## Agent 9: Set Operations Calculator

**File**: `agent_9_set_operations.py`  
**Class**: `SetOperationsCalculator`  
**LLM**: ❌ Not required

**Purpose**: Compute 5 distinct set operations from match results.

| Input | Output |
|-------|--------|
| Match results from Agent 8 | 5 JSON files in `agent-9-set-operations/` |

**5 Set Operations**:

| Operation | Symbol | Description | Output File |
|-----------|--------|-------------|-------------|
| Intersection | G1 ∩ G2 | Rules in both graphs | `intersection.json` |
| Left Difference | G1 - G2 | Rules only in G1 | `g1_minus_g2.json` |
| Right Difference | G2 - G1 | Rules only in G2 | `g2_minus_g1.json` |
| Union | G1 ∪ G2 | All unique rules | `union.json` |
| Contradictions | G1 ⊕ G2 | Conflicting pairs | `contradictions.json` |

**Run**: `python join_graphs.py --g1 FMNA --g2 Revolution-Overlay`

---

## Agent 10: Set Operations Visualizer

**File**: `agent_10_set_visualization.py`  
**Class**: `SetOperationsVisualizer`  
**LLM**: ❌ Not required

**Purpose**: Create HTML visualizations for each set operation result.

| Input | Output |
|-------|--------|
| Set operation results from Agent 9 | 6 HTML files in `agent-10-visualizations/` |

**Generated Files**:

| File | Contents |
|------|----------|
| `index.html` | Summary dashboard with Venn diagram |
| `intersection.html` | G1 ∩ G2 rules |
| `g1_minus_g2.html` | G1 - G2 rules |
| `g2_minus_g1.html` | G2 - G1 rules |
| `union.html` | G1 ∪ G2 rules |
| `contradictions.html` | Conflicting rule pairs |

**Visual Encoding**:
- **ELLIPSE**: Matched rules (from both graphs)
- **RECTANGLE**: G1-only rules
- **CIRCLE**: G2-only rules

**Run**: `python join_graphs.py --g1 FMNA --g2 Revolution-Overlay`

---

## Quick Reference

### All Agents Summary

| # | Agent | File | LLM | Workers | Purpose |
|---|-------|------|-----|---------|---------|
| 1 | Document Organizer | `agent_1_document_organizer.py` | ✅ | - | Chunk PDFs/docs (LLM for TOC detection) |
| 2 | Entity Extractor | `agent_2_entity_extractor.py` | ✅ | - | Extract entities & relationships |
| 3 | Rules Extractor | `agent_3_rules_extractor.py` | ✅ | 10 | Extract business rules |
| 3.5 | Rule Validator | `agent_3_5_rule_validator.py` | ✅ | - | Validate rules (non-blocking) |
| 4 | Rules+Entities Merger | `agent_4_rules_with_entities_merger.py` | ❌ | - | Merge rules with entities |
| 5 | KG Optimizer | `agent_5_knowledge_graph_optimizer.py` | ✅ | - | Dedup + dependencies |
| 6 | Visualizer | `agent_6_visualization_and_report.py` | ❌ | - | Generate HTML reports |
| 7 | Behavior Clusterer | `agent_7_rule_type_clusterer.py` | ❌ | - | Cluster rules by type |
| 8 | Semantic Matcher | `agent_8_semantic_rule_matcher.py` | ✅ | 15 | LLM semantic matching |
| 9 | Set Operations | `agent_9_set_operations.py` | ❌ | - | Compute ∩, ∪, -, ⊕ |
| 10 | Set Visualizer | `agent_10_set_visualization.py` | ❌ | - | Generate comparison HTML |

**All LLM-using agents use the configured reasoning model (default: gpt-5.2 with medium reasoning)**

### Run Commands

```bash
# Phase 1: Single document extraction
python knowledge_graph_generation.py                              # Full pipeline (interactive)
python knowledge_graph_generation.py --provider openai            # Use OpenAI
python knowledge_graph_generation.py --provider anthropic         # Use Anthropic
python knowledge_graph_generation.py --step 3                     # Run specific step
python knowledge_graph_generation.py --batch                      # Process all subdirectories

# Phase 2: Knowledge graph comparison
python join_graphs.py --list             # List available graphs
python join_graphs.py --g1 FMNA --g2 Revolution-Overlay
python join_graphs.py --g1 FM --g2 FMNA --workers 20 --batch-size 15
```

### Configuration

**LLM Models** (`config.json`):
```json
{
  "openai": {
    "models": {
      "reasoning": "gpt-5.2",
      "reasoning_effort": "medium"
    }
  },
  "anthropic": {
    "models": {
      "reasoning": "anthropic/claude-sonnet-4-20250514",
      "reasoning_effort": "high"
    }
  }
}
```

**Workers & Batch Sizes**:

| Agent | Setting | Default | How to Change |
|-------|---------|---------|---------------|
| 3 | `max_workers` | 10 | Code |
| 3 | `rules_per_batch` | 10 (OpenAI), 4 (Anthropic) | `config.json` |
| 8 | `max_workers` | 15 | `--workers` CLI |
| 8 | `batch_size` | 10 | `--batch-size` CLI |

### Performance

| Agent | Time | Notes |
|-------|------|-------|
| 1 | ~30-60 sec | LLM only when no TOC bookmarks |
| 2 | ~5 min | 3 iterations |
| 3 | ~8-12 min | Parallel batching |
| 3.5 | ~2 min | Non-blocking |
| 4 | ~10 sec | No LLM |
| 5 | ~6-8 min | Uses configured model |
| 6 | ~15 sec | No LLM |
| 7 | ~5 sec | No LLM |
| 8 | ~8-15 min | 15 workers |
| 9 | ~2 sec | No LLM |
| 10 | ~10 sec | No LLM |

**Total**: Phase 1 ~25-30 min | Phase 2 ~10-15 min

---

## Related Documentation

- [Main README](../README.md) - Project overview
- [Architecture](../docs/ARCHITECTURE.md) - Technical architecture
- [Product Definition](../docs/PRODUCT_DEFINITION.md) - Features and use cases
- [Prompts README](../prompts/README.md) - Prompt engineering guide

---

**Last Updated**: February 2026 | **Version**: 1.1.0
