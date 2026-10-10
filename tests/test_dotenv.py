"""The workspace .env must be honoured, without overriding the real environment."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from minerupress import cli

_VARS = ("MINERU_API_TOKEN", "CLOUDFLARE_API_TOKEN", "PAGES_PROJECT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # load_dotenv writes straight to os.environ; setenv+delenv makes
    # monkeypatch restore the original state afterwards.
    for name in _VARS:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def _book(ws: Path, plugins: str = "[]") -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    book_yml = ws / "book.yml"
    book_yml.write_text(
        f"volume_uid: uid1\nplugins: {plugins}\nchapters:\n  - slug: ch01\n    title: 第1章\n",
        encoding="utf-8",
    )
    return book_yml


def test_workspace_env_is_loaded_from_book_yml_directory(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    book_yml = _book(ws)
    (ws / ".env").write_text("MINERU_API_TOKEN=from-workspace\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    cli._load_book_runtime(str(book_yml), False)

    assert os.environ["MINERU_API_TOKEN"] == "from-workspace"


def test_real_environment_variable_wins(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    book_yml = _book(ws)
    (ws / ".env").write_text("MINERU_API_TOKEN=from-file\n", encoding="utf-8")
    monkeypatch.setenv("MINERU_API_TOKEN", "from-shell")
    monkeypatch.chdir(tmp_path)

    cli._load_book_runtime(str(book_yml), False)

    assert os.environ["MINERU_API_TOKEN"] == "from-shell"


def test_current_directory_env_is_a_fallback(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    book_yml = _book(ws)
    (ws / ".env").write_text("MINERU_API_TOKEN=from-workspace\n", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text(
        "MINERU_API_TOKEN=from-cwd\nCLOUDFLARE_API_TOKEN=cwd-only\n", encoding="utf-8"
    )
    monkeypatch.chdir(cwd)

    cli._load_book_runtime(str(book_yml), False)

    assert os.environ["MINERU_API_TOKEN"] == "from-workspace"  # workspace first
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "cwd-only"    # only cwd has it


def test_env_file_with_bom_is_read(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    book_yml = _book(ws)
    (ws / ".env").write_bytes(b"\xef\xbb\xbfMINERU_API_TOKEN=bom-token\n")
    monkeypatch.chdir(tmp_path)

    cli._load_book_runtime(str(book_yml), False)

    assert os.environ["MINERU_API_TOKEN"] == "bom-token"


def test_env_is_loaded_before_plugins_are_constructed(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    book_yml = _book(ws, plugins="[cf_pages]")
    (ws / ".env").write_text("PAGES_PROJECT=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _config, plugins, _source = cli._load_book_runtime(str(book_yml), False)

    assert plugins[0].pages_project == "from-dotenv"


def test_missing_env_file_is_fine(tmp_path, monkeypatch) -> None:
    book_yml = _book(tmp_path / "ws")
    monkeypatch.chdir(tmp_path)

    cli._load_book_runtime(str(book_yml), False)

    assert "MINERU_API_TOKEN" not in os.environ


def test_import_does_not_load_dotenv(tmp_path) -> None:
    # Import-time load_dotenv() used to search from the package directory;
    # loading is now done explicitly by the CLI. Check in a fresh interpreter.
    (tmp_path / ".env").write_text("MINERU_API_TOKEN=import-time\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in _VARS}

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, minerupress.api_client, minerupress.plugins.cf_pages;"
            "print(repr(os.environ.get('MINERU_API_TOKEN')))",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "None"
