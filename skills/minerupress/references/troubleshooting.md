# Troubleshooting

Find the symptom, confirm the cause from the log or the MinerU output, then apply the fix. Fix `book.yml`, a plugin or the source data; an edit to generated Markdown is undone by the next export.

## Contents

- [Looking at the MinerU output](#looking-at-the-mineru-output)
- [Fetching](#fetching)
- [Finding volumes and chapters](#finding-volumes-and-chapters)
- [Missing or unwanted content](#missing-or-unwanted-content)
- [Text and formulas](#text-and-formulas)
- [Site build and navigation](#site-build-and-navigation)
- [When it is a toolchain bug](#when-it-is-a-toolchain-bug)

## Looking at the MinerU output

Most questions are answered by the `*_content_list.json` in each directory under `resources/mineru/`. It is a flat list of items in reading order. Each has a `type` and a `page_idx`, plus fields that depend on the type:

| `type` | Content fields |
|---|---|
| `text`, `aside_text` | `text`, optional `text_level` (1 = top heading) |
| `image` | `img_path`, `image_caption`, `image_footnote` (older output: `img_caption`, `img_footnote`) |
| `chart` | `img_path`, `chart_caption`, `chart_footnote` |
| `table` | `table_body` (HTML), `table_caption`, `table_footnote` |
| `code` | `code_body`, `code_caption` |
| `equation` | `text` (LaTeX) |
| `list` | `list_items` |
| `header`, `footer`, `page_number`, `page_footnote` | `text` |

A short script that prints the items of one page, or counts items by type, is usually the fastest way to see why something was or was not exported. `page_idx` is zero-based and restarts in each split part (`<uid>_part2` starts again at 0).

## Fetching

| Symptom | Cause and fix |
|---|---|
| `MinerU API token required` | No token was found. Put `MINERU_API_TOKEN=...` in the `.env` next to `book.yml`, or export it in the shell. Only that `.env` and one in the current directory are read. |
| `Could not download the MinerU result from <host>` | The result archive host is not the API host and may be blocked separately by a proxy or DNS rule. Parsing is finished on the server. Fix the network path to that host and rerun `minerupress fetch`; nothing is uploaded again. |
| `Timed out after ...s waiting for MinerU` | Parsing is still running. Rerun `minerupress fetch` to resume; raise `api.poll_timeout` for a large book. The message lists the `batch_id` of each pending chunk. |
| `MinerU has no usable status for ... batch_id=...` | The saved batch expired or was removed. This is the one case for `minerupress fetch --force`, which uploads again. |
| `MinerU batch ... failed` | MinerU rejected that chunk. Rerun `fetch`; only the failed chunk is uploaded again. If it fails repeatedly, the PDF chunk itself is the problem. |
| `results already fetched ...; skipping` but the user wants a fresh parse | Run `minerupress fetch --force`, after confirming it will use API quota. |
| `fetch` exits 1 with "MinerU output is ready, only the chapter configuration is missing or wrong." | Expected on a new book. The source is in place; configure `chapters` and run `export`. |
| `Local MinerU source selected, but the ... CLI was not found` | `local_toolchain` needs a separately installed `mineru` on `PATH`, or `local_toolchain.executable` pointing at it. |

Do not delete `.minerupress/fetch-state.json` to "start clean" after a failure. It is what prevents a second upload.

## Finding volumes and chapters

| Symptom | Cause and fix |
|---|---|
| `Volume directories not found for UIDs: [...]` | No directory under `mineru_root` starts with that `volume_uid`. Check the directory names and either rename the directory or change `volume_uid` to a matching prefix. |
| `No *_content_list.json found in <dir>` | The directory is not a complete MinerU result. Copy the whole result directory, not only the Markdown. |
| `Error: Chapter boundaries not found ...` | See `chapter-boundaries.md`. Start with `minerupress headings ... --format yaml --body-only`. |
| A chapter contains the next chapter's content | The next chapter's boundary was not found (with `allow_missing_boundaries`) or matched too late. Check the `[NOTE]` and `[WARN]` lines for it. |
| A chapter is nearly empty | Its boundary matched a table-of-contents line or a cross-reference just before the next chapter. Raise `toc_max_page` or add an exact `start_pattern`. |
| The chapter heading appears twice at the top of a page | The printed opener differs from `title` (for example `第四章` against `第4章`), so it was not recognised as a repeat. Add the printed form to `aliases`. |

## Missing or unwanted content

Read `Items by type (written / dropped)` at the end of the export first; it shows which item types lost content.

| Symptom | Cause and fix |
|---|---|
| An image is missing | Look for `[qr_filter] dropped <file>` (a plugin removed it) or `[WARN] image file not found` (the file is absent from the result's `images/` directory). |
| A real figure was removed as a QR code | Lower `qr_filter`'s `max_side` below that figure's size, or remove `qr_filter` and filter in a custom plugin. |
| QR codes are still in the site | Detection is best-effort on small scanned images. Raise `max_side` if they are larger than 250 px; otherwise drop them in a custom `on_image` plugin using something stable about them, such as their size or caption. |
| A caption is missing | A filtered image takes its caption and footnote with it. Otherwise check that the item has `image_caption` or `chart_caption` in the content list; if MinerU did not produce one there is nothing to export. |
| An image shows its file name as alt text | The item has no caption. That is the fallback. |
| Small labels appear under images | Those are `image_footnote` values. They are exported with the image. Remove them in an `on_text` plugin if unwanted. |
| Footnotes are missing | Page footnotes are dropped by default. Set `page_footnotes: paragraph` in `book.yml`. Items at the page bottom that do not start with a footnote marker are still dropped, because MinerU sometimes tags stray code or formula fragments as footnotes. |
| Page headers or page numbers are missing | Intended. `header`, `footer` and `page_number` are never exported. |
| `[WARN] N item(s) of unhandled type '...' have content but were dropped` | MinerU produced an item type the exporter has no rule for. This is content loss and worth reporting; see the last section. |

## Text and formulas

| Symptom | Cause and fix |
|---|---|
| `<span>` or other tags show as literal text | Intended. `<` and `>` in prose and captions are escaped so that books about markup display correctly. Table HTML and code blocks are left as they are. |
| Text such as `a[i](j)` is plain text, not a link | Intended. Bracket-then-parenthesis text from OCR is escaped so Markdown does not turn it into a link. Formulas inside `$...$` are not touched. |
| Formulas show as raw LaTeX | The page could not load MathJax. The template loads a pinned MathJax 3 from a CDN, so an offline browser without a cached copy cannot typeset. Self-host MathJax and point `extra_javascript` in `mkdocs.yml` at the local copy. Also check that `pymdownx.arithmatex` with `generic: true` is still in `markdown_extensions`. |
| No spaces between Chinese and Latin text | `cjk_spacing` is not in `plugins`, or `pangu` is not installed (a warning is printed once). Install `minerupress[all]`. |
| An unclosed code fence swallows the rest of a chapter | The exporter closes a dangling fence in MinerU's `code_body`. If it still happens, the fence is inside a `text` item; fix it in an `on_chapter_done` plugin. |

## Site build and navigation

| Symptom | Cause and fix |
|---|---|
| A chapter is exported but not in the site menu | It is missing from `nav` in `mkdocs.yml`. Run `minerupress nav book.yml` and paste the section, then `minerupress nav book.yml --check`. |
| `mkdocs build --strict` fails with a missing file in nav | `nav` points at a chapter file that no longer exists, usually after a slug was renamed. Same fix. |
| `[WARN] mkdocs.yml: ...` after an export | The same drift, reported automatically. |
| A banner from the Material for MkDocs team about MkDocs 2.0 | Informational. The build still works with the pinned `mkdocs<2` that `minerupress[all]` installs. |
| `mkdocs: command not found` | The site tooling is not installed in this environment. `pip install "minerupress[site]"`. |
| The site deployed when it should only have been exported | `cf_pages` is in `plugins` and `CLOUDFLARE_API_TOKEN` is set. Remove the plugin or unset the token for local runs. |

A book run is finished when: `minerupress export book.yml` exits 0 with every chapter found, the `[NOTE]` lines have been checked, `minerupress nav book.yml --check` exits 0, and `mkdocs build --strict` passes.

## When it is a toolchain bug

Change configuration or write a plugin when the behaviour is specific to one book: a recurring watermark line, a publisher's QR codes, an unusual heading style. Report or fix it in MineruPress when the exporter mishandles MinerU output in general: an item type with content that is dropped, a field that is ignored, a crash. For the second kind, capture the item (type and field names, with the text shortened) and the exact log line, and see `contributing.md`.
