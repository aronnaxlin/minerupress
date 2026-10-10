"""
minerupress.loader
~~~~~~~~~~~~~~~~~~~~~~
Load a book.yml file into a BookConfig + plugin list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from .core import BookConfig, ChapterConfig
from .plugins.base import ExportPlugin

SourceKind = Literal["uploaded_result", "local_toolchain", "official_api"]


@dataclass
class APIConfig:
    """Optional MinerU cloud API settings from book.yml."""
    token: str = ""                  # overrides MINERU_API_TOKEN env var
    enable_formula: bool = True
    enable_table: bool = True
    model_version: str = "vlm"
    poll_timeout: int = 600          # seconds to wait for parsing per fetch run
    # PDF files to upload, keyed by volume_uid prefix
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class LocalToolchainConfig:
    """Optional local MinerU CLI settings from book.yml."""
    executable: str = "mineru"
    args: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class SourceConfig:
    """Selected MinerU source and its optional preparation settings."""
    kind: SourceKind
    api: APIConfig | None = None
    local_toolchain: LocalToolchainConfig | None = None


def load_book_config(
    book_yml: Path,
) -> tuple[BookConfig, list[ExportPlugin], SourceConfig]:
    """
    Parse a book.yml file and return (BookConfig, [plugins], SourceConfig).

    book.yml schema
    ---------------
    source: uploaded_result              # optional; default when omitted
    mineru_root: resources/mineru          # optional, default shown
    docs_out: docs                         # optional
    volume_uid: 73d5b3e7                   # optional default for chapters
    toc_max_page: 10                       # optional; 0 disables TOC-page skipping
    allow_missing_boundaries: false        # optional; strict by default

    # Uploaded MinerU result already exists under mineru_root
    # source: uploaded_result

    # Optional: use a locally installed MinerU CLI
    local_toolchain:
      executable: mineru
      args: []                             # optional extra CLI args; do not include -p/-o
      sources:                             # volume_uid prefix -> local source file/dir
        73d5b3e7: resources/pdfs/vol1.pdf

    # Optional: use MinerU official API
    api:
      token: "your-token"                  # or set MINERU_API_TOKEN env var
      enable_formula: true
      enable_table: true
      model_version: vlm
      poll_timeout: 600                    # seconds to wait for parsing (default 600)
      sources:                             # volume_uid prefix -> PDF path
        73d5b3e7: resources/pdfs/vol1.pdf
        a1b2c3d4: resources/pdfs/vol2.pdf

    # Optional: Cloudflare Pages deployment (cf_pages plugin)
    deploy:
      pages_project: my-book              # or set PAGES_PROJECT env var
      site_dir: site
      branch: main
      wrangler_cmd: npx wrangler

    plugins:                               # optional list
      - qr_filter                          # built-in name
      - cjk_spacing                        # built-in name
      - cf_pages                           # built-in: deploy to Cloudflare Pages
      # - mypackage.MyPlugin               # dotted import path

    chapters:
      - slug: ch01-overview
        title: 第1章 概述
        volume_uid: 73d5b3e7
        start_pattern: "^第\\s*1\\s*章\\s*概述"  # optional
        start_patterns: []                         # optional alternatives
        aliases: []                                # optional title aliases
      ...
    """
    book_yml = Path(book_yml)
    base_dir = book_yml.parent.resolve()
    with open(book_yml, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    default_volume_uid = _default_volume_uid(raw)
    chapters = [
        ChapterConfig(
            slug=ch["slug"],
            title=ch["title"],
            volume_uid=ch.get("volume_uid", default_volume_uid),
            start_pattern=ch.get("start_pattern"),
            toc_max_page=ch.get("toc_max_page"),
            start_patterns=[str(p) for p in ch.get("start_patterns", [])],
            aliases=[str(a) for a in ch.get("aliases", [])],
        )
        for ch in raw["chapters"]
    ]
    missing_volume_uid = [ch.slug for ch in chapters if not ch.volume_uid]
    if missing_volume_uid:
        raise ValueError(
            "Missing volume_uid for chapters: "
            f"{missing_volume_uid}. Set a top-level volume_uid or per-chapter volume_uid."
        )

    config = BookConfig(
        chapters=chapters,
        mineru_root=_resolve_path(base_dir, raw.get("mineru_root", "resources/mineru")),
        docs_out=_resolve_path(base_dir, raw.get("docs_out", "docs")),
        toc_max_page=_optional_int(raw.get("toc_max_page", 10)),
        allow_missing_boundaries=bool(raw.get("allow_missing_boundaries", False)),
    )

    plugins = _load_plugins(raw.get("plugins", []), raw.get("deploy", {}), base_dir)

    api_cfg: APIConfig | None = None
    if "api" in raw:
        a = raw["api"]
        api_cfg = APIConfig(
            token=a.get("token", ""),
            enable_formula=bool(a.get("enable_formula", True)),
            enable_table=bool(a.get("enable_table", True)),
            model_version=a.get("model_version", "vlm"),
            poll_timeout=_poll_timeout(a.get("poll_timeout", 600)),
            sources={
                str(k): str(_resolve_path(base_dir, v))
                for k, v in a.get("sources", {}).items()
            },
        )

    local_cfg: LocalToolchainConfig | None = None
    if "local_toolchain" in raw:
        l = raw["local_toolchain"]
        local_cfg = LocalToolchainConfig(
            executable=str(l.get("executable", "mineru")),
            args=[str(arg) for arg in l.get("args", [])],
            sources={
                str(k): str(_resolve_path(base_dir, v))
                for k, v in l.get("sources", {}).items()
            },
        )

    source_cfg = SourceConfig(
        kind=_resolve_source_kind(raw),
        api=api_cfg,
        local_toolchain=local_cfg,
    )

    return config, plugins, source_cfg


def _poll_timeout(value) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        raise ValueError(
            f"api.poll_timeout must be a positive number of seconds, got {value!r}."
        )
    return seconds


def _optional_int(value) -> int | None:
    if value is None:
        return None
    return int(value)


def _resolve_path(base_dir: Path, value) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else base_dir / path
    return path.resolve()


def _resolve_source_kind(raw: dict) -> SourceKind:
    aliases = {
        "upload": "uploaded_result",
        "uploaded": "uploaded_result",
        "uploaded_result": "uploaded_result",
        "local": "local_toolchain",
        "local_toolchain": "local_toolchain",
        "api": "official_api",
        "official_api": "official_api",
    }

    source_value = raw.get("source")
    if source_value is None:
        # Backward compatibility for existing projects:
        # keep legacy "api:" configs on official_api and everything else on uploaded_result.
        if "api" in raw:
            return "official_api"
        if "local_toolchain" in raw:
            return "local_toolchain"
        return "uploaded_result"

    normalized = aliases.get(str(source_value).strip().lower())
    if normalized is None:
        allowed = ", ".join(sorted(set(aliases.values())))
        raise ValueError(f"Unsupported source: {source_value!r}. Expected one of: {allowed}")
    return normalized


def _default_volume_uid(raw: dict) -> str:
    if raw.get("volume_uid"):
        return str(raw["volume_uid"])
    for source_key in ("api", "local_toolchain"):
        sources = raw.get(source_key, {}).get("sources", {})
        if len(sources) == 1:
            return str(next(iter(sources.keys())))
    return ""


_BUILTIN_PLUGINS: dict[str, str] = {
    "qr_filter":   "minerupress.plugins.qr_filter.QRFilterPlugin",
    "cjk_spacing": "minerupress.plugins.cjk_spacing.CJKSpacingPlugin",
    "cf_pages":    "minerupress.plugins.cf_pages.CloudflarePagesPlugin",
}


def _load_plugins(
    names: list[str],
    deploy_cfg: dict,
    base_dir: Path,
) -> list[ExportPlugin]:
    plugins = []
    for name in names:
        dotted = _BUILTIN_PLUGINS.get(name, name)
        module_path, cls_name = dotted.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, cls_name)
        # Pass deploy: block kwargs to cf_pages (and any future plugins that accept them)
        if name == "cf_pages" and deploy_cfg:
            plugins.append(cls(
                pages_project=deploy_cfg.get("pages_project", ""),
                site_dir=deploy_cfg.get("site_dir", "site"),
                branch=deploy_cfg.get("branch", "main"),
                wrangler_cmd=deploy_cfg.get("wrangler_cmd", "npx wrangler"),
                project_dir=base_dir,
            ))
        else:
            plugins.append(cls())
    return plugins
