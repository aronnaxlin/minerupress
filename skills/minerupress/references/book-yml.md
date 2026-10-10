# book.yml Reference

Minimal uploaded-result export:

```yaml
source: uploaded_result
mineru_root: resources/mineru
docs_out: docs
volume_uid: javaweb
toc_max_page: 10
allow_missing_boundaries: false

plugins:
  - qr_filter:          # optional: a single-key mapping passes options
      max_side: 250
  - cjk_spacing

chapters:
  - slug: ch01-overview
    title: 第1章 Web开发概述
  - slug: appendix-a
    title: 附录A 部分习题的解答
```

Cloud API:

```yaml
source: official_api
api:
  token: ""  # prefer MINERU_API_TOKEN in .env
  enable_formula: true
  enable_table: true
  model_version: vlm
  sources:
    javaweb: resources/pdfs/javaweb.pdf
```

Recommended first-pass fetch config for a raw PDF:

```yaml
source: official_api
volume_uid: my-book
allow_missing_boundaries: true

api:
  token: ""  # prefer MINERU_API_TOKEN in .env
  enable_formula: true
  enable_table: true
  model_version: vlm
  sources:
    my-book: resources/pdfs/my-book.pdf

chapters:
  - slug: placeholder
    title: 我的图书标题
```

Local MinerU CLI (installed separately, not bundled by MineruPress):

```yaml
source: local_toolchain

local_toolchain:
  executable: mineru
  args:
    - -b
    - pipeline
  sources:
    my-book: resources/pdfs/my-book.pdf
```

Boundary controls:

- `title`: canonical display title and default boundary source.
- `aliases`: alternate headings to auto-convert into boundary patterns.
- `start_pattern`: one regex for legacy configs.
- `start_patterns`: multiple regex alternatives.
- `toc_max_page`: skip early table-of-contents matches only for the first boundary in a logical volume.
- `allow_missing_boundaries`: keep `false` for CI/production.

Practical guidance:

- Choose one source mode per workspace. Do not configure `api:` and `local_toolchain:` as competing active workflows.
- If starting from a raw PDF, do the first run in an isolated workspace.
- Copy the PDF into the workspace before running `minerupress fetch`.
- `local_toolchain` requires a separately installed MinerU CLI. `uv pip install -U "mineru[all]"` is the common direct install path; use official docs for optional backends and CLI parameters:
  - https://opendatalab.github.io/MinerU/quick_start/
  - https://opendatalab.github.io/MinerU/quick_start/extension_modules/
  - https://opendatalab.github.io/MinerU/usage/cli_tools/
- Use `minerupress headings resources/mineru --volume-uid my-book --format yaml --body-only` after the first fetch to draft chapter boundaries.
- If TOC entries are matched too early, use a display-only `title` plus an exact `start_pattern`.

Supported inferred heading styles include Chinese chapter/section labels, appendices, English `Chapter`/`Chap.`/`Unit`/`Module`/`Part`/`Section`/`Lesson`/`Lecture`, English `Appendix`/`App.`, project/module/task labels, Roman numerals such as `Lesson IV`, and numeric headings such as `10.1`.
