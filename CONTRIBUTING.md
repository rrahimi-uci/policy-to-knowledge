# Contributing to Policy to Knowledge

This repo is a three-app monorepo. Most changes land in one of these areas:

| Path | App | Stack |
| --- | --- | --- |
| `apps/shell/` | Suite shell | React 19, Vite, TypeScript |
| `apps/pipeline/` | Extraction pipeline and pipeline UI/API | Python, FastAPI, React |
| `apps/explorer/` | Explorer | Python, Flask, vanilla JS |

## Local Setup

The launchers expect per-app Python virtualenvs:

```bash
python3 -m venv apps/pipeline/.venv
apps/pipeline/.venv/bin/pip install -r apps/pipeline/requirements-dev.txt

python3 -m venv apps/explorer/.venv
apps/explorer/.venv/bin/pip install -r apps/explorer/requirements.txt
apps/explorer/.venv/bin/pip install -r apps/explorer/requirements-test.txt
```

Install frontend dependencies:

```bash
(cd frontend && npm install)
(cd apps/pipeline/ui/frontend && npm install)
```

Copy local config files:

```bash
cp .env.example .env
cp apps/pipeline/config.example.json apps/pipeline/config.json
```

## Running Tests

```bash
(cd pipeline && .venv/bin/python -m pytest tests/ -q)
(cd assistant && .venv/bin/python -m pytest tests/ -q)
(cd frontend && npm test)
(cd apps/pipeline/ui/frontend && npm test)
```

Before opening a PR, also run the relevant frontend build:

```bash
(cd frontend && npm run build)
(cd apps/pipeline/ui/frontend && npm run build)
```

Live suites in `apps/explorer/e2etests`, `apps/explorer/uitests`, and
`apps/pipeline/ui/apps/shell/tests/e2e` require the corresponding services running.

## Pull Requests

1. Branch from `main`.
2. Keep changes focused.
3. Update tests when behavior changes.
4. Describe what changed and how you tested it.

## Ground Rules

- Do not commit real data or secrets.
- `apps/explorer/kbs/`, `apps/explorer/kgs/`, `apps/pipeline/compliance-files/`, and `pipeline-output/` are local-data paths.
- `.env` and `apps/pipeline/config.json` are local-only.
- See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for collaboration expectations.
- See [SECURITY.md](SECURITY.md) for private vulnerability reporting.
