"""
Shared fixtures for backend E2E tests.

Every test file receives ``base_url`` and ``api`` automatically.
The ``api`` fixture is a ``requests.Session`` pre-configured with the
base URL so tests can call ``api.get("/api/graph")`` directly.
"""

import os
import pytest
import requests

# ── Constants ────────────────────────────────────────────────────────

BASE_URL = os.getenv("BASE_URL", "http://localhost:5001")
TIMEOUT = 30  # seconds — graph queries can be slow

# Known graph traversal sources (must match graphs.yaml)
KNOWN_GRAPHS = ["sample_guidelines_g", "example_policies_g"]

# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def base_url():
    """Root URL of the running Explorer server."""
    return BASE_URL


class ApiClient:
    """Thin wrapper around ``requests.Session`` that prepends the base URL."""

    def __init__(self, base: str):
        self._base = base.rstrip("/")
        self._session = requests.Session()

    def get(self, path: str, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return self._session.get(f"{self._base}{path}", **kwargs)

    def post(self, path: str, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return self._session.post(f"{self._base}{path}", **kwargs)

    def put(self, path: str, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return self._session.put(f"{self._base}{path}", **kwargs)

    def delete(self, path: str, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return self._session.delete(f"{self._base}{path}", **kwargs)

    def close(self):
        self._session.close()


@pytest.fixture(scope="session")
def api():
    """A reusable API client pointing at the live server."""
    client = ApiClient(BASE_URL)
    yield client
    client.close()


@pytest.fixture(scope="session")
def any_graph_data(api):
    """Fetch the default graph once and cache for the session.

    Returns the parsed JSON dict with ``nodes``, ``links``, ``graph_name``.
    """
    resp = api.get("/api/graph", params={"graph_name": KNOWN_GRAPHS[0]})
    assert resp.status_code == 200, f"Failed to fetch graph: {resp.text}"
    data = resp.json()
    assert len(data["nodes"]) > 0, "Graph has no nodes"
    return data


@pytest.fixture(scope="session")
def any_node_id(any_graph_data):
    """Return the ID (str) of an arbitrary node from the default graph."""
    return any_graph_data["nodes"][0]["id"]


@pytest.fixture(scope="session")
def any_node(any_graph_data):
    """Return the full node dict of an arbitrary node."""
    return any_graph_data["nodes"][0]


@pytest.fixture(scope="session")
def default_graph_name(any_graph_data):
    """The graph_name returned by the first graph fetch."""
    return any_graph_data["graph_name"]
