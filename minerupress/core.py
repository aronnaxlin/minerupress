"""
minerupress.core
~~~~~~~~~~~~~~~~~~~~
Generic MinerU content_list.json → Markdown exporter engine.

Book-specific configuration (chapters, volume UIDs, site metadata) lives
entirely in a book.yml file and is passed in as a BookConfig dataclass.
All content transformation is handled by the plugin system.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from .plugins.base import ExportPlugin

# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

class BoundaryNotFoundError(RuntimeError):
    """Configured chapter boundaries could not be located in the MinerU output."""


@dataclass
class ChapterConfig:
    slug: str                  # output filename stem, e.g. "ch01-overview"
    title: str                 # display title, e.g. "第1章 概述"
    volume_uid: str            # prefix of the MinerU output directory UID
    start_pattern: str | None = None  # regex matched against text-like items to find boundary
    toc_max_page: int | None = None  # overrides BookConfig.toc_max_page for this chapter
    start_patterns: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


@dataclass
class BookConfig:
    chapters: list[ChapterConfig]
    mineru_root: Path = Path("resources/mineru")
    docs_out: Path = Path("docs")
    # Pages before this index are considered table-of-contents and skipped
    # only for the first boundary search in a logical volume.  Set to 0 to
    # disable filtering when a split PDF starts directly at chapter content.
    toc_max_page: int | None = 10
    allow_missing_boundaries: bool = False


@dataclass(frozen=True)
class _VolumeSegment:
    uid: str
    path: Path
    items: list[dict]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SKIP_TYPES = {"page_number", "header", "footer", "page_footnote"}
_BOUNDARY_TYPES = {"text", "aside_text"}
_LEVEL_MAP  = {1: "#", 2: "##", 3: "###", 4: "####"}
_NATURAL_PARTS = re.compile(r"(\d+)")
_CHAPTER_LABEL_RE = re.compile(
    r"^\s*第\s*([0-9０-９一二三四五六七八九十百千万零〇两]+)\s*"
    r"(章|节|讲|课|篇|单元|模块|部分|部)"
)
_BARE_LABEL_RE = re.compile(
    r"^\s*(项目|模块|任务|案例|单元|专题|实验)\s*"
    r"([0-9０-９一二三四五六七八九十百千万零〇两A-Za-z]+)"
)
_APPENDIX_RE = re.compile(r"^\s*附\s*录\s*([A-Za-zＡ-Ｚａ-ｚ0-9０-９一二三四五六七八九十]+)")
_EN_NUMBER_WORD_RE = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    r"eighteenth|nineteenth|twentieth"
)
_EN_NUMBER_TOKEN_RE = rf"(?:[0-9]+[A-Za-z]?|[ivxlcdm]+|{_EN_NUMBER_WORD_RE})"
_EN_CHAPTER_RE = re.compile(
    rf"^\s*(chapter|chap\.?|unit|module|part|section|lesson|lecture|book)\s*"
    rf"({_EN_NUMBER_TOKEN_RE})\b",
    re.IGNORECASE,
)
_EN_APPENDIX_RE = re.compile(
    rf"^\s*(appendix|app\.?)\s*({_EN_NUMBER_TOKEN_RE}|[A-Za-z])\b",
    re.IGNORECASE,
)
_NUMBERED_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)*)\b")
_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_TITLE_TAIL_PATTERN = r"(?:\s|[:：、,，;；.!?。．-])\s*\S.*"
_EN_NUMBERS = {
    "one": 1, "first": 1,
    "two": 2, "second": 2,
    "three": 3, "third": 3,
    "four": 4, "fourth": 4,
    "five": 5, "fifth": 5,
    "six": 6, "sixth": 6,
    "seven": 7, "seventh": 7,
    "eight": 8, "eighth": 8,
    "nine": 9, "ninth": 9,
    "ten": 10, "tenth": 10,
    "eleven": 11, "eleventh": 11,
    "twelve": 12, "twelfth": 12,
    "thirteen": 13, "thirteenth": 13,
    "fourteen": 14, "fourteenth": 14,
    "fifteen": 15, "fifteenth": 15,
    "sixteen": 16, "sixteenth": 16,
    "seventeen": 17, "seventeenth": 17,
    "eighteen": 18, "eighteenth": 18,
    "nineteen": 19, "nineteenth": 19,
    "twenty": 20, "twentieth": 20,
}
_EN_CARDINALS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}
_EN_ORDINALS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
    6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
    11: "eleventh", 12: "twelfth", 13: "thirteenth", 14: "fourteenth",
    15: "fifteenth", 16: "sixteenth", 17: "seventeenth", 18: "eighteenth",
    19: "nineteenth", 20: "twentieth",
}


def _caption_text(raw) -> str:
    if isinstance(raw, list):
        return " ".join(str(x) for x in raw).strip()
    return str(raw).strip() if raw else ""


def _escape_inline_html(text: str) -> str:
    """Render literal tags in prose instead of letting Markdown parse HTML."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _apply_text_plugins(
    item: dict,
    text: str,
    plugins: Sequence[ExportPlugin],
) -> str:
    for plugin in plugins:
        text = plugin.on_text(item, text)
    return _escape_inline_html(text)


def _code_body(item: dict) -> str:
    for key in ("code_body", "text", "content"):
        raw = item.get(key)
        if raw:
            if isinstance(raw, list):
                return "\n".join(str(part) for part in raw).strip()
            return str(raw).strip()
    return ""


def _format_code_block(code: str) -> str | None:
    if not code:
        return None
    if code.lstrip().startswith("```"):
        # MinerU v4 usually emits already-fenced code_body. Preserve the
        # language hint and content, only close an accidentally dangling fence.
        if len(_FENCE_RE.findall(code)) % 2 == 1:
            code = f"{code}\n```"
        return code
    return f"```\n{code}\n```"


def _load_volume(vol_dir: Path) -> list[dict]:
    candidates = sorted(vol_dir.glob("*_content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"No *_content_list.json found in {vol_dir}")
    non_v2 = [p for p in candidates if "v2" not in p.name]
    path = non_v2[0] if non_v2 else candidates[0]
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _natural_key(path: Path) -> list[object]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in _NATURAL_PARTS.split(path.name)
    ]


def _discover_segments(
    mineru_root: Path,
    uid_prefixes: Sequence[str],
) -> dict[str, list[_VolumeSegment]]:
    """Return all physical MinerU directories for each logical volume UID."""
    vol_dirs: dict[str, list[Path]] = {uid: [] for uid in uid_prefixes}
    for d in sorted(mineru_root.iterdir(), key=_natural_key):
        if not d.is_dir():
            continue
        matches = [
            uid for uid in uid_prefixes
            if d.name.startswith(uid)
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Volume directory {d} matches multiple volume_uids: {matches}"
            )
        if matches:
            vol_dirs[matches[0]].append(d)

    missing = [uid for uid, dirs in vol_dirs.items() if not dirs]
    if missing:
        raise FileNotFoundError(
            f"Volume directories not found for UIDs: {missing}\n"
            f"Searched in: {mineru_root}"
        )

    return {
        uid: [_VolumeSegment(uid=uid, path=d, items=_load_volume(d)) for d in dirs]
        for uid, dirs in vol_dirs.items()
    }


def _find_boundary_after(
    segments: Sequence[_VolumeSegment],
    patterns: Sequence[re.Pattern],
    after: tuple[int, int] | None,
    toc_max_page: int | None,
) -> tuple[int, int] | None:
    start_seg = after[0] if after else 0
    for seg_idx in range(start_seg, len(segments)):
        start_item = after[1] + 1 if after and seg_idx == after[0] else 0
        for item_idx, item in enumerate(segments[seg_idx].items[start_item:], start_item):
            if item.get("type") not in _BOUNDARY_TYPES:
                continue
            if (
                after is None
                and seg_idx == 0
                and toc_max_page is not None
                and item.get("page_idx", 0) < toc_max_page
            ):
                continue
            text = item.get("text", "")
            if any(pattern.match(text) for pattern in patterns):
                return seg_idx, item_idx
    return None


def _compile_boundary_patterns(ch: ChapterConfig) -> list[re.Pattern]:
    raw_patterns: list[str] = []
    if ch.start_pattern:
        raw_patterns.append(ch.start_pattern)
    raw_patterns.extend(ch.start_patterns)
    raw_patterns.extend(_generated_boundary_patterns(ch.title, ch.aliases))
    deduped = list(dict.fromkeys(raw_patterns))
    return [re.compile(pat, re.IGNORECASE) for pat in deduped]


def _generated_boundary_patterns(title: str, aliases: Sequence[str]) -> list[str]:
    patterns: list[str] = []
    for heading in [title, *aliases]:
        heading = str(heading).strip()
        if not heading:
            continue
        patterns.append(r"^\s*" + _flexible_literal(heading) + r"\s*$")

        m = _CHAPTER_LABEL_RE.match(heading)
        if m:
            num, unit = m.groups()
            _append_numbered_label_pattern(
                patterns,
                rf"第\s*{_flexible_number(num)}\s*{re.escape(unit)}",
                has_title=bool(heading[m.end():].strip()),
            )
            continue

        m = _APPENDIX_RE.match(heading)
        if m:
            label = m.group(1)
            _append_numbered_label_pattern(
                patterns,
                rf"附\s*录\s*{_flexible_number(label)}",
                has_title=bool(heading[m.end():].strip()),
            )
            continue

        m = _EN_CHAPTER_RE.match(heading)
        if m:
            word, num = m.groups()
            _append_numbered_label_pattern(
                patterns,
                rf"{_english_label_pattern(word)}\s*{_flexible_number(num)}\b",
                has_title=bool(heading[m.end():].strip()),
            )
            continue

        m = _EN_APPENDIX_RE.match(heading)
        if m:
            word, label = m.groups()
            _append_numbered_label_pattern(
                patterns,
                rf"{_english_label_pattern(word)}\s*{_flexible_number(label)}\b",
                has_title=bool(heading[m.end():].strip()),
            )
            continue

        m = _BARE_LABEL_RE.match(heading)
        if m:
            label, num = m.groups()
            _append_numbered_label_pattern(
                patterns,
                rf"{re.escape(label)}\s*{_flexible_number(num)}",
                has_title=bool(heading[m.end():].strip()),
            )
            continue

        m = _NUMBERED_RE.match(heading)
        if m:
            num = re.escape(m.group(1))
            _append_numbered_label_pattern(
                patterns,
                num,
                has_title=bool(heading[m.end():].strip()),
            )
    return patterns


def _append_numbered_label_pattern(
    patterns: list[str],
    label_pattern: str,
    *,
    has_title: bool,
) -> None:
    if has_title:
        patterns.append(rf"^\s*{label_pattern}{_TITLE_TAIL_PATTERN}")
    else:
        patterns.append(rf"^\s*{label_pattern}\s*$")


def _english_label_pattern(word: str) -> str:
    normalized = word.lower().rstrip(".")
    if normalized in {"chap", "chapter"}:
        return r"chap(?:ter)?\.?"
    if normalized in {"app", "appendix"}:
        return r"app(?:endix)?\.?"
    return re.escape(normalized)


def _flexible_literal(text: str) -> str:
    parts = [re.escape(part) for part in re.split(r"\s+", text) if part]
    return r"\s*".join(parts)


def _flexible_number(text: str) -> str:
    normalized = _ascii_digits(text)
    candidates = {re.escape(text), re.escape(normalized)}
    number_value: int | None = None
    if normalized.isdigit():
        number_value = int(normalized)
        candidates.add(re.escape(_int_to_han(number_value)))
    han_int = _han_to_int(normalized)
    if han_int is not None:
        number_value = han_int
        candidates.add(str(han_int))
    roman_int = _roman_to_int(normalized)
    if roman_int is not None:
        number_value = roman_int
        candidates.add(str(roman_int))
    english_int = _EN_NUMBERS.get(normalized.lower())
    if english_int is not None:
        number_value = english_int
        candidates.add(str(english_int))
    if number_value is not None:
        cardinal = _EN_CARDINALS.get(number_value)
        ordinal = _EN_ORDINALS.get(number_value)
        if cardinal:
            candidates.add(re.escape(cardinal))
        if ordinal:
            candidates.add(re.escape(ordinal))
        roman = _int_to_roman(number_value)
        if roman:
            candidates.add(re.escape(roman))
    return "(?:" + "|".join(sorted(candidates)) + ")"


def _ascii_digits(text: str) -> str:
    return text.translate(str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ", "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"))


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


def _roman_to_int(text: str) -> int | None:
    if not text or not re.fullmatch(r"[ivxlcdmIVXLCDM]+", text):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(text.upper()):
        value = values[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    # Reject non-canonical forms so ordinary words made of roman letters don't
    # accidentally become numbers.
    return total if _int_to_roman(total) == text.upper() else None


def _int_to_roman(value: int) -> str:
    if value <= 0 or value >= 4000:
        return ""
    pairs = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out: list[str] = []
    remaining = value
    for amount, numeral in pairs:
        count, remaining = divmod(remaining, amount)
        out.extend([numeral] * count)
    return "".join(out)


def _int_to_han(value: int) -> str:
    if value <= 0 or value >= 100:
        return str(value)
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    tens, ones = divmod(value, 10)
    prefix = "" if tens == 1 else digits[tens]
    suffix = "" if ones == 0 else digits[ones]
    return f"{prefix}十{suffix}"


def _iter_chapter_items(
    segments: Sequence[_VolumeSegment],
    start: tuple[int, int],
    end: tuple[int, int] | None,
) -> Iterator[tuple[int, dict, _VolumeSegment]]:
    end_seg = end[0] if end else len(segments) - 1
    for seg_idx in range(start[0], end_seg + 1):
        segment = segments[seg_idx]
        item_start = start[1] if seg_idx == start[0] else 0
        item_end = end[1] if end and seg_idx == end[0] else len(segment.items)
        for item_idx, item in enumerate(segment.items[item_start:item_end], item_start):
            yield item_idx, item, segment


def _item_to_md(
    item: dict,
    image_out_name: str | None,
    plugins: Sequence[ExportPlugin],
) -> str | None:
    """Convert a single content_list item to Markdown, applying plugins."""

    t = item.get("type", "")
    if t in _SKIP_TYPES:
        return None

    # ---- image ----
    if t == "image":
        raw_path = item.get("img_path", "")
        if not raw_path:
            return None
        out_name = image_out_name
        if out_name is None:
            return None

        raw_caption = item.get("img_caption", "")
        caption = _caption_text(raw_caption)
        alt = caption if caption else out_name
        alt = _apply_text_plugins(item, alt, plugins)
        lines = [f"![{alt}](../images/{out_name})"]
        if caption:
            cap_display = _apply_text_plugins(item, caption, plugins)
            lines.append(f"*{cap_display}*")
        return "\n".join(lines)

    # ---- equation ----
    if t == "equation":
        latex = item.get("text", "").strip()
        if not latex:
            return None
        # MinerU sometimes wraps in $$...$$; strip to avoid doubling
        inner = latex
        if inner.startswith("$$") and inner.endswith("$$"):
            inner = inner[2:-2].strip()
        return f"$$\n{inner}\n$$"

    # ---- table ----
    if t == "table":
        raw_caption = item.get("table_caption", "")
        caption = _caption_text(raw_caption)
        body = item.get("table_body", "")
        parts = []
        if caption:
            cap_display = _apply_text_plugins(item, caption, plugins)
            parts.append(f"**{cap_display}**")
        if body:
            parts.append(body)
        return "\n\n".join(parts) if parts else None

    # ---- code ----
    if t == "code":
        return _format_code_block(_code_body(item))

    # ---- all text-like types ----
    text = item.get("text", "").strip()
    if not text:
        return None

    if t == "text":
        level = item.get("text_level")
        text = _apply_text_plugins(item, text, plugins)
        if level and level in _LEVEL_MAP:
            return f"{_LEVEL_MAP[level]} {text}"
        return text

    # list, aside_text, chart, …
    return _apply_text_plugins(item, text, plugins)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export(config: BookConfig, plugins: Sequence[ExportPlugin] = ()) -> None:
    """
    Run the full export pipeline for one book.

    Parameters
    ----------
    config:
        Book-specific configuration (chapters, paths, etc.)
    plugins:
        Zero or more ExportPlugin instances applied during conversion.
    """
    mineru_root = config.mineru_root
    docs_out    = config.docs_out

    # Discover one or more physical MinerU directories for each logical volume.
    # A single PDF may be split by the API into uid_part1, uid_part2, ...
    uid_prefixes = sorted({ch.volume_uid for ch in config.chapters})
    segments_by_uid = _discover_segments(mineru_root, uid_prefixes)

    # Copy images (plugins may filter individual files)
    images_out = docs_out / "images"
    if images_out.exists():
        shutil.rmtree(images_out)
    images_out.mkdir(parents=True, exist_ok=True)
    image_names: dict[Path, dict[str, str]] = {}
    image_decisions: dict[tuple[Path, int], str | None] = {}
    used_image_names: set[str] = set()
    total_copied = total_skipped = 0
    for segments in segments_by_uid.values():
        for segment in segments:
            image_names[segment.path] = {}
    for segments in segments_by_uid.values():
        for segment in segments:
            img_src = segment.path / "images"
            for item_idx, item in enumerate(segment.items):
                if item.get("type") != "image":
                    continue
                raw_path = item.get("img_path", "")
                if not raw_path:
                    image_decisions[(segment.path, item_idx)] = None
                    continue
                fname = Path(raw_path).name
                img = img_src / fname
                keep = all(p.on_image(item, img) for p in plugins)
                if keep:
                    if not img.exists():
                        print(f"  [WARN] image file not found: {img}")
                        image_decisions[(segment.path, item_idx)] = None
                        continue
                    out_name = image_names[segment.path].get(fname)
                    if out_name is None:
                        out_name = fname
                        if out_name in used_image_names:
                            out_name = f"{segment.path.name}_{fname}"
                        image_names[segment.path][fname] = out_name
                        used_image_names.add(out_name)
                        shutil.copy2(img, images_out / out_name)
                        total_copied += 1
                    image_decisions[(segment.path, item_idx)] = out_name
                else:
                    total_skipped += 1
                    image_decisions[(segment.path, item_idx)] = None
    print(f"  Images: {total_copied} copied, {total_skipped} filtered -> {images_out}")

    chapters_out = docs_out / "chapters"
    if chapters_out.exists():
        shutil.rmtree(chapters_out)
    chapters_out.mkdir(parents=True, exist_ok=True)

    # Group chapters by logical volume, preserving book.yml order.
    vol_chapters: dict[str, list[ChapterConfig]] = {uid: [] for uid in uid_prefixes}
    for ch in config.chapters:
        vol_chapters[ch.volume_uid].append(ch)

    for uid, chapter_list in vol_chapters.items():
        segments = segments_by_uid[uid]
        print(f"  Volume {uid}: {len(segments)} segment(s)")
        for segment in segments:
            print(f"    - {segment.path.name}: {len(segment.items)} items")

        boundaries: list[tuple[tuple[int, int], ChapterConfig]] = []
        missing: list[ChapterConfig] = []
        cursor: tuple[int, int] | None = None
        for ch in chapter_list:
            patterns = _compile_boundary_patterns(ch)
            toc_limit = ch.toc_max_page if ch.toc_max_page is not None else config.toc_max_page
            loc = _find_boundary_after(segments, patterns, cursor, toc_limit)
            if loc is None:
                missing.append(ch)
                print(f"  [WARN] boundary not found: {ch.title}")
                continue
            boundaries.append((loc, ch))
            cursor = loc
        if missing and not config.allow_missing_boundaries:
            missing_titles = ", ".join(ch.title for ch in missing)
            raise BoundaryNotFoundError(
                f"Chapter boundaries not found for volume {uid}: {missing_titles}"
            )

        for i, (start, ch) in enumerate(boundaries):
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else None
            chapter_items = list(_iter_chapter_items(segments, start, end))

            lines: list[str] = [f"# {ch.title}", ""]
            for item_idx, item, segment in chapter_items:
                image_out_name = image_decisions.get((segment.path, item_idx))
                md = _item_to_md(
                    item,
                    image_out_name=image_out_name,
                    plugins=plugins,
                )
                if md is not None:
                    lines.append(md)
                    lines.append("")

            for plugin in plugins:
                lines = plugin.on_chapter_done(ch.slug, lines)

            out_path = chapters_out / f"{ch.slug}.md"
            out_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"  Wrote {out_path.name}  ({len(chapter_items)} items)")

    print(f"\nDone. Output in {docs_out}")

    for plugin in plugins:
        plugin.on_export_done(docs_out)
