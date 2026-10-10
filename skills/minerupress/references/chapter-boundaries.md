# Chapter boundaries

A chapter starts at the first MinerU text item that matches one of its patterns, searching forward from where the previous chapter started. It ends where the next chapter starts. Getting boundaries right is the main piece of manual work in running a book.

## Contents

- [Start with `headings`](#start-with-headings)
- [How a title becomes a boundary](#how-a-title-becomes-a-boundary)
- [Reading the result](#reading-the-result)
- [Fixing a boundary](#fixing-a-boundary)
- [Books with several volumes](#books-with-several-volumes)

## Start with `headings`

```bash
minerupress headings resources/mineru --volume-uid <uid> --format yaml --body-only
```

- stdout is a `chapters:` block with `slug`, full `title` (for example `第7章 特殊情况`) and, where one is needed, a `start_pattern`. Paste it into `book.yml`.
- stderr carries `warning:` lines. Each is something to resolve before exporting: a gap or repeat in chapter numbers, a chapter whose opening was not located (it is listed without a `start_pattern`), or a pattern that would match a different line during export.

To see what the tool is looking at, use the report form:

```bash
minerupress headings resources/mineru --volume-uid <uid> --body-only
```

Each candidate is printed as `<directory>:<item index> page=<page_idx> L<text_level> <toc?|body> <confidence> <kind> <label> | <text>`. Add `--include-generic` to also list level-1 headings that are not chapters, parts or appendices; that helps when a book uses unnumbered chapter titles.

`headings` recognises standalone chapter labels at any heading level, and it reads the running page headers to enumerate chapters. That second source matters for scanned books: OCR often loses the large decorative chapter number on an opening page, but the header on the following pages still says `第 7 章 …`. The chapter is then located by finding its name on the pages just before that header first appears.

`--toc-max-page` (default `20`) only affects which candidates are labelled as table-of-contents lines in this command. It is separate from `toc_max_page` in `book.yml`.

## How a title becomes a boundary

From `title` (and each entry in `aliases`) the exporter derives patterns and tries them in tiers. A weaker tier is used only when the stronger ones find nothing in the rest of the volume.

1. **Strong.** Any `start_pattern` or `start_patterns`, the full title as one line, and "label followed by name" (`第1章 概述`, `Chapter 1: Overview`). Whitespace and number style are flexible: `第1章`, `第 1 章`, `第一章`, `Chapter I`, `Chapter One` are treated as the same label.
2. **Label only.** A whole line that is just the label (`第1章`). This is the common layout where the number and the name are printed as two separate lines.
3. **Name only.** A whole line that is just the chapter name (`概述`), with OCR spacing tolerated (`概 述`). Only lines that MinerU marked as headings qualify, so a sentence or caption that happens to equal the name is not matched.

Recognised label styles include `第N章/节/讲/课/篇/单元/模块/部分`, `附录A`, `项目/模块/任务/案例/单元/专题/实验 N`, `Chapter/Chap./Unit/Module/Part/Section/Lesson/Lecture/Book N`, `Appendix A`, and dotted numbers such as `10.1`. A title that is a bare integer plus a name (`1 绪论`) does not get a label-only pattern, because a lone `1` matches too much.

Only items of type `text` and `aside_text` can be boundaries. Page headers, captions and table cells cannot.

For the first chapter of each volume, matches on pages before `toc_max_page` are ignored so that the table of contents does not win.

## Reading the result

During export:

```
[NOTE] boundary fallback (tier 2, chapter number only): 第1章 概述 -> '第1章' (my-book_part1 item 103, page_idx 18)
```

A note means tier 2 or 3 was used. It is not an error. Check that the quoted text and page are the real chapter opening, especially for tier 3.

```
[WARN] <title>: the same line also appears later at ...
```

The matched line occurs again further on. The first occurrence was taken; if that one is a section heading or a cross-reference, add an explicit `start_pattern`.

```
[WARN] boundary not found: <title>
```

Nothing matched. With the default strict mode the export stops with `Error: Chapter boundaries not found ...` and prints next steps.

After a clean export, a quick sanity check is the per-chapter line `Wrote <slug>.md  (N items)`: a chapter with a handful of items, or one several times larger than its neighbours, usually has a wrong boundary on one side.

## Fixing a boundary

Find out what MinerU actually produced for the opening page, then pick the smallest fix.

| Situation | Fix |
|---|---|
| The chapter is not found | Run the `headings` report and look for the opening line. If the name was recognised differently, add it to `aliases`. If the opening is some other line, write a `start_pattern` for it. |
| The table of contents is matched instead of the body | Raise `toc_max_page` above the last contents page. For a later chapter, write an exact pattern such as `'^\s*第\s*3\s*章\s*$'` that the contents line (which has a page number after it) does not satisfy. |
| The first chapter starts before page 10 | Lower `toc_max_page`, or set it to `0` when the PDF has no contents pages. A chapter that opens a later split part at `page_idx` 0 is not affected: the filter applies only to the first boundary of a volume. |
| The opening line has no heading level | Tier 3 will not match it. Add a `start_pattern` for the exact line. |
| A section heading equals a later chapter's name | Add a `start_pattern` that includes something unique to the real opening, or rely on the label by keeping the number in `title`. |
| OCR dropped both the number and the name | Use any stable text on the opening page as `start_pattern`. If nothing is stable, the MinerU parse needs to be redone or repaired. |

`--allow-missing-boundaries` (or `allow_missing_boundaries: true`) turns a missing boundary into a warning and skips that chapter, merging its content into the previous one. Use it only to get a partial export while diagnosing. A finished book should find every chapter with the strict default.

The printed chapter opening is not duplicated in the output: the exporter writes `# <title>` itself and skips the leading lines on the opening page that only repeat a piece of the title.

## Books with several volumes

Give each PDF its own `volume_uid` and set it per chapter:

```yaml
api:
  sources:
    vol1: resources/pdfs/volume-1.pdf
    vol2: resources/pdfs/volume-2.pdf

chapters:
  - slug: v1-ch01
    title: 第1章 概述
    volume_uid: vol1
  - slug: v2-ch01
    title: 第1章 进阶
    volume_uid: vol2
```

Run `headings` once per `--volume-uid`.

When several uids match a directory (`vol1` and `vol10` both match `vol10_full`), the longest one owns it. A `[WARN] volume_uid '...' also matches ...` line means a directory with a looser name was merged into the volume; rename or move it if it belongs to another book.
