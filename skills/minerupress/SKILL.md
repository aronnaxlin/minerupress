---
name: minerupress
description: Turn MinerU PDF-parsing output into a MkDocs Material book site with the `minerupress` CLI, and maintain the MineruPress toolchain itself. Use this skill whenever the user mentions MineruPress or minerupress, a `book.yml`, MinerU `*_content_list.json` output, or wants to publish a PDF or scanned textbook as an online book or docs site, even if they do not name the tool. Also use it for `minerupress init`, `fetch`, `export`, `headings`, `nav` and `fingerprint`, for "chapter boundary not found" errors, missing captions, images or chapters in the exported site, an interrupted MinerU API fetch, writing an export plugin, or changing the minerupress repository.
---

# MineruPress

MineruPress converts MinerU output into a book site:

```
PDF ──(MinerU)──> resources/mineru/<uid>*/…_content_list.json + images/
    ──(minerupress export)──> docs/chapters/*.md + docs/images/
    ──(mkdocs build)──> site/
```

Everything book-specific lives in one file, `book.yml`: where the MinerU output comes from, the chapter list, and the plugins. The export engine itself knows nothing about any particular book.

## First, work out which job this is

- **Running a book** (most requests): the user has a PDF or MinerU output and wants a site. Use the released package in an isolated workspace. Follow the workflow below.
- **Changing MineruPress itself**: the working directory is the `minerupress` repository (it has `pyproject.toml` and a `minerupress/` package). Read `references/contributing.md` first; it has the checks, the layout and the rules that keep the template and docs in sync.

Do not make a user clone the repository just to run a book. `minerupress init` copies the template out of the installed package.

## Commands that have side effects

Check with the user before running these, because they cost money or quota, publish something, or overwrite files:

| Command | What it does beyond the obvious |
|---|---|
| `minerupress fetch` with `source: official_api` | Uploads the PDFs to the MinerU cloud API and uses the user's API quota. |
| `minerupress fetch --force` | Ignores saved progress and uploads and parses again. Almost never what you want after a failure. |
| `minerupress fetch` with `source: local_toolchain` | Runs the user's own `mineru` CLI, which can take a long time and a lot of memory. |
| `minerupress export` or `fetch` when `cf_pages` is in `plugins` | If `CLOUDFLARE_API_TOKEN` is set, builds the site and deploys it to Cloudflare Pages at the end of the export. |
| `minerupress export` (always) | Deletes and rebuilds `docs/chapters/` and `docs/images/`. Hand edits there are lost. |

Never call the MinerU API "just to test". `export`, `headings`, `nav` and `fingerprint` on existing output are local and safe to run freely.

## Running a book

### 1. Install and create a workspace

```bash
pip install "minerupress[all]"
minerupress init my-book
cd my-book
```

`[all]` brings the plugin dependencies and a pinned MkDocs (`mkdocs<2`). Avoid installing `mkdocs` and `mkdocs-material` on their own without version pins: that can pull MkDocs 2, which the template is not tested with. Use `minerupress[site]` if only the site tooling is missing.

The workspace contains `book.yml`, `mkdocs.yml`, `Makefile`, `.env.example`, `.gitignore`, `docs/index.md` and empty `resources/mineru/` and `resources/pdfs/`.

### 2. Choose one source mode

Set `source` in `book.yml` to exactly one of:

| `source` | Use when | Prepare with |
|---|---|---|
| `uploaded_result` (template default) | MinerU output already exists | Copy each result directory into `resources/mineru/`, then `minerupress export book.yml` |
| `official_api` | Starting from a PDF, using MinerU's cloud API | Put the PDF in `resources/pdfs/`, set `api.sources`, put `MINERU_API_TOKEN` in `.env`, then `minerupress fetch book.yml` |
| `local_toolchain` | Starting from files, with MinerU installed locally | Set `local_toolchain.sources`, then `minerupress fetch book.yml` |

MineruPress does not bundle or install MinerU. For `local_toolchain`, send the user to the MinerU documentation for installation.

`volume_uid` ties the three things together: it is the key in `api.sources`, the prefix of the directory under `resources/mineru/` (`<uid>_full`, or `<uid>_part1`, `<uid>_part2` when a long PDF is split), and the default for every chapter. For `uploaded_result`, set it to a prefix of the directory name MinerU produced.

`fetch` means "prepare the source, then export". `export` means "export what is already in `resources/mineru/`". After the source is prepared once, use `export` for every later run.

**On a new book, `fetch` ends with exit code 1 and "MinerU output is ready, only the chapter configuration is missing or wrong."** That is the expected outcome, not a failed fetch: the template only has a placeholder chapter. Continue with step 3.

**If a fetch is interrupted** (network error, poll timeout), run `minerupress fetch book.yml` again. Progress is saved in `.minerupress/fetch-state.json`, so the rerun polls and downloads without uploading again.

### 3. Fill in the chapters

Ask the tool what the chapters are instead of guessing:

```bash
minerupress headings resources/mineru --volume-uid <uid> --format yaml --body-only
```

The YAML on stdout is a ready `chapters:` block. Replace the placeholder in `book.yml` with it, then rename the slugs if the user wants descriptive ones (`ch01` → `ch01-overview`). Lines starting with `warning:` on stderr are a to-do list: gaps in chapter numbering, chapters whose opening could not be located, or patterns that would hit the wrong line.

Each chapter needs only `slug` and `title`. Add `start_pattern` or `aliases` only when the boundary is not found or lands in the wrong place; `references/chapter-boundaries.md` explains how matching works and how to fix each failure.

### 4. Export and read the log

```bash
minerupress export book.yml
```

The log is the main evidence of whether the export is right. Look at these lines before declaring success:

- `[NOTE] boundary fallback (...)`: the chapter was located by its number alone or its name alone. Check that the reported text and page really are the chapter opening.
- `[WARN] boundary not found`, or an `Error:` followed by next steps: a chapter was not located. Fix `chapters`; do not reach for `--allow-missing-boundaries` except while diagnosing.
- `Images: N copied, M filtered` and `[qr_filter] dropped <file> (WxH)`: which images a plugin removed.
- `Items by type (written / dropped)`: content that was not written. Dropped `header`, `footer` and `page_number` are normal. Any other type with a large dropped count, or a `[WARN] ... unhandled type`, means content is being lost.
- `[WARN] mkdocs.yml: ...`: the site navigation does not match the chapters (next step).

### 5. Sync the navigation and build

The chapter list is written twice: in `book.yml` and in the `nav` of `mkdocs.yml`. Keep them in sync with:

```bash
minerupress nav book.yml            # prints the chapter nav section to paste into mkdocs.yml
minerupress nav book.yml --check    # exit 1 when they differ
mkdocs build --strict
```

Run the check even when the build passes: MkDocs reports a page that is missing from `nav` only at INFO level, so a forgotten chapter builds cleanly and is simply absent from the site.

### 6. Optional: record what changed

```bash
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

It stores a hash per Markdown file and prints which files changed since the last run. Useful before and after a configuration change to see which chapters it affected.

## Fix causes, not output

`docs/chapters/` and `docs/images/` are regenerated on every export, so an edit there lasts until the next run. When a chapter looks wrong, change one of:

- `book.yml` (chapter boundaries, plugins, options such as `page_footnotes`),
- a plugin (text clean-up, image filtering, per-chapter post-processing),
- the MinerU output itself, if the parse is wrong.

Hand-maintained pages such as `docs/index.md` are safe; only the two generated directories are rebuilt.

Treat `.env`, source PDFs, `resources/mineru/`, `docs/chapters/`, `docs/images/`, `site/`, `reports/` and `.minerupress/` as local or generated. Do not commit them unless the user is deliberately versioning a book project.

## Where to read more

| Read | When |
|---|---|
| `references/book-yml.md` | Writing or reviewing `book.yml`: every key, the three source blocks, plugin options, `.env` |
| `references/chapter-boundaries.md` | A boundary is missing or wrong, `headings` output is incomplete, or the book has several volumes |
| `references/troubleshooting.md` | Something in the output is missing or broken: captions, images, footnotes, formulas, fetch failures, build errors |
| `references/contributing.md` | Changing the MineruPress repository, or writing a plugin |
