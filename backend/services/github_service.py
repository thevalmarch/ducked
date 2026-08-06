"""
Ducked Engine — Git Service
Clones repositories and identifies project types.
Every incoming repo is an unknown entity to be analyzed before quarantine.

Handles any forge in settings.ALLOWED_GIT_HOSTS — GitHub, GitLab, Gitea,
Forgejo, and self-hosted instances. Only the pre-clone size check is
forge-specific; cloning and detection are the same everywhere.
"""
import os
import shutil
import subprocess
import logging
from urllib.parse import urlsplit

import httpx

from config import settings
from models import ProjectType

log = logging.getLogger("ducked.github")


class GitHubService:
    """Handles git operations and project type detection."""

    # ── Repo Size Enforcement ─────────────────────────────────────

    @staticmethod
    def parse_repo_url(repo_url: str) -> tuple[str, str, str]:
        """
        Split a validated repo URL into (host, owner_path, repo).

        owner_path is everything before the final segment, so GitLab
        subgroups survive: group/subgroup for .../group/subgroup/project.
        """
        parts = urlsplit(repo_url)
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) < 2:
            raise RuntimeError(f"Cannot parse owner/repo from URL: {repo_url}")

        repo = segments[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        return parts.netloc.lower(), "/".join(segments[:-1]), repo

    def _size_api_url(self, host: str, owner_path: str, repo: str) -> str | None:
        """
        The API endpoint that reports repository size in KB, or None if we
        do not know how to ask this forge.

        GitHub has a dedicated API host. Gitea and Forgejo both expose
        /api/v1/repos/{owner}/{repo} on the instance itself, which covers
        Codeberg, gitea.com, and self-hosted instances.

        GitLab is deliberately absent: repository size sits behind
        ?statistics=true, which requires privileges a public reader does
        not have. Those clones fall through to the post-clone disk check.
        """
        if host == "github.com":
            return f"https://api.github.com/repos/{owner_path}/{repo}"

        # Assume a Gitea-compatible API and treat a bad response as
        # "unknown forge" rather than an error.
        return f"https://{host}/api/v1/repos/{owner_path}/{repo}"

    def check_repo_size(self, repo_url: str) -> None:
        """
        Layer 1: Pre-clone size check via the forge's API.
        Rejects repos larger than MAX_REPO_SIZE_MB before any clone attempt.
        Gracefully degrades if the API is unreachable or the forge is not
        one we can query — Layer 2 (post-clone disk check) catches those,
        bounded by CLONE_TIMEOUT_SECONDS.
        """
        host, owner_path, repo = self.parse_repo_url(repo_url)
        is_github = host == "github.com"
        api_url = self._size_api_url(host, owner_path, repo)

        if api_url is None:
            log.info(
                f"No size API known for {host}. "
                f"Relying on the post-clone disk check."
            )
            return

        try:
            # follow_redirects=False prevents SSRF via redirect to internal host
            resp = httpx.get(
                api_url,
                timeout=10.0,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )

            if resp.status_code in (301, 302, 307, 308):
                # Repo was renamed. Only follow if the redirect stays on the
                # same host we already trusted.
                location = resp.headers.get("location", "")
                expected = "https://api.github.com/" if is_github else f"https://{host}/"
                if not location.startswith(expected):
                    raise RuntimeError(
                        f"{host} API redirected to unexpected host: {location}"
                    )
                resp = httpx.get(
                    location,
                    timeout=10.0,
                    follow_redirects=False,
                    headers={"Accept": "application/json"},
                )

            if resp.status_code == 404 and is_github:
                raise RuntimeError(
                    f"Repository not found: {owner_path}/{repo}. "
                    "Is it a public repository?"
                )

            if resp.status_code != 200:
                # For non-GitHub hosts this usually means the instance is not
                # Gitea-compatible (GitLab, for one), not that the repo is
                # missing. Let the clone be the judge.
                log.warning(
                    f"{host} API returned {resp.status_code} for "
                    f"{owner_path}/{repo}. Skipping pre-clone size check "
                    f"(post-clone disk check will enforce limits)."
                )
                return

            data = resp.json()
            size_kb = data.get("size")
            if not isinstance(size_kb, (int, float)):
                log.warning(
                    f"{host} API response for {owner_path}/{repo} has no usable "
                    f"size field. Skipping pre-clone size check."
                )
                return

            size_mb = size_kb / 1024.0

            if size_mb > settings.MAX_REPO_SIZE_MB:
                raise RuntimeError(
                    f"Repository too large: {size_mb:.1f}MB "
                    f"(limit: {settings.MAX_REPO_SIZE_MB}MB). "
                    f"Rejected before clone."
                )

            log.info(
                f"Pre-clone size check passed: {host}/{owner_path}/{repo} = "
                f"{size_mb:.1f}MB (limit: {settings.MAX_REPO_SIZE_MB}MB)"
            )

        except httpx.HTTPError as e:
            # API unreachable (rate limit, network issue, non-existent host).
            # Let it through — Layer 2 (post-clone disk check) will catch it.
            log.warning(
                f"{host} API check failed ({e}). "
                f"Proceeding with clone — post-clone disk check will enforce limits."
            )
        except ValueError as e:
            # Response was not JSON — almost certainly not a Gitea-style API.
            log.warning(
                f"{host} API returned a non-JSON response ({e}). "
                f"Skipping pre-clone size check."
            )

    def check_clone_disk_usage(self, clone_dir: str) -> None:
        """
        Layer 2: Post-clone disk usage check.
        Measures actual directory size and aborts if it exceeds MAX_CLONE_DISK_MB.
        This catches repos where the forge's size estimate was wrong, and is
        the only size enforcement for forges we cannot query.
        """
        total_bytes = 0
        for dirpath, _dirnames, filenames in os.walk(clone_dir):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_bytes += os.path.getsize(filepath)
                except OSError:
                    pass

        total_mb = total_bytes / (1024 * 1024)

        if total_mb > settings.MAX_CLONE_DISK_MB:
            # Delete the oversized clone immediately
            shutil.rmtree(clone_dir, ignore_errors=True)
            raise RuntimeError(
                f"Cloned repository too large: {total_mb:.1f}MB "
                f"(limit: {settings.MAX_CLONE_DISK_MB}MB). "
                f"Clone deleted."
            )

        log.info(
            f"Post-clone size check passed: {total_mb:.1f}MB "
            f"(limit: {settings.MAX_CLONE_DISK_MB}MB)"
        )

    def clone(self, repo_url: str, target_dir: str) -> None:
        """
        Shallow clone a repository from any allowlisted forge.
        --depth 1 + --single-branch: absolute minimum data transfer.
        We don't need commit history. We need the code. Nothing more.
        """
        log.info(f"Cloning {repo_url} → {target_dir}")

        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", repo_url, target_dir],
            capture_output=True,
            text=True,
            timeout=settings.CLONE_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"git clone failed (exit {result.returncode}): {stderr}")

        log.info("Clone complete.")

    def detect_project_type(self, clone_dir: str) -> ProjectType:
        """
        Analyze cloned directory to determine the project type.
        Detection priority:
          1. Dockerfile (project knows how to build itself)
          2. Python markers (requirements.txt, pyproject.toml, etc.)
          3. Node.js markers (package.json)
          4. Static HTML (index.html at root)
          5. Unknown
        """
        try:
            entries = set(os.listdir(clone_dir))
        except OSError as e:
            log.error(f"Cannot read clone directory: {e}")
            return ProjectType.UNKNOWN

        # 1 — Project ships its own Dockerfile
        if "Dockerfile" in entries or "dockerfile" in entries:
            return ProjectType.DOCKERFILE

        # 2 — Python indicators
        python_markers = {
            "requirements.txt", "pyproject.toml", "setup.py",
            "Pipfile", "setup.cfg",
        }
        if entries & python_markers:
            return ProjectType.PYTHON

        # 3 — Node.js indicators
        if "package.json" in entries:
            return ProjectType.NODE

        # 3.5 — Go indicators
        if "go.mod" in entries:
            return ProjectType.GO

        # 4 — Static HTML site
        if "index.html" in entries:
            return ProjectType.STATIC

        # 5 — Check immediate subdirectories (app is nested inside a folder)
        for entry in entries:
            full_path = os.path.join(clone_dir, entry)
            if os.path.isdir(full_path) and not entry.startswith("."):
                try:
                    sub_entries = set(os.listdir(full_path))
                except OSError:
                    continue
                
                def promote():
                    import shutil
                    # Move everything from subfolder to root, overwriting if needed
                    for item in sub_entries:
                        src = os.path.join(full_path, item)
                        dst = os.path.join(clone_dir, item)
                        if os.path.exists(dst):
                            if os.path.isdir(dst):
                                shutil.rmtree(dst)
                            else:
                                os.remove(dst)
                        shutil.move(src, clone_dir)
                    shutil.rmtree(full_path)
                    log.info(f"Promoted nested app directory: {entry}")

                if "Dockerfile" in sub_entries or "dockerfile" in sub_entries:
                    promote()
                    return ProjectType.DOCKERFILE
                    
                if "package.json" in sub_entries:
                    promote()
                    return ProjectType.NODE
                    
                if "go.mod" in sub_entries:
                    promote()
                    return ProjectType.GO
                    
                if sub_entries & python_markers:
                    promote()
                    return ProjectType.PYTHON
                    
                if "index.html" in sub_entries:
                    promote()
                    return ProjectType.STATIC

        return ProjectType.UNKNOWN
