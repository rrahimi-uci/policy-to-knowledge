"""Runs router — list and inspect pipeline run history."""

from fastapi import APIRouter, HTTPException

from ..services import run_store

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(run_type: str = None, limit: int = 50):
    """List pipeline runs with optional type filter."""
    runs = run_store.list_runs(run_type=run_type, limit=limit)
    return {"runs": runs}


@router.get("/{run_id}")
def get_run(run_id: str):
    """Get detailed info for a specific run."""
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    steps = run_store.get_steps(run_id)
    logs = run_store.get_logs(run_id, limit=500)
    return {"run": run, "steps": steps, "logs": logs}


@router.delete("/{run_id}")
def delete_run(run_id: str):
    """Delete a specific run and its associated data."""
    if not run_store.delete_run(run_id):
        raise HTTPException(404, "Run not found")
    return {"ok": True}


@router.delete("")
def delete_all_runs():
    """Delete all runs."""
    count = run_store.delete_all_runs()
    return {"ok": True, "deleted": count}
