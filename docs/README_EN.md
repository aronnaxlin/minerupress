# MineruPress

Turn MinerU output into publishable MkDocs Material book sites.

MineruPress is a reusable `MinerU -> Markdown -> MkDocs` publishing pipeline for long-form documents such as textbooks, course handouts, internal manuals, training PDFs, and knowledge-base migrations. It keeps book-specific differences in `book.yml` and plugins so the workflow stays repeatable for both humans and AI agents.

## What It Does

- Export MinerU `*_content_list.json` into chapter-based Markdown files.
- Treat multiple physical MinerU directories as one logical `volume_uid`.
- Infer chapter boundaries from titles such as `第10章`, `附录A`, `Chapter 3`, `Lesson IV`, `Appendix B`, `项目二`, or `10.1`.
- Preserve MinerU `code_body` blocks and escape literal HTML/XML tags in prose.
- Rebuild generated `docs/chapters/` and `docs/images/` on every export.
- Inspect MinerU headings and suggest `book.yml` chapter YAML with `minerupress headings`.
- Support image filtering, CJK spacing, Markdown fingerprinting, and optional Cloudflare Pages deployment.

## Install

Recommended install path:

```bash
pip install "minerupress[all]"
pip install mkdocs mkdocs-material
```

For an isolated CLI install:

```bash
pipx install 'minerupress[all]'
pipx inject minerupress mkdocs mkdocs-material
```

For toolchain development instead of normal usage:

```bash
git clone https://github.com/aronnaxlin/minerupress.git
cd minerupress
pip install -e ".[all]"
```

Optional dependency groups:

| Extra | Adds | Used by |
|---|---|---|
| `qr` | `opencv-python` | QR image filtering |
| `cjk` | `pangu` | Chinese/ASCII spacing |
| `all` | both | common full setup |

Python `>=3.11` is required.

## Quick Start

Create a separate book workspace from the template:

```bash
minerupress init ~/dev/my-book/
cd ~/dev/my-book/
```

Then:

1. Preview the placeholder site
2. Choose one `source` mode in `book.yml`
3. Put MinerU output under `resources/mineru/`, or run `minerupress fetch book.yml` for API/local-toolchain sources
4. Edit chapters, export, and preview

```bash
mkdocs serve
```

After real MinerU output is ready:

```bash
minerupress export book.yml
```

Strict build:

```bash
mkdocs build --strict
```

## Common Commands

Local export:

```bash
minerupress export book.yml
```

Fetch from MinerU cloud API, then export:

```bash
minerupress fetch book.yml
```

Fetch first, then export from the main CLI:

```bash
minerupress export --fetch book.yml
```

Fingerprint Markdown output:

```bash
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

Inspect heading candidates and generate chapter YAML:

```bash
minerupress headings resources/mineru --volume-uid javaweb --format yaml --body-only
```

The CLI now uses the unified `minerupress <subcommand>` form. Legacy wrappers such as `minerupress-export`, `minerupress-fetch`, `minerupress-headings`, `mineru-export`, and `mineru-fetch` remain available for backward compatibility.

## Minimal `book.yml`

```yaml
source: uploaded_result
mineru_root: resources/mineru
docs_out: docs
volume_uid: javaweb
toc_max_page: 10
allow_missing_boundaries: false

plugins:
  - qr_filter
  - cjk_spacing

chapters:
  - slug: ch01-overview
    title: 第1章 Web开发概述
```

Guidance:

- The bundled template defaults to `source: uploaded_result`, which never uploads files or runs local parsing.
- Use `source: official_api` with an `api:` block when starting from PDFs through the MinerU official API.
- Use `source: local_toolchain` only when the user installed the MinerU CLI separately; MineruPress does not bundle MinerU.
- Prefer using `title` alone first.
- Boundaries fall back from "label + name" to the label alone (`第1章`) and then to the chapter name alone (heading lines only) and print a `[NOTE]` for every fallback; check those lines.
- Add `aliases` when MinerU headings differ slightly.
- Use `start_pattern` or `start_patterns` only when exact regex control is needed.
- Keep `allow_missing_boundaries: false` for production.

## Built-in Plugins

- `qr_filter`: removes small QR-code images with OpenCV.
- `cjk_spacing`: inserts spacing between CJK and ASCII text with `pangu`, while protecting LaTeX spans.
- `cf_pages`: runs `mkdocs build --strict` and deploys to Cloudflare Pages.

## Documentation

- [Chinese docs index](index.md)
- [Getting Started](guide/getting-started.md)
- [Install and Upgrade](guide/install-and-upgrade.md)
- [End-to-End Workflow](guide/workflow-run-a-book.md)
- [Configuration](guide/configuration.md)
- [Export Pipeline](guide/export-pipeline.md)
- [Plugins](guide/plugins.md)
- [Cloud API and Deploy](guide/cloud-api-and-deploy.md)
- [Validation and Troubleshooting](guide/validation-and-troubleshooting.md)
- [Release and Distribution](guide/release.md)

## Repository Scope

The repository root is the reusable toolchain, not a real book project. For actual books, create a separate working directory with `minerupress init <directory>` and keep generated outputs, secrets, PDFs, and MinerU artifacts out of version control unless that book workspace is intentionally versioned.
