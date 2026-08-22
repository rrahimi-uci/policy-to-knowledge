"""Tests for Agent 1's concurrent per-document processing.

Context: process_knowledge_folder chunked and organized every file in a
single-threaded `for` loop, with an added `time.sleep(1)` between files. The
per-document LLM call (chunk_document_with_reasoning) already goes through a
client whose in-flight concurrency is gated by KG_LLM_CONCURRENCY (default 8,
set by the CLI orchestrator's performance profile) — so the client already
supports up to 8 concurrent reasoning calls, but the loop only ever issued
one at a time. On a real 115-document benchmark corpus this made Step 1
alone take on the order of hours (~2.4 minutes/document, wholly serial),
independent of how many workers the rest of the pipeline used.

Each document writes to its own isolated output subfolder and the agent
holds no other mutable per-document instance state, so dispatching all
documents through a ThreadPoolExecutor is safe. These tests verify the
concurrent version is still correct (same aggregate results, isolated
folders, one file's exception doesn't corrupt another's outcome) and that it
actually achieves overlap rather than just being reorganized code that still
runs one at a time.
"""

import threading
import time
from pathlib import Path
from unittest.mock import patch

from agents.agent_1_document_organizer import DocumentChunk, DocumentChunkingAgent


def _agent() -> DocumentChunkingAgent:
    # create_llm_client doesn't make a network call at construction time, so
    # a fake key is fine — no test here ever calls chunk_document_with_reasoning
    # for real, it's always patched.
    return DocumentChunkingAgent(api_key="test-key")


def _write_docs(tmp_path: Path, n: int) -> list[Path]:
    paths = []
    for i in range(n):
        path = tmp_path / f"doc_{i}.txt"
        path.write_text(f"Document {i} content. " * 50)
        paths.append(path)
    return paths


def _fake_chunks(file_path: Path, count: int = 2) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            chunk_id=f"{file_path.stem}-{i}",
            title=f"section_{i}",
            content=f"Content of {file_path.stem} section {i}. " * 20,
            metadata={"word_count": 100, "chunk_method": "test"},
        )
        for i in range(count)
    ]


def test_all_documents_are_processed_and_aggregated_correctly(tmp_path):
    docs = _write_docs(tmp_path, 6)
    out_dir = tmp_path / "organized"
    agent = _agent()

    with patch.object(agent, "chunk_document_with_reasoning", side_effect=lambda p: _fake_chunks(p, count=3)):
        results = agent.process_knowledge_folder(str(tmp_path), output_folder=str(out_dir))

    assert results["total_files"] == 6
    assert results["processed"] == 6
    assert results["failed"] == 0
    assert results["total_chunks"] == 18  # 6 docs * 3 chunks
    assert len(results["files"]) == 6
    assert all(entry["status"] == "success" for entry in results["files"])
    assert {entry["file"] for entry in results["files"]} == {d.name for d in docs}


def test_each_document_gets_its_own_isolated_output_folder(tmp_path):
    _write_docs(tmp_path, 4)
    out_dir = tmp_path / "organized"
    agent = _agent()

    with patch.object(agent, "chunk_document_with_reasoning", side_effect=lambda p: _fake_chunks(p, count=2)):
        agent.process_knowledge_folder(str(tmp_path), output_folder=str(out_dir))

    produced = {p.name for p in out_dir.iterdir() if p.is_dir()}
    assert produced == {f"doc_{i}" for i in range(4)}
    for i in range(4):
        chunk_files = list((out_dir / f"doc_{i}").glob("*.txt"))
        assert len(chunk_files) == 2


def test_one_failing_document_does_not_corrupt_others(tmp_path):
    docs = _write_docs(tmp_path, 5)
    out_dir = tmp_path / "organized"
    agent = _agent()
    failing_name = docs[2].name

    def maybe_fail(path: Path):
        if path.name == failing_name:
            raise RuntimeError("simulated chunking failure")
        return _fake_chunks(path, count=1)

    with patch.object(agent, "chunk_document_with_reasoning", side_effect=maybe_fail):
        results = agent.process_knowledge_folder(str(tmp_path), output_folder=str(out_dir))

    assert results["processed"] == 4
    assert results["failed"] == 1
    by_name = {entry["file"]: entry for entry in results["files"]}
    assert by_name[failing_name]["status"] == "error"
    assert "simulated chunking failure" in by_name[failing_name]["error"]
    assert all(by_name[d.name]["status"] == "success" for d in docs if d.name != failing_name)


def test_documents_are_actually_processed_concurrently_not_one_at_a_time(tmp_path, monkeypatch):
    """The regression this guards against: a correctly-refactored loop that
    still only ever has one document in flight at a time. Each fake call
    blocks briefly and records its active-overlap high-water mark; with real
    concurrency multiple documents must be mid-chunk simultaneously."""
    monkeypatch.setenv("KG_ORGANIZER_WORKERS", "5")
    _write_docs(tmp_path, 5)
    out_dir = tmp_path / "organized"
    agent = _agent()

    active = 0
    peak_active = 0
    lock = threading.Lock()

    def slow_chunk(path: Path):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return _fake_chunks(path, count=1)

    with patch.object(agent, "chunk_document_with_reasoning", side_effect=slow_chunk):
        start = time.monotonic()
        results = agent.process_knowledge_folder(str(tmp_path), output_folder=str(out_dir))
        elapsed = time.monotonic() - start

    assert results["processed"] == 5
    assert peak_active > 1, "documents ran one at a time despite concurrent dispatch"
    # 5 documents at 0.2s each: ~1.0s serial vs a fraction of that concurrently.
    assert elapsed < 0.8, f"took {elapsed:.2f}s — looks serial, not concurrent"


def test_organizer_workers_env_var_is_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_ORGANIZER_WORKERS", "1")
    _write_docs(tmp_path, 4)
    out_dir = tmp_path / "organized"
    agent = _agent()

    active = 0
    peak_active = 0
    lock = threading.Lock()

    def slow_chunk(path: Path):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _fake_chunks(path, count=1)

    with patch.object(agent, "chunk_document_with_reasoning", side_effect=slow_chunk):
        results = agent.process_knowledge_folder(str(tmp_path), output_folder=str(out_dir))

    assert results["processed"] == 4
    assert peak_active == 1, "KG_ORGANIZER_WORKERS=1 must serialize processing"
