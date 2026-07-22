# Contributing to Ducked

First off — thank you for considering contributing to Ducked! Every bug report, feature idea, and pull request helps make this project better.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Running Tests](#running-tests)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code. Please report unacceptable behavior via the channels listed in the Code of Conduct.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/Ducked.git
   cd Ducked
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feat/your-feature-name
   ```

---

## Development Setup

### Prerequisites

- Python 3.11+
- Docker Engine running
- Git

### Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

Or use the Makefile:

```bash
make install
```

### Start Traefik (reverse proxy)

```bash
make traefik
# or: docker compose up -d
```

### Run the Engine

```bash
make dev
# or: cd backend && python main.py
```

The engine starts at `http://localhost:9000`.

---

## Making Changes

- Keep changes **focused** — one feature or fix per PR.
- Follow existing code patterns and style.
- Add or update tests for any new functionality.
- Update documentation (README, docstrings) if behavior changes.
- Do **not** commit `.env`, secrets, or generated files.

### Code Style

- **Python**: Follow PEP 8. Use type hints. Keep docstrings on public methods.
- **HTML/CSS/JS**: Keep the frontend as a single `index.html` — vanilla, no build tools.
- **Dockerfiles**: Follow best practices (multi-stage builds, non-root users, minimal layers).

---

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Maintenance (deps, CI, tooling) |
| `security` | Security-related changes |

### Examples

```
feat(docker): add Rust project type detection
fix(reaper): prevent double-destroy race condition
docs: update API reference with /logs endpoint
security(build): restrict build-stage network access
```

---

## Pull Request Process

1. **Ensure tests pass** before submitting:
   ```bash
   make test
   ```
2. **Update the CHANGELOG** (`CHANGELOG.md`) under `[Unreleased]`.
3. **Open a PR** against the `main` branch.
4. **Fill out the PR template** — describe what changed, why, and how you tested it.
5. A maintainer will review your PR. Be open to feedback and iteration.

---

## Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

Or:

```bash
make test
```

Tests cover:
- Heuristic project detection engine
- URL validation and SSRF prevention
- Session state machine behavior

> **Note**: Integration tests that involve Docker require a running Docker daemon.

---

## Reporting Bugs

Use the [Bug Report](https://github.com/thevalmarch/Ducked/issues/new?template=bug_report.md) issue template. Include:

- Steps to reproduce
- Expected vs. actual behavior
- Your environment (OS, Python version, Docker version)
- Relevant logs (sanitize any sensitive info)

---

## Suggesting Features

Use the [Feature Request](https://github.com/thevalmarch/Ducked/issues/new?template=feature_request.md) issue template. Describe:

- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

---

## Questions?

Open a [Discussion](https://github.com/thevalmarch/Ducked/discussions) or an issue — we're happy to help.
