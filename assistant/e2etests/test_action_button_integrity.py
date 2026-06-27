"""
E2E tests verifying action-button data is correctly connected to graph vertices.

Covers:
  1. Every task's node_id resolves to a real vertex in its graph
  2. Task node_name matches the actual vertex name
  3. Annotation CRUD round-trips with real vertex IDs
  4. Reviewed / approved state persists for real vertices
  5. Edge action buttons target valid edges
"""

import uuid
from conftest import KNOWN_GRAPHS


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _fetch_all_tasks(api):
    """Return the list of task dicts from the task box API."""
    resp = api.get("/api/tasks")
    assert resp.status_code == 200
    return resp.json()["tasks"]


def _fetch_graph_nodes(api, graph_name):
    """Return a dict mapping node_id (str) → node dict for the graph."""
    resp = api.get("/api/graph", params={"graph_name": graph_name})
    assert resp.status_code == 200, f"Failed to load graph {graph_name}"
    data = resp.json()
    return {str(n["id"]): n for n in data["nodes"]}


# ===================================================================
#  1. Task → Vertex linkage
# ===================================================================


class TestTaskVertexLinkage:
    """Ensure every Task Box task points at a real vertex."""

    def test_all_task_node_ids_exist_in_their_graph(self, api):
        """Every task's node_id must be present as a vertex in its graph."""
        tasks = _fetch_all_tasks(api)
        assert len(tasks) > 0, "No tasks returned"

        # Group tasks by graph to minimise API calls
        by_graph = {}
        for t in tasks:
            by_graph.setdefault(t["graph_name"], []).append(t)

        failures = []
        for graph_name, graph_tasks in by_graph.items():
            nodes = _fetch_graph_nodes(api, graph_name)
            for t in graph_tasks:
                nid = str(t["node_id"])
                if nid not in nodes:
                    failures.append(
                        f"task={t['id']}  node_id={nid}  graph={graph_name}"
                    )

        assert not failures, (
            f"{len(failures)} task(s) point to non-existent vertices:\n"
            + "\n".join(failures)
        )

    def test_task_node_names_match_graph(self, api):
        """Each task's node_name must match the vertex's name property."""
        tasks = _fetch_all_tasks(api)

        by_graph = {}
        for t in tasks:
            by_graph.setdefault(t["graph_name"], []).append(t)

        mismatches = []
        for graph_name, graph_tasks in by_graph.items():
            nodes = _fetch_graph_nodes(api, graph_name)
            for t in graph_tasks:
                nid = str(t["node_id"])
                node = nodes.get(nid)
                if not node:
                    continue  # covered by previous test
                actual_name = node.get("name") or node.get("rule_name") or ""
                if actual_name != t["node_name"]:
                    mismatches.append(
                        f"task={t['id']}  expected='{t['node_name']}'  "
                        f"actual='{actual_name}'  graph={graph_name}"
                    )

        assert not mismatches, (
            f"{len(mismatches)} task node_name mismatch(es):\n"
            + "\n".join(mismatches)
        )

    def test_task_vertex_detail_endpoint_works(self, api):
        """GET /api/vertex/<id> must succeed for every task's node_id."""
        tasks = _fetch_all_tasks(api)
        failures = []
        for t in tasks:
            resp = api.get(
                f"/api/vertex/{t['node_id']}",
                params={"graph_name": t["graph_name"]},
            )
            if resp.status_code != 200:
                failures.append(
                    f"task={t['id']}  node_id={t['node_id']}  "
                    f"graph={t['graph_name']}  status={resp.status_code}"
                )

        assert not failures, (
            f"{len(failures)} vertex detail call(s) failed:\n"
            + "\n".join(failures)
        )

    def test_task_highlight_terms_non_empty(self, api):
        """Every task should have at least one highlight term."""
        tasks = _fetch_all_tasks(api)
        for t in tasks:
            terms = t.get("highlight_terms", [])
            assert len(terms) > 0, (
                f"task={t['id']} has no highlight_terms"
            )


# ===================================================================
#  2. Annotation CRUD with real graph vertex IDs
# ===================================================================


class TestAnnotationWithRealVertices:
    """Annotation read/write using actual vertex IDs from the graph."""

    def _cleanup(self, api, node_id):
        """Remove test annotation to avoid polluting state."""
        api.delete(f"/api/annotations/{node_id}")

    def test_annotation_roundtrip_with_real_vertex(self, api):
        """Write and read back an annotation keyed by a real vertex ID."""
        tasks = _fetch_all_tasks(api)
        task = tasks[0]
        nid = str(task["node_id"])

        payload = {
            "comments": [
                {"author": "e2e-test", "text": "integrity check", "timestamp": "2026-02-26T00:00:00Z"}
            ],
            "reviewed": "yes",
            "reviewHistory": [{"status": "yes", "time": "2026-02-26T00:00:00Z"}],
            "approved": None,
            "approvalHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        }
        try:
            resp = api.put(f"/api/annotations/{nid}", json=payload)
            assert resp.status_code == 200

            # Read back
            get_resp = api.get(f"/api/annotations/{nid}")
            assert get_resp.status_code == 200
            data = get_resp.json()
            assert data["reviewed"] == "yes"
            assert data["comments"][0]["author"] == "e2e-test"
        finally:
            self._cleanup(api, nid)

    def test_reviewed_toggle_persists_for_each_task_vertex(self, api):
        """Simulate reviewed=yes for each task vertex, read back, clean up."""
        tasks = _fetch_all_tasks(api)
        for t in tasks:
            nid = str(t["node_id"])
            payload = {
                "comments": [],
                "reviewed": "yes",
                "reviewHistory": [{"status": "yes", "time": "2026-02-26T00:00:00Z"}],
                "approved": None,
                "approvalHistory": [],
                "versionHistory": [
                    {"changes": {"reviewed": {"from": "none", "to": "yes"}},
                     "time": "2026-02-26T00:00:00Z"}
                ],
                "deleted": False,
                "deletedAt": None,
                "edits": {},
            }
            try:
                put_resp = api.put(f"/api/annotations/{nid}", json=payload)
                assert put_resp.status_code == 200, (
                    f"PUT annotation failed for task={t['id']} node={nid}"
                )
                get_resp = api.get(f"/api/annotations/{nid}")
                assert get_resp.json()["reviewed"] == "yes", (
                    f"Reviewed state not persisted for task={t['id']} node={nid}"
                )
            finally:
                self._cleanup(api, nid)

    def test_approved_toggle_persists_for_each_task_vertex(self, api):
        """Simulate approved=yes for each task vertex, read back, clean up."""
        tasks = _fetch_all_tasks(api)
        for t in tasks:
            nid = str(t["node_id"])
            payload = {
                "comments": [],
                "reviewed": None,
                "reviewHistory": [],
                "approved": "yes",
                "approvalHistory": [{"status": "yes", "time": "2026-02-26T00:00:00Z"}],
                "versionHistory": [],
                "deleted": False,
                "deletedAt": None,
                "edits": {},
            }
            try:
                put_resp = api.put(f"/api/annotations/{nid}", json=payload)
                assert put_resp.status_code == 200
                get_resp = api.get(f"/api/annotations/{nid}")
                assert get_resp.json()["approved"] == "yes", (
                    f"Approved state not persisted for task={t['id']} node={nid}"
                )
            finally:
                self._cleanup(api, nid)

    def test_comment_persists_for_real_vertex(self, api):
        """Add a comment to a real vertex and read it back."""
        tasks = _fetch_all_tasks(api)
        task = tasks[0]
        nid = str(task["node_id"])
        comment_id = f"e2e-{uuid.uuid4().hex[:8]}"

        payload = {
            "comments": [
                {"author": "e2e-bot", "text": comment_id, "timestamp": "2026-02-26T00:00:00Z"}
            ],
            "reviewed": None,
            "reviewHistory": [],
            "approved": None,
            "approvalHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        }
        try:
            api.put(f"/api/annotations/{nid}", json=payload)
            data = api.get(f"/api/annotations/{nid}").json()
            texts = [c["text"] for c in data["comments"]]
            assert comment_id in texts, (
                f"Comment '{comment_id}' not found for node {nid}"
            )
        finally:
            self._cleanup(api, nid)


# ===================================================================
#  3. Cross-graph vertex coverage for action buttons
# ===================================================================


class TestActionButtonVertexCoverage:
    """Every vertex in every graph can be targeted by an annotation."""

    def test_all_vertex_ids_are_annotation_addressable(self, api):
        """Spot-check: the first 5 vertices of each graph can be
        written to and read from the annotation store."""
        failures = []
        for gname in KNOWN_GRAPHS:
            nodes = _fetch_graph_nodes(api, gname)
            sample_ids = list(nodes.keys())[:5]
            for nid in sample_ids:
                payload = {
                    "comments": [],
                    "reviewed": "yes",
                    "reviewHistory": [],
                    "approved": None,
                    "approvalHistory": [],
                    "versionHistory": [],
                    "deleted": False,
                    "deletedAt": None,
                    "edits": {},
                }
                try:
                    put_resp = api.put(f"/api/annotations/{nid}", json=payload)
                    if put_resp.status_code != 200:
                        failures.append(f"PUT failed: graph={gname} node={nid}")
                        continue

                    get_resp = api.get(f"/api/annotations/{nid}")
                    if get_resp.status_code != 200:
                        failures.append(f"GET failed: graph={gname} node={nid}")
                        continue

                    if get_resp.json().get("reviewed") != "yes":
                        failures.append(
                            f"Reviewed not persisted: graph={gname} node={nid}"
                        )
                finally:
                    api.delete(f"/api/annotations/{nid}")

        assert not failures, (
            f"{len(failures)} vertex annotation failure(s):\n"
            + "\n".join(failures)
        )

    def test_vertex_ids_are_non_empty_strings(self, api):
        """Every vertex ID must be a non-empty value suitable for use as
        an annotation key and an onclick handler argument."""
        for gname in KNOWN_GRAPHS:
            nodes = _fetch_graph_nodes(api, gname)
            for nid, node in nodes.items():
                assert nid, f"Empty vertex ID in {gname}"
                assert str(nid).strip(), f"Whitespace-only vertex ID in {gname}"
                # Verify the ID doesn't contain characters that would break
                # JavaScript string literals in onclick attributes
                for bad in ["'", '"', "\n", "\r"]:
                    assert bad not in str(nid), (
                        f"Vertex ID contains '{bad}': {nid} in {gname}"
                    )

    def test_vertex_names_safe_for_action_handlers(self, api):
        """Vertex names must not contain unescaped characters that would
        break the onclick='handleAction(…, \"name\")' pattern."""
        for gname in KNOWN_GRAPHS:
            nodes = _fetch_graph_nodes(api, gname)
            for nid, node in nodes.items():
                name = node.get("name") or node.get("rule_name") or ""
                # Names with newlines or null bytes would break the HTML
                for bad_char in ["\n", "\r", "\x00"]:
                    assert bad_char not in name, (
                        f"Vertex name contains control char in {gname}: "
                        f"id={nid} name={name[:60]!r}"
                    )


# ===================================================================
#  4. Edge action buttons — edge IDs in the graph
# ===================================================================


class TestEdgeActionIntegrity:
    """Edges returned by /api/graph must have valid IDs for action handlers."""

    def test_all_edges_have_non_empty_ids(self, api):
        """Every edge (link) must have a valid, non-empty id."""
        for gname in KNOWN_GRAPHS:
            resp = api.get("/api/graph", params={"graph_name": gname})
            assert resp.status_code == 200
            links = resp.json().get("links", [])
            for link in links:
                eid = link.get("id", "")
                assert eid, f"Empty edge ID in {gname}: {link}"

    def test_edge_source_target_are_valid_vertices(self, api):
        """Every edge's source and target must exist as vertices."""
        for gname in KNOWN_GRAPHS:
            resp = api.get("/api/graph", params={"graph_name": gname})
            assert resp.status_code == 200
            data = resp.json()
            node_ids = {str(n["id"]) for n in data["nodes"]}
            failures = []
            for link in data.get("links", []):
                src = str(link.get("source", ""))
                tgt = str(link.get("target", ""))
                if src not in node_ids:
                    failures.append(
                        f"edge={link.get('id','')} source={src} not in vertices"
                    )
                if tgt not in node_ids:
                    failures.append(
                        f"edge={link.get('id','')} target={tgt} not in vertices"
                    )
            assert not failures, (
                f"Graph {gname}: {len(failures)} broken edge reference(s):\n"
                + "\n".join(failures[:20])
            )

    def test_edge_ids_are_url_safe_or_encodable(self, api):
        """Edge IDs must be encodable via encodeURIComponent for the
        handleEdgeAction onclick handler."""
        import urllib.parse
        for gname in KNOWN_GRAPHS:
            resp = api.get("/api/graph", params={"graph_name": gname})
            links = resp.json().get("links", [])
            for link in links:
                eid = str(link.get("id", ""))
                # Must survive encode → decode round-trip
                encoded = urllib.parse.quote(eid, safe="")
                decoded = urllib.parse.unquote(encoded)
                assert decoded == eid, (
                    f"Edge ID not round-trip safe: {eid!r} in {gname}"
                )
