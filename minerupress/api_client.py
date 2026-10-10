"""
minerupress.api_client
~~~~~~~~~~~~~~~~~~~~~~~~~~
MinerU Precise API (v4) client.

Workflow
--------
1. POST /api/v4/file-urls/batch  → get signed upload URL + batch_id
2. PUT file to signed OSS URL (no Content-Type header; bypass proxy for OSS)
3. System auto-submits parse job after upload completes
4. GET /api/v4/extract-results/batch/{batch_id}  → poll until done
5. Download full_zip_url → extract content_list.json + images

PDF size limit
--------------
MinerU enforces a 200-page limit per file.  If the PDF exceeds this,
fetch() automatically splits it into ≤200-page chunks, uploads each
chunk, and returns a list of output directories.  Chunks are written to a
temporary directory and removed afterwards; the source PDF's directory is
never touched.

Resuming
--------
When fetch() is given a ``state_path``, every successful upload and every
extracted result is recorded there (batch_id per chunk).  Re-running fetch()
for the same source PDF skips the upload, polls the saved batches and only
downloads what is still missing.  ``force=True`` ignores the saved state.

Usage
-----
    from minerupress.api_client import MinerUClient

    client = MinerUClient(token="your-token")
    out_dirs = client.fetch(pdf_path=Path("book.pdf"), dest=Path("resources/mineru"))
    # returns list[Path], one per chunk
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

_BASE = "https://mineru.net"
_POLL_INTERVAL = 10   # seconds between status checks
_POLL_TIMEOUT  = 600  # default seconds before giving up (book.yml: api.poll_timeout)
_PAGE_LIMIT    = 190  # stay safely under the 200-page API limit
_RETRY_ATTEMPTS = 4   # total tries for transient network errors
_RETRY_DELAY    = 2.0 # seconds; doubled after every failed try
_STATE_VERSION = 1


class MinerUAPIError(RuntimeError):
    pass


class MinerUBatchFailed(MinerUAPIError):
    """MinerU reported state=failed for a batch."""

    def __init__(self, message: str, stem: str, batch_id: str) -> None:
        super().__init__(message)
        self.stem = stem
        self.batch_id = batch_id


@dataclass(frozen=True)
class _Chunk:
    """One upload unit: pages [start, end) of the source PDF, or all of it."""
    stem: str
    start: int | None = None
    end: int | None = None


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        return status == 429 or status >= 500
    return isinstance(
        exc,
        (
            requests.ConnectionError,  # includes SSLError
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
            zipfile.BadZipFile,  # truncated download
        ),
    )


def _with_retries(what: str, fn):
    """Call *fn* up to _RETRY_ATTEMPTS times, backing off on transient errors."""
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == _RETRY_ATTEMPTS or not _is_transient(exc):
                raise
            delay = _RETRY_DELAY * 2 ** (attempt - 1)
            print(
                f"  [api] {what}: {type(exc).__name__}; "
                f"retry {attempt}/{_RETRY_ATTEMPTS - 1} in {delay:.0f}s …"
            )
            time.sleep(delay)


class FetchState:
    """
    Resume state for ``fetch()``: ``<workspace>/.minerupress/fetch-state.json``.

    Layout::

        {"version": 1, "volumes": {"<uid>": {
            "source":  {"path", "size", "mtime_ns"},
            "options": {...},                       # API options + page limit
            "parts":   [{"stem", "batch_id", "status", "out_dir"}, ...]
        }}}

    ``status`` is ``pending`` (not uploaded), ``uploaded`` (batch submitted)
    or ``extracted`` (result is on disk at ``out_dir``, relative to dest).
    With ``path=None`` the state lives in memory only.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.volumes: dict[str, dict] = {}
        if self.path is not None and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") == _STATE_VERSION:
                    self.volumes = dict(data.get("volumes", {}))
            except (OSError, ValueError, AttributeError):
                print(f"  [api] ignoring unreadable fetch state: {self.path}")

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = {"version": _STATE_VERSION, "volumes": self.volumes}
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, self.path)


class MinerUClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        enable_formula: bool = True,
        enable_table: bool = True,
        model_version: str = "vlm",
    ) -> None:
        self.token = token or os.environ.get("MINERU_API_TOKEN", "")
        if not self.token:
            raise MinerUAPIError(
                "MinerU API token required. "
                "Set MINERU_API_TOKEN env var or pass token= to MinerUClient."
            )
        self.enable_formula = enable_formula
        self.enable_table = enable_table
        self.model_version = model_version
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.token}"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def fetch(
        self,
        pdf_path: Path,
        dest: Path,
        *,
        uid: str | None = None,
        state_path: Path | None = None,
        force: bool = False,
        poll_timeout: float | None = None,
    ) -> list[Path]:
        """
        Upload *pdf_path* to MinerU, wait for parsing, and extract results
        into *dest*, one directory per chunk.

        Returns a list of output directory paths (usually one, unless the
        PDF was split due to the 200-page limit), in chunk order.  With *uid*
        the directories are named ``<uid>_full`` / ``<uid>_part<N>``;
        otherwise ``<pdf stem>`` / ``<pdf stem>_part<N>``.

        *state_path* enables resuming: batches already uploaded for this PDF
        are polled and downloaded instead of uploaded again, and a volume
        whose results are all on disk is skipped.  *force* ignores that state.
        """
        pdf_path = Path(pdf_path)
        dest = Path(dest)
        timeout = _POLL_TIMEOUT if poll_timeout is None else poll_timeout

        chunks = self._plan_chunks(pdf_path)
        single = len(chunks) == 1
        names = [
            (f"{uid}_full" if single else f"{uid}_part{i}") if uid else chunk.stem
            for i, chunk in enumerate(chunks, 1)
        ]
        out_dirs = [dest / name for name in names]

        key = uid or pdf_path.stem
        state = FetchState(state_path)
        source = self._fingerprint(pdf_path)
        options = {
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "model_version": self.model_version,
            "page_limit": _PAGE_LIMIT,
        }
        record = None if force else state.volumes.get(key)
        if record is not None and not self._record_matches(
            record, source, options, [c.stem for c in chunks]
        ):
            print(f"  [api] {key}: source PDF or API options changed; ignoring saved batches")
            record = None
        if record is None:
            record = {
                "source": source,
                "options": options,
                "parts": [
                    {"stem": c.stem, "batch_id": "", "status": "pending", "out_dir": n}
                    for c, n in zip(chunks, names)
                ],
            }
        else:
            record["parts"] = [dict(p, out_dir=n) for p, n in zip(record["parts"], names)]
        state.volumes[key] = record
        parts = record["parts"]

        # A part counts as done only if its result is really on disk.
        todo = [i for i, p in enumerate(parts) if not self._has_result(p, dest)]
        if not todo:
            print(
                f"  [api] {key}: results already fetched under {dest}; skipping. "
                "Use `minerupress fetch --force` to upload and parse again."
            )
            return out_dirs
        if any(p["batch_id"] for p in parts):
            print(f"  [api] {key}: resuming from saved batches ({len(todo)} part(s) to fetch)")

        # Upload chunks that have no batch yet; persist after each one.
        to_upload = [i for i in todo if not parts[i]["batch_id"]]
        if to_upload:
            self._upload_chunks(pdf_path, chunks, parts, to_upload, state)

        # Poll the batches and download what is missing.
        pending = [(parts[i]["stem"], parts[i]["batch_id"]) for i in todo]
        print(f"  [api] waiting for {len(pending)} batch(es) …")
        try:
            zip_urls = self._poll_all(pending, timeout=timeout)
        except MinerUBatchFailed as exc:
            # A failed batch is dead: forget it so the next run re-uploads
            # just that part and keeps the others.
            for p in parts:
                if p["batch_id"] == exc.batch_id:
                    p["batch_id"], p["status"] = "", "pending"
            state.save()
            raise

        for i in todo:
            part = parts[i]
            print(f"  [api] downloading {part['stem']} (batch_id={part['batch_id']}) …")
            self._download_and_extract(zip_urls[part["stem"]], out_dirs[i])
            part["status"] = "extracted"
            state.save()
            print(f"  [api] extracted → {out_dirs[i]}")

        return out_dirs

    # ------------------------------------------------------------------
    # Resume state helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(pdf_path: Path) -> dict:
        st = pdf_path.stat()
        return {
            "path": str(pdf_path.resolve()),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        }

    @staticmethod
    def _record_matches(record: dict, source: dict, options: dict, stems: list[str]) -> bool:
        try:
            return (
                record["source"] == source
                and record["options"] == options
                and [p["stem"] for p in record["parts"]] == stems
            )
        except (KeyError, TypeError):
            return False

    @staticmethod
    def _has_result(part: dict, dest: Path) -> bool:
        if part.get("status") != "extracted":
            return False
        out_dir = dest / part["out_dir"]
        # Results only reach "extracted" through an atomic swap, so a
        # non-empty directory is enough to trust.
        return out_dir.is_dir() and any(out_dir.iterdir())

    def _upload_chunks(
        self,
        pdf_path: Path,
        chunks: list[_Chunk],
        parts: list[dict],
        indexes: list[int],
        state: FetchState,
    ) -> None:
        # Chunk PDFs live in a temp dir that is always cleaned up; the
        # directory of the source PDF is never written to.
        with tempfile.TemporaryDirectory(prefix="minerupress-split-") as tmp:
            reader = None
            for i in indexes:
                chunk = chunks[i]
                if chunk.start is None:
                    upload_path = pdf_path
                else:
                    if reader is None:
                        reader = self._pdf_reader(pdf_path)
                        print(
                            f"  [api] PDF has {chunks[-1].end} pages "
                            f"(limit {_PAGE_LIMIT}), splitting …"
                        )
                    upload_path = self._write_chunk(reader, chunk, Path(tmp))
                    size_mb = upload_path.stat().st_size / 1024 / 1024
                    print(
                        f"  [api]   {chunk.stem}: pages {chunk.start + 1}-{chunk.end} "
                        f"({size_mb:.1f}MB)"
                    )
                print(f"  [api] uploading {upload_path.name} …")
                upload_url, batch_id = self._get_upload_url(upload_path)
                self._upload_file(upload_path, upload_url)
                parts[i]["batch_id"] = batch_id
                parts[i]["status"] = "uploaded"
                state.save()
                print(f"  [api] uploaded → batch_id={batch_id}")

    # ------------------------------------------------------------------
    # PDF splitting
    # ------------------------------------------------------------------

    @staticmethod
    def _pdf_reader(pdf_path: Path):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise MinerUAPIError(
                "pypdf is required for automatic PDF splitting. "
                "Install it with: pip install pypdf"
            )
        return PdfReader(pdf_path)

    def _plan_chunks(self, pdf_path: Path) -> list[_Chunk]:
        """Return one chunk covering the whole PDF, or ≤_PAGE_LIMIT-page chunks."""
        total = len(self._pdf_reader(pdf_path).pages)
        if total <= _PAGE_LIMIT:
            return [_Chunk(stem=pdf_path.stem)]

        return [
            _Chunk(
                stem=f"{pdf_path.stem}_part{i}",
                start=start,
                end=min(start + _PAGE_LIMIT, total),
            )
            for i, start in enumerate(range(0, total, _PAGE_LIMIT), 1)
        ]

    @staticmethod
    def _write_chunk(reader, chunk: _Chunk, directory: Path) -> Path:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for p in range(chunk.start, chunk.end):
            writer.add_page(reader.pages[p])
        chunk_path = directory / f"{chunk.stem}.pdf"
        with open(chunk_path, "wb") as f:
            writer.write(f)
        return chunk_path

    # ------------------------------------------------------------------
    # Step 1: get signed upload URL
    # ------------------------------------------------------------------

    def _get_upload_url(self, pdf_path: Path) -> tuple[str, str]:
        payload = {
            "files": [{"name": pdf_path.name, "data_id": pdf_path.stem}],
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "model_version": self.model_version,
        }
        resp = self._post("/api/v4/file-urls/batch", json=payload)
        data = resp["data"]
        batch_id: str = data["batch_id"]
        file_urls: list = data["file_urls"]
        if not file_urls:
            raise MinerUAPIError("No upload URL returned by /api/v4/file-urls/batch")
        # API returns a list of URL strings (not dicts)
        url = file_urls[0] if isinstance(file_urls[0], str) else file_urls[0]["url"]
        return url, batch_id

    # ------------------------------------------------------------------
    # Step 2: PUT file to signed OSS URL
    # ------------------------------------------------------------------

    def _upload_file(self, pdf_path: Path, upload_url: str) -> None:
        # OSS signed URLs are sensitive to Content-Type — send no Content-Type
        # header so it matches the empty string in the pre-signed signature.
        # Also bypass any local HTTP proxy, which can corrupt large PUT bodies.
        env = {**os.environ, "NO_PROXY": "*.aliyuncs.com", "no_proxy": "*.aliyuncs.com"}
        result = subprocess.run(
            [
                "curl", "-X", "PUT", upload_url,
                "-H", "Content-Type:",
                "--noproxy", "*",
                "--upload-file", str(pdf_path),
                "-s", "-o", os.devnull,
                "-w", "%{http_code}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        http_code = result.stdout.strip()
        if http_code != "200":
            raise MinerUAPIError(
                f"File upload failed: HTTP {http_code}\n{result.stderr[:200]}"
            )

    # ------------------------------------------------------------------
    # Step 3: poll all batches until done
    # ------------------------------------------------------------------

    def _poll_all(
        self,
        batch_ids: list[tuple[str, str]],
        timeout: float | None = None,
    ) -> dict[str, str]:
        """Returns {chunk_stem: zip_url} for all completed batches."""
        pending = dict(batch_ids)  # stem → batch_id
        zip_urls: dict[str, str] = {}
        limit = _POLL_TIMEOUT if timeout is None else timeout
        deadline = time.monotonic() + limit

        while pending and time.monotonic() < deadline:
            done_stems = []
            for stem, bid in pending.items():
                result = self._batch_result(stem, bid)
                state = result.get("state", "")
                if state == "done":
                    zip_url = result.get("full_zip_url", "")
                    if not zip_url:
                        raise MinerUAPIError(f"Batch {bid} done but full_zip_url missing")
                    zip_urls[stem] = zip_url
                    done_stems.append(stem)
                    print(f"  [api] {stem}: done")
                elif state == "failed":
                    err = result.get("err_msg", "unknown error")
                    raise MinerUBatchFailed(
                        f"MinerU batch {bid} ({stem}) failed: {err}\n"
                        "Rerun `minerupress fetch` to re-upload only the failed part "
                        "(`--force` re-uploads everything).",
                        stem=stem,
                        batch_id=bid,
                    )
                else:
                    print(f"  [api] {stem}: {state}")
            for s in done_stems:
                del pending[s]
            if pending:
                time.sleep(_POLL_INTERVAL)

        if pending:
            listing = "\n".join(f"  {stem}: batch_id={bid}" for stem, bid in pending.items())
            raise MinerUAPIError(
                f"Timed out after {limit:g}s waiting for MinerU. Still pending:\n{listing}\n"
                "Parsing continues on the MinerU side. Rerun `minerupress fetch` to resume "
                "polling and downloading without uploading again; raise `api.poll_timeout` "
                "in book.yml if the book is large."
            )
        return zip_urls

    def _batch_result(self, stem: str, batch_id: str) -> dict:
        """Status of the single file in *batch_id*, with actionable errors."""
        try:
            resp = self._get(f"/api/v4/extract-results/batch/{batch_id}")
            return resp["data"]["extract_result"][0]
        except (MinerUAPIError, requests.HTTPError, KeyError, IndexError, TypeError) as exc:
            if isinstance(exc, requests.HTTPError) and _is_transient(exc):
                raise MinerUAPIError(
                    f"MinerU API kept failing while polling {stem} (batch_id={batch_id}): {exc}\n"
                    "Rerun `minerupress fetch` to resume."
                ) from exc
            raise MinerUAPIError(
                f"MinerU has no usable status for {stem} (batch_id={batch_id}): {exc}\n"
                "The saved batch may have expired or been removed on the server. "
                "Rerun with `minerupress fetch --force` to upload and parse again."
            ) from exc
        except requests.RequestException as exc:
            raise MinerUAPIError(
                f"Could not reach the MinerU API while polling {stem} "
                f"(batch_id={batch_id}): {type(exc).__name__}\n"
                "The batch is saved; rerun `minerupress fetch` to resume."
            ) from exc

    # ------------------------------------------------------------------
    # Step 4: download ZIP and extract
    # ------------------------------------------------------------------

    def _download_and_extract(self, zip_url: str, out_dir: Path) -> None:
        host = urlsplit(zip_url).hostname or "unknown host"
        try:
            data = _with_retries(f"download from {host}", lambda: self._download_zip(zip_url))
        except (requests.RequestException, zipfile.BadZipFile) as exc:
            api_host = urlsplit(_BASE).hostname
            raise MinerUAPIError(
                f"Could not download the MinerU result from {host} "
                f"({type(exc).__name__}).\n"
                "The parse result is already ready on the MinerU server; nothing needs "
                "to be uploaded again. Rerun `minerupress fetch` to resume the download.\n"
                f"Note: {host} is a different host from the API domain ({api_host}), so a "
                "local proxy or DNS rule may block it even though the API itself works. "
                f"Check that {host} resolves and is reachable from this machine."
            ) from exc

        # Extract next to out_dir, then swap in, so a bad zip never leaves a
        # half-written or deleted result behind.
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".minerupress-extract-", dir=out_dir.parent))
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.infolist():
                    target = (tmp / member.filename).resolve()
                    if not target.is_relative_to(tmp.resolve()):
                        raise MinerUAPIError(
                            f"Unsafe ZIP member path in MinerU result: {member.filename}"
                        )
                zf.extractall(tmp)
            if out_dir.exists():
                if out_dir.is_dir():
                    shutil.rmtree(out_dir)
                else:
                    out_dir.unlink()
            tmp.rename(out_dir)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _download_zip(zip_url: str) -> bytes:
        r = requests.get(zip_url, timeout=300)
        if r.status_code == 429 or r.status_code >= 500:
            raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
        if not r.ok:
            raise MinerUAPIError(
                f"ZIP download from {urlsplit(zip_url).hostname} failed: "
                f"HTTP {r.status_code} — {r.text[:200]}\n"
                "Rerun `minerupress fetch`: it asks MinerU for a fresh result URL."
            )
        # Fail here (and retry) on a truncated body instead of during extraction.
        zipfile.ZipFile(io.BytesIO(r.content)).close()
        return r.content

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _post(self, path: str, **kwargs) -> dict:
        r = self._session.post(f"{_BASE}{path}", timeout=60, **kwargs)
        return self._check(r)

    def _get(self, path: str) -> dict:
        def once() -> dict:
            r = self._session.get(f"{_BASE}{path}", timeout=30)
            return self._check(r)

        return _with_retries("status check", once)

    @staticmethod
    def _check(r: requests.Response) -> dict:
        r.raise_for_status()
        body = r.json()
        code = body.get("code", -1)
        if code != 0:
            msg = body.get("msg", body.get("message", str(body)))
            raise MinerUAPIError(f"MinerU API error (code={code}): {msg}")
        return body
