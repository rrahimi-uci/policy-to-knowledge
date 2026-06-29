"""
E2E tests for the task box API:
  - GET  /api/tasks
  - POST /api/tasks/<id>/complete
"""


class TestGetTasks:
    """GET /api/tasks"""

    def test_returns_tasks_list(self, api):
        resp = api.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        assert len(data["tasks"]) == 6

    def test_task_has_required_fields(self, api):
        tasks = api.get("/api/tasks").json()["tasks"]
        required = [
            "id", "type", "title", "description", "node_id",
            "node_name", "graph_name", "assignee", "priority",
            "due_date", "status", "highlight_terms",
        ]
        for task in tasks:
            for field in required:
                assert field in task, f"Task '{task.get('id', '?')}' missing '{field}'"

    def test_task_types_are_valid(self, api):
        tasks = api.get("/api/tasks").json()["tasks"]
        for task in tasks:
            assert task["type"] in ("review", "approval")

    def test_task_priorities_are_valid(self, api):
        tasks = api.get("/api/tasks").json()["tasks"]
        for task in tasks:
            assert task["priority"] in ("high", "medium", "low")

    def test_task_graph_names_are_known(self, api):
        from conftest import KNOWN_GRAPHS
        tasks = api.get("/api/tasks").json()["tasks"]
        for task in tasks:
            assert task["graph_name"] in KNOWN_GRAPHS

    def test_review_and_approval_counts(self, api):
        tasks = api.get("/api/tasks").json()["tasks"]
        review = [t for t in tasks if t["type"] == "review"]
        approval = [t for t in tasks if t["type"] == "approval"]
        assert len(review) == 4
        assert len(approval) == 2


class TestCompleteTask:
    """POST /api/tasks/<task_id>/complete"""

    def test_complete_existing_task(self, api):
        resp = api.post("/api/tasks/task-1/complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["task"]["status"] == "completed"

    def test_complete_nonexistent_task_returns_404(self, api):
        resp = api.post("/api/tasks/task-nonexistent/complete")
        assert resp.status_code == 404
        assert "error" in resp.json()
