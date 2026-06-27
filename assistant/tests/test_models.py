"""
Unit tests for src/models.py — SQLite-backed node-annotation persistence.
Uses an isolated temp database via the P2K_DB_URL override.
"""
import importlib
import sys
from pathlib import Path

import pytest

ASSISTANT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ASSISTANT_ROOT))


@pytest.fixture
def models(tmp_path, monkeypatch):
    # Point the SQLAlchemy engine at a throwaway DB before importing the module.
    monkeypatch.setenv("P2K_DB_URL", f"sqlite:///{tmp_path / 'test.db'}")
    import src.models as m
    importlib.reload(m)
    m.init_db()
    return m


class TestModels:
    def test_init_db_creates_tables(self, models):
        # A session round-trip should work after init_db.
        session = models.SessionLocal()
        try:
            assert session.query(models.NodeAnnotation).count() == 0
        finally:
            session.close()

    def test_removed_models_are_gone(self, models):
        # Lock/release models were removed.
        assert not hasattr(models, "GraphRelease")
        assert not hasattr(models, "GraphState")

    def test_annotation_roundtrip(self, models):
        session = models.SessionLocal()
        try:
            ann = models.NodeAnnotation(
                node_id="123",
                reviewed="yes",
                approved="no",
            )
            session.add(ann)
            session.commit()
            fetched = (
                session.query(models.NodeAnnotation).filter_by(node_id="123").one()
            )
            assert fetched.reviewed == "yes"
            d = fetched.to_dict()
            assert d["reviewed"] == "yes" and d["approved"] == "no"
            # The comments feature was removed from the annotation shape.
            assert "comments" not in d
        finally:
            session.close()

    def test_uses_env_db_url(self, models, tmp_path):
        assert str(tmp_path) in models._DB_URL
