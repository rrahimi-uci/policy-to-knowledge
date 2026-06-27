"""
Impact Analysis router — Regulatory Change Impact Analysis endpoints.

Supports two modes:
  - mode=basic  → fast heuristic analysis (keyword matching, difflib)
  - mode=agentic → 5-step LLM-powered workflow with WebSocket progress
"""

import asyncio

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response

from ..services import impact_store, impact_service, impact_agentic
from ..ws.impact_ws import broadcast_impact

router = APIRouter(prefix="/api/impact", tags=["impact-analysis"])


@router.post("/analyze")
async def start_analysis(
    old_doc: UploadFile = File(...),
    new_doc: UploadFile = File(...),
    graph_name: str = Form(...),
    provider: str = Form("openai"),
    mode: str = Form("agentic"),
):
    """Upload old + new regulatory documents and run impact analysis.

    mode=basic  → fast heuristic engine (no LLM)
    mode=agentic → 5-step LLM workflow with WebSocket progress
    """
    old_bytes = await old_doc.read()
    new_bytes = await new_doc.read()

    old_text = _extract_text(old_bytes, old_doc.filename or "old.txt")
    new_text = _extract_text(new_bytes, new_doc.filename or "new.txt")

    if not old_text.strip():
        raise HTTPException(400, "Old document is empty or unreadable")
    if not new_text.strip():
        raise HTTPException(400, "New document is empty or unreadable")

    analysis = impact_store.create_analysis(
        graph_name=graph_name,
        provider=provider,
        old_doc_name=old_doc.filename or "old_document",
        new_doc_name=new_doc.filename or "new_document",
    )

    if mode == "agentic":
        # Return immediately with analysis_id; run in background with WS progress
        async def _run_bg():
            async def _progress(payload):
                await broadcast_impact(analysis["id"], payload)
            await impact_agentic.run_agentic_analysis(
                analysis_id=analysis["id"],
                old_text=old_text,
                new_text=new_text,
                graph_name=graph_name,
                provider=provider,
                progress_cb=_progress,
            )
        asyncio.create_task(_run_bg())
        return {"id": analysis["id"], "status": "running", "mode": "agentic",
                "message": "Agentic analysis started. Connect to WebSocket for progress."}
    else:
        # Synchronous basic analysis (original heuristic engine)
        result = impact_service.run_analysis(
            analysis_id=analysis["id"],
            old_text=old_text,
            new_text=new_text,
            graph_name=graph_name,
            provider=provider,
        )
        items = impact_store.get_impact_items(result["id"])
        return {**result, "items": items}


@router.get("/analyses")
def list_analyses(graph_name: str = None, limit: int = 50):
    """List all impact analyses, optionally filtered by graph."""
    return {"analyses": impact_store.list_analyses(graph_name, limit)}


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str):
    """Get full impact analysis with all change items."""
    analysis = impact_store.get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(404, f"Analysis '{analysis_id}' not found")
    items = impact_store.get_impact_items(analysis_id)
    return {**analysis, "items": items}


@router.delete("/analyses/{analysis_id}")
def delete_analysis(analysis_id: str):
    """Delete an impact analysis."""
    if not impact_store.delete_analysis(analysis_id):
        raise HTTPException(404, f"Analysis '{analysis_id}' not found")
    return {"deleted": analysis_id}


@router.get("/analyses/{analysis_id}/export/{fmt}")
def export_analysis(analysis_id: str, fmt: str):
    """Export impact analysis as JSON or CSV."""
    if fmt not in ("json", "csv"):
        raise HTTPException(400, f"Unsupported format: {fmt}")

    result = impact_service.export_analysis(analysis_id, fmt)
    if result is None:
        raise HTTPException(404, "Analysis not found")

    if fmt == "json":
        return JSONResponse(
            content=result,
            headers={
                "Content-Disposition": f'attachment; filename="impact_{analysis_id}.json"'
            },
        )
    else:
        return Response(
            content=result,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="impact_{analysis_id}.csv"'
            },
        )


def _extract_text(raw_bytes: bytes, filename: str) -> str:
    """Extract text from uploaded file (plain text or PDF)."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            import PyPDF2
            import io
            reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
            pages = [p.extract_text() or "" for p in reader.pages]
            return "\n\n".join(pages)
        except Exception as exc:
            raise HTTPException(400, f"Failed to parse PDF: {exc}")
    # Reject binary office formats outright — a latin-1 fallback would happily
    # decode them into garbage and feed it to the LLM, wasting tokens.
    if lower.endswith((".docx", ".doc", ".xlsx", ".xls", ".pptx", ".zip")):
        raise HTTPException(
            400,
            f"Unsupported file type for '{filename}'. Provide a .pdf, .txt, or .md file.",
        )
    # Treat everything else as UTF-8 text; reject anything that looks binary.
    if b"\x00" in raw_bytes[:8192]:
        raise HTTPException(
            400, f"'{filename}' appears to be binary, not text. Provide a .pdf, .txt, or .md file."
        )
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1")
