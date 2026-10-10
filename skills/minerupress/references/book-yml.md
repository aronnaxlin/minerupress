# book.yml reference

All relative paths are resolved from the directory that contains `book.yml`, not from the current working directory.

## Contents

- [Top-level keys](#top-level-keys)
- [Chapters](#chapters)
- [Source: uploaded_result](#source-uploaded_result)
- [Source: official_api](#source-official_api)
- [Source: local_toolchain](#source-local_toolchain)
- [Plugins](#plugins)
- [Cloudflare Pages deployment](#cloudflare-pages-deployment)
- [.env](#env)

## Top-level keys

```yaml
source: uploaded_result
mineru_root: resources/mineru
docs_out: docs
volume_uid: my-book
toc_max_page: 10
allow_missing_boundaries: false
page_footnotes: skip

plugins:
  - qr_filter
  - cjk_spacing

chapters:
  - slug: ch01-overview
    title: 第1章 概述
```

| Key | Default | Meaning |
|---|---|---|
| `source` | `uploaded_result` | `uploaded_result`, `official_api` or `local_toolchain`. Set it explicitly in new configs. |
| `mineru_root` | `resources/mineru` | Directory that holds one sub-directory per MinerU result. |
| `docs_out` | `docs` | MkDocs docs directory. `chapters/` and `images/` inside it are rebuilt on every export. |
| `volume_uid` | none | Default logical volume for chapters that do not set their own. Matched as a prefix of directory names under `mineru_root`. If omitted and there is exactly one entry in `api.sources` or `local_toolchain.sources`, that key is used. |
| `toc_max_page` | `10` | When searching for the first chapter of a volume, ignore matches on pages with `page_idx` below this value, so table-of-contents lines are not mistaken for chapter openings. `0` turns the filter off. |
| `allow_missing_boundaries` | `false` | `false` fails the export when any chapter is not found. Keep it `false` for a real run; a missing boundary silently merges two chapters. |
| `page_footnotes` | `skip` | `skip` drops MinerU `page_footnote` items. `paragraph` keeps the ones that start with a footnote marker (`①`, `[1]`, `1.`, `*`, `†`, `注：`) and writes them as blockquotes after the last complete paragraph of their page. Numbering is kept as printed, not relinked. |
| `plugins` | `[]` | See [Plugins](#plugins). |
| `chapters` | required | See [Chapters](#chapters). |

## Chapters

```yaml
chapters:
  - slug: ch01-overview          # output file: docs/chapters/ch01-overview.md
    title: 第1章 概述             # page heading, and the default source of the boundary
  - slug: appendix-a
    title: 附录A 习题解答
    aliases:                     # other headings that mark the same boundary
      - Appendix A
  - slug: ch07-special
    title: 第7章 特殊情况
    start_pattern: '^\s*特殊情况\s*$'   # explicit regex, only when needed
```

| Key | Meaning |
|---|---|
| `slug` | Required. File name stem; keep it unique, because two chapters with one slug overwrite each other. It also appears in `mkdocs.yml` nav paths. |
| `title` | Required. Written as the `# ` heading of the chapter and used to derive the boundary patterns. |
| `volume_uid` | Only for multi-volume books; overrides the top-level value. |
| `aliases` | Alternate headings, converted to patterns the same way as `title`. |
| `start_pattern` | One regular expression matched from the start of a text item, case-insensitive. |
| `start_patterns` | A list of such expressions. |
| `toc_max_page` | Per-chapter override of the top-level value. |

Chapters are located in the order they are listed, each one searched for after the previous one. List them in book order.

Quote regular expressions with single quotes so backslashes are not interpreted by YAML.

How titles become patterns, and what to do when a boundary is wrong, is in `chapter-boundaries.md`.

## Source: uploaded_result

No extra block. Put MinerU result directories under `mineru_root`. Each must contain a `*_content_list.json` and, if the book has figures, an `images/` directory. When both `x_content_list.json` and `x_content_list_v2.json` exist, the one without `v2` is used.

`volume_uid` must be a prefix of the directory name. MinerU often names directories with a UUID, so a short prefix such as `73d5b3e7` is enough. Several directories with the same prefix (`my-book_part1`, `my-book_part2`) are read in natural order as one continuous volume.

## Source: official_api

```yaml
source: official_api
api:
  token: ""              # leave empty and put MINERU_API_TOKEN in .env
  enable_formula: true
  enable_table: true
  model_version: vlm
  poll_timeout: 600      # seconds to wait for parsing in one fetch run
  sources:               # volume_uid -> PDF path
    my-book: resources/pdfs/book.pdf
```

Behaviour worth knowing before running `minerupress fetch`:

- PDFs longer than 190 pages are split into chunks and uploaded separately. Results land in `<uid>_part1`, `<uid>_part2`, and so on; a PDF that fits in one chunk lands in `<uid>_full`. Chapters keep using the one `volume_uid`.
- Progress is recorded in `.minerupress/fetch-state.json` next to `book.yml` after every upload and every extracted chunk. A rerun reuses the saved batches: it does not upload again, and it skips a volume whose results are already on disk.
- The saved record is tied to the PDF's path, size and modification time, and to the API options. Changing any of them starts a fresh upload for that volume. Keep the PDF at a stable path inside the workspace.
- `minerupress fetch --force` ignores the record and uploads everything again.
- If parsing takes longer than `poll_timeout`, the error lists each pending chunk with its `batch_id`. Rerun `fetch`, optionally with a larger `poll_timeout`.
- Result archives are downloaded from a different host than the API. A download error names that host; a proxy or DNS rule can block it while the API itself works. Results stay ready on the server, so fixing the network and rerunning `fetch` is enough.

## Source: local_toolchain

```yaml
source: local_toolchain
local_toolchain:
  executable: mineru
  args:                  # extra CLI arguments
    - -b
    - pipeline
  sources:               # volume_uid -> file or directory
    my-book: resources/pdfs/book.pdf
```

MineruPress runs `<executable> <args> -p <source> -o <temp dir>` and copies the result into `mineru_root`. Do not put `-p`, `--path`, `-o` or `--output` in `args`; they are added automatically and the config is rejected if they are present.

The `mineru` CLI must already be installed. MineruPress neither bundles nor installs it. Installation and CLI options are documented by MinerU:

- https://opendatalab.github.io/MinerU/quick_start/
- https://opendatalab.github.io/MinerU/usage/cli_tools/

## Plugins

A plugin is listed by its built-in name or by a dotted import path to a class. Options are passed with a single-key mapping:

```yaml
plugins:
  - qr_filter:
      max_side: 250
  - cjk_spacing
  - mypackage.cleanup.MyPlugin:
      strip_watermark: true
```

An option name the plugin does not accept is a load-time error that lists the accepted names. A custom plugin's module must be importable by the Python that runs `minerupress` (installed, or on `PYTHONPATH`).

Built-in plugins:

| Name | What it does | Options | Needs |
|---|---|---|---|
| `qr_filter` | Drops images that are QR codes. Prints `[qr_filter] dropped <file> (WxH)` for each. | `max_side` (default `250`): images whose long side is larger are never treated as QR codes. | `opencv-python` |
| `cjk_spacing` | Inserts spaces between CJK and Latin text; leaves `$...$` formulas alone. | none | `pangu` (4.x or 6.x) |
| `cf_pages` | After the export, runs `mkdocs build --strict` and deploys to Cloudflare Pages. | Reads the `deploy:` block. | `mkdocs`, `wrangler` |

A plugin whose dependency is missing warns once and does nothing; it does not fail the export. Both dependencies come with `minerupress[all]`.

When an image is filtered, its caption and footnote are dropped with it.

## Cloudflare Pages deployment

```yaml
plugins:
  - cf_pages

deploy:
  pages_project: my-book     # or PAGES_PROJECT in .env
  site_dir: site
  branch: main
  wrangler_cmd: npx wrangler
```

With `cf_pages` enabled, every successful `export` or `fetch` deploys, provided `CLOUDFLARE_API_TOKEN` is set and a project name is configured. Without the token the plugin prints a message and skips the deploy. If the Pages project does not exist it is created.

Because a plain `export` then publishes the site, confirm with the user before enabling `cf_pages`, and before exporting in a workspace where it is enabled and the token is present. The template's `make deploy` is the explicit alternative.

## .env

`minerupress` reads the `.env` file next to `book.yml` before loading the configuration, then a `.env` in the current directory. Variables already set in the environment are not overridden.

```
MINERU_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
PAGES_PROJECT=my-book
```

Do not write tokens into `book.yml`, and do not print or commit `.env`.
