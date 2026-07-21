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

import pytest

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

    def test_invalid_url_not_github(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="https://gitlab.com/user/repo")

    def test_invalid_url_random_string(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="not a url at all")

    def test_invalid_url_empty(self):
        with pytest.raises(Exception):
            DeployRequest(repo_url="")


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
