<div align="center">

<img src="assets/p2k.png" alt="Policy to Knowledge" width="96" height="96" />

# Policy to Knowledge

**Turn compliance policy documents into queryable, traceable knowledge graphs — then explore, edit, and version them in the browser.**

[![CI](https://github.com/rrahimi-uci/policy-to-knowledge/actions/workflows/ci.yml/badge.svg)](https://github.com/rrahimi-uci/policy-to-knowledge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![OpenAI](https://img.shields.io/badge/LLM-OpenAI-412991.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab.svg)
![Node](https://img.shields.io/badge/Node-20-339933.svg)

[Documentation site](https://rrahimi-uci.github.io/policy-to-knowledge/) ·
[Architecture](https://rrahimi-uci.github.io/policy-to-knowledge/architecture.html) ·
[Repository layout](docs/STRUCTURE.md)

</div>

---

## What it does

Compliance teams drown in dense, ever-changing policy documents. **Policy to Knowledge** runs those documents through a **10-agent OpenAI pipeline** that extracts business rules and entities, deduplicates and links them, and emits an optimized **knowledge graph** — with every rule traceable back to the source passage it came from. A graph **Explorer** then lets you query, visualize, annotate, compare, and version the result.

- 🧩 **Extract** — segment documents, discover entities & relationships, mine business rules, validate, merge, optimize, and visualize.
- 🔀 **Compare** — run set operations (∩, differences, ∪, contradictions) across two graphs to see exactly what changed between policy versions or sources.
- 🕸️ **Explore** — an interactive D3 graph over JanusGraph with search, an AI chat assistant, annotations, and release/versioning.
- 🔎 **Trace** — every rule node keeps a `source_reference` (chunk path) back to the originating document.

## Components

| Path | Purpose | Default URL |
| --- | --- | --- |
| [`apps/shell/`](apps/shell) | React + Vite **suite shell** that embeds the app UIs | `http://localhost:4000` |
| [`apps/pipeline/`](apps/pipeline) | 10-agent extraction + compare pipeline, FastAPI API, React UI | API `:8000` · UI `:5173` |
| [`apps/explorer/`](apps/explorer) | Graph **Explorer** (Flask + JanusGraph/Cassandra/OpenSearch/Redis) | `http://localhost:5000/app`¹ |
| [`tools/video/`](tools/video) | Demo-video generator (deck + AI narration → mp4) | n/a |

¹ On macOS port `5000` is often taken by Docker/AirPlay; the launcher then serves the Explorer on `5050` (set `SERVER_PORT`).

## Project structure

```text
.
├── apps/
│   ├── shell/        # Suite shell — React + Vite (:4000)
│   ├── pipeline/     # 10-agent pipeline + FastAPI API + React UI
│   │   └── cli/      #   extract.py (agents 1–6) · compare.py (agents 7–10)
│   └── explorer/     # Graph explorer — Flask + JanusGraph + D3 UI
├── tools/video/      # Demo capture & AI narration tooling
├── docs/             # GitHub Pages site (served from /docs)
├── assets/           # Shared brand assets
├── docker-compose.yml  # Full local stack
├── start.sh / stop.sh  # One-command orchestration
└── .github/workflows/  # CI (pytest ×2 + vitest ×2 + Allure)
```

See **[docs/STRUCTURE.md](docs/STRUCTURE.md)** for the full layout and the test-directory conventions (`tests/`, `tests/integration/`, `tests/e2e/`).

## Quick start

> **Prerequisites:** Python 3.10+, Node 20, and Docker (for the Explorer's graph stack).

**1. Configure** — copy the gitignored templates and add your OpenAI key:

```bash
cp .env.example .env                                      # add OPENAI_API_KEY
cp apps/pipeline/config.example.json apps/pipeline/config.json
```

**2. Create a Python environment.** A single repo-root `.venv` works for both Python apps — `start.sh` uses it automatically when per-app venvs are absent:

```bash
python3 -m venv .venv
.venv/bin/pip install -r apps/pipeline/requirements-dev.txt
.venv/bin/pip install -r apps/explorer/requirements.txt
```

**3. Add your data** (none ships with this repo — the manifest only lists example graph names):

- Source documents → `apps/pipeline/compliance-files/`
- Knowledge-graph JSON → `apps/explorer/kgs/`
- Source document chunks → `apps/explorer/kbs/`
- Make sure `apps/explorer/conf/graphs.yaml` matches those files.

**4. Launch the full stack** and open the shell:

```bash
./start.sh           # Explorer DB stack + Pipeline API/UI + suite shell
open http://localhost:4000
```

Stop everything (and tear down Docker infra) with `./stop.sh --all`.

## Common workflows

| Goal | Command |
| --- | --- |
| Full suite | `./start.sh` |
| Pipeline only | `cd apps/pipeline && ./start.sh` |
| Explorer only | `cd apps/explorer && ./start.sh` |
| Extract one document | `cd apps/pipeline && .venv/bin/python cli/extract.py --file compliance-files/<batch>/<file>.pdf --provider openai` |
| Batch extraction | `cd apps/pipeline && .venv/bin/python cli/extract.py --batch --provider openai` |
| Compare two graphs | `cd apps/pipeline && .venv/bin/python cli/compare.py --g1 graphA --g2 graphB --workers 15` |
| Incremental graph load | `cd apps/explorer && .venv/bin/python -m src.main setup-if-empty` |

Pipeline parameters (LLM models, reasoning effort, chunk sizes, worker counts, temperatures) are editable from the **Settings** page in the UI and persisted to `apps/pipeline/config.json`.

## Key files

| File | Role |
| --- | --- |
| `apps/pipeline/config.json` | Pipeline models & runtime settings (gitignored; copy from `config.example.json`) |
| `apps/pipeline/domain-prompts/` | Per-domain prompt overrides (mortgage, aml, healthcare, commercial_lending) |
| `apps/explorer/conf/graphs.yaml` | Graph manifest & traversal-source names |
| `.env` | Shared local environment (incl. `OPENAI_API_KEY`); gitignored |
| `pipeline-output/`, `kgs/`, `kbs/` | Generated / user-supplied data; gitignored |

## Documentation

| Doc | Covers |
| --- | --- |
| [docs site](https://rrahimi-uci.github.io/policy-to-knowledge/) | Visual overview, architecture, walkthrough |
| [apps/shell/README.md](apps/shell/README.md) | Suite shell, micro-frontend embedding, routes |
| [apps/pipeline/README.md](apps/pipeline/README.md) | Extraction & compare pipeline, API/UI |
| [apps/explorer/README.md](apps/explorer/README.md) | Explorer runtime, manifest, graph loading |
| [apps/pipeline/docs/ARCHITECTURE.md](apps/pipeline/docs/ARCHITECTURE.md) | Pipeline architecture |
| [apps/pipeline/docs/DOCKER.md](apps/pipeline/docs/DOCKER.md) | Containerized workflows |
| [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) | Local setup & test expectations |

## Testing

Every suite emits [Allure](https://allurereport.org/) results and code coverage; CI runs all four on each push.

```bash
# Backend (pytest → coverage + allure-results/)
(cd apps/pipeline && .venv/bin/python -m pytest)
(cd apps/explorer && .venv/bin/python -m pytest)

# Frontend (vitest → coverage + allure-results/)
(cd apps/shell                && npm test -- --coverage)
(cd apps/pipeline/ui/frontend && npm test -- --coverage)
```

Combine all suites into one Allure report (requires the [Allure CLI](https://allurereport.org/docs/install/)):

```bash
mkdir -p /tmp/allure
cp apps/*/allure-results/* apps/pipeline/ui/frontend/allure-results/* /tmp/allure/ 2>/dev/null
allure serve /tmp/allure
```

Unit tests (`tests/`, co-located `*.test.tsx`) run in CI and cover the logic layer. Live-backend integration (`apps/explorer/tests/integration/`) and Playwright UI suites (`tests/e2e/`) require the corresponding services running — see the component READMEs.

## License

[MIT](LICENSE).
