"""
SQLAlchemy models for persistent node annotation storage.

Stores edits, version history, and review/approval status in a local SQLite
database (app.db) instead of browser localStorage.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, Column, String, Boolean, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

from src.log import log as _log

# ── Database path ────────────────────────────────────────────────

_DB_DIR = Path(__file__).resolve().parent.parent
_DB_URL = os.getenv("P2K_DB_URL", f"sqlite:///{_DB_DIR / 'app.db'}")

engine = create_engine(_DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()


# ── Model ────────────────────────────────────────────────────────

class NodeAnnotation(Base):
    """Persistent per-node annotation: edits, reviews, approvals, versions."""

    __tablename__ = "node_annotations"

    node_id = Column(String(512), primary_key=True, nullable=False)
    reviewed = Column(String(8), nullable=True)           # "yes" | "no" | null
    approved = Column(String(8), nullable=True)            # "yes" | "no" | null
    deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(String(64), nullable=True)
    edits_json = Column(Text, default="{}", nullable=False)           # JSON: { name, content }
    review_history_json = Column(Text, default="[]", nullable=False)  # JSON array
    approval_history_json = Column(Text, default="[]", nullable=False) # JSON array
    version_history_json = Column(Text, default="[]", nullable=False) # JSON array
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # ── Serialisation helpers ────────────────────────────────────

    def to_dict(self) -> dict:
        """Return the annotation as the same shape the frontend expects."""
        return {
            "reviewed": self.reviewed,
            "reviewHistory": json.loads(self.review_history_json or "[]"),
            "approved": self.approved,
            "approvalHistory": json.loads(self.approval_history_json or "[]"),
            "versionHistory": json.loads(self.version_history_json or "[]"),
            "deleted": self.deleted,
            "deletedAt": self.deleted_at,
            "edits": json.loads(self.edits_json or "{}"),
        }

    @classmethod
    def from_dict(cls, node_id: str, data: dict) -> "NodeAnnotation":
        """Create or update from the frontend data shape."""
        return cls(
            node_id=node_id,
            reviewed=data.get("reviewed"),
            approved=data.get("approved"),
            deleted=bool(data.get("deleted", False)),
            deleted_at=data.get("deletedAt"),
            edits_json=json.dumps(data.get("edits", {})),
            review_history_json=json.dumps(data.get("reviewHistory", [])),
            approval_history_json=json.dumps(data.get("approvalHistory", [])),
            version_history_json=json.dumps(data.get("versionHistory", [])),
        )

    def update_from_dict(self, data: dict) -> None:
        """Merge incoming data into this row."""
        if "reviewed" in data:
            self.reviewed = data["reviewed"]
        if "approved" in data:
            self.approved = data["approved"]
        if "deleted" in data:
            self.deleted = bool(data["deleted"])
        if "deletedAt" in data:
            self.deleted_at = data["deletedAt"]
        if "edits" in data:
            self.edits_json = json.dumps(data["edits"])
        if "reviewHistory" in data:
            self.review_history_json = json.dumps(data["reviewHistory"])
        if "approvalHistory" in data:
            self.approval_history_json = json.dumps(data["approvalHistory"])
        if "versionHistory" in data:
            self.version_history_json = json.dumps(data["versionHistory"])


# ── Initialise tables ────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist."""
    Base.metadata.create_all(engine)
    _log("INFO", f"SQLite database ready at {_DB_URL}")
