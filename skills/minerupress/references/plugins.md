# Writing a plugin for a book

Write a plugin when a book needs clean-up that `book.yml` options cannot express and that would otherwise mean editing generated Markdown after every export: a promotional line repeated on many pages, a publisher's stamp image, a recurring OCR mistake. A plugin lives in the book workspace; MineruPress itself is not changed.

The built-in plugins and their options are listed in `book-yml.md`.

## A complete example

Put a Python file in the workspace, next to `book.yml`:

```python
# book_plugins.py
from minerupress.plugins.base import ExportPlugin


class DropPromoLines(ExportPlugin):
    """Remove a promotional line the publisher printed on many pages."""

    def __init__(self, phrase: str = "扫码关注") -> None:
        self.phrase = phrase

    def on_chapter_done(self, slug: str, lines: list[str]) -> list[str]:
        return [line for line in lines if self.phrase not in line]
```

Enable it in `book.yml` by its dotted path, `<module>.<Class>`:

```yaml
plugins:
  - qr_filter
  - book_plugins.DropPromoLines:
      phrase: 扫码关注
```

The module has to be importable by the Python that runs `minerupress`. The workspace directory is not on the import path by default, so run from the workspace with:

```bash
PYTHONPATH=. minerupress export book.yml
```

Without it the export stops with `ModuleNotFoundError: No module named 'book_plugins'`. Set the variable in the workspace `Makefile` if the user runs `make export`.

## Hooks

Subclass `ExportPlugin` and override only what is needed. Every hook has a pass-through default. Plugins run in the order they are listed in `book.yml`.

| Hook | Called | Return |
|---|---|---|
| `on_image(item, img_path) -> bool` | Once for each `image` or `chart` item that has an image file, before chapters are written | `False` drops the image together with its caption and footnote |
| `on_text(item, text) -> str` | For each piece of text: paragraphs, headings, captions, footnotes, list entries, image alt text | The text to use |
| `on_chapter_done(slug, lines) -> list[str]` | After one chapter's Markdown has been assembled | The lines to write |
| `on_export_done(docs_out) -> None` | Once, after all chapters are written | Nothing; for side effects |

`item` is the MinerU content-list entry as a dictionary. Useful keys are `type`, `page_idx`, `text_level`, and for images `img_path`, `image_caption` and `image_footnote`. `troubleshooting.md` lists the fields of each item type.

Choosing a hook:

- Decide per image whether to keep it: `on_image`. `img_path` is the source file, so its size or content can be inspected.
- Change wording inside a paragraph, caption or heading: `on_text`.
- Remove or add whole lines, or do anything that depends on neighbouring lines: `on_chapter_done`.

## Things that go wrong

- **HTML returned from `on_text` shows up as literal text.** `<` and `>` are escaped after `on_text` runs. Add markup in `on_chapter_done` instead.
- **Formulas break.** Leave `$...$` and `$$...$$` spans exactly as they are in `on_text`.
- **`on_image` sees more than photos.** It also receives `chart` items. Check `item.get("type")` if the rule should apply to one kind only.
- **An exception stops the export.** Errors in a custom plugin are not caught. Guard against missing keys with `item.get(...)`.
- **An option is rejected.** Options in `book.yml` are passed to `__init__` as keyword arguments. A name that `__init__` does not accept fails at load time with the list of accepted names, so give every option a default.
- **A rule is too broad.** `lines` in `on_chapter_done` includes headings, image lines, table HTML and code blocks. Match as narrowly as the book allows, and compare the output before and after with `minerupress fingerprint`.

Run `minerupress export book.yml` and read `Items by type` and the chapter files to confirm the plugin did what was intended and nothing else.
