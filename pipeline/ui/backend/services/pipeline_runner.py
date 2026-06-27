"""
Pipeline Runner — launches the extraction / join pipelines as subprocesses
and streams output to the WebSocket + run_store.

Key design decisions
────────────────────
* subprocess.Popen (NOT asyncio.create_subprocess_exec) — asyncio subprocess
  transports are tied to the event loop.  When uvicorn --reload restarts the
  worker the event loop closes and asyncio terminates every subprocess it
  owns.  Popen processes are invisible to the event loop and survive restarts.

* stdout → log file (NOT PIPE) — a PIPE read-end lives in the parent process.
  When the parent dies the write-end in the child gets SIGPIPE and the child
  crashes.  Writing to a plain file has no such dependency.

* start_new_session=True — puts the child in its own session so it is not
  affected by SIGHUP or terminal closure.

* PID + log-file path persisted to SQLite immediately after fork so that a
  new server instance can reconnect to an in-flight run via _monitor_orphan.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import run_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # policy-to-knowledge/
_LOG_DIR = PROJECT_ROOT / "pipeline-logs"

# In-flight Popen objects keyed by run_id (in-memory only, rebuilt on restart)
_active: Dict[str, subprocess.Popen] = {}

STEP_LABELS = {
    "1":   "Document Segmentation & Organization",
    "2":   "Domain Entity & Relationship Discovery",
    "3":   "Business Rules Extraction",
    "3.5": "Rule Quality Validation",
    "4":   "Rules & Entity Integration",
    "5":   "Knowledge Graph Deduplication & Optimization",
    "6":   "Graph Visualization & Export",
}

# join_graphs.py prints "STEP 1/4", "STEP 2/4", … but pipeline_runner
# tracks them as steps 7-10.  Map step-id → join-script label.
_JOIN_STEP_LABEL = {"7": "1/4", "8": "2/4", "9": "3/4", "10": "4/4"}

# Track run_ids that were explicitly cancelled so _run_process won't overwrite
_cancelled: set = set()

# Accumulated LLM costs per run_id
_run_costs: Dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConcurrentRunError(RuntimeError):
    """Raised when an extraction run targets a (provider, batch_name) that
    already has an in-flight run.  Two parallel runs writing to the same
    pipeline-output/<provider>/<batch_name>/ tree race each other and
    produce corrupt or partially-deleted intermediate artifacts."""


def _conflicting_running_run(provider: str, batch_name: Optional[str]) -> Optional[dict]:
    """Return the existing running extraction run that targets the same
    (provider, batch_name), or None if no conflict exists.

    Comparison is done on the normalized batch_name so callers can't bypass
    by changing case or whitespace.
    """
    if not batch_name:
        return None
    target = batch_name.strip().lower()
    if not target:
        return None
    for run in run_store.list_running_runs():
        if run.get("run_type") != "extraction":
            continue
        if (run.get("provider") or "").lower() != provider.lower():
            continue
        cfg = run.get("config") or {}
        existing = (cfg.get("batch_name") or cfg.get("folder") or "").strip().lower()
        if existing and existing == target:
            return run
    return None


# ── Public API ──────────────────────────────────────────────────────────────

async def start_extraction(
    *,
    provider: str = "openai",
    domain: str = "mortgage",
    folder: str = None,
    documents: List[str] = None,
    target_rules: int = None,
    workers: int = None,
    skip_optimize: bool = False,
    step: int = None,
    batch_name: str = None,
    ws_callback=None,
) -> str:
    """Launch the extraction pipeline and return a run_id."""
    documents = documents or []

    resolved_folder = folder
    resolved_documents = documents
    source_mode = "folder" if folder else "documents"

    # When specific documents are selected we must NOT collapse to folder
    # batch mode — that would process every file in the folder.  Only
    # collapse when the caller did *not* send individual documents.
    # The folder field is set by the frontend for "batch" (whole-folder) mode.

    run_id = uuid.uuid4().hex[:12]

    # Determine the batch_name for output directory naming.
    # When processing specific files, derive batch_name from their parent
    # folder so the output lands in the same place as a full-folder run.
    effective_batch_name = batch_name
    if not effective_batch_name and resolved_folder:
        effective_batch_name = resolved_folder
    elif not effective_batch_name and resolved_documents:
        parent_folders = {
            str(Path(doc).parent).replace("\\", "/")
            for doc in resolved_documents
            if str(Path(doc).parent) not in {"", "."}
        }
        if len(parent_folders) == 1:
            effective_batch_name = parent_folders.pop()

    # ── Concurrency guard ────────────────────────────────────────────────
    # Two extraction runs targeting the same (provider, batch_name) write
    # to the same pipeline-output/<provider>/<batch_name>/ tree.  Agents 1-4
    # will race over the same JSON files and one run can clobber another's
    # intermediate output (observed: agent-4 file vanishing during agent-5
    # optimisation, leaving the source with only agent-5-optimized/ on disk).
    # Refuse to start a new run when one is already in-flight.
    conflict = _conflicting_running_run(provider, effective_batch_name)
    if conflict:
        raise ConcurrentRunError(
            f"Extraction for '{effective_batch_name}' (provider={provider}) "
            f"is already running as run_id={conflict.get('id')}. "
            "Wait for it to finish or cancel it before starting a new run."
        )

    run_store.create_run(
        run_id,
        run_type="extraction",
        domain=domain,
        provider=provider,
        config={
            "folder": resolved_folder or effective_batch_name,
            "source_mode": source_mode,
            "target_rules": target_rules,
            "workers": workers,
            "skip_optimize": skip_optimize,
            "step": step,
            "batch_name": effective_batch_name,
            "documents": resolved_documents if not resolved_folder else [],
        },
        documents=resolved_documents if not resolved_folder else [],
    )

    # Build command
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "knowledge_graph_generation.py"),
        "--provider", provider,
        "--domain", domain,
    ]
    if target_rules:
        cmd += ["--target-rules", str(target_rules)]
    if workers:
        cmd += ["--workers", str(workers)]
    if skip_optimize:
        cmd.append("--skip-optimize")
    if step:
        cmd += ["--step", str(step)]

    # Resolve source — order matters:
    # 1. Explicit batch_name → batch mode (all files)
    # 2. Folder (no individual docs selected) → batch mode (all files)
    # 3. Individual documents selected → batch mode with explicit --files
    # 4. Single document → --file
    if batch_name:
        cmd += ["--batch", "--batch-dir", batch_name]
    elif resolved_folder:
        # Whole-folder batch mode
        cmd += ["--batch", "--batch-dir", resolved_folder]
    elif resolved_documents and len(resolved_documents) > 1:
        # Multiple specific files selected — pass each explicitly
        # Use batch mode with --files so output goes to the right place
        file_paths = [
            str(PROJECT_ROOT / "compliance-files" / doc)
            for doc in resolved_documents
        ]
        if effective_batch_name:
            cmd += ["--batch", "--batch-dir", effective_batch_name]
        cmd += ["--files"] + file_paths
    elif resolved_documents and len(resolved_documents) == 1:
        # Single specific file — use batch mode with --files so output
        # directory is named after the parent folder, not the file stem
        file_path = str(PROJECT_ROOT / "compliance-files" / resolved_documents[0])
        if effective_batch_name:
            cmd += ["--batch", "--batch-dir", effective_batch_name, "--files", file_path]
        else:
            cmd += ["--file", file_path]

    steps_to_track = ["1", "2", "3", "3.5", "4", "5", "6"] if not step else [str(step)]
    for s in steps_to_track:
        run_store.upsert_step(run_id, s, "pending")

    asyncio.create_task(_launch_and_monitor(run_id, cmd, steps_to_track, ws_callback))
    return run_id


async def start_comparison(
    *,
    g1: str,
    g2: str,
    provider: str = "openai",
    workers: int = None,
    batch_size: int = None,
    ws_callback=None,
) -> str:
    """Launch the join/comparison pipeline and return a run_id."""
    run_id = uuid.uuid4().hex[:12]

    run_store.create_run(
        run_id,
        run_type="comparison",
        provider=provider,
        config={"g1": g1, "g2": g2, "workers": workers, "batch_size": batch_size},
    )

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "join_graphs.py"),
        "--g1", g1, "--g2", g2, "--provider", provider,
    ]
    if workers:
        cmd += ["--workers", str(workers)]
    if batch_size:
        cmd += ["--batch-size", str(batch_size)]

    steps = ["7", "8", "9", "10"]
    for s in steps:
        run_store.upsert_step(run_id, s, "pending")

    asyncio.create_task(_launch_and_monitor(run_id, cmd, steps, ws_callback))
    return run_id


async def cancel_run(run_id: str) -> bool:
    now = _now()
    proc = _active.get(run_id)

    if proc and proc.poll() is None:
        _cancelled.add(run_id)
        run_store.update_run(run_id, status="cancelled", finished_at=now)
        run_store.add_log(run_id, "Pipeline cancellation requested by user", "WARN")
        for s in run_store.get_steps(run_id):
            if s["status"] in ("pending", "running"):
                run_store.upsert_step(run_id, s["step"], "skipped")
        _kill_proc(proc)
        run_store.add_log(run_id, "Pipeline process terminated — cancellation complete", "WARN")
        return True

    # No in-memory process — check stored PID (stale run after restart)
    run = run_store.get_run(run_id)
    if run and run.get("status") == "running":
        pid = run.get("pid")
        if pid:
            _kill_pid(pid)
        run_store.update_run(run_id, status="cancelled", finished_at=now)
        run_store.add_log(run_id, "Pipeline cancelled (recovered orphan process)", "WARN")
        for s in run_store.get_steps(run_id):
            if s["status"] in ("pending", "running"):
                run_store.upsert_step(run_id, s["step"], "skipped")
        _active.pop(run_id, None)
        return True

    return False


async def attach_orphan(run_id: str, pid: int, log_file: Optional[str]) -> None:
    """
    Called at startup for runs whose process is still alive after a server
    restart.  Monitors the PID and updates the run status when it exits.
    """
    asyncio.create_task(_monitor_orphan(run_id, pid, log_file))


# ── Internal helpers ─────────────────────────────────────────────────────────

def _kill_pid(pid: int) -> None:
    """Kill a process by PID using SIGTERM then immediate SIGKILL fallback.
    Tries the whole process group first, then the PID directly."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), sig)
            return
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.kill(pid, sig)
            return
        except (ProcessLookupError, PermissionError):
            pass


def _kill_proc(proc: subprocess.Popen) -> None:
    """Terminate a Popen process group, escalating to SIGKILL immediately if SIGTERM fails."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            proc.terminate()
        except Exception:
            pass

    # Give the process 2 s to exit cleanly, then SIGKILL
    async def _force():
        await asyncio.sleep(2)
        if proc.poll() is None:
            _kill_pid(proc.pid)

    asyncio.create_task(_force())


async def _launch_and_monitor(
    run_id: str,
    cmd: list,
    steps: list,
    ws_callback=None,
) -> None:
    """
    Fork the subprocess, persist its PID + log path, then tail the log file
    while it runs.  Uses subprocess.Popen so the child is NOT owned by the
    asyncio event loop and survives uvicorn --reload.
    """
    _LOG_DIR.mkdir(exist_ok=True)
    log_path = _LOG_DIR / f"{run_id}.log"

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    # Open the log file and hand the fd to the child; close parent's handle
    # immediately after fork — the child has its own independent fd.
    log_fd = open(log_path, "wb", buffering=0)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=log_fd,
            cwd=str(PROJECT_ROOT),
            env=env,
            start_new_session=True,   # own session → survives parent death
        )
    finally:
        log_fd.close()

    _active[run_id] = proc
    run_store.set_pid(run_id, proc.pid)
    run_store.set_log_file(run_id, str(log_path))

    await _tail_log(run_id, log_path, proc, steps, ws_callback)


async def _tail_log(
    run_id: str,
    log_path: Path,
    proc: subprocess.Popen,
    steps: list,
    ws_callback=None,
) -> None:
    """
    Read the log file line-by-line while the process runs, updating step
    status and pushing lines to the WebSocket subscriber.
    """
    current_step_idx = 0

    reader = open(log_path, "r", errors="replace")
    try:
        while True:
            line = reader.readline()
            if line:
                line = line.rstrip("\n")
                if not line:
                    continue
                await _handle_line(run_id, line, steps, current_step_idx, ws_callback)

                # Update current_step_idx if this line advanced it
                current_step_idx = _advance_step(
                    run_id, line, steps, current_step_idx
                )
            else:
                if proc.poll() is not None:
                    # Process has exited; drain any remaining output
                    for remaining in reader:
                        remaining = remaining.rstrip("\n")
                        if remaining:
                            await _handle_line(
                                run_id, remaining, steps, current_step_idx, ws_callback
                            )
                    break
                await asyncio.sleep(0.1)
    finally:
        reader.close()

    retcode = proc.wait()
    _active.pop(run_id, None)
    _run_costs.pop(run_id, None)
    was_cancelled = run_id in _cancelled
    _cancelled.discard(run_id)

    now = _now()
    if was_cancelled:
        final_status = "cancelled"
    elif retcode == 0:
        run_store.update_run(run_id, status="completed", finished_at=now)
        for s in steps:
            info = [st for st in run_store.get_steps(run_id) if st["step"] == s]
            if info and info[0]["status"] in ("pending", "running"):
                run_store.upsert_step(run_id, s, "completed")
        final_status = "completed"
    else:
        run_store.update_run(
            run_id, status="failed", finished_at=now,
            error=f"Process exited with code {retcode}",
        )
        final_status = "failed"

    if ws_callback:
        await ws_callback(run_id, {"type": "status", "status": final_status})


def _orphan_succeeded(
    run_type: str,
    log_file: Optional[str],
    provider: str,
    started_at: Optional[str],
) -> bool:
    """
    Return True if two independent signals confirm the orphan run completed.

    Signal 1 — log file: look for the final-step completion marker.
    Signal 2 — filesystem: look for a visualization HTML that was written
                after this run started (works for both batch and folder runs).
    """
    final_step = "10" if run_type == "comparison" else "6"

    # Signal 1: scan the log file
    if log_file and Path(log_file).exists():
        try:
            content = Path(log_file).read_text(errors="replace")
            if f"Step {final_step}" in content and "completed" in content.lower():
                return True
            # join_graphs.py doesn't emit "Step 10 completed"; instead it
            # prints "JOINS COMPLETE!" when the comparison pipeline finishes.
            if run_type == "comparison" and "JOINS COMPLETE" in content:
                return True
        except Exception:
            pass

    # Signal 2: any viz HTML written after this run's started_at
    try:
        run_start_ts: float = (
            datetime.fromisoformat(started_at).timestamp() if started_at else 0.0
        )
        viz_subdir_name = (
            "agent-10-visualizations" if run_type == "comparison"
            else "agent-6-visualization-and-report"
        )
        output_base = PROJECT_ROOT / "pipeline-output"
        if output_base.exists():
            for subdir in output_base.iterdir():
                if not subdir.is_dir() or subdir.name.startswith("_"):
                    continue
                viz_dir = subdir / viz_subdir_name
                if not viz_dir.exists():
                    continue
                for html in viz_dir.glob("*.html"):
                    if html.stat().st_mtime >= run_start_ts:
                        return True
    except Exception:
        pass

    return False


async def _monitor_orphan(
    run_id: str,
    pid: int,
    log_file: Optional[str],
) -> None:
    """
    Monitor a pipeline process that survived a server restart.
    We can't read its exit code (not our child), so we poll the PID
    and determine outcome from the log file + filesystem.
    """
    run_store.add_log(
        run_id,
        f"[server restart] Reconnected to pipeline process PID {pid}. Monitoring until completion.",
        "INFO",
    )

    # Reconstruct the step list from what's already in the DB so that
    # _advance_step can keep the workflow diagram in sync.
    existing_steps = [s["step"] for s in run_store.get_steps(run_id)]
    steps = existing_steps or ["1", "2", "3", "3.5", "4", "5", "6"]
    current_step_idx = 0

    reader = None
    if log_file and Path(log_file).exists():
        reader = open(log_file, "r", errors="replace")

    try:
        while True:
            if reader:
                for line in iter(reader.readline, ""):
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    await _handle_line(run_id, line, steps, current_step_idx)
                    current_step_idx = _advance_step(run_id, line, steps, current_step_idx)

            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                break   # process exited

            await asyncio.sleep(2)

        # Drain remaining output after process exits
        if reader:
            for line in reader:
                line = line.rstrip("\n")
                if not line:
                    continue
                await _handle_line(run_id, line, steps, current_step_idx)
                current_step_idx = _advance_step(run_id, line, steps, current_step_idx)
    finally:
        if reader:
            reader.close()

    now = _now()
    # We can't read the exit code (not our child), so infer success from two
    # independent signals: the log file and the filesystem output.
    run = run_store.get_run(run_id)
    provider = (run or {}).get("provider", "openai")
    config = (run or {}).get("config", {})
    run_type = (run or {}).get("type", "extraction")
    started_at = (run or {}).get("started_at")

    if _orphan_succeeded(run_type, log_file, provider, started_at):
        run_store.update_run(run_id, status="completed", finished_at=now)
        for s in run_store.get_steps(run_id):
            if s["status"] in ("pending", "running"):
                run_store.upsert_step(run_id, s["step"], "completed")
    else:
        run_store.update_run(
            run_id, status="interrupted", finished_at=now,
            error=(
                "Server restarted during the run. "
                "Check the Knowledge Graph Explorer — output may still be complete. "
                "If incomplete, re-run from Step 3."
            ),
        )
        for s in run_store.get_steps(run_id):
            if s["status"] in ("pending", "running"):
                run_store.upsert_step(run_id, s["step"], "failed",
                                      detail="Monitoring lost due to server restart")


# ── Line processing helpers ───────────────────────────────────────────────────

async def _handle_line(
    run_id: str,
    line: str,
    steps: list,
    current_step_idx: int,
    ws_callback=None,
) -> None:
    # ── Parse structured LLM cost lines ──
    if line.startswith("[LLM_COST]"):
        try:
            entry = json.loads(line[len("[LLM_COST]"):])
            totals = _run_costs.setdefault(run_id, {
                "total_cost": 0.0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_cached_tokens": 0,
                "llm_calls": 0,
            })
            totals["total_cost"] = round(totals["total_cost"] + entry.get("cost", 0), 6)
            totals["total_prompt_tokens"] += entry.get("prompt_tokens", 0)
            totals["total_completion_tokens"] += entry.get("completion_tokens", 0)
            totals["total_cached_tokens"] += entry.get("cached_tokens", 0)
            totals["llm_calls"] += 1
            # Persist running total
            run_store.update_run(run_id, result=totals)
            # Push live update to UI
            if ws_callback:
                await ws_callback(run_id, {"type": "cost", **totals})
        except (json.JSONDecodeError, TypeError):
            pass
        return  # Don't log cost lines as regular log entries

    level = "INFO"
    if "❌" in line or "ERROR" in line or "FAILED" in line:
        level = "ERROR"
    elif "⚠️" in line or "WARNING" in line:
        level = "WARN"

    run_store.add_log(run_id, line, level)

    if ws_callback:
        await ws_callback(run_id, {
            "type": "log",
            "level": level,
            "message": line,
            "step": steps[min(current_step_idx, len(steps) - 1)],
        })


def _advance_step(
    run_id: str,
    line: str,
    steps: list,
    current_step_idx: int,
) -> int:
    """Update step status based on the current log line; return new step index."""
    if current_step_idx >= len(steps):
        return current_step_idx

    cur_step = steps[current_step_idx]
    step_label = STEP_LABELS.get(cur_step, f"Step {cur_step}")

    # join_graphs.py uses "STEP N/4" labels instead of "Step 7" etc.
    join_label = _JOIN_STEP_LABEL.get(cur_step)

    is_completion = f"Step {cur_step}" in line and "completed" in line.lower()

    # Detect the *next* join step starting (which means the current one finished).
    next_join_started = False
    if join_label and not is_completion:
        next_idx = current_step_idx + 1
        if next_idx < len(steps):
            next_join = _JOIN_STEP_LABEL.get(steps[next_idx])
            if next_join and f"STEP {next_join}" in line:
                next_join_started = True

    # "JOINS COMPLETE!" means the last join step finished.
    if join_label and "JOINS COMPLETE" in line:
        is_completion = True

    # A new join step starting also completes the previous one.
    if next_join_started:
        is_completion = True

    # Only transition to "running" if this line is NOT also a completion line,
    # so that started_at and finished_at are never set to the same timestamp.
    if not is_completion and (
        f"Step {cur_step}" in line
        or f"STEP {cur_step}" in line
        or (join_label and f"STEP {join_label}" in line)
        or "LAUNCHING AGENT" in line
    ):
        run_store.upsert_step(run_id, cur_step, "running")

    if is_completion:
        run_store.upsert_step(run_id, cur_step, "completed")
        current_step_idx += 1
        if current_step_idx < len(steps):
            run_store.upsert_step(run_id, steps[current_step_idx], "running")

    if ("FAILED" in line or "❌" in line) and step_label.lower() in line.lower():
        run_store.upsert_step(run_id, cur_step, "failed", detail=line)

    return current_step_idx


def _kill_orphan_pipeline_processes() -> None:
    """Find and SIGTERM any orphaned pipeline script processes."""
    for script in ("knowledge_graph_generation.py", "join_graphs.py"):
        try:
            result = subprocess.run(
                ["pgrep", "-f", script],
                capture_output=True, text=True, timeout=5,
            )
            for pid_str in result.stdout.strip().split("\n"):
                if not pid_str:
                    continue
                pid = int(pid_str)
                if pid == os.getpid():
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        except Exception:
            pass
