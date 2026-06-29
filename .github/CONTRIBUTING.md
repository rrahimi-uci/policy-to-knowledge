# Contributing to Policy to Knowledge

Thanks for your interest in improving **Policy to Knowledge**. This document
covers how the repository is laid out, how to set up a local environment, and
how to run the test suites before opening a pull request.

This is a three-app monorepo. Most changes land in one of these areas:

| Path | App | Stack |
| --- | --- | --- |
| `apps/shell/` | Shell | React 19, Vite, TypeScript (`:4000`) |
| `apps/pipeline/` | Pipeline | FastAPI API (`:8000`) + React UI (`:5173`) + extraction agents |
| `apps/explorer/` | Explorer | Flask + JanusGraph, served under `/app` (`:5000`) |

## Local setup

### Python apps

The apps run in Python virtual environments. You can create a per-app `.venv`
(as shown below) or a single shared `.venv` at the repository root:

```bash
# Pipeline
python3 -m venv apps/pipeline/.venv
apps/pipeline/.venv/bin/pip install -r apps/pipeline/requirements-dev.txt

# Explorer
python3 -m venv apps/explorer/.venv
apps/explorer/.venv/bin/pip install -r apps/explorer/requirements.txt
apps/explorer/.venv/bin/pip install -r apps/explorer/requirements-test.txt
```

### Frontends

```bash
(cd apps/shell && npm install)
(cd apps/pipeline/ui/frontend && npm install)
```

### Configuration

```bash
cp .env.example .env
cp apps/pipeline/config.example.json apps/pipeline/config.json
```

The pipeline uses the OpenAI API. Set `OPENAI_API_KEY` in your `.env` file
before running extraction or comparison.

## Running the stack

Bring up all services together, then stop them when you are done:

```bash
./start.sh   # start shell, pipeline (API + UI), and explorer
./stop.sh    # stop all services
```

The pipeline also exposes command-line entry points:

```bash
python apps/pipeline/cli/extract.py   # extract a knowledge graph from documents
python apps/pipeline/cli/compare.py   # compare two knowledge graphs
```

## Running tests

### Python unit tests

Unit tests live in each app's `tests/` directory and run under `pytest` in CI:

```bash
(cd apps/pipeline && .venv/bin/python -m pytest tests/ -q)
(cd apps/explorer && .venv/bin/python -m pytest tests/ -q)
```

The Explorer additionally ships integration and end-to-end suites that require
the corresponding services to be running:

- `apps/explorer/tests/integration/` — integration tests against a live stack.
- `apps/explorer/tests/e2e/` — Playwright end-to-end tests.

### Frontend tests

Unit tests are co-located with the components and run under Vitest; Playwright
end-to-end specs live in each frontend's `tests/e2e/` directory:

```bash
(cd apps/shell && npm test)
(cd apps/pipeline/ui/frontend && npm test)
```

Before opening a PR, build any frontend you changed:

```bash
(cd apps/shell && npm run build)
(cd apps/pipeline/ui/frontend && npm run build)
```

CI runs `pytest` for both Python apps, Vitest for both frontends, and publishes
a merged Allure report.

## Pull requests

1. Branch from `main`.
2. Keep changes focused and reasonably small.
3. Update or add tests when behavior changes.
4. Describe what changed and how you tested it.

## Ground rules

- Never commit secrets or real data. `.env` files and
  `apps/pipeline/config.json` are gitignored and local-only.
- Local-data paths are not committed: `apps/explorer/kbs/`,
  `apps/explorer/kgs/`, `apps/pipeline/compliance-files/`, and
  `pipeline-output/`.
- See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for collaboration expectations.
- See [SECURITY.md](SECURITY.md) for private vulnerability reporting.
