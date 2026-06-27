# Explorer

An AI-powered **Compliance Knowledge Graph** platform built with **JanusGraph**, **OpenAI**, and **D3.js**. Explorer enables intelligent exploration of compliance regulations — Policy to Knowledge internal guidelines, Fannie Mae, Freddie Mac, and Revolution overlays — through natural language conversation, semantic search, interactive graph visualization, collaborative annotation, and release management.

> **Backend:** this folder is the JanusGraph/Cassandra/OpenSearch
> implementation that serves the shared frontend via the `apiBaseUrl` setting.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Web Client (D3.js + SSE)                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS
┌────────────────────────────▼────────────────────────────────────────┐
│                   Explorer — Flask API                        │
│                                                                     │
│  ┌──────────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │  AI Chat Agent   │  │  Graph Query   │  │  Vector Search     │   │
│  │  (GPT-5.2)       │  │  Service       │  │  Service           │   │
│  │  7 Tool Calls    │  │  (Gremlin)     │  │  (k-NN + Embeds)   │   │
│  └───────┬──────────┘  └───────┬────────┘  └───────┬────────────┘   │
│          │                     │                    │               │
│          └─────────────┬───────┘────────────────────┘               │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  Connection Pool (Singleton) — Gremlin WS + OpenSearch HTTP │     │
│  └───────┬─────────────────────────────┬──────────────────────┘     │
│          │                             │                            │
│  ┌───────▼──────────┐   ┌─────────────▼─────────────┐              │
│  │  Redis (LRU)     │   │  graphs.yaml Manifest     │              │
│  │  Query Cache     │   │  Multi-Graph Config        │              │
│  └──────────────────┘   └───────────────────────────┘              │
└──────────┬─────────────────────────────┬───────────────────────────┘
           │                             │
┌──────────▼──────────┐   ┌──────────────▼──────────────┐
│  JanusGraph Server  │   │  OpenSearch 2.17            │
│  (Multi-Graph)      │   │  ┌────────────────────────┐ │
│                     │   │  │ Full-Text Indices       │ │
│  sample_guidelines_g │   │  │  (JanusGraph mixed idx) │ │
│  fannie_mae_g       │   │  ├────────────────────────┤ │
│  revolution_g       │   │  │ k-NN Vector Indices    │ │
│                     │   │  │  (Semantic Search)      │ │
└──────────┬──────────┘   │  └────────────────────────┘ │
           │              └─────────────────────────────┘
┌──────────▼──────────┐
│  Apache Cassandra   │
│  4.1 (Storage)      │
└─────────────────────┘
```

## Features

- **AI Chat Agent** — Conversational assistant powered by OpenAI GPT-5.2 with 12 tool calls (Gremlin, semantic search, text search, graph navigation, related rules, statistics, rule comparison, dependency path finding, source references, review status, cross-graph search); supports reasoning models (o1/o3/o4-mini/gpt-5)
- **Interactive Graph Visualization** — D3.js force-directed graph with zoom, click-to-inspect, and real-time node navigation
- **Node Detail Panel** — Inspect full rule properties, references, neighbors, and dependency cards; supports comment/edit/delete/share actions
- **Graph Editing** — Full CRUD for vertices and edges with validation, graph-lock guards, auto-category linking, and instant semantic re-indexing
- **Release Management** — Create immutable graph snapshots, lock graphs to prevent edits during released state, browse release history
- **Approval & Review Toggles** — Mark nodes as Reviewed or Approved directly from the detail panel; state persists in SQLite
- **Comment & Annotation System** — Add threaded comments with author attribution; edit node name/content with full version history
- **Task Box** — Floating task panel surfacing nodes that need review or approval, with filter tabs and badge counter
- **AI Rewrite** — ✨🖊️ sparkle button on text fields calls GPT to rephrase content in-place
- **AI Connection Suggestions** — 3-signal scoring (semantic + entity + rule-type affinity) to suggest edges for new nodes
- **Rule ID Suggestion** — Auto-generates structured Rule IDs (`BR_{ENTITY}_{TYPE}_{SEQ}_{SUB}`) from node metadata via GPT
- **Reference Resolution** — Maps rule references and structured `source_reference` (with word-position highlighting) to source document chunks
- **Dark / Light Theme** — Toggle between night and day modes; preference persists via localStorage
- **Semantic Search** — OpenSearch k-NN with sentence-transformer embeddings (all-MiniLM-L6-v2)
- **Full-Text Search** — JanusGraph mixed index via OpenSearch
- **Graph Search Bar** — Filter visible nodes in real time with a text query; dimmed/bright visual feedback and match counter
- **Gremlin Query Console** — Execute custom Gremlin traversals
- **Streaming Responses** — Server-Sent Events (SSE) for real-time token-by-token AI responses with process visibility
- **Multi-Graph Support** — Manifest-driven architecture (`graphs.yaml`); add a new graph by adding an entry and a KG JSON file
- **Admin Tools** — Consistency checks, embedding rebuilds, task re-resolution, force-clean and rebuild
- **URL Prefix Support** — WSGI middleware for deployment behind reverse proxies (default `/app`)

## Prerequisites

- **Docker** & **Docker Compose** (v2+)
- **Python 3.10+**
- **OpenAI API key** (set in `.env` file)

## Quick Start

### 1. Install Python Dependencies

```bash
python -m venv .venv
source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env   # or create .env manually
```

Add your OpenAI API key to `.env`:
```
OPENAI_API_KEY=sk-...
```

### 3. Start Everything

```bash
./start.sh           # Incremental (default) — preserves all existing data
./start.sh --fresh   # Rebuild graphs & re-index; keeps Docker volumes intact
./start.sh --clean   # Wipe everything (volumes + SQLite + Redis) and rebuild from scratch
./start.sh --help    # Show all options
```

`./start.sh` (incremental mode) will:
1. Generate JanusGraph config files from `graphs.yaml`
2. Start Docker services (Cassandra, OpenSearch, Redis, JanusGraph)
3. Wait for all services to be healthy
4. Load data **only for graphs that are empty or newly added** — existing graphs are untouched
5. Index semantic search embeddings for any graphs that are missing them
6. Start the Flask server on **http://localhost:5000**

### 4. Open in Browser

Navigate to **http://localhost:5000**

### 5. Stop

```bash
./stop.sh          # Stop server only (Docker stays running for fast restart)
./stop.sh --all    # Stop server + Docker containers
./start.sh --clean # Nuclear reset: wipe all volumes + DBs, then rebuild
```

## Project Structure

```
assistant/
├── docker-compose.yml          # Cassandra + OpenSearch + JanusGraph + Redis
├── requirements.txt            # Python dependencies (13 packages)
├── start.sh                    # One-command startup (--fresh / --clean modes)
├── stop.sh                     # Graceful shutdown
├── architecture.md             # Detailed architecture notes
├── conf/
│   ├── config.py               # Env-based configuration (all settings)
│   ├── graph_manifest.py       # Runtime graph manifest from graphs.yaml
│   ├── graphs.yaml             # Multi-graph configuration (single source of truth)
│   ├── gremlin-server.yaml     # Gremlin Server config (auto-generated)
│   ├── init-graphs.groovy      # Graph initialization script (auto-generated)
│   └── janusgraph-*.properties # Per-graph JanusGraph properties (auto-generated)
├── kgs/
│   ├── absa-kg.json            # Absa AML knowledge graph
│   ├── barclays-kg.json        # Barclays AML knowledge graph
│   ├── comercial_lending-kg.json # Commercial lending knowledge graph
│   ├── fannie_mae-kg.json      # Fannie Mae knowledge graph
│   ├── freddie_mac-kg.json     # Freddie Mac knowledge graph
│   ├── healthcare-kg.json      # Healthcare compliance knowledge graph
│   ├── prmi-kg.json            # PRMI knowledge graph
│   └── revolution-kg.json      # Revolution overlays knowledge graph
├── kbs/
│   ├── absa/                   # Source documents (Absa AML)
│   ├── barclays/               # Source documents (Barclays AML)
│   ├── comercial-lending/      # Source documents (Commercial lending)
│   ├── fannie-mae/             # Source documents (Fannie Mae guidelines)
│   ├── freddie-mac/            # Source documents (Freddie Mac guidelines)
│   ├── healthcare/             # Source documents (Healthcare compliance)
│   ├── prmi/                   # Source documents (PRMI guidelines)
│   └── revolution/             # Source documents (Revolution overlays)
├── scripts/
│   └── generate_graph_config.py # Auto-generates conf/ files from graphs.yaml
├── src/
│   ├── cache.py                # Redis response caching layer
│   ├── connection_pool.py      # Gremlin + OpenSearch connection pools
│   ├── data_loader.py          # Graph data loader (multi-graph, batch)
│   ├── docs_sync.py            # Document synchronization between kbs/ and pipeline
│   ├── graph_connection.py     # Gremlin connection helper
│   ├── gremlin_queries.py      # Example traversal queries
│   ├── log.py                  # Single-line JSON structured logging
│   ├── main.py                 # CLI entry point (setup / setup-if-empty / force-clean / serve)
│   ├── models.py               # SQLAlchemy models (NodeAnnotation, GraphRelease, GraphState)
│   ├── schema.py               # JanusGraph schema + mixed index
│   ├── semantic_search.py      # OpenSearch k-NN indexing & vector search
│   └── server.py               # Flask API + AI chat agent + SSE streaming
├── ui/
│   ├── index.html              # Full SPA entry point
│   ├── css/                    # Modular stylesheets (10 files)
│   │   ├── variables.css       # CSS custom properties + theme tokens
│   │   ├── layout.css          # Page layout & responsive structure
│   │   ├── components.css      # Shared UI components
│   │   ├── graph.css           # D3 graph visualization
│   │   ├── detail.css          # Node detail panel
│   │   ├── create.css          # Vertex/edge creation forms
│   │   ├── manage.css          # Graph management panel
│   │   ├── tasks.css           # Task box panel
│   │   ├── release.css         # Release management panel
│   │   └── chat.css            # Chat agent panel
│   └── js/                     # Modular JavaScript modules (13 files)
│       ├── app.js              # Application bootstrap
│       ├── state.js            # Global state management
│       ├── storage.js          # LocalStorage persistence
│       ├── utils.js            # Shared utilities
│       ├── graph.js            # D3 force graph rendering
│       ├── detail.js           # Node detail panel logic
│       ├── create.js           # Vertex/edge creation logic
│       ├── actions.js          # CRUD action handlers
│       ├── manage.js           # Graph management logic
│       ├── tasks.js            # Task panel logic
│       ├── release.js          # Release management logic
│       ├── chat.js             # AI chat interface + SSE
│       └── shortcuts.js        # Keyboard shortcuts
├── uitests/                    # Playwright E2E UI tests (TypeScript)
│   ├── playwright.config.ts
│   ├── package.json
│   └── tests/
└── e2etests/                   # Pytest backend API tests
    ├── conftest.py
    └── test_*.py               # 10 per-endpoint test files
```

## Data Model

```
(business_rule) ──depends_on──▶ (business_rule)
       │
       └──belongs_to_category──▶ (entity_category)
```

Knowledge graphs are defined in `graphs.yaml` and loaded at startup. Only graphs with existing KG JSON files are loaded:

| Graph | Traversal Source | KG File | Domain |
|-------|-----------------|---------|--------|
| Sample Guidelines | `sample_guidelines_g` | `kgs/sample-guidelines-kg.json` | Policy to Knowledge internal policy |
| Fannie Mae | `fannie_mae_g` | `kgs/fannie_mae-kg.json` | Mortgage |
| Freddies Mac | `freddies_mac_g` | `kgs/freddies_mac-kg.json` | Mortgage |
| Freddie Mac | `freddie_mac_g` | `kgs/freddie_mac-kg.json` | Mortgage |
| Revolution | `revolution_g` | `kgs/revolution-kg.json` | Mortgage overlays |
| PRMI | `prmi_g` | `kgs/prmi-kg.json` | Mortgage |
| Absa | `absa_g` | `kgs/absa-kg.json` | Anti-money laundering |
| Barclays | `barclays_g` | `kgs/barclays-kg.json` | Anti-money laundering |
| Anti Money Laundry | `anti_money_laundry_g` | `kgs/anti_money_laundry-kg.json` | Anti-money laundering |
| Comercial Lending | `comercial_lending_g` | `kgs/comercial_lending-kg.json` | Commercial lending |
| Healthcare | `healthcare_g` | `kgs/healthcare-kg.json` | Healthcare |

### Vertex Properties

**Core:** `rule_id`, `rule_name`, `rule_type`, `description`, `conditions`, `consequences`, `exceptions`, `reference`, `mandatory`, `confidence_score`, `entity_type`, `category`, `vertex_uuid`

**Extended (v2):** `source_reference` (structured JSON with chunk path and word positions), `effective_date`, `expiration_date`, `superseded_by`, `jurisdiction`, `risk_level`, `enforcement_action`, `applicability_scope`, `audit_frequency`, `reference_verified`, `confidence_breakdown`, `deduplication_info`

**Vertex labels:** `business_rule`, `entity_category`

**Rule types:** `constraint`, `eligibility`, `process`, `prohibition`, `documentation`, `validation`

**Edge labels:** `depends_on`, `belongs_to_category`

**Dependency types:** `prerequisite`, `sequential`, `conditional`, `complementary`, `contradictory`, `override`, `validation`

### Persistence

- **Graph data** — JanusGraph (Cassandra + OpenSearch)
- **Annotations** (comments, edits, approvals, review history) — SQLite (`app.db`) via SQLAlchemy, keyed by vertex ID
- **Graph releases** — SQLite (`app.db`) — immutable snapshots with full graph JSON
- **Graph lock state** — SQLite (`app.db`) — per-graph lock flag and current release reference

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Explorer UI |
| `GET` | `/api/` | Health check |
| **Graph** | | |
| `GET` | `/api/graph?graph_name=…` | Full graph as `{nodes, links}` |
| `GET` | `/api/graph/status?graph_name=…` | Graph lock/release status |
| `GET` | `/api/graph/releases?graph_name=…` | List all releases for a graph |
| `GET` | `/api/graph/release/<id>` | Get a single release with snapshot |
| `POST` | `/api/graph/release` | Create a new release (snapshot + lock) |
| `POST` | `/api/graph/unlock` | Unlock a graph for editing |
| **Vertex** | | |
| `GET` | `/api/vertex/<id>` | Vertex detail + neighbors |
| `GET` | `/api/vertex/schema` | Vertex schema metadata (labels, rule types, dependency types) |
| `POST` | `/api/vertex` | Create a new vertex |
| `DELETE` | `/api/vertex/<id>` | Delete a vertex and its incident edges |
| `POST` | `/api/vertex/suggest-connections` | AI-suggested connections for a new node |
| **Edge** | | |
| `POST` | `/api/edge` | Create a new edge |
| `DELETE` | `/api/edge` | Delete an edge by source/target/label |
| `POST` | `/api/edge/reverse` | Reverse an edge direction (preserves properties) |
| **Search** | | |
| `GET` | `/api/search/text?q=…&graph_name=…` | Full-text keyword search |
| `GET` | `/api/search/semantic?q=…&top_k=5` | Semantic similarity search |
| **Chat** | | |
| `POST` | `/api/chat` | AI chat (non-streaming) |
| `POST` | `/api/chat/stream` | AI chat with SSE streaming |
| **Annotations** | | |
| `GET` | `/api/annotations/<node_id>` | Get all annotations for a node |
| `PUT` | `/api/annotations/<node_id>` | Create or update annotations |
| `GET` | `/api/annotations` | List all annotations |
| `DELETE` | `/api/annotations/<node_id>` | Delete all annotations for a node |
| **Tasks** | | |
| `GET` | `/api/tasks` | List pending review/approval tasks |
| `POST` | `/api/tasks/<id>/complete` | Mark a task as complete |
| **AI Helpers** | | |
| `POST` | `/api/rewrite` | AI rewrite of a text field |
| `POST` | `/api/suggest-rule-id` | Generate a structured Rule ID from node metadata |
| **References** | | |
| `GET` | `/api/reference/resolve?ref=…` | Resolve a rule reference to source document chunks |
| `GET` | `/api/reference/chunk?chunk_id=…` | Render a source document chunk as HTML |
| **Gremlin** | | |
| `GET` | `/api/gremlin/examples` | Pre-built Gremlin query examples |
| `POST` | `/api/gremlin/execute` | Execute raw Gremlin query |
| **Admin** | | |
| `POST` | `/api/admin/reset` | Force-clean and rebuild data stores |
| `GET` | `/api/admin/consistency` | Run consistency checks and return report |
| `POST` | `/api/admin/rebuild-embeddings` | Rebuild OpenSearch embedding index |
| `POST` | `/api/admin/rebuild-tasks` | Re-resolve task node IDs from live graph |

## Chat Agent Capabilities

The AI agent (GPT-5.2) has access to 12 tools and can chain up to 5 tool calls per conversation turn:

| # | Tool | Description |
|---|------|-------------|
| 1 | **semantic_search** | Find rules by conceptual similarity (OpenSearch k-NN) |
| 2 | **text_search** | Find rules by exact text content (JanusGraph mixed index) |
| 3 | **execute_gremlin** | Run arbitrary Gremlin graph traversals |
| 4 | **get_vertex_details** | Inspect a specific node with full properties, neighbors, and dependencies; auto-navigates the graph |
| 5 | **get_graph_data** | Retrieve full graph for visualization (switches active graph) |
| 6 | **find_related_rules** | Find a rule by name (exact or fuzzy) and return its full dependency neighborhood |
| 7 | **get_graph_statistics** | Comprehensive stats across all loaded graphs (counts, distributions, hub rules, risk, jurisdictions) |
| 8 | **compare_rules** | Side-by-side comparison of 2+ rules — properties, dependencies, and overlap analysis |
| 9 | **find_dependency_path** | Discover the shortest dependency chain between two named rules |
| 10 | **get_source_reference** | Retrieve the original source document chunk that a rule was extracted from |
| 11 | **get_review_status** | Summarize annotation, review, and approval status with optional filtering |
| 12 | **cross_graph_search** | Search across all loaded knowledge graphs simultaneously |

### Example Queries

- *"What are the top 5 most connected rules?"*
- *"Find rules about income verification"*
- *"Show me the Policy to Knowledge guidelines graph"*
- *"What categories have the most rules?"*
- *"What rules depend on Capital Reserve Requirement?"*
- *"Compare the DTI Ratio rule with the LTV Requirement rule"*
- *"What is the dependency path between Appraisal Requirements and Property Eligibility?"*
- *"Show me the source document for the ARM Adjustment Cap rule"*
- *"Which rules still need review?"*
- *"Search for 'escrow' across all graphs"*

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Graph Database | JanusGraph 1.0.0 |
| Storage Backend | Apache Cassandra 4.1 |
| Index Backend | OpenSearch 2.17 |
| AI Model | OpenAI GPT-5.2 (reasoning models supported) |
| Embeddings | all-MiniLM-L6-v2 (384-dim) |
| Backend | Python 3.10+ / Flask 3.1 |
| Frontend | D3.js v7, marked.js |
| Streaming | Server-Sent Events (SSE) |
| Cache | Redis 7 (LRU, sub-ms latency) |
| Metadata Store | SQLite via SQLAlchemy |

## Configuration

All settings are configurable via environment variables or `.env`. Key categories:

| Category | Examples |
|----------|----------|
| Infrastructure | `JANUSGRAPH_HOST/PORT`, `CASSANDRA_HOST/PORT`, `OPENSEARCH_HOST/PORT` |
| Redis | `REDIS_HOST/PORT`, `CACHE_TTL` (3600s), `REDIS_MAX_MEMORY` (256mb) |
| LLM | `OPENAI_CHAT_MODEL` (gpt-5.2), `OPENAI_REASONING_EFFORT` (medium), `MAX_TOOL_ROUNDS` (5) |
| Flask | `SERVER_HOST`, `SERVER_PORT` (5000), `URL_PREFIX` (/app) |
| Search | `SEMANTIC_SEARCH_DEFAULT_TOP_K` (5), `TEXT_SEARCH_MAX_RESULTS` (10), `KNN_ENGINE` (lucene) |
| Embedding | `EMBEDDING_MODEL` (all-MiniLM-L6-v2), `EMBEDDING_DIM` (384) |
| Pool | `POOL_MIN_SIZE` (2), `POOL_MAX_SIZE` (10) |

## Adding a New Knowledge Graph

1. Add an entry to `conf/graphs.yaml` with display name, traversal source, keyspace, and KG file path
2. Place the KG JSON file in `kgs/`
3. (Optional) Place source documents in `kbs/<folder>/`
4. Run `./start.sh` — config files are auto-regenerated and only the new graph is loaded; **existing graph data is preserved**

> `generate_graph_config.py` runs automatically inside `start.sh`. You only need to run it manually when regenerating config files outside of a full startup (e.g. for Docker config updates without a restart).

## CLI Commands

```bash
python -m src.main setup           # Destructive: schema → clear → load → embed → consistency
python -m src.main setup-if-empty  # Incremental: load only empty/new graphs, skip populated ones
python -m src.main force-clean     # Nuclear: destroy all data → rebuild
python -m src.main consistency     # Run consistency checks
python -m src.main serve           # Start Flask server
python -m src.main queries         # Run example Gremlin queries
python -m src.main semantic        # Run semantic search demo
```

## Cleanup

```bash
./stop.sh --all              # Stop server + Docker containers
./start.sh --clean           # Full nuclear reset: destroy all volumes, wipe SQLite & Redis, rebuild
```

## Notes

- JanusGraph uses `elasticsearch` as the index backend name for OpenSearch compatibility
- Schema uses a mixed index (`mixedContentIndex`) for full-text + exact-match search
- Semantic search uses HNSW algorithm for approximate nearest-neighbor vector search (configurable engine: `lucene` or `nmslib`)
- Node annotations (comments, edits, approvals, review flags) are persisted in `app.db` (SQLite) — this file is not inside a Docker volume so it survives `docker compose down`
- Graph releases and lock state are also stored in `app.db`
- Use `./start.sh --fresh` to rebuild graph data while keeping `app.db`; use `./start.sh --clean` to wipe everything
- Config files (`gremlin-server.yaml`, `init-graphs.groovy`, `janusgraph-*.properties`) are auto-generated from `graphs.yaml` — do not edit them directly
- All logs follow single-line JSON format per project logging standards
- The server supports deployment behind reverse proxies via the `URL_PREFIX` setting (default `/app`)
