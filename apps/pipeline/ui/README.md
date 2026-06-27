# Pipeline UI

`pipeline/ui/` contains the FastAPI backend and React frontend that sit on top
of the extraction pipeline.

## Start

From `pipeline/`:

```bash
./start.sh
```

Or use the wrapper in this directory:

```bash
./ui/start.sh
```

This starts:

- backend at `http://localhost:8000`
- frontend at `http://localhost:5173`

## Manual Development

Backend:

```bash
cd pipeline
.venv/bin/uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd pipeline/ui/frontend
npm install
npm run dev
```

## Tests

```bash
cd pipeline/ui/frontend
npm test
npm run build
npm run test:e2e
```

The frontend build and Vitest checks run in the root CI workflow at
`.github/workflows/ci.yml`.

## Structure

| Path | Purpose |
| --- | --- |
| `backend/routers/` | REST endpoints |
| `backend/ws/` | WebSocket handlers |
| `backend/services/` | run storage and orchestration helpers |
| `frontend/src/` | React application |
| `frontend/tests/e2e/` | Playwright tests |
