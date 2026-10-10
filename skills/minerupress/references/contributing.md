# Working on MineruPress itself

Use this when the task changes the toolchain: the Python package, the bundled template, the documentation, the tests, or a plugin. Read the repository's `AGENTS.md` as well; it is the authoritative statement of the project's conventions and it is updated together with the code.

## Contents

- [Set up and check](#set-up-and-check)
- [Layout](#layout)
- [Rules that keep the project consistent](#rules-that-keep-the-project-consistent)
- [Writing a plugin](#writing-a-plugin)
- [Testing against real output](#testing-against-real-output)
- [What to update with a behaviour change](#what-to-update-with-a-behaviour-change)

## Set up and check

```bash
git clone https://github.com/aronnaxlin/minerupress.git
cd minerupress
pip install -e ".[dev,all]"

python -m compileall minerupress
pytest
```

Run both checks after every change. If a dependency is missing and `pytest` cannot run, run `compileall` at least and say plainly which checks were not run.

## Layout

| Path | Role |
|---|---|
| `minerupress/core.py` | Export engine: volume discovery, chapter boundaries, item-to-Markdown conversion, image copying, plugin hooks, export statistics |
| `minerupress/loader.py` | Parses `book.yml` into `BookConfig`, plugin instances and `SourceConfig` |
| `minerupress/cli.py` | The `minerupress` command and its subcommands; legacy entry points |
| `minerupress/api_client.py` | MinerU cloud API client: PDF splitting, upload, polling, download, resume state |
| `minerupress/headings.py` | `minerupress headings`: chapter candidates from text items and running headers |
| `minerupress/nav.py` | `minerupress nav`: chapter nav snippet and drift check against `mkdocs.yml` |
| `minerupress/fingerprint.py` | SHA-256 fingerprints of the exported Markdown |
| `minerupress/plugins/` | `ExportPlugin` base class and the built-in plugins |
| `minerupress/book_template/` | Template shipped in the package and copied by `minerupress init` |
| `book_template/` | The same template at the repository root |
| `docs/` | Project documentation. Not a book's generated output. |
| `skills/minerupress/` | This skill |
| `tests/` | pytest suite, synthetic data only |

## Rules that keep the project consistent

- **The engine stays book-agnostic.** Nothing in `core.py` may depend on one book's wording, labels or layout. Differences between books belong in `book.yml` or in a plugin. A heuristic is acceptable only if it is stated in general terms and would be reasonable for a book it has never seen.
- **The two template directories must be identical.** Change `book_template/` and `minerupress/book_template/` together. A test compares them, and `diff -r book_template minerupress/book_template` should print nothing. A new template file also needs an entry under `package-data` in `pyproject.toml`, or it will be missing from the released package.
- **Plugins degrade, they do not crash.** A missing optional dependency or a failure inside a built-in plugin produces one warning and a no-op, so an ordinary export still completes.
- **Paths are resolved from `book.yml`.** Use `pathlib.Path` and resolve relative paths against the directory of `book.yml`, never the current working directory.
- **`api_client.fetch()` returns directories in chunk order.** The exporter reads split parts in that order; a reordering shifts every chapter.
- **Commands with side effects stay explicit.** Anything that uploads, deploys or deletes should be easy to predict from the command name and documented as such.
- **Do not commit book data.** No source PDFs, MinerU output, generated chapters, `site/`, `reports/` or `.env` in this repository.
- **Keep configuration plain.** `BookConfig` and friends are dataclasses. Do not introduce a configuration framework for a new field.

## Writing a plugin

Subclass `minerupress.plugins.base.ExportPlugin` and override only the hooks needed. Hooks run in this order during an export:

| Hook | Called | Return |
|---|---|---|
| `on_image(item, img_path) -> bool` | Once per `image` or `chart` item that has an `img_path`, before chapters are written | `False` drops the image together with its caption and footnote |
| `on_text(item, text) -> str` | For each piece of text: paragraphs, headings, captions, footnotes, list entries, alt text | The text to use |
| `on_chapter_done(slug, lines) -> list[str]` | After a chapter's Markdown lines are assembled | The lines to write |
| `on_export_done(docs_out) -> None` | Once, after all chapters are written | Nothing; for side effects such as deployment |

Points that are easy to get wrong:

- `on_text` receives the raw MinerU text. Escaping of `<`, `>` and link-like text happens afterwards, so HTML returned from `on_text` is displayed literally. To inject markup, do it in `on_chapter_done`.
- Leave `$...$` and `$$...$$` spans untouched in `on_text`; changing them breaks formulas.
- Check `item.get("type")` instead of assuming an image: `on_image` also receives `chart` items.
- Constructor arguments are the plugin's options. `book.yml` passes them as a mapping under the plugin name, and an unknown name is rejected with the list of accepted ones, so give them clear names and defaults.

A user's own plugin needs no change to MineruPress: it is referenced by dotted path in `plugins:` and must be importable.

To add a built-in plugin:

1. Add the module under `minerupress/plugins/`.
2. Register its short name in `_BUILTIN_PLUGINS` in `loader.py`.
3. Export it from `minerupress/plugins/__init__.py` and `minerupress/__init__.py` if it should be importable.
4. Add tests, and update the places listed in the last section.

## Testing against real output

Synthetic tests only prove the code matches the author's assumptions about MinerU output, and those assumptions have been wrong before (field names, item types, where chapter numbers appear). When a change touches conversion or boundary detection, also run it on a real MinerU result:

- Use a throwaway workspace outside the repository with `mineru_root` pointing at the real output and `docs_out` in a temp directory.
- Compare before and after: per-chapter item counts, the `Items by type` table, a diff of the generated chapters.
- Keep the real data out of the repository. Reproduce what was learned as a small synthetic fixture in `tests/`.

Never call the MinerU API from tests. `tests/test_fetch.py` shows how the client's network methods are replaced.

## What to update with a behaviour change

A change that a user can observe is not finished until these agree with it:

- `README.md` and `docs/README_EN.md`
- the relevant page under `docs/guide/` (`configuration.md`, `export-pipeline.md`, `plugins.md`, `cloud-api-and-deploy.md`, `workflow-run-a-book.md`, `validation-and-troubleshooting.md`)
- both copies of the template (`book.yml` comments, `mkdocs.yml`, `Makefile`)
- the docstring of `load_book_config` for a new `book.yml` key
- `AGENTS.md`
- this skill, including the reference file that covers the area

User documentation describes the released package and `minerupress init` first, and source installation only for contributors. The primary commands are `minerupress <subcommand>`; the legacy entry points (`minerupress-export`, `mineru-export` and similar) exist only for old projects and are not presented as the workflow.

Release steps are in `docs/guide/release.md`.
