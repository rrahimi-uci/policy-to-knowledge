"""
Policy to Knowledge — FastAPI Backend

Wraps the existing CLI-based knowledge graph pipeline with a REST + WebSocket API.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import documents, pipeline, graphs, compare, runs, settings, prompts
from .routers import impact_analysis, obligations, publish
from .services import run_store, pipeline_runner, impact_store, obligation_store
from .ws.pipeline_ws import ws_pipeline
from .ws.impact_ws import ws_impact


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_store.init_db()
    impact_store.init_tables()
    obligation_store.init_tables()

    # Reconcile any runs that were 'running' when the server last stopped.
    # Dead-PID runs are immediately marked 'interrupted'; alive-PID runs get
    # an orphan monitor coroutine so they complete normally.
    alive = run_store.reconcile_stale_runs()
    for entry in alive:
        await pipeline_runner.attach_orphan(
            entry["run_id"], entry["pid"], entry.get("log_file")
        )

    yield


app = FastAPI(
    title="Policy to Knowledge",
    description="Knowledge Graph Extraction Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for local React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:4000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routers
app.include_router(documents.router)
app.include_router(pipeline.router)
app.include_router(graphs.router)
app.include_router(compare.router)
app.include_router(runs.router)
app.include_router(settings.router)
app.include_router(prompts.router)
app.include_router(impact_analysis.router)
app.include_router(obligations.router)
app.include_router(publish.router)

# WebSocket
app.websocket("/ws/pipeline/{run_id}")(ws_pipeline)
app.websocket("/ws/impact/{analysis_id}")(ws_impact)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "p2k"}


# Serve React SPA in production (if built)
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="spa")
