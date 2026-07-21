"""
Ducked Engine — Data Models
In-memory structures. No database. Born and destroyed with the process.
"""
import asyncio
import re
from collections import deque
from enum import Enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator
from config import settings


# ── Enums ──────────────────────────────────────────────────────────


class ProjectType(str, Enum):
    PYTHON = "python"
    NODE = "node"
    STATIC = "static"
    DOCKERFILE = "dockerfile"
    GO = "go"
    UNKNOWN = "unknown"


class SessionStatus(str, Enum):
    QUEUED = "queued"
    CLONING = "cloning"
    DETECTING = "detecting"
    BUILDING = "building"
    RUNNING = "running"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    FAILED = "failed"


# ── API Schemas ────────────────────────────────────────────────────


class DeployRequest(BaseModel):
    model_config = ConfigDict(strict=False)
    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        cleaned = v.strip().rstrip("/")

        # ── SSRF Prevention: reject dangerous schemes before regex ──
        lower = cleaned.lower()
        if lower.startswith("file://"):
            raise ValueError("file:// URLs are not allowed.")
        if lower.startswith("git://"):
            raise ValueError("git:// URLs are not allowed. Use HTTPS.")
        if lower.startswith("ssh://") or lower.startswith("git@"):
            raise ValueError("SSH URLs are not allowed. Use HTTPS.")
        if lower.startswith("http://"):
            raise ValueError("HTTP URLs are not allowed. Use HTTPS.")

        # ── Strict GitHub HTTPS URL pattern ──
        # Owner: 1-39 chars, must start with alphanumeric (blocks ".." and ".")
        # Repo:  1-100 chars, must start with alphanumeric
        # Optional .git suffix with escaped dot
        pattern = r"^https://github\.com/[a-zA-Z0-9][\w.\-]{0,38}/[a-zA-Z0-9][\w.\-]{0,99}(\.git)?$"
        if not re.match(pattern, cleaned):
            raise ValueError(
                "Only public GitHub HTTPS URLs are accepted "
                "(e.g. https://github.com/owner/repo)."
            )
        return cleaned


class DeployResponse(BaseModel):
    session_id: str
    preview_url: str
    status: str
    message: str


# ── In-Memory Session ──────────────────────────────────────────────

# Max log lines kept in memory per session — protects against
# malicious builds that spam stdout (e.g. `RUN yes "spam"`)
MAX_LOG_HISTORY = 1000


class Session:
    """
    Ephemeral session state.
    Born when a deploy request arrives. Dies when the container is destroyed.
    No persistence. No mercy.
    """

    __slots__ = (
        "session_id", "repo_url", "clone_dir", "status", "project_type",
        "container_id", "image_id", "image_tag",
        "created_at", "started_at", "destroyed_at", "error",
        "_subscribers", "_log_history",
    )

    def __init__(self, session_id: str, repo_url: str, clone_dir: str):
        self.session_id: str = session_id
        self.repo_url: str = repo_url
        self.clone_dir: str = clone_dir
        self.status: SessionStatus = SessionStatus.QUEUED
        self.project_type: ProjectType | None = None
        self.container_id: str | None = None
        self.image_id: str | None = None
        self.image_tag: str | None = None
        self.created_at: datetime = datetime.now(timezone.utc)
        self.started_at: datetime | None = None
        self.destroyed_at: datetime | None = None
        self.error: str | None = None

        # ── Broadcast infrastructure ──
        self._subscribers: list[asyncio.Queue] = []
        self._log_history: deque[dict] = deque(maxlen=MAX_LOG_HISTORY)

    # ── Pub/Sub ────────────────────────────────────────────────────

    def broadcast(self, event: dict) -> None:
        """Push an event to all connected WebSocket clients."""
        self._log_history.append(event)
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Client can't keep up — drop the event

    def subscribe(self) -> asyncio.Queue:
        """Register a new WebSocket client. Returns its personal queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a disconnected client's queue. No zombies allowed."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ── Serialization ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        elapsed = remaining = None
        if self.started_at and self.status == SessionStatus.RUNNING:
            elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
            remaining = max(0.0, settings.CONTAINER_TTL_SECONDS - elapsed)

        return {
            "session_id": self.session_id,
            "repo_url": self.repo_url,
            "preview_url": f"{settings.PREVIEW_BASE_URL}/preview/{self.session_id}",
            "status": self.status.value,
            "project_type": self.project_type.value if self.project_type else None,
            "container_id": self.container_id[:12] if self.container_id else None,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "destroyed_at": self.destroyed_at.isoformat() if self.destroyed_at else None,
            "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
            "remaining_seconds": round(remaining, 1) if remaining is not None else None,
            "error": self.error,
        }

