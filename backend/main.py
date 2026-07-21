"""
Ducked Engine — Main Application
The orchestrator. Receives deploy requests, manages the ephemeral lifecycle,
and ensures every container meets its inevitable end.

Usage:
    pip install -r requirements.txt
    python main.py

    Then POST to http://localhost:9000/api/deploy with:
    {"repo_url": "https://github.com/user/repo"}
"""
import asyncio
import glob
import ipaddress
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from config import settings
from models import (
    DeployRequest,
    DeployResponse,
    Session,
    SessionStatus,
)
from services.github_service import GitHubService
from services.docker_service import DockerService


# ── Logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ducked")

def send_alert(msg: str):
    """Send a lightweight webhook alert in the background."""
    if not settings.DISCORD_WEBHOOK_URL:
        return
    async def _post():
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    settings.DISCORD_WEBHOOK_URL,
                    json={"content": f"🦆 **Ducked Engine Alert**\\n{msg}"},
                    timeout=5.0
                )
        except Exception as e:
            log.warning(f"Failed to send webhook alert: {e}")
    asyncio.create_task(_post())


# ── In-Memory State ───────────────────────────────────────────────

sessions: dict[str, Session] = {}


# ── Services ──────────────────────────────────────────────────────

github_svc = GitHubService()
docker_svc = DockerService()


# ── Rate Limiter (FIX 1) ─────────────────────────────────────────

def _get_real_client_ip(request: Request) -> str:
    """
    Extract the real client IP for rate limiting.
    - Default: use request.client.host (direct TCP connection IP).
    - If the connecting IP is in TRUSTED_PROXY_CIDRS, parse X-Forwarded-For
      and take the rightmost non-trusted IP (prevents XFF spoofing).
    - If no trusted proxies configured, X-Forwarded-For is COMPLETELY IGNORED.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"

    if not settings.TRUSTED_PROXY_CIDRS:
        return client_ip

    # Check if connecting IP is a trusted proxy
    try:
        client_addr = ipaddress.ip_address(client_ip)
        is_trusted = any(
            client_addr in ipaddress.ip_network(cidr, strict=False)
            for cidr in settings.TRUSTED_PROXY_CIDRS
        )
    except ValueError:
        return client_ip

    if not is_trusted:
        return client_ip

    # Connecting IP is a trusted proxy — read XFF
    xff = request.headers.get("x-forwarded-for", "")
    if not xff:
        return client_ip

    # Take the rightmost non-trusted IP (standard secure algorithm)
    ips = [ip.strip() for ip in xff.split(",")]
    for ip in reversed(ips):
        try:
            addr = ipaddress.ip_address(ip)
            is_proxy = any(
                addr in ipaddress.ip_network(cidr, strict=False)
                for cidr in settings.TRUSTED_PROXY_CIDRS
            )
            if not is_proxy:
                return ip
        except ValueError:
            continue

    return client_ip


limiter = Limiter(key_func=_get_real_client_ip)


# ── Reaper — The Grim Reaper of Containers (FIX 7: Enhanced) ─────

# Maximum expected session lifetime (clone + build + run + buffer)
_MAX_SESSION_LIFETIME = (
    settings.CLONE_TIMEOUT_SECONDS
    + settings.BUILD_TIMEOUT_SECONDS
    + settings.CONTAINER_TTL_SECONDS
    + 60  # generous buffer
)


async def reaper():
    """
    Background task that:
    1. Destroys sessions whose TTL has expired (original behavior)
    2. Sweeps for orphaned Docker resources not tracked in sessions dict (FIX 7)
    3. Cleans orphaned temp directories (FIX 7)
    """
    log.info(
        f"⏳ Reaper active. Checking every {settings.REAPER_INTERVAL_SECONDS}s "
        f"for containers exceeding {settings.CONTAINER_TTL_SECONDS}s TTL."
    )
    sweep_counter = 0
    while True:
        await asyncio.sleep(settings.REAPER_INTERVAL_SECONDS)
        now = datetime.now(timezone.utc)

        # ── 1. Expire running sessions past TTL ──
        expired = [
            sid
            for sid, session in sessions.items()
            if session.status == SessionStatus.RUNNING
            and session.started_at is not None
            and (now - session.started_at).total_seconds() >= settings.CONTAINER_TTL_SECONDS
        ]

        for sid in expired:
            session = sessions[sid]
            elapsed = (now - session.started_at).total_seconds()
            log.info(
                f"⏰ [{sid}] TTL expired ({elapsed:.1f}s >= {settings.CONTAINER_TTL_SECONDS}s). "
                f"Initiating destruction sequence."
            )
            await destroy_session(sid)

        # ── 2. Orphan sweep (every ~30 seconds, not every tick) ──
        sweep_counter += 1
        if sweep_counter >= (30 // max(settings.REAPER_INTERVAL_SECONDS, 1)):
            sweep_counter = 0
            await _sweep_orphans()


# ── Session Destruction ──────────────────────────────────────────

async def destroy_session(session_id: str) -> None:
    """
    Completely destroy a session — container, image, clone directory.
    After this, zero traces of the session remain on the host system.
    """
    session = sessions.get(session_id)
    if not session or session.status in (SessionStatus.DESTROYING, SessionStatus.DESTROYED):
        return

    session.status = SessionStatus.DESTROYING
    sid = session.session_id

    log.info(f"💀 [{sid}] === DESTRUCTION SEQUENCE INITIATED ===")

    # 1. Kill and remove container
    if session.container_id:
        await asyncio.to_thread(docker_svc.destroy_container, session.container_id)

    # 2. Remove image and all layers
    if session.image_id:
        await asyncio.to_thread(docker_svc.destroy_image, session.image_id)

    # 3. Wipe clone directory from disk
    if session.clone_dir and os.path.exists(session.clone_dir):
        shutil.rmtree(session.clone_dir, ignore_errors=True)
        log.info(f"💀 [{sid}] Clone directory wiped: {session.clone_dir}")

    session.status = SessionStatus.DESTROYED
    session.destroyed_at = datetime.now(timezone.utc)

    # Notify any connected WebSocket clients that the session is over
    session.broadcast({"type": "status", "status": "destroyed"})

    log.info(f"✅ [{sid}] === DESTRUCTION COMPLETE. ZERO TRACES REMAIN. ===")


# ── Deploy Pipeline ──────────────────────────────────────────────

async def deploy_pipeline(session: Session) -> None:
    """
    The core ephemeral lifecycle:
      1. Clone the repo (shallow, single branch)
      2. Detect project type
      3. Build Docker image (network ON)
      4. Run container (constraints active)
      5. Reaper handles destruction when TTL expires
    """
    sid = session.session_id

    try:
        # ── Pre-Clone: Repo size check (Layer 1 — GitHub API) ──
        session.status = SessionStatus.CLONING
        session.broadcast({"type": "status", "status": "cloning"})
        log.info(f"📦 [{sid}] Pre-clone size check via GitHub API...")
        await asyncio.to_thread(github_svc.check_repo_size, session.repo_url)

        # ── Phase 1: Clone ──
        log.info(f"📦 [{sid}] Phase 1/4 — Cloning {session.repo_url}...")
        await asyncio.to_thread(github_svc.clone, session.repo_url, session.clone_dir)

        # Remove .git directory — we don't need history in the image
        git_dir = os.path.join(session.clone_dir, ".git")
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir, ignore_errors=True)

        # ── Post-Clone: Disk usage check (Layer 2 — actual size) ──
        await asyncio.to_thread(github_svc.check_clone_disk_usage, session.clone_dir)

        log.info(f"📦 [{sid}] Clone complete.")

        # ── Phase 2: Detect ──
        session.status = SessionStatus.DETECTING
        session.broadcast({"type": "status", "status": "detecting"})
        project_type = github_svc.detect_project_type(session.clone_dir)
        session.project_type = project_type
        log.info(f"🔍 [{sid}] Phase 2/4 — Project type detected: {project_type.value}")

        # ── Phase 3: Build ──
        session.status = SessionStatus.BUILDING
        session.broadcast({"type": "status", "status": "building"})
        log.info(f"🔨 [{sid}] Phase 3/4 — Building image...")

        def on_build_log(line: str):
            session.broadcast({"type": "build_log", "data": line})

        image_id, image_tag = await asyncio.to_thread(
            docker_svc.build_image,
            session.clone_dir,
            project_type,
            session.session_id,
            on_log=on_build_log,
        )
        session.image_id = image_id
        session.image_tag = image_tag
        log.info(f"🔨 [{sid}] Image ready: {image_tag}")

        # ── Phase 4: Run ──
        log.info(f"🚀 [{sid}] Phase 4/4 — Starting container (constraints: ACTIVE)...")
        container_id = await asyncio.to_thread(
            docker_svc.run_container,
            image_tag,
            session.session_id,
        )
        session.container_id = container_id
        session.status = SessionStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)
        session.broadcast({
            "type": "status",
            "status": "running",
            "preview_url": f"{settings.PREVIEW_BASE_URL}/preview/{sid}",
        })

        log.info(
            f"🚀 [{sid}] Container is LIVE: {container_id[:12]}\n"
            f"   ├─ CPU:  {settings.CONTAINER_CPU_LIMIT} cores\n"
            f"   ├─ RAM:  {settings.CONTAINER_MEM_LIMIT}\n"
            f"   ├─ PIDs: {settings.CONTAINER_PIDS_LIMIT}\n"
            f"   ├─ FS:   read-only\n"
            f"   └─ TTL:  {settings.CONTAINER_TTL_SECONDS}s — the clock is ticking."
        )

    except Exception as e:
        session.status = SessionStatus.FAILED
        session.error = str(e)
        session.broadcast({"type": "status", "status": "failed", "error": str(e)})
        log.error(f"❌ [{sid}] Pipeline failed: {e}")

        # Cleanup any partial resources
        if session.clone_dir and os.path.exists(session.clone_dir):
            shutil.rmtree(session.clone_dir, ignore_errors=True)
        if session.image_id:
            try:
                await asyncio.to_thread(docker_svc.destroy_image, session.image_id)
            except Exception:
                pass


# ── Orphan Sweep (FIX 7) ─────────────────────────────────────────

async def _sweep_orphans():
    """
    Scan for orphaned Docker resources and temp directories that aren't
    tracked in the sessions dict. This handles cases where the FastAPI
    process crashed mid-session or Docker daemon restarted.
    """
    tracked_container_ids = {
        s.container_id for s in sessions.values() if s.container_id
    }
    tracked_image_ids = {
        s.image_id for s in sessions.values() if s.image_id
    }

    try:
        # Find all ducked-managed containers in Docker
        all_containers = await asyncio.to_thread(
            docker_svc.client.containers.list,
            all=True,
            filters={"label": settings.DUCKED_LABEL_KEY},
        )
        for container in all_containers:
            if container.id not in tracked_container_ids:
                log.warning(
                    f"🧹 Orphan container found: {container.short_id}. Removing."
                )
                try:
                    container.remove(force=True, v=True)
                except Exception:
                    pass

        # Find all ducked-managed images in Docker
        all_images = await asyncio.to_thread(
            docker_svc.client.images.list,
            filters={"label": settings.DUCKED_LABEL_KEY},
        )
        for image in all_images:
            if image.id not in tracked_image_ids:
                log.warning(
                    f"🧹 Orphan image found: {image.short_id}. Removing."
                )
                try:
                    await asyncio.to_thread(
                        docker_svc.client.images.remove, image.id, force=True
                    )
                except Exception:
                    pass

    except Exception as e:
        log.debug(f"Orphan sweep Docker check failed: {e}")

    # Clean orphaned temp directories
    try:
        tmpdir = tempfile.gettempdir()
        for entry in os.listdir(tmpdir):
            if not entry.startswith("ducked_"):
                continue
            dirpath = os.path.join(tmpdir, entry)
            if not os.path.isdir(dirpath):
                continue
            # Check if any session tracks this directory
            tracked = any(s.clone_dir == dirpath for s in sessions.values())
            if not tracked:
                try:
                    age = datetime.now().timestamp() - os.path.getmtime(dirpath)
                    if age > _MAX_SESSION_LIFETIME:
                        shutil.rmtree(dirpath, ignore_errors=True)
                        log.warning(f"🧹 Orphan temp dir removed: {entry}")
                except OSError:
                    pass
    except Exception as e:
        log.debug(f"Orphan sweep temp dir check failed: {e}")


# ── Cloud Metadata / Internal IP Blocking (FIX 7) ────────────────

def _setup_iptables_rules():
    """
    Block Docker containers from accessing cloud metadata endpoints
    and internal network ranges via iptables DOCKER-USER chain.
    Requires root/sudo on Linux. On non-Linux systems (macOS), gracefully skips.
    If iptables exists but lacks permissions, logs the exact commands to run manually.
    """
    rules = [
        # Cloud metadata (AWS/GCP/Azure IAM credential theft)
        ("-d 169.254.169.254/32", "cloud metadata endpoint"),
        # Full link-local range
        ("-d 169.254.0.0/16", "link-local range"),
        # RFC1918 private ranges (host internal network)
        ("-d 10.0.0.0/8", "RFC1918 10.x.x.x"),
        ("-d 192.168.0.0/16", "RFC1918 192.168.x.x"),
    ]
    # NOTE: 172.16.0.0/12 deliberately omitted — Docker's own bridge
    # networks (172.17-31.x.x) live there and blocking them would break
    # inter-container communication during builds.

    try:
        failed_commands = []
        for rule_target, description in rules:
            cmd = ["iptables", "-C", "DOCKER-USER", *rule_target.split(), "-j", "DROP"]
            # Check if rule already exists
            check = subprocess.run(cmd, capture_output=True)
            if check.returncode == 0:
                log.info(f"🔒 iptables rule already exists: block {description}")
                continue

            # Try to add the rule
            add_cmd = ["iptables", "-I", "DOCKER-USER", *rule_target.split(), "-j", "DROP"]
            result = subprocess.run(add_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                log.info(f"🔒 iptables rule added: block {description}")
            else:
                failed_commands.append(
                    f"sudo iptables -I DOCKER-USER {rule_target} -j DROP"
                )

        if failed_commands:
            log.warning(
                "⚠️  Could not apply iptables rules (need root/sudo privileges).\n"
                "    Run these commands manually on the host BEFORE starting the engine:\n\n"
                + "\n".join(f"    {cmd}" for cmd in failed_commands)
                + "\n"
            )

    except FileNotFoundError:
        # iptables binary doesn't exist (e.g. macOS, non-Linux systems)
        log.warning(
            "⚠️  iptables not found (not a Linux system?).\n"
            "    On the PRODUCTION Linux host, run these commands before starting the engine:\n\n"
            + "\n".join(
                f"    sudo iptables -I DOCKER-USER {r[0]} -j DROP" for r in rules
            )
            + "\n"
        )
    except OSError as e:
        log.warning(f"⚠️  iptables setup failed ({e}). Metadata blocking not active.")


# ── FastAPI Application ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    log.info("=" * 60)
    log.info("🦆 DUCKED ENGINE — The Constrained Canvas")
    log.info("=" * 60)

    # Verify Docker connection
    try:
        docker_svc.client.ping()
        info = docker_svc.client.info()
        log.info(f"🐳 Docker connected: v{info.get('ServerVersion', '?')}")
    except Exception as e:
        log.critical(f"❌ Docker connection failed: {e}")
        send_alert(f"❌ Startup failed: Docker connection error: {e}")
        log.critical("Ensure Docker is running and accessible.")
        raise SystemExit(1)

    # Cleanup leftovers from previous runs
    docker_svc.cleanup_ducked_resources()

    # Ensure Docker network exists
    docker_svc.ensure_network(settings.DOCKER_NETWORK)

    # FIX 7: Apply iptables rules to block cloud metadata / internal IPs
    _setup_iptables_rules()

    # Start the reaper
    reaper_task = asyncio.create_task(reaper())

    log.info(
        f"⚙️  Constraints: CPU={settings.CONTAINER_CPU_LIMIT}, "
        f"RAM={settings.CONTAINER_MEM_LIMIT}, "
        f"TTL={settings.CONTAINER_TTL_SECONDS}s, "
        f"Max sessions={settings.MAX_CONCURRENT_SESSIONS}"
    )
    log.info(
        f"🔒 Rate limit: {settings.RATE_LIMIT_PER_MINUTE}/min, "
        f"{settings.RATE_LIMIT_PER_HOUR}/hour per IP"
    )
    log.info(f"🌐 API listening on http://{settings.API_HOST}:{settings.API_PORT}")
    log.info("=" * 60)

    yield

    # Shutdown — destroy everything
    log.info("🛑 Shutting down. Destroying all active sessions...")
    reaper_task.cancel()
    for sid in list(sessions.keys()):
        if sessions[sid].status == SessionStatus.RUNNING:
            await destroy_session(sid)
    log.info("🦆 Ducked Engine stopped. All sessions destroyed.")


app = FastAPI(
    title="Ducked Engine",
    description="The Constrained Canvas — Ephemeral code execution platform.",
    version="0.1.0",
    lifespan=lifespan,
)

# FIX 1: Register rate limiter and its exception handler
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return HTTP 429 with clear JSON error when rate limit is hit."""
    client_ip = request.client.host if request.client else "unknown"
    send_alert(f"🚨 Rate limit hit by IP `{client_ip}`")
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                f"Rate limit exceeded. "
                f"Max {settings.RATE_LIMIT_PER_MINUTE} deploys/minute, "
                f"{settings.RATE_LIMIT_PER_HOUR} deploys/hour per IP."
            )
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API Endpoints ────────────────────────────────────────────────


@app.post("/api/deploy", response_model=DeployResponse)
@limiter.limit(
    f"{settings.RATE_LIMIT_PER_MINUTE}/minute;{settings.RATE_LIMIT_PER_HOUR}/hour"
)
async def deploy(request: Request, deploy_request: DeployRequest):
    """
    Deploy a GitHub repository.
    Clones, builds, and runs the project in an isolated container.
    Rate limited: 3/minute, 10/hour per IP (FIX 1).
    """
    # FIX 6: Global concurrency cap — returns 503, not 429
    active_count = sum(
        1 for s in sessions.values()
        if s.status in (
            SessionStatus.QUEUED, SessionStatus.CLONING,
            SessionStatus.DETECTING, SessionStatus.BUILDING,
            SessionStatus.RUNNING,
        )
    )
    if active_count >= settings.MAX_CONCURRENT_SESSIONS:
        send_alert(f"⚠️ Global concurrency cap reached ({active_count} sessions)")
        raise HTTPException(
            status_code=503,
            detail=(
                f"System busy — {active_count} active sessions "
                f"(max {settings.MAX_CONCURRENT_SESSIONS}). "
                f"Try again shortly."
            ),
        )

    # Create session
    session_id = uuid.uuid4().hex
    clone_dir = os.path.join(tempfile.gettempdir(), f"ducked_{session_id}")

    session = Session(
        session_id=session_id,
        repo_url=deploy_request.repo_url,
        clone_dir=clone_dir,
    )
    sessions[session_id] = session

    # Launch pipeline in background
    asyncio.create_task(deploy_pipeline(session))

    log.info(f"📥 [{session_id}] Deploy request accepted: {deploy_request.repo_url}")

    return DeployResponse(
        session_id=session_id,
        preview_url=f"{settings.PREVIEW_BASE_URL}/preview/{session_id}",
        status=session.status.value,
        message="Deploy pipeline initiated. Check /api/sessions/{session_id} for status.",
    )


@app.get("/api/sessions")
async def list_sessions():
    """List all sessions (active and destroyed)."""
    return {
        "sessions": [s.to_dict() for s in sessions.values()],
        "active": sum(
            1 for s in sessions.values()
            if s.status == SessionStatus.RUNNING
        ),
        "total": len(sessions),
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get detailed status of a specific session."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Manually destroy a session before its TTL expires."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if session.status == SessionStatus.DESTROYED:
        return {"message": f"Session {session_id} already destroyed."}

    await destroy_session(session_id)
    return {"message": f"Session {session_id} destroyed."}


@app.get("/api/sessions/{session_id}/logs")
async def get_session_logs(session_id: str):
    """Get stdout/stderr logs from the container."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not session.container_id:
        raise HTTPException(status_code=400, detail="Container not yet started.")

    logs = docker_svc.get_logs(session.container_id)
    return {"session_id": session_id, "logs": logs}


@app.websocket("/api/sessions/{session_id}/ws")
async def session_ws(websocket: WebSocket, session_id: str):
    """
    Live log stream via WebSocket.

    FIX 8 — Log Stream Security Audit:
    - This endpoint streams ONLY container build/run stdout/stderr.
    - Event types: "status" (session state changes), "build_log" (docker build output).
    - No host environment variables, file paths, or internal network details are leaked.
    - Container env vars are all non-sensitive: HOME=/tmp, PYTHONDONTWRITEBYTECODE=1,
      PYTHONUNBUFFERED=1, NODE_ENV=production, PORT=<port>.
    - Docker socket (/var/run/docker.sock) is NOT mounted into user containers.
    - A malicious repo's code runs isolated inside its container with:
      read-only filesystem, dropped capabilities, no-new-privileges, PID limit.
    """
    session = sessions.get(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found.")
        return

    await websocket.accept()
    queue = session.subscribe()

    try:
        # Replay log history for late-joining clients
        for event in list(session._log_history):
            await websocket.send_json(event)

        # Stream live events
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        session.unsubscribe(queue)


@app.get("/api/health")
async def health():
    """Engine health check."""
    active = sum(
        1 for s in sessions.values()
        if s.status in (
            SessionStatus.QUEUED, SessionStatus.CLONING,
            SessionStatus.DETECTING, SessionStatus.BUILDING,
            SessionStatus.RUNNING,
        )
    )
    return {
        "status": "alive",
        "engine": "ducked",
        "active_sessions": active,
        "max_sessions": settings.MAX_CONCURRENT_SESSIONS,
        "container_ttl_seconds": settings.CONTAINER_TTL_SECONDS,
    }


# ── Frontend Serving ─────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    return FileResponse("../frontend/index.html")

app.mount("/static", StaticFiles(directory="../frontend"), name="frontend")

# ── Entrypoint ───────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level="info",
    )
