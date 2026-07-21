"""
Ducked Engine — Docker Service
The quarantine officer. Builds, constrains, runs, and mercilessly destroys containers.
Every container is a prisoner with a death sentence — the only question is when.
"""
import os
import json
import logging

import docker
from docker.errors import BuildError, APIError, ImageNotFound, NotFound

from config import settings
from models import ProjectType

log = logging.getLogger("ducked.docker")


class DockerService:
    """Manages the full container lifecycle: build → run → destroy."""

    def __init__(self):
        self.client = docker.from_env()

    def ensure_network(self, network_name: str) -> None:
        """Create the Docker network if it doesn't exist."""
        try:
            self.client.networks.get(network_name)
            log.info(f"Docker network '{network_name}' exists.")
        except NotFound:
            self.client.networks.create(network_name, driver="bridge")
            log.info(f"Docker network '{network_name}' created.")

    # ──────────────────────────────────────────────────────────────
    #  BUILD
    # ──────────────────────────────────────────────────────────────

    def build_image(
        self,
        clone_dir: str,
        project_type: ProjectType,
        session_id: str,
        on_log=None,
    ) -> tuple[str, str]:
        """
        Build a Docker image from the cloned repository.
        Network is OPEN during build (pip install, npm install need it).
        If on_log is provided, each build log line is streamed via on_log(line).
        Returns (image_id, image_tag).
        """
        tag = f"ducked-session:{session_id}"

        # Generate Dockerfile if the project doesn't ship one
        if project_type != ProjectType.DOCKERFILE:
            dockerfile_content = self._generate_dockerfile(clone_dir, project_type)
            with open(os.path.join(clone_dir, "Dockerfile"), "w") as f:
                f.write(dockerfile_content)
            log.info(f"Generated Dockerfile for project type: {project_type.value}")

        # Create .dockerignore to minimize build context
        dockerignore_path = os.path.join(clone_dir, ".dockerignore")
        if not os.path.exists(dockerignore_path):
            with open(dockerignore_path, "w") as f:
                f.write(
                    ".git\n.github\n.gitignore\n.vscode\n.idea\n"
                    "__pycache__\n*.pyc\n*.pyo\n"
                    "node_modules\n.npm\n"
                    ".env\n.env.*\n"
                    "*.md\nLICENSE\n"
                )

        # Build — streaming logs via low-level API
        # FIX 3: Build stage is sandboxed with CPU/memory limits.
        # Network remains open for dependency installs (pip, npm, go mod).
        # Internal/metadata IP access is blocked via iptables (setup in main.py).
        try:
            resp = self.client.api.build(
                path=clone_dir,
                tag=tag,
                rm=True,
                forcerm=True,
                nocache=True,
                labels={settings.DUCKED_LABEL_KEY: session_id},
                timeout=settings.BUILD_TIMEOUT_SECONDS,
                decode=True,
                # ── BUILD STAGE RESOURCE LIMITS ──
                container_limits={
                    "cpushares": int(settings.BUILD_CPU_LIMIT * 1024),
                    "memory": settings.BUILD_MEM_BYTES,
                    "memswap": settings.BUILD_MEM_BYTES,  # No swap
                },
            )

            for chunk in resp:
                if "stream" in chunk:
                    line = chunk["stream"].rstrip("\n")
                    if line and on_log:
                        on_log(line)
                elif "error" in chunk:
                    error_msg = chunk["error"].strip()
                    if on_log:
                        on_log(f"ERROR: {error_msg}")
                    raise RuntimeError(f"Docker build failed: {error_msg}")

            # Retrieve the built image object
            image = self.client.images.get(tag)

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Docker build failed: {e}") from e

        log.info(f"Image built: {tag} ({image.short_id})")
        return image.id, tag

    # ──────────────────────────────────────────────────────────────
    #  RUN
    # ──────────────────────────────────────────────────────────────

    def run_container(self, image_tag: str, session_id: str) -> str:
        """
        Run container with brutal, non-negotiable constraints.
        Network: isolated bridge (inbound only via Traefik). Resources: CAPPED.
        Returns container_id.
        """
        container_name = f"ducked-{session_id}"

        # ── DYNAMIC PORT DETECTION ──
        # Find out which port the container actually EXPOSEs (e.g., 5000 for Flask, 3000 for Node)
        # Fallback to config default if no EXPOSE instruction is found.
        image = self.client.images.get(image_tag)
        exposed_ports = image.attrs.get("Config", {}).get("ExposedPorts", {})
        if exposed_ports:
            # Grab the first exposed port (e.g., "5000/tcp" -> "5000")
            port = list(exposed_ports.keys())[0].split("/")[0]
        else:
            port = str(settings.CONTAINER_INTERNAL_PORT)

        # Traefik labels — the doorman's instructions
        labels = {
            settings.DUCKED_LABEL_KEY: session_id,
            "traefik.enable": "true",
            f"traefik.http.routers.ducked-{session_id}.rule":
                f"PathPrefix(`/preview/{session_id}`)",
            f"traefik.http.routers.ducked-{session_id}.entrypoints": "web",
            f"traefik.http.middlewares.strip-{session_id}.stripprefix.prefixes":
                f"/preview/{session_id}",
            f"traefik.http.routers.ducked-{session_id}.middlewares":
                f"strip-{session_id}",
            f"traefik.http.services.ducked-{session_id}.loadbalancer.server.port":
                port,
        }

        try:
            container = self.client.containers.run(
                image_tag,
                detach=True,
                name=container_name,

                # ── RESOURCE CONSTRAINTS ──
                nano_cpus=int(settings.CONTAINER_CPU_LIMIT * 1e9),
                mem_limit=settings.CONTAINER_MEM_LIMIT,
                memswap_limit=settings.CONTAINER_MEM_LIMIT,   # No swap
                pids_limit=settings.CONTAINER_PIDS_LIMIT,      # Fork bomb protection

                # ── NETWORK ──
                network=settings.DOCKER_NETWORK,               # Traefik-routable bridge

                # ── FILESYSTEM CONSTRAINTS ──
                read_only=True,
                tmpfs={
                    "/tmp": "size=64m,mode=1777",
                    "/run": "size=16m,mode=1777",
                },

                # ── SECURITY HARDENING ──
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                cap_add=["NET_BIND_SERVICE"],

                # ── ENVIRONMENT ──
                environment={
                    "HOME": "/tmp",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUNBUFFERED": "1",
                    "NODE_ENV": "production",
                    "PORT": str(port),
                },

                # ── TRAEFIK LABELS ──
                labels=labels,
            )
        except Exception as e:
            log.warning(f"Container start failed, cleaning up orphan: {e}")
            try:
                orphan = self.client.containers.get(container_name)
                orphan.remove(force=True, v=True)
                log.info(f"Orphaned container removed: {container_name}")
            except (NotFound, APIError):
                pass
            raise

        log.info(
            f"Container started: {container.short_id} | "
            f"CPU: {settings.CONTAINER_CPU_LIMIT} | "
            f"RAM: {settings.CONTAINER_MEM_LIMIT} | "
            f"PIDs: {settings.CONTAINER_PIDS_LIMIT} | "
            f"NET: {settings.DOCKER_NETWORK} | "
            f"Preview: /preview/{session_id}"
        )
        return container.id

    # ──────────────────────────────────────────────────────────────
    #  DESTROY
    # ──────────────────────────────────────────────────────────────

    def destroy_container(self, container_id: str) -> None:
        """Kill and remove a container. No mercy, no questions."""
        short = container_id[:12]
        try:
            container = self.client.containers.get(container_id)
            container.kill()
            log.info(f"Container killed: {short}")
        except (NotFound, APIError):
            log.debug(f"Container already dead: {short}")

        try:
            container = self.client.containers.get(container_id)
            container.remove(force=True, v=True)
            log.info(f"Container removed: {short}")
        except (NotFound, APIError):
            log.debug(f"Container already removed: {short}")

    def destroy_image(self, image_id: str) -> None:
        """Remove image and all its layers. Leave nothing behind."""
        short = image_id[:12] if len(image_id) > 12 else image_id
        try:
            self.client.images.remove(image_id, force=True, noprune=False)
            log.info(f"Image purged: {short}")
        except (ImageNotFound, APIError) as e:
            log.debug(f"Image removal note: {e}")

    def get_logs(self, container_id: str, tail: int = 200) -> str:
        """Retrieve container stdout/stderr logs."""
        try:
            container = self.client.containers.get(container_id)
            return container.logs(tail=tail, timestamps=True).decode(
                "utf-8", errors="replace"
            )
        except (NotFound, APIError):
            return "[Container not found or already destroyed]"

    def cleanup_ducked_resources(self) -> None:
        """
        Nuclear cleanup: remove ALL ducked-managed containers and images.
        Called on engine startup to clean leftover debris from previous runs.
        """
        # Containers
        containers = self.client.containers.list(
            all=True,
            filters={"label": settings.DUCKED_LABEL_KEY},
        )
        for c in containers:
            try:
                c.remove(force=True, v=True)
                log.info(f"Startup cleanup: removed container {c.short_id}")
            except APIError:
                pass

        # Images
        images = self.client.images.list(
            filters={"label": settings.DUCKED_LABEL_KEY},
        )
        for img in images:
            try:
                self.client.images.remove(img.id, force=True)
                log.info(f"Startup cleanup: removed image {img.short_id}")
            except (ImageNotFound, APIError):
                pass

        if containers or images:
            log.info(
                f"Startup cleanup complete: "
                f"{len(containers)} containers, {len(images)} images removed."
            )

    # ──────────────────────────────────────────────────────────────
    #  DOCKERFILE GENERATION
    # ──────────────────────────────────────────────────────────────

    def _generate_dockerfile(self, clone_dir: str, project_type: ProjectType) -> str:
        generators = {
            ProjectType.PYTHON: self._dockerfile_python,
            ProjectType.NODE: self._dockerfile_node,
            ProjectType.STATIC: self._dockerfile_static,
            ProjectType.GO: self._dockerfile_go,
            ProjectType.UNKNOWN: self._dockerfile_generic,
        }
        generator = generators.get(project_type, self._dockerfile_generic)
        return generator(clone_dir)

    def _dockerfile_go(self, clone_dir: str) -> str:
        port = settings.CONTAINER_INTERNAL_PORT
        return f"""FROM golang:alpine AS builder

WORKDIR /app
COPY . .
RUN go mod download || true
RUN go build -o app_binary .

FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/app_binary .

# Non-root user
RUN adduser -D -H ducked
USER ducked

EXPOSE {port}
CMD ["./app_binary"]
"""

    def _dockerfile_python(self, clone_dir: str) -> str:
        cmd = self._detect_python_cmd(clone_dir)
        port = settings.CONTAINER_INTERNAL_PORT

        # Determine install strategy based on available files
        install_lines = []
        has_requirements = os.path.exists(os.path.join(clone_dir, "requirements.txt"))
        has_pyproject = os.path.exists(os.path.join(clone_dir, "pyproject.toml"))
        has_setup_py = os.path.exists(os.path.join(clone_dir, "setup.py"))

        if has_requirements:
            install_lines.append("COPY requirements.txt ./")
            install_lines.append(
                "RUN pip install --no-cache-dir -r requirements.txt"
            )

        # Always install uvicorn as a fallback ASGI server
        install_lines.append(
            "RUN pip install --no-cache-dir uvicorn 2>/dev/null || true"
        )

        install_block = "\n".join(install_lines)

        # Post-copy install for pyproject.toml / setup.py projects
        post_copy = ""
        if has_pyproject or has_setup_py:
            post_copy = "RUN pip install --no-cache-dir . 2>/dev/null || true"

        return f"""FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    HOME=/tmp

WORKDIR /app

# Install dependencies (network available during build)
{install_block}

# Copy project source
COPY . .
{post_copy}

# Non-root user — principle of least privilege
RUN adduser --disabled-password --no-create-home --gecos "" ducked
USER ducked

EXPOSE {port}
CMD {cmd}
"""

    def _dockerfile_node(self, clone_dir: str) -> str:
        cmd = self._detect_node_cmd(clone_dir)
        port = settings.CONTAINER_INTERNAL_PORT

        return f"""FROM node:20-alpine

ENV NODE_ENV=production \\
    HOME=/tmp

WORKDIR /app

# Install dependencies (network available during build)
COPY package*.json ./
RUN npm ci --omit=dev 2>/dev/null || npm install --omit=dev 2>/dev/null || true

# Copy project source
COPY . .

# Non-root user
RUN adduser -D -H ducked
USER ducked

EXPOSE {port}
CMD {cmd}
"""

    def _dockerfile_static(self, clone_dir: str) -> str:
        port = settings.CONTAINER_INTERNAL_PORT

        return f"""FROM python:3.12-alpine

ENV HOME=/tmp

WORKDIR /srv

# Copy static files
COPY . .

# Non-root user
RUN adduser -D -H ducked
USER ducked

EXPOSE {port}
CMD ["python", "-m", "http.server", "{port}"]
"""

    def _dockerfile_generic(self, clone_dir: str) -> str:
        port = settings.CONTAINER_INTERNAL_PORT
        return f"""FROM alpine:latest

WORKDIR /app
COPY . .

EXPOSE {port}
CMD ["sh", "-c", "echo '[ducked] Container alive. No known entrypoint detected.'; sleep 30"]
"""

    # ──────────────────────────────────────────────────────────────
    #  ENTRYPOINT DETECTION
    # ──────────────────────────────────────────────────────────────

    def _detect_python_cmd(self, clone_dir: str) -> str:
        """Detect the best CMD for a Python project."""
        port = str(settings.CONTAINER_INTERNAL_PORT)

        # 1. Check Procfile (highest priority — developer's explicit intent)
        procfile_path = os.path.join(clone_dir, "Procfile")
        if os.path.exists(procfile_path):
            with open(procfile_path) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("web:"):
                        cmd = stripped.split(":", 1)[1].strip()
                        parts = cmd.split()
                        return json.dumps(parts)

        # 2. Read ONLY requirements.txt / Pipfile for framework detection.
        #    DO NOT read pyproject.toml here — it contains the project's own name
        #    which causes false positives (e.g. pallets/flask would match "flask").
        reqs_content = ""
        for marker_file in ("requirements.txt", "Pipfile"):
            path = os.path.join(clone_dir, marker_file)
            if os.path.exists(path):
                with open(path) as f:
                    reqs_content += f.read().lower() + "\n"

        has_flask = "flask" in reqs_content
        has_fastapi = "fastapi" in reqs_content or "uvicorn" in reqs_content
        has_django = "django" in reqs_content

        # 3. Detect entry file
        entry_file = None
        for candidate in ("app.py", "main.py", "server.py", "run.py", "wsgi.py"):
            if os.path.exists(os.path.join(clone_dir, candidate)):
                entry_file = candidate
                break

        # 4. Django
        if has_django and os.path.exists(os.path.join(clone_dir, "manage.py")):
            return f'["python", "manage.py", "runserver", "0.0.0.0:{port}"]'

        # 5. FastAPI / ASGI
        if has_fastapi and entry_file:
            module = entry_file.replace(".py", "")
            return f'["uvicorn", "{module}:app", "--host", "0.0.0.0", "--port", "{port}"]'

        # 6. Flask
        if has_flask:
            target = entry_file or "app.py"
            module = target.replace(".py", "")
            return (
                f'["flask", "--app", "{module}", "run", '
                f'"--host", "0.0.0.0", "--port", "{port}"]'
            )

        # 7. Generic Python with detected entry file
        if entry_file:
            return f'["python", "{entry_file}"]'

        # 8. Last resort
        return (
            '["python", "-c", '
            '"print(\'[ducked] No Python entrypoint detected.\'); '
            'import time; time.sleep(30)"]'
        )

    def _detect_node_cmd(self, clone_dir: str) -> str:
        """Detect the best CMD for a Node.js project."""

        pkg_path = os.path.join(clone_dir, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path) as f:
                    pkg = json.load(f)
            except (json.JSONDecodeError, OSError):
                pkg = {}

            # Check scripts.start
            if pkg.get("scripts", {}).get("start"):
                return '["npm", "start"]'

            # Check main field
            if "main" in pkg:
                return f'["node", "{pkg["main"]}"]'

        # Check common entry files
        for candidate in ("index.js", "app.js", "server.js", "main.js", "src/index.js"):
            if os.path.exists(os.path.join(clone_dir, candidate)):
                return f'["node", "{candidate}"]'

        return (
            '["node", "-e", '
            '"console.log(\'[ducked] No Node.js entrypoint detected.\'); '
            'setTimeout(()=>{},30000)"]'
        )
