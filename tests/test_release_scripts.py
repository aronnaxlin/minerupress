import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NEXT_VERSION = ROOT / "scripts" / "next-version.sh"
STAMP_VERSION = ROOT / "scripts" / "stamp-version.py"

needs_git_and_bash = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="needs git and bash",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c", "user.name=test",
            "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false",
            "-c", "tag.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _commit(repo: Path, subject: str, body: str = "") -> None:
    message = ["-m", subject, *(["-m", body] if body else [])]
    _git(repo, "commit", "--allow-empty", *message)


def _next_version(repo: Path) -> str:
    result = subprocess.run(
        ["bash", str(NEXT_VERSION)], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "first")
    return tmp_path


@needs_git_and_bash
def test_first_release_without_any_tag(repo: Path) -> None:
    assert _next_version(repo) == "0.0.1"


@needs_git_and_bash
def test_nothing_to_release_on_a_tagged_commit(repo: Path) -> None:
    _git(repo, "tag", "v0.1.2")

    assert _next_version(repo) == ""


@needs_git_and_bash
def test_commits_after_the_latest_tag_bump_the_patch(repo: Path) -> None:
    _git(repo, "tag", "v0.1.2")
    _commit(repo, "fix something")
    _commit(repo, "fix something else")

    assert _next_version(repo) == "0.1.3"


@needs_git_and_bash
def test_highest_tag_is_chosen_by_version_not_by_text(repo: Path) -> None:
    _git(repo, "tag", "v0.1.9")
    _commit(repo, "second")
    _git(repo, "tag", "v0.1.10")
    _git(repo, "tag", "v1")
    _git(repo, "tag", "vnext")
    _commit(repo, "third")

    assert _next_version(repo) == "0.1.11"


@needs_git_and_bash
def test_skip_marker_counts_only_in_the_subject(repo: Path) -> None:
    _git(repo, "tag", "v0.1.2")
    _commit(repo, "docs: fix a typo [skip release]")
    assert _next_version(repo) == ""

    _commit(repo, "fix the release script", body="It used to honour [skip release] in the body.")
    assert _next_version(repo) == "0.1.3"


def _stamp(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STAMP_VERSION), *args], capture_output=True, text=True
    )


def test_stamp_writes_the_version_into_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    shutil.copy(ROOT / "pyproject.toml", pyproject)

    result = _stamp("0.1.3", str(pyproject))

    assert result.returncode == 0, result.stderr
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert project["version"] == "0.1.3"
    assert project["name"] == "minerupress"


@pytest.mark.parametrize("version", ["v0.1.3", "0.1", "0.1.3.dev1", ""])
def test_stamp_rejects_anything_but_a_release_version(tmp_path: Path, version: str) -> None:
    pyproject = tmp_path / "pyproject.toml"
    shutil.copy(ROOT / "pyproject.toml", pyproject)
    before = pyproject.read_text(encoding="utf-8")

    assert _stamp(version, str(pyproject)).returncode != 0
    assert pyproject.read_text(encoding="utf-8") == before


def test_committed_pyproject_carries_the_placeholder_version() -> None:
    # A real version here would be shipped by every later release until someone
    # remembered to edit it; the release workflow is the only writer.
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["version"] == "0.0.0.dev0"
