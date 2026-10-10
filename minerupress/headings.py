"""
minerupress.headings
~~~~~~~~~~~~~~~~~~~~
Inspect MinerU content_list.json files and suggest chapter boundaries.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from typing import Iterable

from .core import (
    BookConfig,
    _VolumeSegment,
    _find_boundary_after,
    _flexible_literal,
    _irregular_segment_dirs,
)

_NATURAL_PARTS = re.compile(r"(\d+)")
_SPACE_RE = re.compile(r"\s+")
_TOC_LEADER_RE = re.compile(r"(?:\.{2,}|…+|··+|--+)\s*\d+\s*$")
_TRAILING_PAGE_RE = re.compile(r"\s+(?:\.{2,}|…+|··+)?\s*\d+\s*$")
_CHAPTER_ONLY_RE = re.compile(
    r"^\s*第\s*([0-9０-９一二三四五六七八九十百千万零〇两]+)\s*章\s*$"
)
_CHAPTER_FULL_RE = re.compile(
    r"^\s*第\s*([0-9０-９一二三四五六七八九十百千万零〇两]+)\s*章\s*(.+?)\s*$"
)
_APPENDIX_ONLY_RE = re.compile(r"^\s*附\s*录\s*([A-Za-zＡ-Ｚａ-ｚ0-9０-９]+)\s*$")
_APPENDIX_FULL_RE = re.compile(r"^\s*附\s*录\s*([A-Za-zＡ-Ｚａ-ｚ0-9０-９]+)\s*(.+?)\s*$")
_PART_RE = re.compile(
    r"^\s*第\s*([0-9０-９一二三四五六七八九十百千万零〇两]+)\s*篇\s*(.+?)?\s*$"
)
_SECTION_RE = re.compile(r"^\s*\d+(?:\.\d+)+\s+")
# Label and name split by a space or punctuation, as opposed to a sentence
# that merely starts with "第3章".
_SEPARATED_TITLE_RE = re.compile(
    r"^\s*(?:第\s*[0-9０-９一二三四五六七八九十百千万零〇两]+\s*[章篇]"
    r"|附\s*录\s*[A-Za-zＡ-Ｚａ-ｚ0-9０-９]+)\s*[\s:：、.．\-—]\s*\S"
)
_HEADING_TYPES = {"text", "aside_text"}
# Running page headers: "第 7 章 减治法", optionally prefixed by a page number.
_HEADER_CHAPTER_RE = re.compile(
    r"^\s*(?:\d+\s+)?第\s*([0-9０-９一二三四五六七八九十百千万零〇两]+)\s*章\s*(.*)$"
)
_HEADER_APPENDIX_RE = re.compile(
    r"^\s*(?:\d+\s+)?附\s*录\s*([A-Za-zＡ-Ｚａ-ｚ0-9０-９]+)\s*(.*)$"
)
# A chapter known only from running headers must show up on several pages,
# otherwise one OCR slip in a header would invent a chapter.
_MIN_HEADER_REPEATS = 2
_YAML_PLAIN_RE = re.compile(r"[\w][\w .\-()（）、，。·/]*", re.UNICODE)
_YAML_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "y", "n", "~"}


@dataclass(frozen=True)
class HeadingCandidate:
    segment: str
    item_idx: int
    page_idx: int | None
    level: int | None
    text: str
    kind: str
    label: str
    title: str
    start_pattern: str
    is_toc_like: bool
    confidence: str


def load_content_items(mineru_root: Path, volume_uid: str | None = None) -> list[tuple[str, list[dict]]]:
    """Load MinerU content_list items grouped by physical segment directory."""
    root = Path(mineru_root)
    if not root.exists():
        raise FileNotFoundError(f"MinerU root not found: {root}")

    dirs = [
        path for path in sorted(root.iterdir(), key=_natural_key)
        if path.is_dir() and (volume_uid is None or path.name.startswith(volume_uid))
    ]
    if not dirs:
        target = f" matching volume_uid={volume_uid!r}" if volume_uid else ""
        raise FileNotFoundError(f"No MinerU segment directories found in {root}{target}")

    if volume_uid:
        odd = _irregular_segment_dirs(dirs, volume_uid)
        if odd:
            print(
                f"warning: volume_uid {volume_uid!r} also matches "
                f"{', '.join(d.name for d in odd)}; they are inspected as extra segments",
                file=sys.stderr,
            )

    loaded: list[tuple[str, list[dict]]] = []
    for directory in dirs:
        candidates = sorted(directory.glob("*_content_list.json"))
        if not candidates:
            continue
        non_v2 = [path for path in candidates if "v2" not in path.name]
        content_path = non_v2[0] if non_v2 else candidates[0]
        with open(content_path, encoding="utf-8") as f:
            loaded.append((directory.name, json.load(f)))
    if not loaded:
        raise FileNotFoundError(f"No *_content_list.json files found in {root}")
    return loaded


def analyze_headings(
    segments: list[tuple[str, list[dict]]],
    *,
    toc_max_page: int | None = 20,
    include_toc: bool = True,
    include_generic: bool = False,
    warnings: list[str] | None = None,
) -> list[HeadingCandidate]:
    """Return heading-like MinerU text items, with TOC and boundary hints.

    Chapters whose opening page lost the "第N章" label are recovered from the
    running page headers.  Problems worth a human look (number gaps, chapters
    that could not be located, patterns that would resolve to another line) are
    appended to ``warnings`` when a list is given.
    """
    notes: list[str] = warnings if warnings is not None else []
    results: list[HeadingCandidate] = []
    for segment_name, items in segments:
        for item_idx, item in enumerate(items):
            item_type = item.get("type")
            if item_type not in _HEADING_TYPES:
                continue
            text = _normalize_text(item.get("text", ""))
            if not text:
                continue
            if (
                item_type == "text"
                and item.get("text_level") != 1
                and not _is_label_text(text, item.get("text_level"))
            ):
                continue
            candidate = _classify_heading(
                segment_name=segment_name,
                item_idx=item_idx,
                item=item,
                text=text,
                items=items,
                toc_max_page=toc_max_page,
            )
            if candidate and not include_generic and candidate.kind == "heading":
                continue
            if candidate and (include_toc or not candidate.is_toc_like):
                results.append(candidate)

    results = _add_header_chapters(segments, results, notes)
    order = {name: idx for idx, (name, _) in enumerate(segments)}
    results.sort(key=lambda c: (order.get(c.segment, 0), c.item_idx))
    notes.extend(_check_chapter_sequence(results))
    notes.extend(_check_start_patterns(segments, results))
    return results


def _is_label_text(text: str, level: object) -> bool:
    """Whether a text item that is not a level-1 heading may still open a chapter.

    A line holding only "第N章" is a label at any level (MinerU often tags it
    level 2 or nothing).  Label plus name needs some heading level and a
    separator, otherwise it is more likely a sentence that starts with a
    cross-reference.
    """
    if _CHAPTER_ONLY_RE.match(text) or _APPENDIX_ONLY_RE.match(text):
        return True
    if not _optional_int(level):
        return False
    return _SEPARATED_TITLE_RE.match(text) is not None


@dataclass
class _RunningHeader:
    kind: str
    label: str
    titles: Counter
    count: int
    segment: str
    item_idx: int
    page_idx: int | None


def _collect_running_headers(
    segments: list[tuple[str, list[dict]]],
) -> list[_RunningHeader]:
    """Enumerate chapters/appendices from ``type: header`` items, first seen first."""
    found: dict[tuple[str, str], _RunningHeader] = {}
    for segment_name, items in segments:
        for item_idx, item in enumerate(items):
            if item.get("type") != "header":
                continue
            text = _normalize_text(item.get("text", ""))
            kind = "chapter"
            match = _HEADER_CHAPTER_RE.match(text)
            if not match:
                kind = "appendix"
                match = _HEADER_APPENDIX_RE.match(text)
            if not match:
                continue
            label = _ascii_digits(match.group(1))
            if kind == "appendix":
                label = label.upper()
            title = _clean_title(_strip_toc_tail(match.group(2)))
            key = (kind, _chapter_key(label))
            header = found.get(key)
            if header is None:
                header = found[key] = _RunningHeader(
                    kind=kind,
                    label=label,
                    titles=Counter(),
                    count=0,
                    segment=segment_name,
                    item_idx=item_idx,
                    page_idx=_optional_int(item.get("page_idx")),
                )
            header.count += 1
            if title:
                header.titles[title] += 1
    return list(found.values())


def _chapter_key(label: str) -> str:
    value = _han_to_int(label)
    if value is None and label.isdigit():
        value = int(label)
    return str(value) if value is not None else label


def _add_header_chapters(
    segments: list[tuple[str, list[dict]]],
    candidates: list[HeadingCandidate],
    notes: list[str],
) -> list[HeadingCandidate]:
    """Add chapters that have running headers but no standalone label item."""
    order = {name: idx for idx, (name, _) in enumerate(segments)}
    items_by_name = dict(segments)
    known = {
        (c.kind, _chapter_key(c.label))
        for c in candidates
        if c.kind in {"chapter", "appendix"} and not c.is_toc_like
    }
    resolved = list(candidates)

    def position(c: HeadingCandidate) -> tuple[int, int]:
        return order.get(c.segment, 0), c.item_idx

    for header in _collect_running_headers(segments):
        key = (header.kind, _chapter_key(header.label))
        title = header.titles.most_common(1)[0][0] if header.titles else ""
        if key in known:
            _fill_missing_title(resolved, key, title)
            continue
        name = _display_label(header.kind, header.label)
        if header.count < _MIN_HEADER_REPEATS:
            notes.append(
                f"ignored {name}: seen in a single running header only "
                f"({header.segment}:{header.item_idx}); likely an OCR slip"
            )
            continue

        header_pos = (order[header.segment], header.item_idx)
        previous = [
            position(c) for c in resolved
            if c.kind in {"chapter", "appendix"}
            and not c.is_toc_like
            and position(c) < header_pos
        ]
        floor = max(previous) if previous else (0, -1)
        opener = _find_named_opener(segments, title, floor, header_pos)
        if opener is None:
            notes.append(
                f"{name}: running header '{title}' first seen at "
                f"{header.segment}:{header.item_idx} (page_idx {header.page_idx}) "
                f"but no opening line was found; add a start_pattern by hand"
            )
            resolved.append(
                HeadingCandidate(
                    segment=header.segment,
                    item_idx=header.item_idx,
                    page_idx=header.page_idx,
                    level=None,
                    text=f"{name} {title}".strip(),
                    kind=header.kind,
                    label=header.label,
                    title=title,
                    start_pattern="",
                    is_toc_like=False,
                    confidence="low",
                )
            )
            continue

        seg_name, item_idx, others = opener
        item = items_by_name[seg_name][item_idx]
        text = _normalize_text(item.get("text", ""))
        if others:
            notes.append(
                f"{name}: {len(others) + 1} lines equal '{text}' before its first "
                f"running header; using {seg_name}:{item_idx} (the first heading)"
            )
        resolved.append(
            HeadingCandidate(
                segment=seg_name,
                item_idx=item_idx,
                page_idx=_optional_int(item.get("page_idx")),
                level=_optional_int(item.get("text_level")),
                text=text,
                kind=header.kind,
                label=header.label,
                title=title,
                start_pattern=_name_pattern(item.get("text", "")),
                is_toc_like=False,
                confidence="medium",
            )
        )
    return resolved


def _fill_missing_title(
    candidates: list[HeadingCandidate],
    key: tuple[str, str],
    title: str,
) -> None:
    if not title:
        return
    for idx, c in enumerate(candidates):
        if (
            c.kind == key[0]
            and not c.is_toc_like
            and _chapter_key(c.label) == key[1]
            and not c.title
        ):
            candidates[idx] = HeadingCandidate(**{**c.__dict__, "title": title})


def _find_named_opener(
    segments: list[tuple[str, list[dict]]],
    title: str,
    after: tuple[int, int],
    before: tuple[int, int],
) -> tuple[str, int, list[int]] | None:
    """Find the text line equal to ``title`` (ignoring whitespace) in (after, before).

    Lines carrying a heading level win over plain paragraphs.  Returns the
    segment name, the item index, and the indexes of other equally good lines.
    """
    target = _SPACE_RE.sub("", title)
    if not target:
        return None
    heading_hits: list[tuple[int, int]] = []
    plain_hits: list[tuple[int, int]] = []
    for seg_idx in range(after[0], before[0] + 1):
        items = segments[seg_idx][1]
        lo = after[1] + 1 if seg_idx == after[0] else 0
        hi = before[1] if seg_idx == before[0] else len(items)
        for item_idx in range(lo, hi):
            item = items[item_idx]
            if item.get("type") not in _HEADING_TYPES:
                continue
            if _SPACE_RE.sub("", str(item.get("text", ""))) != target:
                continue
            hits = heading_hits if item.get("text_level") else plain_hits
            hits.append((seg_idx, item_idx))
    hits = heading_hits or plain_hits
    if not hits:
        return None
    seg_idx, item_idx = hits[0]
    return segments[seg_idx][0], item_idx, [h[1] for h in hits[1:]]


def _name_pattern(raw_text: object) -> str:
    """Whole-line pattern for a chapter-name line, keeping its OCR spacing."""
    text = _normalize_text(raw_text)
    return r"^\s*" + _flexible_literal(text) + r"\s*$"


def _check_chapter_sequence(candidates: list[HeadingCandidate]) -> list[str]:
    """Warn about gaps, repeats and reordering in body chapter numbers."""
    notes: list[str] = []
    numbers: list[tuple[int, HeadingCandidate]] = []
    for c in candidates:
        if c.kind != "chapter" or c.is_toc_like:
            continue
        value = _han_to_int(c.label)
        if value is None and c.label.isdigit():
            value = int(c.label)
        if value is None:
            notes.append(f"chapter label {c.label!r} at {c.segment}:{c.item_idx} is not a number")
            continue
        numbers.append((value, c))

    seen: set[int] = set()
    previous = 0
    for value, c in numbers:
        where = f"{c.segment}:{c.item_idx}"
        if value in seen:
            notes.append(f"第{value}章 appears more than once (again at {where})")
        elif seen and value < previous:
            notes.append(f"第{value}章 at {where} comes after 第{previous}章")
        elif value > previous + 1 and previous:
            missing = ", ".join(f"第{n}章" for n in range(previous + 1, value))
            notes.append(f"chapter numbering gap before 第{value}章: missing {missing}")
        elif value > 1 and not previous:
            # Normal when only a later part of the book was inspected.
            notes.append(
                f"first chapter found is 第{value}章; 第1章 and earlier are not "
                f"in the inspected segments"
            )
        seen.add(value)
        previous = max(previous, value)
    return notes


def _check_start_patterns(
    segments: list[tuple[str, list[dict]]],
    candidates: list[HeadingCandidate],
) -> list[str]:
    """Check that each emitted start_pattern lands where the exporter will look.

    The exporter takes the first line matching the pattern after the previous
    chapter, so a repeated line can silently move a boundary.  The
    table-of-contents skip uses the exporter default (``BookConfig``).
    """
    order = {name: idx for idx, (name, _) in enumerate(segments)}
    vsegments = [
        _VolumeSegment(uid="", path=Path(name), items=items) for name, items in segments
    ]
    toc_max_page = BookConfig(chapters=[]).toc_max_page
    notes: list[str] = []
    cursor: tuple[int, int] | None = None
    for c in candidates:
        if c.is_toc_like or c.kind not in {"chapter", "appendix"} or not c.start_pattern:
            continue
        intended = (order.get(c.segment, 0), c.item_idx)
        found = _find_boundary_after(
            vsegments, [re.compile(c.start_pattern, re.IGNORECASE)], cursor, toc_max_page
        )
        if found != intended:
            where = "no line" if found is None else f"{segments[found[0]][0]}:{found[1]}"
            notes.append(
                f"{_display_label(c.kind, c.label)}: start_pattern {c.start_pattern} "
                f"would resolve to {where}, not {c.segment}:{c.item_idx}; "
                f"adjust start_pattern, or set toc_max_page in book.yml"
            )
        cursor = intended
    return notes


def print_report(candidates: Iterable[HeadingCandidate]) -> None:
    for candidate in candidates:
        marker = "toc?" if candidate.is_toc_like else "body"
        page = "?" if candidate.page_idx is None else str(candidate.page_idx)
        print(
            f"{candidate.segment}:{candidate.item_idx} "
            f"page={page} L{candidate.level} {marker} {candidate.confidence} "
            f"{candidate.kind} {candidate.label} | {candidate.text}"
        )
        if candidate.title:
            print(f"  title: {candidate.title}")
        if candidate.start_pattern:
            print(f"  start_pattern: {candidate.start_pattern}")


def print_yaml(candidates: Iterable[HeadingCandidate]) -> None:
    print("chapters:")
    for candidate in candidates:
        if candidate.is_toc_like or candidate.kind not in {"chapter", "appendix"}:
            continue
        title = _full_title(candidate)
        slug = _slug_for(candidate)
        print(f"  - slug: {_yaml_str(slug)}")
        print(f"    title: {_yaml_str(title)}")
        if candidate.start_pattern:
            print(f"    start_pattern: {_yaml_str(candidate.start_pattern)}")
        print()


def _display_label(kind: str, label: str) -> str:
    if kind == "appendix":
        return f"附录{label}"
    return f"第{label}章"


def _full_title(candidate: HeadingCandidate) -> str:
    """The chapter title as it should appear in book.yml: label plus name."""
    if candidate.kind not in {"chapter", "appendix"}:
        return candidate.title or candidate.text
    label = _display_label(candidate.kind, candidate.label)
    return f"{label} {candidate.title}" if candidate.title else label


def _yaml_str(value: str) -> str:
    """Render a scalar so it survives a YAML round trip."""
    plain = (
        _YAML_PLAIN_RE.fullmatch(value) is not None
        and value.lower() not in _YAML_RESERVED
        and not re.fullmatch(r"[0-9.+\-eE_]+", value)
    )
    return value if plain else "'" + value.replace("'", "''") + "'"


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str = "minerupress-headings",
) -> int:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Inspect MinerU output and suggest chapter boundary YAML.",
    )
    parser.add_argument("mineru_root", nargs="?", default="resources/mineru")
    parser.add_argument("--volume-uid", help="Only inspect segment directories with this prefix.")
    parser.add_argument(
        "--toc-max-page",
        type=int,
        default=20,
        help="Pages below this index are treated as likely table-of-contents pages.",
    )
    parser.add_argument(
        "--format",
        choices=("report", "yaml"),
        default="report",
        help="Output a diagnostic report or book.yml chapter YAML.",
    )
    parser.add_argument(
        "--body-only",
        action="store_true",
        help="Hide heading candidates that look like table-of-contents entries.",
    )
    parser.add_argument(
        "--include-generic",
        action="store_true",
        help="Also show generic MinerU level-1 headings that are not chapters, parts, or appendices.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    segments = load_content_items(Path(args.mineru_root), args.volume_uid)
    warnings: list[str] = []
    candidates = analyze_headings(
        segments,
        toc_max_page=args.toc_max_page,
        include_toc=not args.body_only,
        include_generic=args.include_generic,
        warnings=warnings,
    )
    if args.format == "yaml":
        print_yaml(candidates)
    else:
        print_report(candidates)
    # stdout stays pasteable into book.yml; problems go to stderr.
    for note in warnings:
        print(f"warning: {note}", file=sys.stderr)
    return 0


def _classify_heading(
    *,
    segment_name: str,
    item_idx: int,
    item: dict,
    text: str,
    items: list[dict],
    toc_max_page: int | None,
) -> HeadingCandidate | None:
    page_idx = _optional_int(item.get("page_idx"))
    level = _optional_int(item.get("text_level"))
    is_toc = _is_toc_like(text, page_idx, toc_max_page)

    match = _CHAPTER_ONLY_RE.match(text)
    if match:
        label = _ascii_digits(match.group(1))
        title = _next_title(items, item_idx)
        return _candidate(segment_name, item_idx, page_idx, level, text, "chapter", label, title, is_toc, "high")

    match = _CHAPTER_FULL_RE.match(text)
    if match:
        label = _ascii_digits(match.group(1))
        raw_title = _clean_title(_strip_toc_tail(match.group(2)))
        confidence = "low" if is_toc else "medium"
        return _candidate(segment_name, item_idx, page_idx, level, text, "chapter", label, raw_title, is_toc, confidence)

    match = _APPENDIX_ONLY_RE.match(text)
    if match:
        label = _ascii_digits(match.group(1)).upper()
        title = _next_title(items, item_idx)
        return _candidate(segment_name, item_idx, page_idx, level, text, "appendix", label, title, is_toc, "high")

    match = _APPENDIX_FULL_RE.match(text)
    if match:
        label = _ascii_digits(match.group(1)).upper()
        raw_title = _clean_title(_strip_toc_tail(match.group(2)))
        confidence = "low" if is_toc else "medium"
        return _candidate(segment_name, item_idx, page_idx, level, text, "appendix", label, raw_title, is_toc, confidence)

    match = _PART_RE.match(text)
    if match:
        label = _ascii_digits(match.group(1))
        title = _clean_title(_strip_toc_tail(match.group(2) or _next_title(items, item_idx)))
        return _candidate(segment_name, item_idx, page_idx, level, text, "part", label, title, is_toc, "medium")

    if level == 1 and not _SECTION_RE.match(text):
        return HeadingCandidate(
            segment=segment_name,
            item_idx=item_idx,
            page_idx=page_idx,
            level=level,
            text=text,
            kind="heading",
            label="",
            title=_clean_title(text),
            start_pattern="",
            is_toc_like=is_toc,
            confidence="low",
        )
    return None


def _candidate(
    segment: str,
    item_idx: int,
    page_idx: int | None,
    level: int | None,
    text: str,
    kind: str,
    label: str,
    title: str,
    is_toc_like: bool,
    confidence: str,
) -> HeadingCandidate:
    return HeadingCandidate(
        segment=segment,
        item_idx=item_idx,
        page_idx=page_idx,
        level=level,
        text=text,
        kind=kind,
        label=label,
        title=title,
        start_pattern=_start_pattern(kind, label),
        is_toc_like=is_toc_like,
        confidence=confidence,
    )


def _start_pattern(kind: str, label: str) -> str:
    escaped = re.escape(label)
    if kind == "chapter":
        return rf"^第\s*{escaped}\s*章$"
    if kind == "appendix":
        return rf"^附\s*录\s*{escaped}$"
    return ""


def _next_title(items: list[dict], item_idx: int) -> str:
    for next_item in items[item_idx + 1:item_idx + 8]:
        if next_item.get("type") != "text":
            continue
        text = _normalize_text(next_item.get("text", ""))
        if not text or _SECTION_RE.match(text):
            continue
        if _CHAPTER_ONLY_RE.match(text) or _APPENDIX_ONLY_RE.match(text):
            continue
        return _clean_title(_strip_toc_tail(text))
    return ""


def _is_toc_like(text: str, page_idx: int | None, toc_max_page: int | None) -> bool:
    if _TOC_LEADER_RE.search(text):
        return True
    if toc_max_page is not None and page_idx is not None and page_idx < toc_max_page:
        if _TRAILING_PAGE_RE.search(text) and (
            _CHAPTER_FULL_RE.match(text)
            or _APPENDIX_FULL_RE.match(text)
            or _PART_RE.match(text)
        ):
            return True
    return False


def _strip_toc_tail(text: str) -> str:
    stripped = _TOC_LEADER_RE.sub("", text).strip()
    return _TRAILING_PAGE_RE.sub("", stripped).strip()


def _clean_title(text: str) -> str:
    text = _normalize_text(text)
    # MinerU sometimes splits Chinese title glyphs with spaces, e.g. "引 论".
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


def _slug_for(candidate: HeadingCandidate) -> str:
    if candidate.kind == "chapter":
        value = _han_to_int(candidate.label)
        if value is None and candidate.label.isdigit():
            value = int(candidate.label)
        if value is not None:
            return f"ch{value:02d}"
        return f"ch-{_ascii_slug(candidate.label)}"
    if candidate.kind == "appendix":
        return f"appendix-{_ascii_slug(candidate.label).lower()}"
    return _ascii_slug(candidate.title or candidate.text)


def _ascii_slug(text: str) -> str:
    text = _ascii_digits(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "chapter"


def _normalize_text(text: object) -> str:
    return _SPACE_RE.sub(" ", str(text or "")).strip()


def _natural_key(path: Path) -> list[object]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in _NATURAL_PARTS.split(path.name)
    ]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ascii_digits(text: str) -> str:
    return text.translate(
        str.maketrans(
            "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        )
    )


def _han_to_int(text: str) -> int | None:
    digits = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    if not text or any(ch not in digits and ch not in "十百千万" for ch in text):
        return None
    total = section = number = 0
    for ch in text:
        if ch in digits:
            number = digits[ch]
        elif ch == "十":
            section += (number or 1) * 10
            number = 0
        elif ch == "百":
            section += (number or 1) * 100
            number = 0
        elif ch == "千":
            section += (number or 1) * 1000
            number = 0
        elif ch == "万":
            total += (section + number) * 10000
            section = number = 0
    return total + section + number


if __name__ == "__main__":
    main()
