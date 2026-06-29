# Pipeline Architecture

Technical architecture of the **pipeline** app: a 10-agent OpenAI extraction pipeline, a FastAPI backend, and a React/Vite UI.

## System Overview

A multi-agent system that transforms unstructured documents into structured knowledge graphs. The pipeline is **domain-agnostic** and configured for a specific industry through pluggable domain prompts (for example `mortgage`, `aml`, `healthcare`, `commercial_lending`).

```mermaid
flowchart LR
    subgraph Input["📥 Input Layer"]
        PDF[PDF Documents]
        DOCX[Word Documents]
        MD[Markdown Files]
        CSV[CSV/Excel Data]
        DC[Domain Config]
    end

    subgraph Processing["⚙️ Processing Layer"]
        AP[Agent Pipeline]
        PS[Prompt System]
        LLM[LLM Integration]
    end

    subgraph Output["📤 Output Layer"]
        KG[Knowledge Graphs]
        VIZ[Visualizations]
        MERGE[Set Operations]
    end

    Input --> Processing --> Output
```

---

## 1. High-Level Architecture

### Layered Architecture

```mermaid
flowchart TB
    subgraph Presentation["🎨 Presentation Layer"]
        HTML[HTML Reports<br/>vis.js graphs]
    end

    subgraph Orchestration["🎯 Orchestration Layer"]
        MAIN[cli/extract.py<br/>Extraction]
        COMPARE[cli/compare.py<br/>Set Operations]
    end

    subgraph Agents["🤖 Agent Layer"]
        direction LR
        EXT[Extraction Pipeline<br/>Agents 1→2→3→3.5→4→5→6]
        CMP[Comparison Pipeline<br/>Agents 7→8→9→10]
    end

    subgraph Services["🔧 Services Layer"]
        LLMC[LLM Client<br/>OpenAI SDK]
        PM[Prompt Manager]
    end

    subgraph Infrastructure["🏗️ Infrastructure Layer"]
        DOCKER[Docker Containers]
        FS[File System I/O]
        API[LLM API<br/>OpenAI]
    end

    Presentation --> Orchestration
    Orchestration --> Agents
    Agents --> Services
    Services --> Infrastructure
```

### Component Responsibilities

| Layer | Components | Responsibility |
|-------|------------|----------------|
| **Presentation** | HTML Reports | User-facing outputs and visualization |
| **Orchestration** | `cli/extract.py`, `cli/compare.py` | Pipeline execution coordination |
| **Agent** | 10 specialized agents | Domain-specific processing logic |
| **Services** | `utils/` modules | Shared infrastructure (LLM client, prompts, config) |
| **Infrastructure** | Docker, File I/O | Deployment and data persistence |

### Agent Roster

| # | Agent | Pipeline | Role |
|---|-------|----------|------|
| 1 | Document Organizer | Extraction | Chunk and structure source documents |
| 2 | Entity Extractor | Extraction | Discover entities and relationships |
| 3 | Rules Extractor | Extraction | Extract business rules with a taxonomy |
| 3.5 | Validator | Extraction | Verify rules against source text |
| 4 | Merger | Extraction | Merge rules and entities into a graph |
| 5 | Optimizer | Extraction | Deduplicate and map dependencies |
| 6 | Visualization | Extraction | Render HTML report and graph |
| 7 | Clusterer | Comparison | Cluster rules across two graphs |
| 8 | Semantic Matcher | Comparison | Match semantically equivalent rules |
| 9 | Set Operations | Comparison | Compute intersection/difference/union |
| 10 | Set Visualization | Comparison | Render comparison HTML outputs |

---

## 2. Agent Pipeline Architecture

### Extraction Pipeline (Agents 1-6)

Sequential processing that transforms compliance documents into knowledge graphs:

```mermaid
flowchart LR
    subgraph Extraction["Extraction Pipeline"]
        A1[🔧 Agent 1<br/>Document<br/>Organizer]
        A2[🏷️ Agent 2<br/>Entity<br/>Extractor]
        A3[📜 Agent 3<br/>Rules<br/>Extractor]
        A35[✅ Agent 3.5<br/>Validator]
        A4[🔗 Agent 4<br/>Merger]
        A5[⚡ Agent 5<br/>Optimizer]
        A6[📊 Agent 6<br/>Visualization]
    end

    A1 -->|chunks.txt| A2
    A2 -->|entities.json| A3
    A3 -->|rules.json| A35
    A35 -->|report.json| A4
    A4 -->|kg.json| A5
    A5 -->|optimized.json| A6
    A6 -->|HTML Report| OUT((Output))
```

### Comparison Pipeline (Agents 7-10)

Set operations for comparing two knowledge graphs (`cli/compare.py`):

```mermaid
flowchart TB
    KG1[(Knowledge<br/>Graph 1)]
    KG2[(Knowledge<br/>Graph 2)]
    
    subgraph Compare["Comparison Pipeline"]
        A7[📊 Agent 7<br/>Clusterer]
        A8[🔍 Agent 8<br/>Semantic Matcher]
        A9[➗ Agent 9<br/>Set Operations]
        A10[🎨 Agent 10<br/>Set Visualization]
    end

    KG1 --> A7
    KG2 --> A7
    A7 -->|clusters.json| A8
    A8 -->|matches.json| A9
    A9 -->|set results| A10

    subgraph Outputs["HTML Outputs"]
        INT[intersection.html]
        G1G2[g1_minus_g2.html]
        G2G1[g2_minus_g1.html]
        UNION[union.html]
        CONTRA[contradictions.html]
        INDEX[index.html]
    end

    A10 --> Outputs
```

### Agent Interface Contract

All agents follow a standardized interface pattern:

```mermaid
flowchart LR
    subgraph Input
        JSON[JSON/Text Files]
        CFG[Config Params]
        PRIOR[Prior Agent Output]
    end

    subgraph Process
        LOAD[Load Prompts]
        LLM[Call LLM]
        TRANSFORM[Transform Data]
        VALIDATE[Validate Results]
    end

    subgraph Output
        OJSON[JSON Files]
        HTML[HTML Reports]
        CSV[CSV Exports]
    end

    Input --> Process --> Output
```

---

## 3. Document Processing Architecture

### Agent 1: Document Chunker Tools

Agent 1 uses a tool-based architecture with specialized chunkers for different document formats:

```mermaid
flowchart TB
    subgraph InputDocs["Input Documents"]
        PDF[📄 PDF]
        MD[📝 Markdown]
        CSV[📊 CSV]
        XLS[📈 Excel]
    end

    subgraph Registry["Chunker Tool Registry"]
        ROUTE[Extension-based Routing]
    end

    subgraph Chunkers["Specialized Chunkers"]
        PDFC[PDFChunker<br/>PyPDF2 + LLM]
        MDC[MarkdownChunker<br/>langchain]
        CSVC[CSVChunker<br/>pandas]
        XLSC[ExcelChunker<br/>pandas + openpyxl]
    end

    subgraph Output["Unified Output"]
        CHUNKS[DocumentChunk<br/>with metadata]
    end

    PDF --> ROUTE
    MD --> ROUTE
    CSV --> ROUTE
    XLS --> ROUTE

    ROUTE --> PDFC
    ROUTE --> MDC
    ROUTE --> CSVC
    ROUTE --> XLSC

    PDFC --> CHUNKS
    MDC --> CHUNKS
    CSVC --> CHUNKS
    XLSC --> CHUNKS
```

### Chunker Tool Specifications

| Tool | Input Format | Library | Chunking Strategy |
|------|--------------|---------|-------------------|
| **PDFChunker** | `.pdf` | PyPDF2 + LLM | TOC-based hierarchical splitting |
| **DocxChunker** | `.docx` | python-docx | Heading-based hierarchical splitting |
| **MarkdownChunker** | `.md` | langchain-text-splitters | Header hierarchy (H1-H4) |
| **CSVChunker** | `.csv`, `.tsv` | pandas | Row-based grouping |
| **ExcelChunker** | `.xlsx`, `.xls` | pandas + openpyxl | Sheet-aware processing |

### DocumentChunk Schema

```mermaid
classDiagram
    class DocumentChunk {
        +string chunk_id
        +string title
        +string content
        +List section_path
        +int row_start
        +int row_end
        +string sheet_name
        +Dict metadata
        +string source_file
    }
    
    class BaseChunker {
        +can_handle(file_path) bool
        +chunk(file_path, config) List
        +set supported_extensions
        +string name
    }
    
    BaseChunker <|-- PDFChunker
    BaseChunker <|-- DocxChunker
    BaseChunker <|-- MarkdownChunker
    BaseChunker <|-- CSVChunker
    BaseChunker <|-- ExcelChunker
```

---

## 4. Prompt Architecture

The system uses production prompts loaded at runtime by `PromptManager`.

```mermaid
flowchart TB
    subgraph Prompts["📁 prompts/"]
        PROD["*.txt<br/>Production prompts"]
    end

    subgraph Runtime["🔧 Runtime"]
        PM[PromptManager<br/>Cache + Format]
        AGENT[Agent N]
        LLMCLIENT[LLM Client]
    end

    PROD -->|loads| PM
    PM -->|provides| AGENT
    AGENT -->|sends| LLMCLIENT
```

### Prompt-to-Agent Mapping

| Agent | Prompt File | Focus |
|-------|-------------|-------|
| 1 | `document_structure_analysis.txt` | TOC extraction, hierarchical chunking |
| 2 | `entity_extraction.txt`, `entity_refinement.txt` | Entity/relationship discovery |
| 3 | `business_rules_extraction.txt` | Rule extraction with taxonomy |
| 3.5 | `validation_report.txt` | Source verification |
| 5 | `rule_deduplication.txt`, `dependency_analysis.txt` | Dedup, dependency mapping |
| 8 | `rule_matcher.txt`, `rule_matcher_batch.txt` | Semantic similarity |

---

## 5. LLM Integration Architecture

### LLM Interface

```mermaid
flowchart TB
    subgraph Client["utils/llm_client.py"]
        LITE[OpenAI SDK]
    end

    subgraph Providers["LLM Provider"]
        OAI[OpenAI]
    end

    Client --> OAI
```

The system is **OpenAI-only**. Models are configured in `config.json` and read by `utils/config.py`:

| Role | Config key | Default |
|------|------------|---------|
| Reasoning | `openai.models.reasoning` | `gpt-5.2` |
| Optimizer | `openai.models.optimizer` | `gpt-5.2` |
| Embeddings | `openai.models.embeddings` | `text-embedding-ada-002` |

### Extraction Settings

| Aspect | Config key | Default |
|--------|------------|---------|
| Worker count | `pipeline.max_workers` | 30 parallel |
| Rules per batch | `rules_extractor.rules_per_batch` | 10 |
| Output path | `directories.output` | `pipeline-output/` |

---

## 6. Data Flow Architecture

### Output Directory Structure

```mermaid
flowchart TB
    subgraph Root["pipeline-output/"]
        subgraph Provider["provider/"]
            subgraph Doc["document/"]
                A1OUT[agent-1-organized-documents/]
                A2OUT[agent-2-entities/]
                A3OUT[agent-3-rules/]
                A35OUT[agent-3-5-validation/]
                A4OUT[agent-4-rules-with-entities/]
                A5OUT[agent-5-optimized/]
                A6OUT[agent-6-visualization-and-report/]
            end
            subgraph Merged["_merged/doc1_doc2/"]
                A7OUT[agent-7-rule-clusters/]
                A8OUT[agent-8-rule-matches/]
                A9OUT[agent-9-set-operations/]
                A10OUT[agent-10-visualizations/]
            end
        end
    end
```

### Inter-Agent Data Contracts

```mermaid
flowchart LR
    A1[Agent 1] -->|"chunks/*.txt"| A2[Agent 2]
    A2 -->|"entities.json"| A3[Agent 3]
    A3 -->|"rules.json"| A35[Agent 3.5]
    A35 -->|"validation.json"| A4[Agent 4]
    A4 -->|"kg.json"| A5[Agent 5]
    A5 -->|"optimized.json"| A6[Agent 6]
    A6 -->|"*.html"| OUT1((Output))

    A7[Agent 7] -->|"clusters.json"| A8[Agent 8]
    A8 -->|"matches.json"| A9[Agent 9]
    A9 -->|"set_ops.json"| A10[Agent 10]
    A10 -->|"*.html"| OUT2((Output))
```

---

## 7. Deployment Architecture

### Container Architecture

```mermaid
flowchart TB
    subgraph Docker["Docker Environment"]
        subgraph CLI["p2k (Dockerfile.cli)<br/>python:3.11-slim"]
            AGENTS[Agent Execution]
            LLMCALL[LLM API Calls]
        end

        subgraph API["p2k-ui (Dockerfile.api)<br/>python:3.12-slim"]
            FASTAPI[FastAPI Backend]
            REACT[Built React UI]
        end

        subgraph Volumes["Shared Volumes"]
            CF["compliance-files/"]
            PO["pipeline-output/ RW"]
            CONFIG["config.json"]
        end
    end

    CLI --> Volumes
    API --> Volumes
```

The batch CLI image (`Dockerfile.cli`) runs `cli/extract.py` as its entrypoint. The API image (`Dockerfile.api`) builds the React frontend and serves it from FastAPI on port `8000`. See [DOCKER.md](DOCKER.md) for full details.

### Running with Docker

```bash
# Run extraction pipeline (Agents 1–6)
docker compose run --rm p2k --provider openai

# Run comparison pipeline (Agents 7–10)
docker compose run --rm --entrypoint python p2k cli/compare.py --g1 mortgage --g2 commercial_lending

# View reports directly
open pipeline-output/*/agent-6-visualization-and-report/*_knowledge_graph.html
```

---

## 8. Extension Architecture

### Adding a New Agent

```mermaid
flowchart TB
    subgraph NewAgent["Adding Agent N"]
        CREATE["1. Create<br/>agents/agent_N_name.py"]
        INTERFACE["2. Define Interface<br/>Input - Process - Output"]
        REGISTER["3. Register in<br/>cli/extract.py or cli/compare.py"]
        PROMPT["4. Create prompt<br/>if LLM-dependent"]
    end

    CREATE --> INTERFACE --> REGISTER --> PROMPT
```

### Adding a New Rule Type

1. **Update taxonomy** in `prompts/business_rules_extraction.txt`
2. **Update visualization** color mapping in agent_6 and agent_10

---

## 9. Security Considerations

```mermaid
flowchart TB
    subgraph Security["Security Model"]
        API["API Keys<br/>Environment Variables"]
        DATA["Data Isolation<br/>Per-provider outputs"]
        VOL["Volume Mounts<br/>Read-only sources"]
    end

    subgraph Best["Best Practices"]
        ENV[".env files excluded<br/>from version control"]
        CONFIG["config.json with<br/>sensitive data gitignored"]
        DOCKER["Docker secrets for<br/>production deployment"]
    end

    Security --> Best
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | App overview and quick start |
| [DOCKER.md](DOCKER.md) | Container deployment guide |
| [SETUP.md](SETUP.md) | Local environment setup |
| [agents/README.md](../agents/README.md) | Agent implementation details |
| [prompts/README.md](../prompts/README.md) | Production prompt reference |
