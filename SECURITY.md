# Security Policy

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

If you discover a security vulnerability in Ducked, please report it responsibly:

1. **Email**: Send a detailed report to **[thevalmarch@gmail.com](mailto:thevalmarch@gmail.com)**
2. **Subject line**: `[SECURITY] Brief description of the vulnerability`
3. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

| Action | Timeline |
|--------|----------|
| Acknowledgment of report | Within 48 hours |
| Initial assessment | Within 1 week |
| Fix and disclosure | Within 30 days (coordinated) |

We will credit reporters in the CHANGELOG and README (unless you prefer to remain anonymous).

---

## Security Architecture

Ducked executes **untrusted code** from public GitHub repositories. Security is not optional — it's the core design constraint. Every container is treated as hostile.

### Container Isolation

| Layer | Control | Purpose |
|-------|---------|---------|
| **CPU** | 0.5 cores (cgroup) | Prevent crypto-mining, infinite loops |
| **Memory** | 256MB, no swap | OOM-Killer terminates memory hogs |
| **PIDs** | 50 max | Fork bomb protection |
| **Filesystem** | Read-only root + tmpfs | No persistent writes to host |
| **Capabilities** | ALL dropped, only `NET_BIND_SERVICE` | Minimal privilege |
| **Privileges** | `no-new-privileges` | No privilege escalation |
| **Network** | Isolated bridge (`ducked-net`) | No direct host access |
| **TTL** | 60 seconds | Guaranteed destruction |

### Network Security

- **iptables rules** block containers from accessing:
  - Cloud metadata endpoints (`169.254.169.254`)
  - Link-local range (`169.254.0.0/16`)
  - RFC1918 private ranges (`10.0.0.0/8`, `192.168.0.0/16`)
- Docker socket (`/var/run/docker.sock`) is **never** mounted into user containers.
- Build network is open (for `pip install`, `npm install`) but metadata/internal IPs are blocked.

### Input Validation

- **URL validation**: Only `https://github.com/owner/repo` format accepted.
- **SSRF prevention**: `file://`, `git://`, `ssh://`, `http://` schemes rejected.
- **Repo size limits**: Pre-clone (GitHub API, 50MB) + post-clone (disk, 100MB).
- **Rate limiting**: Per-IP (3/min, 10/hour) to prevent abuse.
- **Concurrency cap**: Max 10 simultaneous sessions globally.

### Cleanup Guarantees

- **Reaper loop**: Background task checks every 2 seconds for expired containers.
- **Orphan sweep**: Every 30 seconds, scans for Docker resources not tracked in memory.
- **Startup cleanup**: On engine restart, all previous ducked-managed resources are destroyed.

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Current |

---

## Known Limitations

These are **not vulnerabilities** but documented security boundaries:

1. **Build-stage network access**: Containers have network access during `docker build` (needed for dependency installation). Metadata/internal IPs are blocked via iptables, but outbound internet access to arbitrary hosts is allowed during build.

2. **Docker Desktop (macOS/Windows)**: The iptables-based metadata blocking only works on Linux hosts. Docker Desktop environments lack iptables support. **Do not run Ducked in production on macOS/Windows.**

3. **In-memory state**: Sessions are stored in memory only. A process crash loses all session tracking (but the orphan sweep recovers Docker resources on restart).

4. **Single-process**: The engine runs as a single FastAPI process. There is no distributed session state or horizontal scaling.

---

## Scope

The following are **in scope** for security reports:

- Container escape or privilege escalation
- Host filesystem access from user containers
- SSRF via repository URL manipulation
- Credential theft (cloud metadata, environment variables)
- Denial of service beyond rate limits
- Log injection or XSS via WebSocket stream

The following are **out of scope**:

- Self-hosted instances with misconfigured Docker/firewall
- Vulnerabilities in upstream dependencies (report to the dependency maintainer)
- Social engineering attacks
