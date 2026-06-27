"""
E2E tests for annotation CRUD:
  - GET    /api/annotations/<node_id>
  - PUT    /api/annotations/<node_id>
  - GET    /api/annotations
  - DELETE /api/annotations/<node_id>
"""

import uuid


class TestAnnotationCRUD:
    """Full create → read → update → delete lifecycle."""

    def _node_id(self):
        """Return a unique fake node ID for isolation."""
        return f"e2e-{uuid.uuid4().hex[:12]}"

    def test_get_nonexistent_returns_defaults(self, api):
        nid = self._node_id()
        resp = api.get(f"/api/annotations/{nid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["comments"] == []
        assert data["deleted"] is False

    def test_put_creates_annotation(self, api):
        nid = self._node_id()
        payload = {
            "comments": [
                {"author": "pytest", "text": "E2E annotation test", "timestamp": "2026-02-26T00:00:00Z"}
            ],
            "reviewed": "approved",
            "reviewHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        }
        resp = api.put(f"/api/annotations/{nid}", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["comments"]) == 1
        assert data["comments"][0]["author"] == "pytest"
        assert data["reviewed"] == "approved"

    def test_get_returns_saved_annotation(self, api):
        nid = self._node_id()
        payload = {
            "comments": [{"author": "e2e", "text": "read back", "timestamp": "2026-02-26T01:00:00Z"}],
            "reviewed": "pending",
            "reviewHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        }
        api.put(f"/api/annotations/{nid}", json=payload)

        resp = api.get(f"/api/annotations/{nid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["comments"][0]["text"] == "read back"

    def test_put_updates_existing(self, api):
        nid = self._node_id()
        # Create
        api.put(f"/api/annotations/{nid}", json={
            "comments": [],
            "reviewed": None,
            "reviewHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        })
        # Update
        resp = api.put(f"/api/annotations/{nid}", json={
            "comments": [{"author": "update", "text": "updated", "timestamp": "2026-02-26T02:00:00Z"}],
            "reviewed": "rejected",
            "reviewHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        })
        assert resp.status_code == 200
        assert resp.json()["reviewed"] == "rejected"

    def test_delete_annotation(self, api):
        nid = self._node_id()
        # Create
        api.put(f"/api/annotations/{nid}", json={
            "comments": [],
            "reviewed": None,
            "reviewHistory": [],
            "versionHistory": [],
            "deleted": False,
            "deletedAt": None,
            "edits": {},
        })
        # Delete
        resp = api.delete(f"/api/annotations/{nid}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify it's gone (returns defaults)
        get_resp = api.get(f"/api/annotations/{nid}")
        assert get_resp.json()["comments"] == []

    def test_list_all_annotations(self, api):
        resp = api.get("/api/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
