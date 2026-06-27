# Policy to Knowledge - Compliance Knowledge Graph Builder

> **Policy to Knowledge** — **CO**mpliance **R**ules **T**ransformation & **EX**traction System

An automated 10-agent AI pipeline that transforms compliance documents into structured knowledge graphs with interactive visualizations, business rules extraction, dependency analysis, and multi-graph merge capabilities.

## 🎯 Overview

Policy to Knowledge uses a multi-agent AI system powered by OpenAI GPT-5.2 or Anthropic Claude Sonnet 4 to extract and organize knowledge from complex compliance documents.

📖 **[Product Definition](docs/PRODUCT_DEFINITION.md)** | 🏗️ **[Architecture](docs/ARCHITECTURE.md)** | 🐳 **[Docker Guide](docs/DOCKER.md)**

### 🤖 10-Agent Pipeline

**Extraction Pipeline (Agents 1-6):**

1. **Document Organizer** — Splits documents (PDF, DOCX, Markdown, CSV, Excel) into hierarchical chunks using table of contents
2. **Entity Extractor** — Extracts domain entities and relationships with meta-agent prompt optimization
3. **Rules Extractor** — Parallel batch extraction of business rules with 10-category taxonomy
4. **Rule Validator** (3.5) — Non-blocking quality validation with actionable recommendations
5. **Rules+Entities Merger** — Enriches rules with entity context into a complete knowledge graph
6. **Knowledge Graph Optimizer** — Deduplicates rules and analyzes dependencies (7 dependency types)
7. **Visualization Generator** — Creates interactive HTML with vis.js network graphs and searchable tables

**Merge Pipeline (Agents 7-10):**

7. **Rule Type Clusterer** — Groups rules by behavior (formula, threshold, sequence, method, mandate)
8. **Semantic Rule Matcher** — LLM-powered rule comparison with batch parallelism
9. **Set Operations** — Computes intersection, union, differences, and contradictions between graphs
10. **Set Visualization** — Generates comparison HTML reports with Venn diagrams

### ✨ Key Features

- 🐳 **Docker-First Deployment** — Containerized pipeline with volume-mounted output
- 📊 **Interactive Visualizations** — Network graphs with color-coded dependencies and searchable rule tables
- 🔄 **Multi-Provider Support** — OpenAI and Anthropic via unified LiteLLM interface
- ⚡ **Parallel Processing** — Batch processing in Agents 3, 5, and 8 for 3-10x speedup
- 🔀 **Knowledge Graph Merging** — Compare and merge graphs from different compliance documents
- 📈 **Execution Tracking** — Start/end times and formatted duration reports

---

## 📁 Project Structure

```
pipeline/
│
├── 🐳 Docker
│   ├── Dockerfile                              # Python 3.11 container
│   └── docker-compose.yml                      # Service orchestration
│
├── 🤖 Agents
│   ├── agent_1_document_organizer.py           # TOC-based document chunking
│   ├── agent_2_entity_extractor.py             # Entity extraction (meta-agent)
│   ├── agent_3_rules_extractor.py              # Rules extraction (parallel batch)
│   ├── agent_3_5_rule_validator.py             # Non-blocking quality validation
│   ├── agent_4_rules_with_entities_merger.py   # Knowledge graph assembly
│   ├── agent_5_knowledge_graph_optimizer.py    # Deduplication + dependency analysis
│   ├── agent_6_visualization_and_report.py     # Interactive HTML generation
│   ├── agent_7_rule_type_clusterer.py          # Rule behavior clustering
│   ├── agent_8_semantic_rule_matcher.py        # LLM-powered rule comparison
│   ├── agent_9_set_operations.py               # Graph set operations
│   └── agent_10_set_visualization.py           # Merge report visualization
│
├── 📝 Prompts
│   ├── document_structure_analysis.txt         # TOC extraction
│   ├── entity_extraction.txt                   # Entity/relationship discovery
│   ├── entity_refinement.txt                   # Iterative quality improvement
│   ├── entity_resolution.txt                   # Entity conflict resolution
│   ├── business_rules_extraction.txt           # 10-category rule taxonomy
│   ├── rule_deduplication.txt                  # Conservative deduplication
│   ├── rule_resolution.txt                     # Rule conflict resolution
│   ├── dependency_analysis.txt                 # 7-type dependency mapping
│   ├── validation_report.txt                   # Source verification
│   ├── rule_matcher.txt                        # Semantic similarity matching
│   └── rule_matcher_batch.txt                  # Batch rule comparison
│
├── 🛠️ Utilities
│   ├── config.py                               # Configuration management
│   ├── llm_client.py                           # LiteLLM unified interface
│   ├── prompt_manager.py                       # Domain-aware prompt loading/formatting
│   ├── rule_uniqueness.py                      # Rule ID/name deduplication
│   └── text_to_html_converter.py               # HTML report generator
│
├── 📂 Data
│   ├── compliance-files/                       # Input documents
│   └── pipeline-output/                        # Generated outputs
│       ├── openai/                             # GPT-5.2 results
│       └── anthropic/                          # Claude Sonnet 4 results
│
├── 📖 Documentation
│   └── docs/
│       ├── ARCHITECTURE.md                     # Technical architecture
│       ├── DOCKER.md                           # Docker deployment guide
│       ├── PRODUCT_DEFINITION.md               # Product definition & ROI
│       └── SETUP.md                            # Security & configuration
│
├── ⚙️ Configuration
│   ├── config.json                             # Pipeline configuration
│   ├── config.example.json                     # Configuration template
│   └── .env / .env.example                     # API keys
│
├── knowledge_graph_generation.py               # Extraction pipeline orchestrator
└── join_graphs.py                              # Merge pipeline orchestrator
```

---

## 🚀 Quick Start

### Option A: Docker (Recommended)

```bash
# 1. Clone and navigate
git clone https://github.com/your-org/policy-to-knowledge.git
cd kernel-lab/policy-to-knowledge/pipeline

# 2. Set up environment
cp .env.example .env
nano .env  # Add your OPENAI_API_KEY and/or ANTHROPIC_API_KEY

# 3. Place compliance documents
cp your-document.pdf compliance-files/

# 4. Build and run
docker compose build
docker compose up -d p2k-ui

# 5. Open the UI
open http://localhost:8000

# 6. Run the batch pipeline when needed
docker compose run --rm p2k --provider openai
```

See [docs/DOCKER.md](docs/DOCKER.md) for the complete Docker guide, including the web UI/API container and the batch pipeline runner.

### Option B: Native Setup

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp config.example.json config.json
cp .env.example .env
nano .env  # Add OPENAI_API_KEY and ANTHROPIC_API_KEY

# 4. Add compliance documents
cp your-document.pdf compliance-files/

# 5. Run pipeline
python3 knowledge_graph_generation.py --provider openai
```

See [docs/SETUP.md](docs/SETUP.md) for the detailed setup guide.

---

## 📊 Running the Pipeline

### Extraction Pipeline (Agents 1-6)

```bash
# Process all files in compliance-files/
python3 knowledge_graph_generation.py

# Process a specific file
python3 knowledge_graph_generation.py --file compliance-files/FMNA.pdf

# Use a specific provider
python3 knowledge_graph_generation.py --provider anthropic

# Run a specific agent step
python3 knowledge_graph_generation.py --step 1   # Document organizer only
python3 knowledge_graph_generation.py --step 6   # Visualization only
```

### Batch Processing

Process all files in subdirectories together as batches:

```bash
# Scan compliance-files/ for subdirectories and process each as a batch
python3 knowledge_graph_generation.py --batch

# Process a specific subdirectory
python3 knowledge_graph_generation.py --batch-dir healthcare

# Batch mode with specific provider
python3 knowledge_graph_generation.py --batch --provider openai
```

### Merge Pipeline (Agents 7-10)

Compare and merge knowledge graphs from different compliance documents:

```bash
# List available knowledge graphs
python3 join_graphs.py --list

# Join two graphs (computes all set operations)
python3 join_graphs.py --g1 FMNA --g2 Revolution-Overlay --workers 15

# Join with custom batch size
python3 join_graphs.py --g1 FM --g2 FMNA --workers 20 --batch-size 15
```

---

## 📁 Output Structure

### Per-Document Output (Agents 1-6)

```
pipeline-output/openai/FMNA/
├── agent-1-organized-documents/              # Organized text chunks
├── agent-2-entities/
│   └── entity_types_and_relationships.json   # Entities & relationships
├── agent-3-rules/
│   └── compliance_rules_with_entities.json   # Extracted business rules
├── agent-3-5-validation/
│   └── validation_report.json                # Quality validation report
├── agent-4-rules-with-entities/
│   └── compliance_knowledge_graph.json       # Complete knowledge graph
├── agent-5-optimized/
│   └── optimized_compliance_knowledge_graph.json  # Deduplicated + dependencies
└── agent-6-visualization-and-report/
    └── FMNA_knowledge_graph.html              # Interactive visualization
```

### Merge Output (Agents 7-10)

```
pipeline-output/openai/_merged/FMNA_Revolution-Overlay/
├── agent-7-rule-clusters/
│   └── rule_clusters.json                    # Rules grouped by behavior
├── agent-8-rule-matches/
│   └── match_results.json                    # Semantic comparison results
├── agent-9-set-operations/
│   ├── intersection.json                     # Rules in both graphs
│   ├── union.json                            # All unique rules
│   ├── g1_minus_g2.json                      # G1-exclusive rules
│   ├── g2_minus_g1.json                      # G2-exclusive rules
│   └── contradictions.json                   # Conflicting rule pairs
└── agent-10-visualizations/
    ├── index.html                            # Summary dashboard
    ├── intersection.html
    ├── union.html
    ├── g1_minus_g2.html
    ├── g2_minus_g1.html
    └── contradictions.html
```

---

## 📊 View Results

```bash
# Open extraction visualization
open pipeline-output/openai/FMNA/agent-6-visualization-and-report/FMNA_knowledge_graph.html

# Open merge comparison dashboard
open pipeline-output/openai/_merged/FMNA_Revolution-Overlay/agent-10-visualizations/index.html
```

### Visualization Features

- **Interactive Network Graph** — Entities, rules, and dependencies with color coding (vis.js)
- **Searchable Rules Table** — Real-time filtering by rule text, type, or entity
- **5 Key Metrics** — Business rules, dependencies, confidence scores, low confidence alerts, duplicates removed
- **Dependency Colors** — 7 types: prerequisite, sequential, conditional, complementary, contradictory, override, validation
- **Responsive Design** — Works on desktop, tablet, and mobile

---

## 📈 Pipeline Results (FMNA.pdf)

### Model Comparison

| Metric | OpenAI GPT-5.2 | Anthropic Claude Sonnet 4 |
|--------|----------------|---------------------------|
| **Rules Extracted** | 306 (after optimization) | 125 (clean, no duplication) |
| **Entity Types** | 44 entities, 40 relationships | 44 entities, 40 relationships |
| **Duplicate Groups** | 4 (5 rules removed) | 0 (excellent diversity) |
| **Dependencies** | 26 with impact analysis | 14 critical path focused |
| **Batch Size** | 10 rules/batch | 4 rules/batch |
| **Processing Time** | ~25-30 min | ~20-25 min |
| **Extraction Style** | Comprehensive, literal | Selective, well-structured |
| **Best For** | Complete audit coverage | Core requirements |

---

## 🔧 Configuration

### Environment Variables (`.env`)

```bash
OPENAI_API_KEY=sk-proj-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here   # Optional
```

### Pipeline Configuration (`config.json`)

```json
{
  "openai": {
    "api_key": "${OPENAI_API_KEY}",
    "models": {
      "reasoning": "gpt-5.2",
      "reasoning_effort": "medium"
    }
  },
  "anthropic": {
    "api_key": "${ANTHROPIC_API_KEY}",
    "models": {
      "reasoning": "anthropic/claude-sonnet-4-20250514",
      "reasoning_effort": "high"
    }
  },
  "rules_extractor": {
    "target_rules": 300,
    "rules_per_batch_openai": 10,
    "rules_per_batch_anthropic": 4
  }
}
```

**Provider Notes:**
- OpenAI: Use model name directly (e.g., `gpt-5.2`)
- Anthropic: Must include `anthropic/` prefix for LiteLLM (e.g., `anthropic/claude-sonnet-4-20250514`)
- Each provider outputs to its own directory: `pipeline-output/openai/` or `pipeline-output/anthropic/`

---

## 🔧 Technology Stack

| Component | Technology |
|-----------|------------|
| **LLM Providers** | OpenAI GPT-5.2, Anthropic Claude Sonnet 4 |
| **LLM Interface** | LiteLLM (unified multi-provider) |
| **Language** | Python 3.11 |
| **Document Processing** | PyPDF2, python-docx, pandas, openpyxl, langchain-text-splitters |
| **Visualization** | vis.js (embedded in HTML) |
| **Containerization** | Docker, Docker Compose |

---

## 🎯 Use Cases

### For Compliance Officers

- **View interactive HTML visualization** — Explore knowledge graph with network diagram
- **Search specific requirements** — Find rules by entity, category, or keyword
- **Track dependencies** — Understand rule relationships and prerequisites
- **Compare documents** — Merge pipeline shows overlap and contradictions

### For Developers

- **Deploy with Docker** — Containerized setup with one command
- **Access structured JSON** — Programmatic access to rules and entities
- **Extend with custom agents** — Add domain-specific processing

### For Researchers

- **Compare LLM performance** — OpenAI vs Anthropic extraction quality
- **Study prompt engineering** — Optimized prompts for knowledge extraction
- **Benchmark processing** — Parallel vs sequential agent performance

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[docs/PRODUCT_DEFINITION.md](docs/PRODUCT_DEFINITION.md)** | Product definition, business case, ROI analysis |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Technical architecture and design |
| **[docs/DOCKER.md](docs/DOCKER.md)** | Docker deployment guide |
| **[docs/SETUP.md](docs/SETUP.md)** | Security and configuration setup |
| **[agents/README.md](agents/README.md)** | Agent implementation details |
| **[utils/README.md](utils/README.md)** | Utility modules reference |
| **[prompts/README.md](prompts/README.md)** | Prompt engineering details |

---

## 🤝 Contributing

Areas for enhancement:

- 🌍 **Multi-language support** — Extend beyond English compliance documents
- 🔧 **Additional LLM providers** — Azure OpenAI, Gemini
- 📊 **Enhanced visualizations** — Timeline views, rule evolution tracking
- 🧪 **Testing framework** — Unit tests and integration tests for agents
- 📄 **Report formats** — PDF export, Word export
- 🔄 **Incremental updates** — Document versioning and delta extraction
- 🔀 **N-way merge** — Merge more than 2 knowledge graphs simultaneously

## 📄 License

This project is part of the your-org/kernel-lab repository under `policy-to-knowledge/pipeline`.

## 🆘 Support

- 📖 Check documentation in respective README files
- 💬 For Docker issues, see [docs/DOCKER.md](docs/DOCKER.md) troubleshooting
- 🔧 For agent issues, see [agents/README.md](agents/README.md)

---

**Last Updated**: February 2026
**Product**: Policy to Knowledge
