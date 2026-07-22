<p align="center">
  <h1 align="center">🦆 Ducked Engine</h1>
  <p align="center"><strong>The Constrained Canvas</strong> — Paste a repo. Watch it live. Watch it die.</p>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/docker-required-2496ED.svg?logo=docker&logoColor=white" alt="Docker Required">
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

---

Ducked is an ephemeral code execution platform that clones any public GitHub repository, builds it inside an isolated Docker container with brutal resource constraints, lets it live for exactly **60 seconds**, then destroys everything — container, image, and cloned files. Zero traces remain.

---

## How It Works

```
User submits GitHub URL
        │
        ▼
   ┌─────────┐     ┌───────────┐     ┌──────────┐     ┌─────────┐
   │  Clone  │────▶│  Detect   │────▶│  Build   │────▶│   Run   │
   │  (git)  │     │(heuristic)│     │ (docker) │     │ (live!) │
   └─────────┘     └───────────┘     └──────────┘     └────┬────┘
                                                           │ 60s
                                                           ▼
                                                     ┌──────────┐
                                                     │ DESTROY  │
                                                     │ (reaper) │
                                                     └──────────┘
```

1. **Clone** — Shallow clone (`--depth 1`) of the target repository.
2. **Detect** — Heuristic engine analyzes the codebase and identifies the project type (Python, Node.js, Go, Static HTML, or Dockerfile).
3. **Build** — An optimized Dockerfile is synthesized on-the-fly and the image is built with streaming logs.
4. **Run** — The container starts with hard resource constraints. Traefik dynamically routes traffic to it.
5. **Destroy** — After 60 seconds, the Reaper kills the container, purges the image, and wipes all temporary files.

---

## Supported Project Types

| Type | Detection | Base Image |
|------|-----------|------------|
| **Python** | `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile` | `python:3.12-slim` |
| **Node.js** | `package.json` | `node:20-alpine` |
| **Go** | `go.mod` | `golang:alpine` (multi-stage) |
| **Static HTML** | `index.html` | `python:3.12-alpine` (http.server) |
| **Dockerfile** | `Dockerfile` at root | Project's own Dockerfile |

The heuristic engine also detects nested project structures and automatically promotes them to the root level.

---

## Security Constraints

Every container runs inside a hardened sandbox:

| Constraint | Value | Purpose |
|-----------|-------|---------| 
| **CPU** | 0.5 cores | Prevent crypto-mining and infinite loops |
| **Memory** | 256 MB (no swap) | OOM-Killer terminates memory hogs |
| **PIDs** | 50 max | Fork bomb protection |
| **Filesystem** | Read-only + tmpfs | No persistent writes to host |
| **Capabilities** | `ALL` dropped, only `NET_BIND_SERVICE` | Minimal privilege |
| **Privileges** | `no-new-privileges` | No privilege escalation |
| **Network** | Isolated bridge (`ducked-net`) | No direct host access |
| **TTL** | 60 seconds | Guaranteed destruction |

For the full security architecture and responsible disclosure policy, see [SECURITY.md](SECURITY.md).

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker Engine running
- Git

### 1. Clone the repository

```bash
git clone https://github.com/thevalmarch/Ducked.git
cd Ducked
```

### 2. Set up environment (optional)

```bash
cp .env.example .env
# Edit .env to configure Discord webhooks, etc.
```

### 3. Start Traefik (reverse proxy)

```bash
make traefik
# or: docker compose up -d
```

### 4. Install dependencies

```bash
make install
# or: cd backend && pip install -r requirements.txt
```

### 5. Run the engine

```bash
make dev
# or: cd backend && python main.py
```

The engine starts at `http://localhost:9000`. Open it in your browser, paste a GitHub URL, and watch.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_WEBHOOK_URL` | `None` | Discord webhook for operational alerts |
| `ACME_EMAIL` | `thevalmarch@gmail.com` | Email for Let's Encrypt certificates (Traefik) |

See [`.env.example`](.env.example) for a ready-to-use template.

---

## API Reference

### Deploy a Repository
```
POST /api/deploy
Content-Type: application/json

{"repo_url": "https://github.com/user/repo"}
```

### List Sessions
```
GET /api/sessions
```

### Get Session Status
```
GET /api/sessions/{session_id}
```

### Get Session Logs
```
GET /api/sessions/{session_id}/logs
```

### Destroy a Session Early
```
DELETE /api/sessions/{session_id}
```

### Live Log Stream (WebSocket)
```
WS /api/sessions/{session_id}/ws
```

### Health Check
```
GET /api/health
```

---

## Production Deployment

The Quick Start above runs everything on `localhost` for local development. Running Ducked for real (public) usage requires:

- **A VPS** (or any Linux host) with Docker installed — the sandboxing (iptables rules, cgroup limits) assumes a real Linux kernel, not macOS/Windows Docker Desktop.
- **Traefik** as the reverse proxy in front of the engine, handling routing to ephemeral preview containers (`docker-compose.yml` provides the base config) and TLS termination.
- **A domain name** pointed at the VPS, with `PREVIEW_BASE_URL` in `backend/config.py` updated from `http://localhost` to your real domain (e.g. `https://ducked.dev`), and Traefik configured for automatic HTTPS (e.g. via Let's Encrypt).
- Running the iptables rules printed at startup (metadata/internal-IP blocking) — these only apply automatically on Linux hosts with root/sudo.

Without these, the engine works but is only reachable locally and isn't hardened for public exposure.

---

## Architecture

```
frontend/
  index.html          # Single-page app (vanilla HTML/CSS/JS)

backend/
  main.py             # FastAPI orchestrator + Reaper loop
  config.py           # All constraints and settings
  models.py           # Pydantic schemas + Session state machine
  services/
    github_service.py # Git clone + heuristic project detection
    docker_service.py # Build, run, destroy + Dockerfile synthesis

docker-compose.yml    # Traefik reverse proxy configuration
```

---

## Development

```bash
make help          # Show all available commands
make dev           # Start the engine
make test          # Run unit tests
make lint          # Compile-check all Python files
make clean         # Remove all ducked Docker resources
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development workflow.

---

## Philosophy

Ducked is not Vercel. Ducked is not Heroku. Those platforms keep code alive. Ducked lets code **prove it deserves to live** — within 256MB of RAM, half a CPU core, and 60 ticking seconds. If it survives, you see it run. If it doesn't, it dies on the first second.

That's not a bug. That's the feature.

---

## Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md) before opening a PR.

## Security

Found a vulnerability? Please report it responsibly. See [SECURITY.md](SECURITY.md) for our disclosure policy.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Made with 🦆 by <a href="https://github.com/thevalmarch">Val March</a>
</p>
