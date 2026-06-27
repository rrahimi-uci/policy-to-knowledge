# Contributing to Policy to Knowledge

Thanks for your interest in contributing! This repo is a monorepo with three
applications. Most changes touch one of them:

| Path | App | Stack |
|---|---|---|
| `frontend/` | Suite Shell | React 19 + Vite + TypeScript |
| `pipeline/` | Pipeline (extraction) | Python (FastAPI) + React UI under `pipeline/ui/` |
| `assistant/` | Explorer / Assistant | Python (Flask) + vanilla-JS UI |

## Getting set up

```bash
# Python apps (use a virtualenv)
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements-dev.txt        # pipeline + tests
pip install -r assistant/requirements-test.txt      # explorer offline tests

# Frontends
cd frontend && npm install
cd pipeline/ui/frontend && npm install
```

Copy the example configs and fill in your own keys (never commit real secrets):

```bash
cp .env.example .env
cp pipeline/config.example.json pipeline/config.json   # optional; falls back to the example
```

## Running the test suites

```bash
# Pipeline (Python)
cd pipeline && python -m pytest

# Explorer offline unit tests (Python)
cd assistant && python -m pytest tests/

# Frontends (Vitest)
cd frontend && npm test
cd pipeline/ui/frontend && npm test
```

End-to-end suites (`assistant/e2etests`, `*/tests/e2e` Playwright) require the
live services running and are not part of CI.

## Pull requests

1. Fork and branch from `main` (`git checkout -b feat/my-change`).
2. Keep changes focused; match the surrounding code style.
3. Add or update tests for behavior changes.
4. Make sure the relevant suites above pass, plus `npm run build` for frontends.
5. Open a PR using the template and describe the change and how you tested it.

## Ground rules

- **No real data or secrets.** The `kbs/`, `kgs/`, `compliance-files/`, and
  `pipeline-output/` directories are gitignored placeholders — supply your own
  data locally. `.env` and `config.json` are gitignored; never commit keys.
- Be respectful — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Report security issues privately — see [SECURITY.md](SECURITY.md).
