"""
Ducked Engine — GitHub Service
Clones repositories and identifies project types.
Every incoming repo is an unknown entity to be analyzed before quarantine.
"""
import os
import re
import shutil
import subprocess
import logging

import httpx

from config import settings
from models import ProjectType

log = logging.getLogger("ducked.github")


class GitHubService:
    """Handles git operations and project type detection."""

    # ── Repo Size Enforcement ─────────────────────────────────────

    def check_repo_size(self, repo_url: str) -> None:
        """
        Layer 1: Pre-clone size check via GitHub API.
        Rejects repos larger than MAX_REPO_SIZE_MB before any clone attempt.
        Gracefully degrades if the API is unreachable — Layer 2 catches it.
        """
        # Extract owner/repo from validated URL
        match = re.match(
            r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", repo_url
        )
        if not match:
            raise RuntimeError(f"Cannot parse owner/repo from URL: {repo_url}")

        owner, repo = match.group(1), match.group(2)
        api_url = f"https://api.github.com/repos/{owner}/{repo}"

        try:
            # follow_redirects=False prevents SSRF via redirect to internal host
            resp = httpx.get(
                api_url,
                timeout=10.0,
                follow_redirects=False,
                headers={"Accept": "application/vnd.github.v3+json"},
            )

            if resp.status_code == 301:
                # Repo was renamed — check that redirect stays on api.github.com
                location = resp.headers.get("location", "")
                if not location.startswith("https://api.github.com/"):
                    raise RuntimeError(
                        f"GitHub API redirected to unexpected host: {location}"
                    )
                # Follow the single safe redirect
                resp = httpx.get(
                    location,
                    timeout=10.0,
                    follow_redirects=False,
                    headers={"Accept": "application/vnd.github.v3+json"},
                )

            if resp.status_code == 404:
                raise RuntimeError(
                    f"Repository not found: {owner}/{repo}. "
                    "Is it a public repository?"
                )

            if resp.status_code != 200:
                log.warning(
                    f"GitHub API returned {resp.status_code} for {owner}/{repo}. "
                    f"Skipping pre-clone size check (Layer 2 will catch oversized repos)."
                )
                return

            data = resp.json()
            size_kb = data.get("size", 0)
            size_mb = size_kb / 1024.0

            if size_mb > settings.MAX_REPO_SIZE_MB:
                raise RuntimeError(
                    f"Repository too large: {size_mb:.1f}MB "
                    f"(limit: {settings.MAX_REPO_SIZE_MB}MB). "
                    f"Rejected before clone."
                )

            log.info(
                f"Pre-clone size check passed: {owner}/{repo} = {size_mb:.1f}MB "
                f"(limit: {settings.MAX_REPO_SIZE_MB}MB)"
            )

        except httpx.HTTPError as e:
            # API unreachable (rate limit, network issue, etc.)
            # Let it through — Layer 2 (post-clone disk check) will catch it
            log.warning(
                f"GitHub API check failed ({e}). "
                f"Proceeding with clone — post-clone disk check will enforce limits."
            )

    def check_clone_disk_usage(self, clone_dir: str) -> None:
        """
        Layer 2: Post-clone disk usage check.
        Measures actual directory size and aborts if it exceeds MAX_CLONE_DISK_MB.
        This catches repos where the GitHub API size estimate was wrong.
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
        Shallow clone a GitHub repository.
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
