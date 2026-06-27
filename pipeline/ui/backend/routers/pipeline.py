"""Pipeline router — start, status, cancel pipeline runs."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from ..services import pipeline_runner, run_store
from ..ws.pipeline_ws import broadcast

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class StartRequest(BaseModel):
    provider: str = "openai"
    domain: str = "mortgage"
    folder: Optional[str] = None
    documents: List[str] = []
    target_rules: Optional[int] = None
    workers: Optional[int] = None
    skip_optimize: bool = False
    step: Optional[int] = None
    batch_name: Optional[str] = None


@router.get("/running")
def running_pipelines():
    """Return all currently running pipeline runs."""
    runs = run_store.list_running_runs()
    return {"runs": runs}


@router.get("/history")
def pipeline_history(run_type: Optional[str] = None, limit: int = 50):
    """Return recent pipeline runs (any status) for restart-from-history UI."""
    runs = run_store.list_runs(run_type=run_type, limit=limit)
    return {"runs": runs}


@router.post("/start")
async def start_pipeline(req: StartRequest):
    """Start an extraction pipeline run."""
    try:
        run_id = await pipeline_runner.start_extraction(
            provider=req.provider,
            domain=req.domain,
            folder=req.folder,
            documents=req.documents,
            target_rules=req.target_rules,
            workers=req.workers,
            skip_optimize=req.skip_optimize,
            step=req.step,
            batch_name=req.batch_name,
            ws_callback=broadcast,
        )
    except pipeline_runner.ConcurrentRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"run_id": run_id, "status": "running"}


@router.get("/{run_id}/status")
def pipeline_status(run_id: str):
    """Get current status and steps for a pipeline run."""
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    steps = run_store.get_steps(run_id)
    return {"run": run, "steps": steps}


@router.get("/{run_id}/logs")
def pipeline_logs(run_id: str, after_id: int = 0):
    """Get log entries for a run (supports polling via after_id)."""
    logs = run_store.get_logs(run_id, after_id=after_id)
    return {"logs": logs}


@router.delete("/{run_id}")
async def cancel_pipeline(run_id: str):
    """Cancel a running pipeline."""
    ok = await pipeline_runner.cancel_run(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or already finished")
    return {"status": "cancelled"}
