# Explorer — Playwright UI Tests

End-to-end browser tests for the Explorer UI, driven by Playwright. This package has
its own `package.json` and `playwright.config.ts`.

> This directory was previously named `uitests/`. It is now `tests/e2e/`.

## Prerequisites

- A running Explorer server (Flask) reachable under the `/app` prefix
- The Docker data stack running (`docker compose up -d` from `apps/explorer`)
- At least one loaded graph with data

The test base URL comes from the `BASE_URL` environment variable and defaults to
`http://localhost:5001/app` (see `playwright.config.ts`). Start the server on the
matching port first:

```bash
# from apps/explorer
docker compose up -d
SERVER_PORT=5050 URL_PREFIX=/app .venv/bin/python -m src.server
```

## Running

```bash
# from apps/explorer/tests/e2e
npm install
npx playwright install chromium

# Run the full suite against the server
BASE_URL=http://localhost:5050/app npx playwright test

# A single spec
BASE_URL=http://localhost:5050/app npx playwright test 01-graph-discovery.spec.ts

# Headed / debug
BASE_URL=http://localhost:5050/app npx playwright test --headed
BASE_URL=http://localhost:5050/app npx playwright test --debug
```

Tests run sequentially with a single worker because they share server state.

## Coverage

The specs in this directory exercise:

- graph discovery and search
- low-confidence review and approval toggles
- node creation and deletion
- edge detail inspection
- task-box flows
- AI rewrite and rule-ID suggestion helpers
- URL-prefix and URL-access behavior
- complex multi-step workflows and loaded-graph data checks
