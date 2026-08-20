"""Test configuration for pipeline-p2c.

Every test here is offline and deterministic: no network, no credentials, no model
calls, no uncommitted local data. XSD conformance against the normative OMG
schemas needs those schemas on disk, so it is opt-in behind ``--xsd-dir`` and the
``xsd`` marker rather than part of the default run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: The committed legacy corpora, used by the compatibility tests. They live in the
#: sibling pipeline app; the tests skip cleanly if that app is not checked out.
LEGACY_CORPORA = ("comercial_lending", "fannie_mae", "freddie_mac", "healthcare")
LEGACY_ROOT = PROJECT_ROOT.parent / "pipeline" / "pipeline-output"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--xsd-dir",
        action="store",
        default=None,
        help="Directory holding the pinned OMG schemas (see scripts/fetch_schemas.py). "
        "Enables the xsd-marked conformance tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "xsd: validates emitted XML against the normative OMG schemas"
    )


@pytest.fixture(scope="session")
def xsd_dir(request: pytest.FixtureRequest) -> Path:
    value = request.config.getoption("--xsd-dir")
    if not value:
        pytest.skip("no --xsd-dir given; run scripts/fetch_schemas.py first")
    path = Path(value)
    if not path.is_dir():
        pytest.skip(f"--xsd-dir {path} is not a directory")
    return path


@pytest.fixture(scope="session")
def fixtures() -> dict:
    from fixtures import all_fixtures

    return all_fixtures()


@pytest.fixture
def eligibility(fixtures: dict):
    return fixtures["eligibility_decision"]


@pytest.fixture
def notice(fixtures: dict):
    return fixtures["notice_process"]


def legacy_graph_paths() -> list[Path]:
    """Return committed legacy graphs, or an empty list when absent."""
    paths = []
    for corpus in LEGACY_CORPORA:
        candidate = (
            LEGACY_ROOT
            / corpus
            / "agent-5-optimized"
            / "optimized_compliance_knowledge_graph.json"
        )
        if candidate.exists():
            paths.append(candidate)
    return paths


@pytest.fixture
def sample_request():
    """One synthetic extraction request, built without touching a PDF."""
    from extraction.offer import ExtractionRequest, TextUnit

    sentences = (
        "The Seller must verify the borrower's income before closing.",
        "A loan is ineligible if the credit score is below 620.",
        "This paragraph states no requirement.",
    )
    units = []
    offset = 4000
    for index, text in enumerate(sentences, start=1):
        units.append(TextUnit(index=index, char_start=offset,
                              char_end=offset + len(text), text=text))
        offset += len(text) + 1
    return ExtractionRequest(
        chunk_id="chunk_0000000000test",
        document_id="doc_0000000000test",
        section_path="B3-3.1",
        units=tuple(units),
    )


@pytest.fixture
def sample_requests(sample_request):
    """Three requests over distinct chunks, for the concurrency and isolation tests."""
    from dataclasses import replace

    return tuple(
        replace(sample_request, chunk_id=f"chunk_000000000test{n}")
        for n in range(3)
    )
