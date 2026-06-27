"""Graphs router — list, view, export knowledge graphs."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from ..services import graph_service

router = APIRouter(prefix="/api/graphs", tags=["graphs"])


@router.get("")
def list_graphs(provider: str = None):
    """List all generated knowledge graphs."""
    return {"graphs": graph_service.list_graphs(provider)}


@router.get("/{name}")
def get_graph(name: str, provider: str = "openai"):
    """Get full knowledge graph data."""
    data = graph_service.get_graph_data(name, provider)
    if not data:
        raise HTTPException(404, f"Knowledge graph '{name}' not found")
    return data


@router.get("/{name}/visualization")
def get_visualization(name: str, provider: str = "openai", theme: str = "light"):
    """Serve the interactive HTML visualization themed to match the app."""
    html = graph_service.get_visualization_html(name, provider)
    if not html:
        raise HTTPException(404, "Visualization not found")
    html = graph_service.apply_theme(html, theme)
    return HTMLResponse(content=html)


@router.delete("/{name}")
def delete_graph(name: str, provider: str = "openai"):
    """Delete a knowledge graph and all its pipeline output files."""
    deleted = graph_service.delete_graph(name, provider)
    if not deleted:
        raise HTTPException(404, f"Knowledge graph '{name}' not found")
    return {"deleted": name}


@router.get("/{name}/export/{fmt}")
def export_graph(name: str, fmt: str, provider: str = "openai"):
    """Export knowledge graph as JSON or CSV."""
    if fmt == "json":
        data = graph_service.get_graph_data(name, provider)
        if not data:
            raise HTTPException(404, "Graph not found")
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f'attachment; filename="{name}_graph.json"'},
        )
    elif fmt == "csv":
        from pathlib import Path
        csv_path = graph_service._pipeline_output() / name / "agent-5-optimized" / "optimized-business_rules_export.csv"
        if not csv_path.exists():
            csv_path = graph_service._pipeline_output() / name / "agent-4-rules-with-entities" / "business_rules_complete.csv"
        if not csv_path.exists():
            raise HTTPException(404, "CSV export not found")
        from fastapi.responses import FileResponse
        return FileResponse(csv_path, media_type="text/csv", filename=f"{name}_rules.csv")
    else:
        raise HTTPException(400, f"Unsupported format: {fmt}")
