"""
Ducked Engine — Unit Tests
Tests for the heuristic detection engine and data models.

Run:
    cd backend
    python -m pytest tests/ -v
"""
import os
import json
import shutil
import tempfile
from dataclasses import replace

import pytest

from config import settings
from models import DeployRequest, ProjectType, Session, SessionStatus
from services.github_service import GitHubService


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def github_svc():
    return GitHubService()


@pytest.fixture
def temp_dir():
    """Create a temporary directory, yield it, then clean up."""
    d = tempfile.mkdtemp(prefix="ducked_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def allow_hosts(monkeypatch):
    """
    Temporarily extend the git host allowlist.

    Settings is a frozen dataclass, so this swaps in a replacement instance
    on the models module rather than mutating the original.
    """
    def _allow(*hosts: str):
        patched = replace(
            settings, ALLOWED_GIT_HOSTS=settings.ALLOWED_GIT_HOSTS + hosts
        )
        monkeypatch.setattr("models.settings", patched)
        return patched

    return _allow


# ── Heuristic Engine Tests ────────────────────────────────────────


class TestProjectDetection:
    """Test that the heuristic engine correctly identifies project types."""

    def test_detect_python_requirements(self, github_svc, temp_dir):
        open(os.path.join(temp_dir, "requirements.txt"), "w").close()
        open(os.path.join(temp_dir, "app.py"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.PYTHON

    def test_detect_python_pyproject(self, github_svc, temp_dir):
        open(os.path.join(temp_dir, "pyproject.toml"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.PYTHON

    def test_detect_python_setup_py(self, github_svc, temp_dir):
        open(os.path.join(temp_dir, "setup.py"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.PYTHON

    def test_detect_node(self, github_svc, temp_dir):
        with open(os.path.join(temp_dir, "package.json"), "w") as f:
            json.dump({"name": "test", "scripts": {"start": "node index.js"}}, f)
        assert github_svc.detect_project_type(temp_dir) == ProjectType.NODE

    def test_detect_go(self, github_svc, temp_dir):
        with open(os.path.join(temp_dir, "go.mod"), "w") as f:
            f.write("module example.com/test\n\ngo 1.21\n")
        open(os.path.join(temp_dir, "main.go"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.GO

    def test_detect_static_html(self, github_svc, temp_dir):
        open(os.path.join(temp_dir, "index.html"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.STATIC

    def test_detect_dockerfile(self, github_svc, temp_dir):
        open(os.path.join(temp_dir, "Dockerfile"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.DOCKERFILE

    def test_detect_dockerfile_takes_priority(self, github_svc, temp_dir):
        """If a Dockerfile AND requirements.txt exist, Dockerfile wins."""
        open(os.path.join(temp_dir, "Dockerfile"), "w").close()
        open(os.path.join(temp_dir, "requirements.txt"), "w").close()
        assert github_svc.detect_project_type(temp_dir) == ProjectType.DOCKERFILE

    def test_detect_unknown_empty_dir(self, github_svc, temp_dir):
        assert github_svc.detect_project_type(temp_dir) == ProjectType.UNKNOWN

    def test_detect_nested_node_project(self, github_svc, temp_dir):
        """Projects nested one level deep should be detected and promoted."""
        nested = os.path.join(temp_dir, "app")
        os.makedirs(nested)
        with open(os.path.join(nested, "package.json"), "w") as f:
            json.dump({"name": "nested-test"}, f)
        result = github_svc.detect_project_type(temp_dir)
        assert result == ProjectType.NODE
        # After promotion, package.json should be at root
        assert os.path.exists(os.path.join(temp_dir, "package.json"))


# ── Model Validation Tests ────────────────────────────────────────


class TestDeployRequest:
    """Test URL validation on the DeployRequest model."""

    def test_valid_github_url(self):
        req = DeployRequest(repo_url="https://github.com/user/repo")
        assert req.repo_url == "https://github.com/user/repo"

    def test_valid_github_url_with_git_suffix(self):
        req = DeployRequest(repo_url="https://github.com/user/repo.git")
        assert req.repo_url == "https://github.com/user/repo.git"

    def test_valid_github_url_trailing_slash(self):
        req = DeployRequest(repo_url="https://github.com/user/repo/")
        assert req.repo_url == "https://github.com/user/repo"

    def test_invalid_url_random_string(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="not a url at all")

    def test_invalid_url_empty(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="")


class TestAllowedForges:
    """Every host in the allowlist is accepted; everything else is not."""

    @pytest.mark.parametrize("host", ["github.com", "gitlab.com", "codeberg.org", "gitea.com"])
    def test_default_hosts_accepted(self, host):
        req = DeployRequest(repo_url=f"https://{host}/owner/repo")
        assert req.repo_url == f"https://{host}/owner/repo"

    def test_gitlab_subgroup_path(self):
        """GitLab nests projects under subgroups; owner/repo is not enough."""
        url = "https://gitlab.com/group/subgroup/project"
        assert DeployRequest(repo_url=url).repo_url == url

    def test_deeply_nested_path_rejected(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://gitlab.com/a/b/c/d/e/f")

    def test_unlisted_host_rejected(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://evil.example.com/owner/repo")

    def test_self_hosted_requires_allowlisting(self, allow_hosts):
        """A self-hosted forge only works once the operator opts in."""
        url = "https://git.acme.test/owner/repo"
        with pytest.raises(Exception):
            DeployRequest(repo_url=url)

        allow_hosts("git.acme.test")
        assert DeployRequest(repo_url=url).repo_url == url

    def test_allowlisted_host_with_port(self, allow_hosts):
        """The whole authority must match, port included."""
        allow_hosts("forge.acme.test:3000")

        url = "https://forge.acme.test:3000/owner/repo"
        assert DeployRequest(repo_url=url).repo_url == url

        # Same host, different port — not the allowlisted authority.
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://forge.acme.test:9999/owner/repo")


class TestUrlSSRFDefences:
    """
    The allowlist is the primary defence. These cover what can still be
    smuggled through a URL that names an allowed host.
    """

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "git://github.com/owner/repo",
        "ssh://git@github.com/owner/repo",
        "git@github.com:owner/repo.git",
        "http://github.com/owner/repo",
        "ftp://github.com/owner/repo",
    ])
    def test_non_https_schemes_rejected(self, url):
        with pytest.raises(Exception):
            DeployRequest(repo_url=url)

    @pytest.mark.parametrize("url", [
        # Authority confusion — the real host is after the @.
        "https://github.com@evil.example.com/owner/repo",
        "https://user:pass@github.com/owner/repo",
    ])
    def test_credentials_in_authority_rejected(self, url):
        with pytest.raises(Exception):
            DeployRequest(repo_url=url)

    @pytest.mark.parametrize("url", [
        "https://169.254.169.254/owner/repo",   # cloud metadata
        "https://127.0.0.1/owner/repo",
        "https://localhost/owner/repo",
        "https://10.0.0.1/owner/repo",
        "https://[::1]/owner/repo",
    ])
    def test_internal_targets_rejected(self, url):
        with pytest.raises(Exception):
            DeployRequest(repo_url=url)

    @pytest.mark.parametrize("url", [
        "https://github.com/../../etc/passwd",
        "https://github.com/owner/../../../root",
        "https://github.com/./repo",
    ])
    def test_path_traversal_rejected(self, url):
        with pytest.raises(Exception):
            DeployRequest(repo_url=url)

    def test_query_and_fragment_rejected(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://github.com/owner/repo?foo=bar")
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://github.com/owner/repo#frag")

    def test_single_segment_path_rejected(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://github.com/owner")


class TestRepoUrlParsing:
    """parse_repo_url feeds the forge size check."""

    def test_parses_github(self, github_svc):
        assert github_svc.parse_repo_url(
            "https://github.com/owner/repo"
        ) == ("github.com", "owner", "repo")

    def test_strips_git_suffix(self, github_svc):
        assert github_svc.parse_repo_url(
            "https://github.com/owner/repo.git"
        ) == ("github.com", "owner", "repo")

    def test_keeps_gitlab_subgroups_in_owner_path(self, github_svc):
        assert github_svc.parse_repo_url(
            "https://gitlab.com/group/subgroup/project"
        ) == ("gitlab.com", "group/subgroup", "project")

    def test_github_uses_the_api_host(self, github_svc):
        url = github_svc._size_api_url("github.com", "owner", "repo")
        assert url == "https://api.github.com/repos/owner/repo"

    def test_other_forges_use_the_gitea_api_on_the_instance(self, github_svc):
        url = github_svc._size_api_url("codeberg.org", "owner", "repo")
        assert url == "https://codeberg.org/api/v1/repos/owner/repo"


# ── Session Tests ─────────────────────────────────────────────────


class TestSession:
    """Test Session state machine behavior."""

    def test_session_creation(self):
        s = Session("test123", "https://github.com/user/repo", "/tmp/test")
        assert s.session_id == "test123"
        assert s.status == SessionStatus.QUEUED
        assert s.container_id is None

    def test_session_broadcast(self):
        s = Session("test123", "https://github.com/user/repo", "/tmp/test")
        q = s.subscribe()
        s.broadcast({"type": "test", "data": "hello"})
        assert not q.empty()
        event = q.get_nowait()
        assert event["data"] == "hello"

    def test_session_unsubscribe(self):
        s = Session("test123", "https://github.com/user/repo", "/tmp/test")
        q = s.subscribe()
        s.unsubscribe(q)
        s.broadcast({"type": "test"})
        assert q.empty()

    def test_session_to_dict(self):
        s = Session("abc", "https://github.com/user/repo", "/tmp/abc")
        d = s.to_dict()
        assert d["session_id"] == "abc"
        assert d["status"] == "queued"
        assert d["container_id"] is None
