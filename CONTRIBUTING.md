# Contributing to Policy to Knowledge

This repo is a three-app monorepo. Most changes land in one of these areas:

| Path | App | Stack |
| --- | --- | --- |
| `frontend/` | Suite shell | React 19, Vite, TypeScript |
| `pipeline/` | Extraction pipeline and pipeline UI/API | Python, FastAPI, React |
| `assistant/` | Explorer | Python, Flask, vanilla JS |

## Local Setup

The launchers expect per-app Python virtualenvs:

```bash
python3 -m venv pipeline/.venv
pipeline/.venv/bin/pip install -r pipeline/requirements-dev.txt

python3 -m venv assistant/.venv
assistant/.venv/bin/pip install -r assistant/requirements.txt
assistant/.venv/bin/pip install -r assistant/requirements-test.txt
```

Install frontend dependencies:

```bash
(cd frontend && npm install)
(cd pipeline/ui/frontend && npm install)
```

Copy local config files:

```bash
cp .env.example .env
cp pipeline/config.example.json pipeline/config.json
```

## Running Tests

```bash
(cd pipeline && .venv/bin/python -m pytest tests/ -q)
(cd assistant && .venv/bin/python -m pytest tests/ -q)
(cd frontend && npm test)
(cd pipeline/ui/frontend && npm test)
```

Before opening a PR, also run the relevant frontend build:

```bash
(cd frontend && npm run build)
(cd pipeline/ui/frontend && npm run build)
```

Live suites in `assistant/e2etests`, `assistant/uitests`, and
`pipeline/ui/frontend/tests/e2e` require the corresponding services running.

## Pull Requests

1. Branch from `main`.
2. Keep changes focused.
3. Update tests when behavior changes.
4. Describe what changed and how you tested it.

## Ground Rules

- Do not commit real data or secrets.
- `assistant/kbs/`, `assistant/kgs/`, `pipeline/compliance-files/`, and `pipeline-output/` are local-data paths.
- `.env` and `pipeline/config.json` are local-only.
- See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for collaboration expectations.
- See [SECURITY.md](SECURITY.md) for private vulnerability reporting.
