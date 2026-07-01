# Repository Layout

A map of the monorepo, what each part does, and the conventions used.

```
policy-to-knowledge/
├── apps/
│   ├── pipeline/            FastAPI + 10-agent LLM extraction pipeline (+ React UI)
│   │   ├── cli/             Command-line entry points
│   │   │   ├── extract.py   Agents 1-6: document → knowledge graph
│   │   │   └── compare.py   Agents 7-10: compare / merge two graphs (set operations)
│   │   ├── agents/          Agent implementations (agent_1 … agent_10)
│   │   │   └── experimental/  Non-pipeline prototypes (not imported by the pipeline)
│   │   ├── utils/           Config + shared helpers
│   │   ├── prompts/         Base prompt templates
│   │   ├── domain-prompts/  Per-domain prompt overrides (mortgage, aml, healthcare, …)
│   │   ├── ui/
│   │   │   ├── backend/     FastAPI app (routers/, services/, ws/)
│   │   │   └── frontend/    React + Vite UI (unit tests co-located; e2e in tests/e2e/)
│   │   ├── tests/           Unit tests (pytest) — run in CI
│   │   ├── Dockerfile.cli   CLI / batch image (ENTRYPOINT cli/extract.py)
│   │   └── Dockerfile.api   API + UI image
│   │
│   ├── explorer/            Flask + JanusGraph graph explorer (vanilla-JS/D3 UI)
│   │   ├── src/             Server + graph/data/cache/search modules
│   │   ├── conf/            Generated JanusGraph configs (from scripts/generate_graph_config.py)
│   │   ├── ui/              Static front-end (css/, js/)
│   │   └── tests/
│   │       ├── (unit)       *.py unit tests (pytest) — run in CI
│   │       ├── integration/ Backend API tests against a live stack (pytest, not in CI)
│   │       └── e2e/         Playwright UI tests against a live server (not in CI)
│   │
│   └── shell/               React/Vite suite shell that embeds the app UIs
│       ├── src/             Components, hooks, bridge (unit tests co-located *.test.tsx)
│       └── tests/e2e/       Playwright UI tests
│
├── docs/                   GitHub Pages site (index.html, architecture.html, this file)
├── assets/                 Shared brand assets (logo)
│
├── docker-compose.yml      Full local stack (explorer DB + all app services)
├── deploy-config.yaml      Deployment configuration
├── start.sh / stop.sh      Bring the whole local stack up / down
├── README.md
└── LICENSE
```

## Test conventions

The unifying rule: **browser / live-service end-to-end tests live in `tests/e2e/`**.

| Kind | Python apps (pipeline, explorer) | Frontends (shell, pipeline UI) |
| --- | --- | --- |
| Unit | `tests/` (pytest) — **runs in CI** | co-located `*.test.ts(x)` (Vitest) — **runs in CI** |
| Integration (live services) | `tests/integration/` (pytest) | — |
| End-to-end UI (live server) | `tests/e2e/` (Playwright) | `tests/e2e/` (Playwright) |

CI runs only the unit layer. Integration and e2e need a running stack and are invoked
explicitly (see each suite's README). The explorer's `pytest.ini` therefore ignores
`tests/integration` and `tests/e2e` so `pytest tests/` stays unit-only.

Frontend unit tests are intentionally **co-located** next to the source they cover
(idiomatic Vitest/React Testing Library); they are not moved into a `tests/` folder.

## Docker images

- Per-app `docker-compose.yml` files build/run a single app for local iteration.
- The **root** `docker-compose.yml` brings up the full stack (explorer's
  JanusGraph/Cassandra/OpenSearch/Redis plus the app services).
- Pipeline ships two images: `Dockerfile.cli` (batch extraction, entry `cli/extract.py`)
  and `Dockerfile.api` (the FastAPI API + built React UI).
