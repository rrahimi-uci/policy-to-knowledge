"""Compare router — launch and view graph comparisons."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from ..services import pipeline_runner, graph_service
from ..ws.pipeline_ws import broadcast

router = APIRouter(prefix="/api/compare", tags=["compare"])


class CompareRequest(BaseModel):
    g1: str
    g2: str
    provider: str = "openai"
    workers: Optional[int] = None
    batch_size: Optional[int] = None


@router.post("")
async def start_comparison(req: CompareRequest):
    """Launch a graph comparison pipeline."""
    run_id = await pipeline_runner.start_comparison(
        g1=req.g1,
        g2=req.g2,
        provider=req.provider,
        workers=req.workers,
        batch_size=req.batch_size,
        ws_callback=broadcast,
    )
    return {"run_id": run_id, "status": "running"}


@router.get("")
def list_comparisons(provider: str = "openai"):
    """List completed graph comparisons."""
    return {"comparisons": graph_service.list_comparisons(provider)}


@router.get("/{name}/data")
def get_comparison_data(name: str, provider: str = "openai"):
    """Get set operation results for a comparison."""
    try:
        data = graph_service.get_comparison_data(name, provider)
    except graph_service.UnsafeNameError:
        raise HTTPException(400, "Invalid comparison name")
    if not data:
        raise HTTPException(404, "Comparison not found")
    return data


@router.get("/{name}/visualization/{operation}")
def get_comparison_viz(name: str, operation: str, provider: str = "openai", theme: str = "light"):
    """Get HTML visualization for a specific set operation, themed."""
    try:
        html = graph_service.get_comparison_html(name, operation, provider)
    except graph_service.UnsafeNameError:
        raise HTTPException(400, "Invalid comparison name")
    if not html:
        raise HTTPException(404, "Visualization not found")
    html = graph_service.apply_theme(html, theme)
    return HTMLResponse(content=html)
