# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-22

### Added

- **Core Engine**: FastAPI-based orchestrator with full ephemeral lifecycle (clone → detect → build → run → destroy).
- **Heuristic Detection**: Automatic project type detection for Python, Node.js, Go, Static HTML, and Dockerfile projects.
- **Nested Project Support**: Detects and promotes projects nested one level deep inside subdirectories.
- **Dynamic Dockerfile Generation**: On-the-fly Dockerfile synthesis tailored to each detected project type.
- **Python Entrypoint Detection**: Automatic detection of Flask, FastAPI/ASGI, Django, and generic Python apps via Procfile, requirements.txt, and file heuristics.
- **Node.js Entrypoint Detection**: Reads `package.json` scripts, main field, and common entry files.
- **Go Multi-Stage Builds**: Compiled Go binaries via `golang:alpine` builder stage.
- **Container Sandboxing**: Read-only filesystem, dropped capabilities, no-new-privileges, PID limits, CPU/memory cgroup constraints.
- **Build-Stage Resource Limits**: CPU, memory, and timeout constraints during `docker build`.
- **Reaper**: Background loop that destroys containers after TTL expiry (60 seconds).
- **Orphan Sweep**: Periodic cleanup of Docker resources and temp directories not tracked in memory.
- **Startup Cleanup**: Automatic removal of leftover ducked-managed containers/images from previous runs.
- **Repo Size Enforcement**: Two-layer protection — GitHub API pre-clone check (50MB) + post-clone disk check (100MB).
- **SSRF Prevention**: Strict URL validation, scheme restrictions, metadata IP blocking via iptables.
- **Rate Limiting**: Per-IP rate limits (3/min, 10/hour) with secure X-Forwarded-For handling for trusted proxies.
- **Global Concurrency Cap**: Maximum 10 simultaneous sessions with HTTP 503 response.
- **WebSocket Log Streaming**: Real-time build/run log streaming with history replay for late-joining clients.
- **Traefik Integration**: Dynamic reverse proxy routing with automatic HTTPS via Let's Encrypt.
- **Frontend**: Single-page vanilla HTML/CSS/JS app for submitting repos and watching live deployments.
- **Discord Webhooks**: Optional alert system for rate limit hits, concurrency caps, and startup failures.
- **REST API**: Full session management (deploy, list, status, destroy, logs, health check).

### Security

- All container capabilities dropped except `NET_BIND_SERVICE`.
- Read-only root filesystem with limited tmpfs mounts.
- Cloud metadata endpoint blocking (169.254.169.254) via iptables DOCKER-USER chain.
- RFC1918 private range blocking for container network isolation.
- No Docker socket mounted into user containers.
- `no-new-privileges` security option on all containers.

[Unreleased]: https://github.com/thevalmarch/Ducked/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/thevalmarch/Ducked/releases/tag/v0.1.0
