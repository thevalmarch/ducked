"""
Ducked Engine — Configuration
The Constrained Canvas: Every limit, every boundary, defined here.
"""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    # ── Container Constraints (RUN stage) ─────────────────────────
    CONTAINER_CPU_LIMIT: float = 0.5
    CONTAINER_MEM_LIMIT: str = "256m"
    CONTAINER_TTL_SECONDS: int = 60          # 60s for testing; 600 for production
    MAX_CONCURRENT_CONTAINERS: int = 5       # Legacy; see MAX_CONCURRENT_SESSIONS
    CONTAINER_PIDS_LIMIT: int = 50           # Fork bomb protection
    CONTAINER_INTERNAL_PORT: int = 8080

    # ── Build Constraints (BUILD stage) ───────────────────────────
    BUILD_CPU_LIMIT: float = 0.5             # CPU cores for docker build
    BUILD_MEM_LIMIT: str = "512m"            # Memory limit for docker build
    BUILD_MEM_BYTES: int = 512 * 1024 * 1024 # Same as above in bytes (for Docker API)
    BUILD_TIMEOUT_SECONDS: int = 90          # Hard build timeout (reduced from 180)
    BUILD_PIDS_LIMIT: int = 100              # PID limit during build

    # ── Timeouts ───────────────────────────────────────────────────
    CLONE_TIMEOUT_SECONDS: int = 60

    # ── Repo Size Limits ──────────────────────────────────────────
    MAX_REPO_SIZE_MB: int = 50               # Pre-clone GitHub API check (KB→MB)
    MAX_CLONE_DISK_MB: int = 100             # Post-clone actual disk check

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 3           # Max deploys per minute per IP
    RATE_LIMIT_PER_HOUR: int = 10            # Max deploys per hour per IP

    # ── Global Concurrency ────────────────────────────────────────
    MAX_CONCURRENT_SESSIONS: int = 10        # Global cap (all stages combined)

    # ── Trusted Proxies (for X-Forwarded-For) ─────────────────────
    # Empty = never trust XFF, use direct connection IP only.
    # Set to e.g. ("172.17.0.0/16",) if API is behind a reverse proxy.
    TRUSTED_PROXY_CIDRS: tuple = ()

    # ── Docker Labels & Network ────────────────────────────────────
    DUCKED_LABEL_KEY: str = "ducked.managed"
    DOCKER_NETWORK: str = "ducked-net"

    # ── Preview Routing ────────────────────────────────────────────
    PREVIEW_BASE_URL: str = "http://localhost"  # Change to https://ducked.dev in prod

    # ── Reaper ─────────────────────────────────────────────────────
    REAPER_INTERVAL_SECONDS: int = 2

    # ── API Server ─────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = int(os.getenv("API_PORT", "9000"))

    # ── Monitoring ─────────────────────────────────────────────────
    DISCORD_WEBHOOK_URL: str | None = None  # Set via environment variable in prod

import os
# Allow overriding from environment
_env_webhook = os.getenv("DISCORD_WEBHOOK_URL")

settings = Settings(
    DISCORD_WEBHOOK_URL=_env_webhook if _env_webhook else None
)
