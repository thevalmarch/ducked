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
from urllib.parse import urlsplit

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


# Each path segment: 1-100 chars, must start alphanumeric. The leading
# alphanumeric blocks "." and ".." outright, so no traversal can survive.
_PATH_SEGMENT = re.compile(r"^[a-zA-Z0-9][\w.\-]{0,99}$")

# GitLab allows nested subgroups (group/subgroup/project), so a path may
# carry more than owner/repo. Capped to keep the surface small.
MAX_PATH_SEGMENTS = 5


class DeployRequest(BaseModel):
    model_config = ConfigDict(strict=False)
    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        """
        Accept an HTTPS URL pointing at an allowlisted git forge.

        The host allowlist (settings.ALLOWED_GIT_HOSTS) is the primary SSRF
        defence. Everything else here narrows what can be smuggled through
        a URL that *does* name an allowed host.
        """
        cleaned = v.strip().rstrip("/")

        # ── SSRF Prevention: reject dangerous schemes before parsing ──
        lower = cleaned.lower()
        if lower.startswith("file://"):
            raise ValueError("file:// URLs are not allowed.")
        if lower.startswith("git://"):
            raise ValueError("git:// URLs are not allowed. Use HTTPS.")
        if lower.startswith("ssh://") or lower.startswith("git@"):
            raise ValueError("SSH URLs are not allowed. Use HTTPS.")
        if lower.startswith("http://"):
            raise ValueError("HTTP URLs are not allowed. Use HTTPS.")
        if not lower.startswith("https://"):
            raise ValueError(
                "Only HTTPS git URLs are accepted "
                "(e.g. https://github.com/owner/repo)."
            )

        parts = urlsplit(cleaned)

        # Credentials in the authority are both a leak risk and a classic
        # way to disguise the real host (https://github.com@evil.com/...).
        if "@" in parts.netloc:
            raise ValueError("URLs containing credentials are not allowed.")

        host = parts.netloc.lower()
        if host not in settings.ALLOWED_GIT_HOSTS:
            allowed = ", ".join(sorted(settings.ALLOWED_GIT_HOSTS))
            raise ValueError(
                f"'{host}' is not an allowed git host. "
                f"Accepted hosts: {allowed}. "
                f"Self-hosted instances are added via GIT_ALLOWED_HOSTS."
            )

        # Nothing downstream reads these, and they only widen the surface.
        if parts.query:
            raise ValueError("Query strings are not allowed in repository URLs.")
        if parts.fragment:
            raise ValueError("Fragments are not allowed in repository URLs.")

        segments = [s for s in parts.path.split("/") if s]
        if len(segments) < 2:
            raise ValueError(
                "URL must include an owner and a repository "
                "(e.g. https://github.com/owner/repo)."
            )
        if len(segments) > MAX_PATH_SEGMENTS:
            raise ValueError(
                f"Repository path is too deeply nested "
                f"(max {MAX_PATH_SEGMENTS} segments)."
            )

        for segment in segments:
            if not _PATH_SEGMENT.match(segment) or segment.endswith("."):
                raise ValueError(f"Invalid path segment: {segment!r}")

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

