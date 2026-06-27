"""Publish router — tracked publish-to-graph-db with real-time step updates."""

import asyncio
import io
import os
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import run_store
from ..ws.pipeline_ws import broadcast

router = APIRouter(prefix="/api/publish", tags=["publish"])

PUBLISH_STEPS = ["P1", "P2", "P3", "P4", "P5", "P6"]

# Base URL for assistant (Flask API) including its URL_PREFIX.
#   docker-compose: http://assistant:5000/app
#   Azure ACA:      http://assistant/app   (port 80 → targetPort)
CA_BASE = os.environ.get("CA_BASE", "http://assistant:5000/app").rstrip("/")

# Base URL this service exposes to assistant for step callbacks.
#   docker-compose: http://kg-backend:8000
#   Azure ACA:      http://kg-backend
KG_BACKEND_BASE = os.environ.get("KG_BACKEND_BASE", "http://kg-backend:8000").rstrip("/")

# Where pipeline-output lives. In Docker/ACA the kg-backend image mounts it
# at /app/pipeline-output. In local dev (uvicorn run from the repo) it's at
# <repo>/pipeline/pipeline-output. Honor PIPELINE_OUTPUT_DIR if set,
# otherwise prefer /app/pipeline-output when present and fall back to the
# repo-relative path so local publishes work without env tweaks.
def _resolve_pipeline_output_dir() -> Path:
    env_val = os.environ.get("PIPELINE_OUTPUT_DIR")
    if env_val:
        return Path(env_val)
    container_path = Path("/app/pipeline-output")
    if container_path.exists():
        return container_path
    # publish.py -> routers -> backend -> ui -> pipeline
    return Path(__file__).resolve().parents[3] / "pipeline-output"


PIPELINE_OUTPUT_DIR = _resolve_pipeline_output_dir()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublishRequest(BaseModel):
    source_name: str
    provider: str = "openai"
    display_name: Optional[str] = None


class StepCallback(BaseModel):
    step: str
    status: str
    detail: Optional[str] = None


@router.post("/start")
async def start_publish(body: PublishRequest):
    """Create a tracked publish run and launch the publish in the background."""
    run_id = str(uuid.uuid4())

    run_store.create_run(
        run_id,
        run_type="publish",
        domain=body.source_name,
        provider=body.provider,
        config={"source_name": body.source_name, "display_name": body.display_name},
    )

    # Pre-insert all steps as pending
    for step_id in PUBLISH_STEPS:
        run_store.upsert_step(run_id, step_id, "pending")

    run_store.add_log(run_id, f"Publishing '{body.source_name}' to Graph DB", "INFO")

    # Launch background task
    asyncio.create_task(
        _run_publish(run_id, body.source_name, body.provider, body.display_name)
    )

    return {"run_id": run_id, "status": "running"}


@router.post("/{run_id}/step")
async def receive_step_callback(run_id: str, body: StepCallback):
    """Receive step status updates from assistant during publish."""
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    run_store.upsert_step(run_id, body.step, body.status, body.detail)
    if body.detail:
        level = "ERROR" if body.status == "failed" else "INFO"
        run_store.add_log(run_id, body.detail, level)

    await broadcast(run_id, {
        "type": "step",
        "step": body.step,
        "status": body.status,
        "detail": body.detail,
    })

    return {"ok": True}


async def _run_publish(
    run_id: str,
    source_name: str,
    provider: str,
    display_name: Optional[str],
    max_retries: int = 5,
    initial_delay: float = 3.0,
):
    """Background task: call assistant publish with callback_url.

    Retries on connection errors (e.g. assistant still booting)
    with exponential back-off up to *max_retries* attempts.
    """
    callback_url = f"{KG_BACKEND_BASE}/api/publish/{run_id}/step"

    try:
        # Locate local artifacts on this (kg-backend) container so we can
        # upload them — assistant doesn't share the pipeline-output
        # filesystem in Azure Container Apps.
        base = PIPELINE_OUTPUT_DIR / provider / source_name
        kg_path = base / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
        if not kg_path.exists():
            kg_path = base / "agent-4-rules-with-entities" / "compliance_knowledge_graph.json"
        if not kg_path.exists():
            raise FileNotFoundError(
                f"No KG file found for '{source_name}' (provider={provider}) under {base}"
            )

        docs_dir = base / "agent-1-organized-documents"
        docs_archive_bytes: Optional[bytes] = None
        if docs_dir.is_dir():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                # Add directory contents at the archive root so extracting
                # into agent-1-organized-documents/ produces the same tree.
                for entry in sorted(docs_dir.rglob("*")):
                    tf.add(entry, arcname=str(entry.relative_to(docs_dir)))
            docs_archive_bytes = buf.getvalue()
            run_store.add_log(
                run_id,
                f"Prepared docs archive ({len(docs_archive_bytes)} bytes) for upload",
                "INFO",
            )
        else:
            run_store.add_log(
                run_id,
                f"No organized documents found at {docs_dir} — references will not be linkable",
                "WARN",
            )

        kg_bytes = kg_path.read_bytes()

        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            data_fields = {
                "source_name": source_name,
                "provider": provider,
                "callback_url": callback_url,
            }
            if display_name:
                data_fields["display_name"] = display_name

            files = {
                "kg_file": ("kg.json", kg_bytes, "application/json"),
            }
            if docs_archive_bytes is not None:
                files["docs_archive"] = (
                    "docs.tar.gz",
                    docs_archive_bytes,
                    "application/gzip",
                )

            resp = None
            for attempt in range(1, max_retries + 1):
                try:
                    resp = await client.post(
                        f"{CA_BASE}/api/graph/publish",
                        data=data_fields,
                        files=files,
                    )
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as conn_err:
                    if attempt == max_retries:
                        raise conn_err
                    delay = initial_delay * (2 ** (attempt - 1))
                    run_store.add_log(
                        run_id,
                        f"assistant not reachable (attempt {attempt}/{max_retries}), retrying in {delay:.0f}s",
                        "WARN",
                    )
                    await asyncio.sleep(delay)

            if resp is None:
                # max_retries < 1 (or every attempt was skipped) — no request was made.
                raise RuntimeError(
                    f"publish made no request to the assistant (max_retries={max_retries})"
                )
            raw_body = resp.text.strip()
            try:
                data = resp.json() if raw_body else {}
            except ValueError:
                data = {}

            if resp.status_code == 409:
                # Already published — mark all steps skipped
                for step_id in PUBLISH_STEPS:
                    run_store.upsert_step(run_id, step_id, "skipped", "Already published")
                run_store.update_run(
                    run_id,
                    status="completed",
                    result=data,
                    finished_at=_now(),
                )
                run_store.add_log(run_id, "Graph is already published", "INFO")
                await broadcast(run_id, {"type": "status", "status": "completed"})
                return

            if resp.status_code >= 400:
                error_msg = data.get("error") or raw_body or f"Publish failed with status {resp.status_code}"
                run_store.update_run(
                    run_id,
                    status="failed",
                    error=error_msg,
                    finished_at=_now(),
                )
                run_store.add_log(run_id, error_msg, "ERROR")
                await broadcast(run_id, {"type": "status", "status": "failed", "error": error_msg})
                return

            if not data:
                raise ValueError(
                    f"assistant returned an empty or non-JSON success response (status {resp.status_code})"
                )

            # Success
            status_val = "completed"
            if data.get("status") == "partial":
                status_val = "completed_with_warnings"
                run_store.add_log(
                    run_id,
                    data.get("warning", "Completed with warnings"),
                    "WARN",
                )

            run_store.update_run(
                run_id,
                status=status_val,
                result=data,
                finished_at=_now(),
            )
            summary = (
                f"Published '{data.get('display_name', source_name)}' — "
                f"{data.get('rules', 0)} rules, {data.get('entities', 0)} entities"
            )
            run_store.add_log(run_id, summary, "INFO")
            await broadcast(run_id, {"type": "status", "status": "completed"})

    except Exception as exc:
        error_msg = f"Publish failed: {exc}"
        run_store.update_run(
            run_id,
            status="failed",
            error=error_msg,
            finished_at=_now(),
        )
        run_store.add_log(run_id, error_msg, "ERROR")
        # Mark any remaining running/pending steps as failed
        steps = run_store.get_steps(run_id)
        for s in steps:
            if s["status"] in ("pending", "running"):
                run_store.upsert_step(run_id, s["step"], "failed")
        await broadcast(run_id, {"type": "status", "status": "failed", "error": error_msg})
