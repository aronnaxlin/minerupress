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
```

`[all]` also installs the site dependencies (`mkdocs>=1.6,<2` and `mkdocs-material>=9.5,<10`, which keeps you clear of the MkDocs 2.0 incompatibilities). Use `minerupress[site]` if you only want those.

For an isolated CLI install:

```bash
pipx install 'minerupress[all]'
pipx inject minerupress mkdocs --include-apps   # only exposes the mkdocs command
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
| `site` | `mkdocs>=1.6,<2`, `mkdocs-material>=9.5,<10` | `mkdocs serve` / `mkdocs build --strict` |
| `all` | all of the above | common full setup |

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

Print the chapter nav for `mkdocs.yml`, or check the existing nav against `book.yml` (read-only; `mkdocs.yml` is never rewritten):

```bash
minerupress nav book.yml
minerupress nav book.yml --check
```

`--check` exits non-zero when a chapter is missing from the nav, the nav points at a chapter file that `book.yml` does not define, or the order differs. `mkdocs build --strict` only reports pages missing from `nav` at INFO level, so run it after adding or removing chapters.

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
- Add `aliases` when MinerU headings differ slightly.
- Use `start_pattern` or `start_patterns` only when exact regex control is needed.
- Keep `allow_missing_boundaries: false` for production.

## Built-in Plugins

- `qr_filter`: removes small QR-code images with OpenCV. It tries the original image plus upscaled, bordered and binarised variants, and only accepts a hit whose quad fills most of the image and is close to square, so small matrices, chessboards and graph drawings are kept. Every dropped image is printed with its file name and size.
- `cjk_spacing`: inserts spacing between CJK and ASCII text with `pangu`, while protecting LaTeX spans.
- `cf_pages`: runs `mkdocs build --strict` and deploys to Cloudflare Pages.

Pass options to a plugin with a single-key mapping; plain names keep working, and `cf_pages` still reads its settings from `deploy:`:

```yaml
plugins:
  - qr_filter:
      max_side: 250     # images larger than this are never treated as QR codes
  - cjk_spacing
```

An unknown option name fails with an error that lists the options the plugin accepts. Custom dotted-path plugins receive options the same way, as `__init__` keyword arguments.

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
