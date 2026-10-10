---
name: minerupress
description: 'Use when an AI agent needs to help a user or contributor work with MineruPress: install the released CLI, initialize a book workspace, choose exactly one source mode (`uploaded_result`, `official_api`, or `local_toolchain`), export MinerU results into MkDocs Material chapters, inspect heading boundaries, verify builds, troubleshoot generated output, develop plugins, or maintain the MineruPress repository. Trigger for MineruPress, minerupress, MinerU content_list.json, book.yml, `minerupress init`, `minerupress export`, `minerupress fetch`, `minerupress headings`, `minerupress fingerprint`, generated docs/chapters, or PDF-to-MkDocs book publishing automation.'
---

# MineruPress

Use this skill to support MineruPress as a user-facing publishing tool and as a contributor-maintained Python package.

## Audience Split

For ordinary users, prefer the released package and an isolated book workspace:

```bash
pip install "minerupress[all]"
pip install mkdocs mkdocs-material
minerupress init my-book
cd my-book
```

For contributors changing MineruPress itself, use the repository checkout:

```bash
git clone https://github.com/aronnaxlin/minerupress.git
cd minerupress
pip install -e ".[dev]"
```

Do not make users clone the toolchain repo just to run a book. The bundled template is copied with `minerupress init <directory>` from the installed package.

## Source Modes

Choose exactly one source mode per book workspace:

- `uploaded_result`: The user already has MinerU output under `resources/mineru/`. This is the bundled template default and has no network or local parsing side effects.
- `official_api`: The user starts from PDFs and wants MinerU official API parsing. Requires `api.sources` and `MINERU_API_TOKEN`.
- `local_toolchain`: The user starts from PDFs, images, Office files, or a directory and already installed MinerU's `mineru` CLI separately.

MineruPress must not bundle MinerU or silently install it. For `local_toolchain`, point users to MinerU official installation and CLI docs, with `uv pip install -U "mineru[all]"` as the common install path and official docs as the authority for optional backends and parameters.

## Preferred User Workflow

1. Create or enter an isolated book workspace with `minerupress init <dir>`.
2. Choose one `source` in `book.yml`.
3. Prepare source data:
   - For `uploaded_result`, put MinerU output directories under `resources/mineru/`.
   - For `official_api`, put PDFs under `resources/pdfs/`, configure `api.sources`, then run `minerupress fetch book.yml`.
   - For `local_toolchain`, install MinerU separately, configure `local_toolchain.sources`, then run `minerupress fetch book.yml`.
4. Inspect generated MinerU output and heading candidates.
5. Refine `chapters` in `book.yml`.
6. Run `minerupress export book.yml`.
7. Verify with `mkdocs build --strict`.
8. Optionally create fingerprints with `minerupress fingerprint --docs-dir docs --out reports/fingerprints.json`.

Use `minerupress export --fetch book.yml` only as a convenience or backward-compatible shortcut. In explanations, keep `fetch` as "prepare source then export" and `export` as "export existing MinerU output".

## Workspace Rules

When operating on a book workspace:

- Read `book.yml` and `mkdocs.yml` first.
- Read local `AGENTS.md` if present.
- Treat `.env`, source PDFs, `resources/mineru/`, `docs/chapters/`, `docs/images/`, `site/`, and `reports/` as local/generated unless the user explicitly wants to version that book project.
- Do not hand-edit generated chapter Markdown as the durable fix; update `book.yml`, the source MinerU output, or a plugin.
- Copy PDFs into the workspace, usually under `resources/pdfs/`, before API fetch or local parsing. Fetch resume state identifies the source PDF by path, size and mtime, so a stable local copy resumes reliably. Split chunks go to a temp dir, never next to the PDF.
- `official_api` fetch is resumable: batch IDs are saved in `.minerupress/fetch-state.json`. After a download failure or poll timeout, rerun `minerupress fetch`; do not re-upload by hand. Use `minerupress fetch --force` only when the user wants to upload and parse again. Never call the MinerU API just to test.
- `MINERU_API_TOKEN` and `CLOUDFLARE_*` are read from the `.env` next to `book.yml`; real environment variables take precedence.
- On a new book `fetch` ends with a non-zero exit and a "source is ready, chapters missing" message because the template has a placeholder chapter. That is expected: run `minerupress headings`, fix `chapters`, then `minerupress export`.

## Commands

Current primary CLI:

```bash
minerupress init my-book
minerupress export book.yml
minerupress fetch book.yml
minerupress headings resources/mineru --volume-uid my-book --format yaml --body-only
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

Legacy wrappers such as `minerupress-export`, `minerupress-fetch`, `minerupress-headings`, `mineru-export`, and `mineru-fetch` remain available only for existing projects. Do not present them as the main workflow.

## `book.yml` Guidance

Set `source` explicitly for new configs:

```yaml
source: uploaded_result
mineru_root: resources/mineru
docs_out: docs
volume_uid: my-book
toc_max_page: 10
allow_missing_boundaries: false

plugins:
  - qr_filter
  - cjk_spacing

chapters:
  - slug: ch01-overview
    title: 第1章 概述
```

For API mode:

```yaml
source: official_api
api:
  token: ""
  enable_formula: true
  enable_table: true
  model_version: vlm
  sources:
    my-book: resources/pdfs/book.pdf
```

For local MinerU CLI mode:

```yaml
source: local_toolchain
local_toolchain:
  executable: mineru
  args:
    - -b
    - pipeline
  sources:
    my-book: resources/pdfs/book.pdf
```

`local_toolchain.args` must not include `-p`, `--path`, `-o`, or `--output`; MineruPress appends those automatically.

## Chapter Boundary Guidance

Prefer chapter `title` plus `slug`; omit regexes unless matching is ambiguous.

Use `aliases` for alternate visible headings:

```yaml
chapters:
  - slug: appendix-a
    title: 附录A 部分习题的解答
    aliases:
      - Appendix A
```

Use `start_patterns` for precise regex alternatives:

```yaml
chapters:
  - slug: unit-01
    title: 第一单元 Web 基础
    start_patterns:
      - "^Unit\\s*1\\b"
      - "^第\\s*一\\s*单元"
```

Only use `--allow-missing-boundaries` while diagnosing bad MinerU output. A successful production run should find every configured chapter boundary.

If TOC lines such as `第1章 引论 …… 3` are matched before the real body heading, switch to exact body-heading regexes:

```yaml
chapters:
  - slug: ch01-introduction
    title: 引论
    start_pattern: "^第\\s*1\\s*章$"
```

Use the headings helper before hand-writing many boundaries:

```bash
minerupress headings resources/mineru --volume-uid my-book --format report
minerupress headings resources/mineru --volume-uid my-book --format yaml --body-only
```

## Verification

For a user workspace:

```bash
minerupress export book.yml
mkdocs build --strict
```

For repository development:

```bash
python -m compileall minerupress
pytest
```

When template behavior changes, confirm `book_template/` and `minerupress/book_template/` are synchronized and that `minerupress init <tmp-dir>` creates a buildable placeholder site.

## Generated Output Behavior

Each export rebuilds:

- `docs/chapters/`
- `docs/images/`

If a chapter appears wrong, fix the configuration, source data, or plugin. Avoid treating generated Markdown as the source of truth.

## Content Details

MinerU code items may store their body in `code_body` rather than `text`. The exporter preserves already-fenced code blocks from MinerU and wraps unfenced code.

Literal HTML/XML tags in normal prose and captions are escaped during export so textbooks can discuss tags such as `<span>` without MkDocs rendering them as real HTML. Raw `table_body` HTML is preserved as table markup.

## References

Read `references/book-yml.md` for compact config examples. For the current end-to-end user workflow, read `docs/guide/getting-started.md`, `docs/guide/configuration.md`, and `docs/guide/workflow-run-a-book.md`.
