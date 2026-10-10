"""Fetch resume / retry / cleanup behaviour. Every network call is mocked."""

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
import requests
from pypdf import PdfWriter

from minerupress import api_client, cli
from minerupress.api_client import FetchState, MinerUAPIError, MinerUClient


def _make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with open(path, "wb") as f:
        writer.write(f)


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text)
    return buf.getvalue()


class FakeAPI:
    """Stands in for the network side of MinerUClient."""

    def __init__(self, monkeypatch, client: MinerUClient) -> None:
        self.uploads: list[str] = []          # uploaded file names, in order
        self.upload_dirs: list[Path] = []     # where each uploaded file lived
        self.polls: list[str] = []            # batch_ids polled
        self.downloads: list[str] = []        # out_dir names written
        self.fail_upload_on: int | None = None  # 1-based upload index to raise on
        self.fail_download = False
        self.states: dict[str, dict] = {}     # batch_id -> extract_result override
        self.missing_batches: set[str] = set()
        self.client = client

        monkeypatch.setattr(client, "_get_upload_url", self._get_upload_url)
        monkeypatch.setattr(client, "_upload_file", self._upload_file)
        monkeypatch.setattr(client, "_get", self._get)
        monkeypatch.setattr(client, "_download_and_extract", self._download)
        monkeypatch.setattr(api_client, "_POLL_INTERVAL", 0)

    def _get_upload_url(self, pdf_path: Path):
        batch_id = f"batch-{len(self.uploads) + 1}-{pdf_path.stem}"
        return f"https://oss.example/{pdf_path.name}", batch_id

    def _upload_file(self, pdf_path: Path, url: str) -> None:
        if self.fail_upload_on == len(self.uploads) + 1:
            raise MinerUAPIError("upload failed")
        assert pdf_path.is_file()
        self.uploads.append(pdf_path.name)
        self.upload_dirs.append(pdf_path.parent)

    def _get(self, path: str) -> dict:
        batch_id = path.rsplit("/", 1)[-1]
        self.polls.append(batch_id)
        if batch_id in self.missing_batches:
            raise MinerUAPIError("MinerU API error (code=-60012): task not found")
        result = {"state": "done", "full_zip_url": f"https://cdn.example/{batch_id}.zip"}
        result.update(self.states.get(batch_id, {}))
        return {"data": {"extract_result": [result]}}

    def _download(self, zip_url: str, out_dir: Path) -> None:
        if self.fail_download:
            raise MinerUAPIError("download failed")
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        (out_dir / f"{out_dir.name}_content_list.json").write_text("[]", encoding="utf-8")
        self.downloads.append(out_dir.name)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(api_client, "_PAGE_LIMIT", 2)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf = pdf_dir / "book.pdf"
    _make_pdf(pdf, 5)  # -> 3 chunks of <= 2 pages
    client = MinerUClient(token="test-token")
    api = FakeAPI(monkeypatch, client)
    dest = tmp_path / "mineru"
    state_path = tmp_path / ".minerupress" / "fetch-state.json"

    def run(**kwargs):
        kwargs.setdefault("uid", "uid1")
        kwargs.setdefault("state_path", state_path)
        return client.fetch(pdf, dest, **kwargs)

    return pdf, dest, state_path, api, run


def test_fetch_returns_dirs_in_chunk_order_named_after_uid(setup) -> None:
    pdf, dest, state_path, api, run = setup

    out = run()

    assert out == [dest / "uid1_part1", dest / "uid1_part2", dest / "uid1_part3"]
    assert api.uploads == ["book_part1.pdf", "book_part2.pdf", "book_part3.pdf"]
    assert all(p.is_dir() for p in out)


def test_unsplit_pdf_is_named_full(setup, monkeypatch) -> None:
    pdf, dest, state_path, api, run = setup
    monkeypatch.setattr(api_client, "_PAGE_LIMIT", 50)

    out = run()

    assert out == [dest / "uid1_full"]
    assert api.uploads == ["book.pdf"]


def test_download_failure_then_rerun_does_not_upload_again(setup) -> None:
    pdf, dest, state_path, api, run = setup
    api.fail_download = True

    with pytest.raises(MinerUAPIError):
        run()

    assert len(api.uploads) == 3
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    parts = saved["volumes"]["uid1"]["parts"]
    assert [p["stem"] for p in parts] == ["book_part1", "book_part2", "book_part3"]
    assert all(p["batch_id"] and p["status"] == "uploaded" for p in parts)
    assert parts[0]["out_dir"] == "uid1_part1"

    api.fail_download = False
    out = run()

    assert len(api.uploads) == 3  # nothing uploaded on resume
    assert out == [dest / "uid1_part1", dest / "uid1_part2", dest / "uid1_part3"]
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert {p["status"] for p in saved["volumes"]["uid1"]["parts"]} == {"extracted"}


def test_resume_only_downloads_missing_parts(setup) -> None:
    pdf, dest, state_path, api, run = setup
    run()
    api.polls.clear()
    api.downloads.clear()
    # one result lost from disk (e.g. user cleaned mineru_root)
    shutil.rmtree(dest / "uid1_part2")

    out = run()

    assert api.downloads == ["uid1_part2"]
    assert api.polls == ["batch-2-book_part2"]
    assert len(api.uploads) == 3
    assert out[1] == dest / "uid1_part2"


def test_complete_volume_is_skipped_with_force_hint(setup, capsys) -> None:
    pdf, dest, state_path, api, run = setup
    run()
    api.polls.clear()
    api.downloads.clear()
    capsys.readouterr()

    out = run()

    assert api.polls == [] and api.downloads == []
    assert len(api.uploads) == 3
    assert out == [dest / "uid1_part1", dest / "uid1_part2", dest / "uid1_part3"]
    assert "--force" in capsys.readouterr().out


def test_force_ignores_state_and_uploads_again(setup) -> None:
    pdf, dest, state_path, api, run = setup
    run()

    run(force=True)

    assert len(api.uploads) == 6


def test_changed_source_pdf_is_not_resumed(setup) -> None:
    pdf, dest, state_path, api, run = setup
    run()
    _make_pdf(pdf, 6)  # same path, different size

    run()

    assert len(api.uploads) == 3 + 3


def test_changed_api_options_are_not_resumed(setup) -> None:
    pdf, dest, state_path, api, run = setup
    run()

    api.client.model_version = "pipeline"
    run()

    assert len(api.uploads) == 6


def test_failed_upload_keeps_earlier_batches(setup) -> None:
    pdf, dest, state_path, api, run = setup
    api.fail_upload_on = 2

    with pytest.raises(MinerUAPIError):
        run()
    assert api.uploads == ["book_part1.pdf"]
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    parts = saved["volumes"]["uid1"]["parts"]
    assert [bool(p["batch_id"]) for p in parts] == [True, False, False]

    api.fail_upload_on = None
    run()

    # part1 was not uploaded a second time
    assert api.uploads == ["book_part1.pdf", "book_part2.pdf", "book_part3.pdf"]


def test_failed_batch_is_forgotten_so_only_it_is_resubmitted(setup) -> None:
    pdf, dest, state_path, api, run = setup
    api.states["batch-2-book_part2"] = {"state": "failed", "err_msg": "bad scan"}

    with pytest.raises(MinerUAPIError, match="bad scan"):
        run()
    assert len(api.uploads) == 3

    api.states.clear()
    run()

    assert api.uploads[3:] == ["book_part2.pdf"]


def test_expired_saved_batch_suggests_force(setup) -> None:
    pdf, dest, state_path, api, run = setup
    api.fail_download = True
    with pytest.raises(MinerUAPIError):
        run()
    api.fail_download = False
    api.missing_batches.add("batch-1-book_part1")

    with pytest.raises(MinerUAPIError) as err:
        run()

    msg = str(err.value)
    assert "batch-1-book_part1" in msg
    assert "--force" in msg
    assert len(api.uploads) == 3


def test_poll_timeout_error_lists_batch_ids_and_resume_hint(setup, monkeypatch) -> None:
    pdf, dest, state_path, api, run = setup
    api.states["batch-2-book_part2"] = {"state": "running"}
    api.states["batch-3-book_part3"] = {"state": "running"}
    monkeypatch.setattr(api_client, "_POLL_INTERVAL", 0.01)

    with pytest.raises(MinerUAPIError) as err:
        run(poll_timeout=0.05)

    msg = str(err.value)
    assert "book_part2" in msg and "batch_id=batch-2-book_part2" in msg
    assert "batch_id=batch-3-book_part3" in msg
    assert "book_part1" not in msg  # finished parts are not reported as pending
    assert "minerupress fetch" in msg
    assert "poll_timeout" in msg
    # the batches survive for the next run
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert all(p["batch_id"] for p in saved["volumes"]["uid1"]["parts"])


def test_poll_timeout_defaults_to_module_constant(setup, monkeypatch) -> None:
    pdf, dest, state_path, api, run = setup
    api.states["batch-1-book_part1"] = {"state": "running"}
    monkeypatch.setattr(api_client, "_POLL_TIMEOUT", 0.03)
    monkeypatch.setattr(api_client, "_POLL_INTERVAL", 0.01)

    with pytest.raises(MinerUAPIError, match="Timed out after 0.03s"):
        run()


def test_split_chunks_use_temp_dir_and_are_removed_after_failure(setup) -> None:
    pdf, dest, state_path, api, run = setup
    # a user file that looks like a chunk must survive untouched
    precious = pdf.parent / "book_part1.pdf"
    precious.write_bytes(b"user data")
    before = sorted(p.name for p in pdf.parent.iterdir())
    api.fail_download = True

    with pytest.raises(MinerUAPIError):
        run()

    assert sorted(p.name for p in pdf.parent.iterdir()) == before
    assert precious.read_bytes() == b"user data"
    assert api.upload_dirs and all(d != pdf.parent for d in api.upload_dirs)
    assert all(not d.exists() for d in api.upload_dirs)


def test_chunk_temp_dir_removed_when_upload_fails(setup) -> None:
    pdf, dest, state_path, api, run = setup
    api.fail_upload_on = 2

    with pytest.raises(MinerUAPIError):
        run()

    assert all(not d.exists() for d in api.upload_dirs)
    assert sorted(p.name for p in pdf.parent.iterdir()) == ["book.pdf"]


def test_no_state_path_still_fetches(setup) -> None:
    pdf, dest, state_path, api, run = setup

    out = run(state_path=None, uid=None)

    assert out == [dest / "book_part1", dest / "book_part2", dest / "book_part3"]
    assert not state_path.exists()


def test_fetch_state_ignores_corrupt_file(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")

    assert FetchState(path).volumes == {}


# ---------------------------------------------------------------------------
# Download retry / error reporting (requests.get mocked)
# ---------------------------------------------------------------------------

_URL = "https://cdn-mineru.openxlab.org.cn/pdf/2026-01-01/abc.zip"


class _Resp:
    def __init__(self, content: bytes = b"", status: int = 200, text: str = "") -> None:
        self.content = content
        self.status_code = status
        self.text = text
        self.ok = status < 400


@pytest.fixture
def no_sleep(monkeypatch):
    delays: list[float] = []
    monkeypatch.setattr(api_client.time, "sleep", delays.append)
    return delays


def test_download_retries_transient_errors_with_backoff(tmp_path, monkeypatch, no_sleep) -> None:
    calls = []
    payload = _zip_bytes({"book_content_list.json": "[]", "images/a.png": "x"})

    def fake_get(url, timeout):
        calls.append(url)
        if len(calls) < 3:
            raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")
        return _Resp(payload)

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    out_dir = tmp_path / "out"

    MinerUClient(token="t")._download_and_extract(_URL, out_dir)

    assert len(calls) == 3
    assert no_sleep == [2.0, 4.0]
    assert (out_dir / "book_content_list.json").is_file()
    assert (out_dir / "images" / "a.png").is_file()


def test_download_retries_server_errors(tmp_path, monkeypatch, no_sleep) -> None:
    payload = _zip_bytes({"a_content_list.json": "[]"})
    responses = iter([_Resp(status=503, text="busy"), _Resp(payload)])
    monkeypatch.setattr(api_client.requests, "get", lambda url, timeout: next(responses))

    MinerUClient(token="t")._download_and_extract(_URL, tmp_path / "out")

    assert no_sleep == [2.0]


def test_download_retries_truncated_zip(tmp_path, monkeypatch, no_sleep) -> None:
    good = _zip_bytes({"a_content_list.json": "[]" * 100})
    responses = iter([_Resp(good[:20]), _Resp(good)])
    monkeypatch.setattr(api_client.requests, "get", lambda url, timeout: next(responses))

    MinerUClient(token="t")._download_and_extract(_URL, tmp_path / "out")

    assert (tmp_path / "out" / "a_content_list.json").is_file()


def test_download_failure_explains_host_and_resume(tmp_path, monkeypatch, no_sleep) -> None:
    def fake_get(url, timeout):
        raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    out_dir = tmp_path / "out"

    with pytest.raises(MinerUAPIError) as err:
        MinerUClient(token="t")._download_and_extract(_URL, out_dir)

    msg = str(err.value)
    assert "cdn-mineru.openxlab.org.cn" in msg
    assert "already ready" in msg
    assert "minerupress fetch" in msg
    assert "mineru.net" in msg
    assert "proxy" in msg and "DNS" in msg
    assert "abc.zip" not in msg  # signed URL path is not echoed
    assert len(no_sleep) == api_client._RETRY_ATTEMPTS - 1
    assert not out_dir.exists()


def test_download_client_error_is_not_retried(tmp_path, monkeypatch, no_sleep) -> None:
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return _Resp(status=403, text="expired")

    monkeypatch.setattr(api_client.requests, "get", fake_get)

    with pytest.raises(MinerUAPIError, match="cdn-mineru.openxlab.org.cn"):
        MinerUClient(token="t")._download_and_extract(_URL, tmp_path / "out")

    assert len(calls) == 1


def test_zip_path_traversal_is_rejected_and_leaves_nothing(tmp_path, monkeypatch) -> None:
    payload = _zip_bytes({"../evil.txt": "x"})
    monkeypatch.setattr(api_client.requests, "get", lambda url, timeout: _Resp(payload))
    root = tmp_path / "mineru"
    root.mkdir()

    with pytest.raises(MinerUAPIError, match="Unsafe ZIP"):
        MinerUClient(token="t")._download_and_extract(_URL, root / "vol")

    assert list(root.iterdir()) == []
    assert not (tmp_path / "evil.txt").exists()


def test_failed_extract_keeps_previous_result(tmp_path, monkeypatch) -> None:
    root = tmp_path / "mineru"
    old = root / "vol"
    old.mkdir(parents=True)
    (old / "keep.txt").write_text("old", encoding="utf-8")
    payload = _zip_bytes({"../evil.txt": "x"})
    monkeypatch.setattr(api_client.requests, "get", lambda url, timeout: _Resp(payload))

    with pytest.raises(MinerUAPIError):
        MinerUClient(token="t")._download_and_extract(_URL, old)

    assert (old / "keep.txt").read_text(encoding="utf-8") == "old"


def test_status_check_retries_transient_errors(monkeypatch, no_sleep) -> None:
    client = MinerUClient(token="t")
    attempts = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0, "data": {"ok": True}}

    def fake_get(url, timeout):
        attempts.append(url)
        if len(attempts) == 1:
            raise requests.ConnectionError("reset")
        return Resp()

    monkeypatch.setattr(client._session, "get", fake_get)

    assert client._get("/api/v4/x")["data"] == {"ok": True}
    assert len(attempts) == 2


def test_upload_discards_output_to_os_devnull(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class Result:
            stdout = "200"
            stderr = ""

        return Result()

    monkeypatch.setattr(api_client.subprocess, "run", fake_run)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    MinerUClient(token="t")._upload_file(pdf, "https://oss.example/a.pdf")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-o") + 1] == api_client.os.devnull


# ---------------------------------------------------------------------------
# CLI: fetch end to end, boundary failures
# ---------------------------------------------------------------------------

def _workspace(tmp_path: Path, chapter_title: str) -> Path:
    ws = tmp_path / "ws"
    (ws / "resources" / "pdfs").mkdir(parents=True)
    _make_pdf(ws / "resources" / "pdfs" / "book.pdf", 5)
    (ws / "book.yml").write_text(
        "source: official_api\n"
        "volume_uid: uid1\n"
        "api:\n"
        "  poll_timeout: 123\n"
        "  sources:\n"
        "    uid1: resources/pdfs/book.pdf\n"
        "plugins: []\n"
        "chapters:\n"
        f"  - slug: ch01\n    title: {chapter_title}\n",
        encoding="utf-8",
    )
    return ws


def _cli_fake(monkeypatch, heading: str):
    monkeypatch.setattr(api_client, "_PAGE_LIMIT", 2)
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    seen = {"uploads": 0, "poll_timeout": None}
    real_poll_all = MinerUClient._poll_all

    def fake_upload_url(self, pdf_path):
        seen["uploads"] += 1
        return "https://oss.example/x", f"b-{pdf_path.stem}"

    def fake_poll_all(self, batch_ids, timeout=None):
        seen["poll_timeout"] = timeout
        return real_poll_all(self, batch_ids, timeout=timeout)

    def fake_get(self, path):
        return {"data": {"extract_result": [{"state": "done", "full_zip_url": "https://c/x.zip"}]}}

    def fake_download(self, zip_url, out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        items = [{"type": "text", "text_level": 1, "page_idx": 20, "text": heading},
                 {"type": "text", "text": "body"}]
        (out_dir / f"{out_dir.name}_content_list.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )

    monkeypatch.setattr(MinerUClient, "_get_upload_url", fake_upload_url)
    monkeypatch.setattr(MinerUClient, "_upload_file", lambda self, p, u: None)
    monkeypatch.setattr(MinerUClient, "_get", fake_get)
    monkeypatch.setattr(MinerUClient, "_poll_all", fake_poll_all)
    monkeypatch.setattr(MinerUClient, "_download_and_extract", fake_download)
    return seen


def test_cli_fetch_exports_and_passes_poll_timeout(tmp_path, monkeypatch, capsys) -> None:
    ws = _workspace(tmp_path, "第1章 概述")
    seen = _cli_fake(monkeypatch, "第1章 概述")
    monkeypatch.chdir(tmp_path)

    rc = cli.root_main(["fetch", str(ws / "book.yml")])

    assert rc == 0
    assert seen["poll_timeout"] == 123
    assert (ws / "docs" / "chapters" / "ch01.md").is_file()
    assert (ws / "resources" / "mineru" / "uid1_part1").is_dir()
    assert (ws / ".minerupress" / "fetch-state.json").is_file()
    # source dir has no leftover chunks
    assert [p.name for p in (ws / "resources" / "pdfs").iterdir()] == ["book.pdf"]

    # second run skips; --force uploads again
    uploads = seen["uploads"]
    assert cli.root_main(["fetch", str(ws / "book.yml")]) == 0
    assert seen["uploads"] == uploads
    assert cli.root_main(["fetch", str(ws / "book.yml"), "--force"]) == 0
    assert seen["uploads"] == uploads * 2


def test_cli_fetch_missing_boundary_is_clean_nonzero_exit(tmp_path, monkeypatch, capsys) -> None:
    ws = _workspace(tmp_path, "第9章 不存在")
    seen = _cli_fake(monkeypatch, "第1章 概述")
    monkeypatch.chdir(tmp_path)

    rc = cli.root_main(["fetch", str(ws / "book.yml")])

    err = capsys.readouterr().err
    assert rc == 1
    assert "Traceback" not in err
    assert "Chapter boundaries not found for volume uid1" in err
    assert "MinerU output is ready" in err
    assert "minerupress headings" in err
    assert "--volume-uid uid1 --format yaml --body-only" in err
    # shown relative to the current directory when possible
    assert str(Path("ws") / "resources" / "mineru") in err
    assert "minerupress export" in err
    # the fetched result is kept, and a rerun does not upload again
    assert (ws / "resources" / "mineru" / "uid1_part1").is_dir()
    uploads = seen["uploads"]
    cli.root_main(["fetch", str(ws / "book.yml")])
    assert seen["uploads"] == uploads


def test_cli_export_missing_boundary_is_clean_nonzero_exit(tmp_path, capsys) -> None:
    ws = _workspace(tmp_path, "第9章 不存在")
    vol = ws / "resources" / "mineru" / "uid1_full"
    vol.mkdir(parents=True)
    (vol / "uid1_full_content_list.json").write_text(
        json.dumps([{"type": "text", "text_level": 1, "page_idx": 20, "text": "第1章 概述"}]),
        encoding="utf-8",
    )

    rc = cli.root_main(["export", str(ws / "book.yml")])

    err = capsys.readouterr().err
    assert rc == 1
    assert "Traceback" not in err
    assert "Chapter boundaries not found" in err
    assert "minerupress headings" in err


def test_cli_fetch_api_error_is_printed_without_traceback(tmp_path, monkeypatch, capsys) -> None:
    ws = _workspace(tmp_path, "第1章 概述")
    _cli_fake(monkeypatch, "第1章 概述")

    def boom(self, zip_url, out_dir):
        raise MinerUAPIError("Could not download the MinerU result from cdn.example")

    monkeypatch.setattr(MinerUClient, "_download_and_extract", boom)
    monkeypatch.chdir(tmp_path)

    rc = cli.root_main(["fetch", str(ws / "book.yml")])

    assert rc == 1
    assert "cdn.example" in capsys.readouterr().err
