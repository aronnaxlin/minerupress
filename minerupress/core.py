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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from .plugins.base import ExportPlugin

# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

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
# Types rendered from an image file; chart items carry an img_path just like images.
_IMAGE_TYPES = {"image", "chart"}
# Types with a dedicated branch (or the generic text fallback) in _item_to_md.
_HANDLED_TYPES = {"text", "aside_text", "image", "chart", "equation", "table", "code", "list"}
# Keys that describe an item rather than carry content; used to decide whether
# an unhandled item type silently throws something away.
_META_KEYS = {"type", "sub_type", "page_idx", "bbox", "text_level", "page_size", "index", "id"}
# Caption / footnote field names per item type.  MinerU v2 uses image_*; older
# exports use img_*, so both spellings are accepted.
_CAPTION_KEYS = {
    "image": ("image_caption", "img_caption"),
    "chart": ("chart_caption", "image_caption", "img_caption"),
    "table": ("table_caption",),
    "code": ("code_caption",),
}
_FOOTNOTE_KEYS = {
    "image": ("image_footnote", "img_footnote"),
    "chart": ("chart_footnote", "image_footnote", "img_footnote"),
    "table": ("table_footnote",),
    "code": ("code_footnote",),
}
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
_NAME_SEPARATORS = " \t\u3000:：、,，;；.．-—–·"
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


def _first_field(item: dict, keys: Sequence[str]):
    """Return the first non-empty value among *keys* (or "")."""
    for key in keys:
        value = item.get(key)
        if value:
            return value
    return ""


def _caption_of(item: dict) -> str:
    return _caption_text(_first_field(item, _CAPTION_KEYS.get(item.get("type", ""), ())))


def _footnotes_of(item: dict) -> list[str]:
    raw = _first_field(item, _FOOTNOTE_KEYS.get(item.get("type", ""), ()))
    entries = raw if isinstance(raw, list) else [raw]
    return [str(e).strip() for e in entries if e and str(e).strip()]


# Spans Markdown must leave alone: arithmatex claims them before links and
# backslash escapes, so inserting "\" or "&lt;" inside would corrupt the math.
_MATH_SPAN_RE = re.compile(
    r"\$\$.+?\$\$"
    r"|(?<![\\$])\$(?!\s)(?:\\.|[^\\$])+?(?<!\s)\$(?!\d)"
    r"|\\\(.+?\\\)"
    r"|\\\[.+?\\\]",
    re.DOTALL,
)


def _escape_prose(text: str) -> str:
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    # OCR text such as "next[j](1≤j≤m-1)" would otherwise become a link.
    return text.replace("](", "\\](")


def _escape_inline_html(text: str) -> str:
    """Render literal tags and link-like text in prose; math spans are untouched."""
    parts: list[str] = []
    pos = 0
    for m in _MATH_SPAN_RE.finditer(text):
        parts.append(_escape_prose(text[pos:m.start()]))
        parts.append(m.group())
        pos = m.end()
    parts.append(_escape_prose(text[pos:]))
    return "".join(parts)


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


def _segment_name_is_regular(name: str, uid: str) -> bool:
    """True for the directory names MineruPress itself produces for ``uid``."""
    return re.fullmatch(rf"{re.escape(uid)}(?:_full|_part\d+)?", name) is not None


def _irregular_segment_dirs(dirs: Sequence[Path], uid: str) -> list[Path]:
    """Directories that only match ``uid`` as a loose prefix, e.g. ``algo30_full``.

    Short prefixes of MinerU UUID directories (``73d5`` -> ``73d5b3e7-...``) are
    a documented way to write ``volume_uid``; they are only suspicious when
    ``uid`` also has regular candidates (``uid``, ``uid_full``, ``uid_partN``).
    """
    if not any(_segment_name_is_regular(d.name, uid) for d in dirs):
        return []
    return [d for d in dirs if not _segment_name_is_regular(d.name, uid)]


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
        # Overlapping prefixes (vol1 / vol10): the most specific UID owns it.
        if matches:
            vol_dirs[max(matches, key=len)].append(d)

    missing = [uid for uid, dirs in vol_dirs.items() if not dirs]
    if missing:
        raise FileNotFoundError(
            f"Volume directories not found for UIDs: {missing}\n"
            f"Searched in: {mineru_root}"
        )

    for uid, dirs in vol_dirs.items():
        odd = _irregular_segment_dirs(dirs, uid)
        if odd:
            names = ", ".join(d.name for d in odd)
            print(
                f"  [WARN] volume_uid {uid!r} also matches {names}; these are "
                f"merged into the volume as extra segments. Use a longer "
                f"volume_uid or move unrelated directories out of {mineru_root} "
                f"if that is not intended."
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
    *,
    heading_only: bool = False,
) -> tuple[int, int] | None:
    start_seg = after[0] if after else 0
    for seg_idx in range(start_seg, len(segments)):
        start_item = after[1] + 1 if after and seg_idx == after[0] else 0
        for item_idx, item in enumerate(segments[seg_idx].items[start_item:], start_item):
            if item.get("type") not in _BOUNDARY_TYPES:
                continue
            if heading_only and not item.get("text_level"):
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


@dataclass(frozen=True)
class _BoundaryTier:
    name: str
    patterns: list[re.Pattern]
    # Name-only lines are weak evidence, so they must at least be headings.
    heading_only: bool = False


def _compile_boundary_patterns(ch: ChapterConfig) -> list[re.Pattern]:
    """Strong (tier 1) patterns: explicit patterns, full title, label + name."""
    raw_patterns: list[str] = []
    if ch.start_pattern:
        raw_patterns.append(ch.start_pattern)
    raw_patterns.extend(ch.start_patterns)
    raw_patterns.extend(_generated_boundary_patterns(ch.title, ch.aliases))
    deduped = list(dict.fromkeys(raw_patterns))
    return [re.compile(pat, re.IGNORECASE) for pat in deduped]


def _compile_boundary_tiers(ch: ChapterConfig) -> list[_BoundaryTier]:
    """Boundary patterns from strongest to weakest evidence.

    1. ``strong``: explicit patterns, the full title, label followed by name.
    2. ``label``: the numbering label alone on its line ("第1章").
    3. ``name``: the chapter name alone on its heading line ("递 推 法").

    MinerU often emits label and name as two separate items, or loses the
    label altogether, so the weaker tiers are only tried when the stronger
    ones find nothing in the remaining range.
    """
    strong = _compile_boundary_patterns(ch)
    seen = {pat.pattern for pat in strong}
    label_raw, name_raw = _fallback_boundary_patterns([ch.title, *ch.aliases])

    def compile_new(raw: list[str]) -> list[re.Pattern]:
        fresh = [pat for pat in dict.fromkeys(raw) if pat not in seen]
        seen.update(fresh)
        return [re.compile(pat, re.IGNORECASE) for pat in fresh]

    return [
        _BoundaryTier("strong", strong),
        _BoundaryTier("label", compile_new(label_raw)),
        _BoundaryTier("name", compile_new(name_raw), heading_only=True),
    ]


_TIER_LABELS = {
    "label": "tier 2, chapter number only",
    "name": "tier 3, chapter name only",
}


def _find_chapter_boundary(
    segments: Sequence[_VolumeSegment],
    ch: ChapterConfig,
    after: tuple[int, int] | None,
    toc_max_page: int | None,
) -> tuple[int, int] | None:
    """Locate ``ch`` after ``after``, falling back to weaker evidence if needed."""
    for tier in _compile_boundary_tiers(ch):
        if not tier.patterns:
            continue
        loc = _find_boundary_after(
            segments, tier.patterns, after, toc_max_page,
            heading_only=tier.heading_only,
        )
        if loc is None:
            continue
        if tier.name != "strong":
            _report_boundary_fallback(segments, ch, tier, loc)
        return loc
    return None


def _report_boundary_fallback(
    segments: Sequence[_VolumeSegment],
    ch: ChapterConfig,
    tier: _BoundaryTier,
    loc: tuple[int, int],
) -> None:
    where = _describe_item(segments, loc)
    print(
        f"  [NOTE] boundary fallback ({_TIER_LABELS[tier.name]}): "
        f"{ch.title} -> {where}"
    )
    # A weak line that repeats later is a sign the first hit may be a section
    # heading or a cross-reference instead of the real chapter opening.
    later = _find_boundary_after(
        segments, tier.patterns, loc, None, heading_only=tier.heading_only,
    )
    if later is not None:
        print(
            f"  [WARN] {ch.title}: the same line also appears later at "
            f"{_describe_item(segments, later)}; if the first hit is wrong, "
            f"set start_pattern for this chapter"
        )


def _describe_item(segments: Sequence[_VolumeSegment], loc: tuple[int, int]) -> str:
    segment = segments[loc[0]]
    item = segment.items[loc[1]]
    text = " ".join(str(item.get("text", "")).split())
    return (
        f"{text!r} ({segment.path.name} item {loc[1]}, "
        f"page_idx {item.get('page_idx', '?')})"
    )


def _generated_boundary_patterns(title: str, aliases: Sequence[str]) -> list[str]:
    patterns: list[str] = []
    for heading in [title, *aliases]:
        heading = str(heading).strip()
        if not heading:
            continue
        patterns.append(r"^\s*" + _flexible_literal(heading) + r"\s*$")

        split = _split_heading_label(heading)
        if split:
            label_pattern, rest, _ = split
            _append_numbered_label_pattern(
                patterns,
                label_pattern,
                has_title=bool(rest.strip()),
            )
    return patterns


def _fallback_boundary_patterns(headings: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return (label-only, name-only) patterns for headings of ``label name`` form."""
    label_only: list[str] = []
    name_only: list[str] = []
    for heading in headings:
        heading = str(heading).strip()
        split = _split_heading_label(heading) if heading else None
        if not split:
            continue
        label_pattern, rest, distinctive = split
        name = rest.strip(_NAME_SEPARATORS)
        if not name:
            continue
        # A bare "1" is too likely to be a stray page or list number.
        if distinctive:
            label_only.append(rf"^\s*{label_pattern}\s*$")
        name_only.append(r"^\s*" + _flexible_literal(name, spaced_cjk=True) + r"\s*$")
    return label_only, name_only


def _split_heading_label(heading: str) -> tuple[str, str, bool] | None:
    """Split ``heading`` into (label regex, remaining text, label_is_distinctive)."""
    m = _CHAPTER_LABEL_RE.match(heading)
    if m:
        num, unit = m.groups()
        return rf"第\s*{_flexible_number(num)}\s*{re.escape(unit)}", heading[m.end():], True

    m = _APPENDIX_RE.match(heading)
    if m:
        label = m.group(1)
        return rf"附\s*录\s*{_flexible_number(label)}", heading[m.end():], True

    m = _EN_CHAPTER_RE.match(heading)
    if m:
        word, num = m.groups()
        pattern = rf"{_english_label_pattern(word)}\s*{_flexible_number(num)}\b"
        return pattern, heading[m.end():], True

    m = _EN_APPENDIX_RE.match(heading)
    if m:
        word, label = m.groups()
        pattern = rf"{_english_label_pattern(word)}\s*{_flexible_number(label)}\b"
        return pattern, heading[m.end():], True

    m = _BARE_LABEL_RE.match(heading)
    if m:
        label, num = m.groups()
        return rf"{re.escape(label)}\s*{_flexible_number(num)}", heading[m.end():], True

    m = _NUMBERED_RE.match(heading)
    if m:
        return re.escape(m.group(1)), heading[m.end():], "." in m.group(1)
    return None


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


def _flexible_literal(text: str, *, spaced_cjk: bool = False) -> str:
    """Literal regex that tolerates whitespace differences.

    With ``spaced_cjk`` whitespace is also allowed between adjacent CJK
    characters, because OCR often spaces out short titles ("递 推 法").
    """
    tokens = [part for part in re.split(r"\s+", text) if part]
    if spaced_cjk:
        tokens = [
            r"\s*".join(re.escape(c) for c in _split_cjk_runs(token))
            for token in tokens
        ]
    else:
        tokens = [re.escape(token) for token in tokens]
    return r"\s*".join(tokens)


def _split_cjk_runs(token: str) -> list[str]:
    """Split ``token`` so that adjacent CJK characters become separate pieces."""
    pieces: list[str] = []
    buf = ""
    for ch in token:
        if _is_cjk(ch):
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(ch)
        else:
            buf += ch
    if buf:
        pieces.append(buf)
    return pieces


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"


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


_LIST_BULLET_RE = re.compile(r"^[-*+•·]\s*")
_LIST_ORDINAL_RE = re.compile(r"^(\d+)[.．)）]\s*")


def _list_entry_text(entry) -> str:
    if isinstance(entry, dict):
        entry = entry.get("text") or entry.get("content") or ""
    return re.sub(r"\s*\n\s*", " ", str(entry)).strip()


def _list_to_md(item: dict, plugins: Sequence[ExportPlugin]) -> str | None:
    """Render ``list_items`` as a Markdown list without doubling existing markers."""
    lines: list[str] = []
    for entry in item.get("list_items") or []:
        text = _list_entry_text(entry)
        if not text:
            continue
        m = _LIST_ORDINAL_RE.match(text)
        if m:
            marker, text = f"{m.group(1)}.", text[m.end():]
        else:
            marker, text = "-", _LIST_BULLET_RE.sub("", text, count=1)
        text = _apply_text_plugins(item, text, plugins)
        if text:
            lines.append(f"{marker} {text}")
    return "\n".join(lines) if lines else None


def _footnotes_md(item: dict, plugins: Sequence[ExportPlugin]) -> list[str]:
    return [_apply_text_plugins(item, note, plugins) for note in _footnotes_of(item)]


def _figure_to_md(
    item: dict,
    out_name: str,
    plugins: Sequence[ExportPlugin],
) -> str:
    caption = _caption_of(item)
    alt = _apply_text_plugins(item, caption if caption else out_name, plugins)
    lines = [f"![{alt}](../images/{out_name})"]
    if caption:
        cap_display = _apply_text_plugins(item, caption, plugins)
        lines.append(f"*{cap_display}*")
    return "\n\n".join(["\n".join(lines), *_footnotes_md(item, plugins)])


def _item_to_md(
    item: dict,
    image_out_name: str | None,
    plugins: Sequence[ExportPlugin],
) -> str | None:
    """Convert a single content_list item to Markdown, applying plugins."""

    t = item.get("type", "")
    if t in _SKIP_TYPES:
        return None

    # ---- image / chart ----
    if t in _IMAGE_TYPES:
        if item.get("img_path"):
            # A filtered image takes its caption and footnote with it.
            if image_out_name is None:
                return None
            return _figure_to_md(item, image_out_name, plugins)
        if t == "image":
            return None
        # A chart without an image falls through to its text, if any.

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
        caption = _caption_of(item)
        body = item.get("table_body", "")
        parts = []
        if caption:
            cap_display = _apply_text_plugins(item, caption, plugins)
            parts.append(f"**{cap_display}**")
        if body:
            parts.append(body)
        if not parts:
            return None
        return "\n\n".join([*parts, *_footnotes_md(item, plugins)])

    # ---- code ----
    if t == "code":
        block = _format_code_block(_code_body(item))
        if block is None:
            return None
        caption = _caption_of(item)
        if not caption:
            return block
        cap_display = _apply_text_plugins(item, caption, plugins)
        return f"**{cap_display}**\n\n{block}"

    # ---- list ----
    if t == "list" and item.get("list_items"):
        md = _list_to_md(item, plugins)
        if md is not None:
            return md

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


def _has_content(item: dict) -> bool:
    return any(v for k, v in item.items() if k not in _META_KEYS)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _leading_title_count(
    chapter_items: Sequence[tuple[int, dict, _VolumeSegment]],
    ch: ChapterConfig,
) -> int:
    """Count leading boundary items that only repeat the chapter title.

    export() already writes ``# {ch.title}``; MinerU usually also emits the
    printed chapter opener ("第1章", "递 推 法", …) as separate short items on
    the opening page.  Only a run of items whose text, ignoring whitespace, is
    a piece of the title or one of its aliases is skipped; a boundary that hit
    ordinary prose stops the run immediately.
    """
    titles = [_compact(t) for t in (ch.title, *ch.aliases) if str(t).strip()]
    if not chapter_items or not titles:
        return 0
    first_page = chapter_items[0][1].get("page_idx")
    count = 0
    for _, item, _segment in chapter_items:
        if item.get("type") in _SKIP_TYPES:
            count += 1
            continue
        text = _compact(str(item.get("text", "")))
        if (
            item.get("type") not in _BOUNDARY_TYPES
            or item.get("page_idx") != first_page
            or len(text) < 2
            or not any(text in title for title in titles)
        ):
            break
        count += 1
    # Trailing page furniture is dropped anyway; only report real title items.
    while count and chapter_items[count - 1][1].get("type") in _SKIP_TYPES:
        count -= 1
    return count


@dataclass
class _ItemStats:
    """Per-type written / dropped tallies for the console summary."""
    written: Counter = field(default_factory=Counter)
    dropped: Counter = field(default_factory=Counter)
    unhandled: Counter = field(default_factory=Counter)

    def add(self, other: "_ItemStats") -> None:
        self.written.update(other.written)
        self.dropped.update(other.dropped)
        self.unhandled.update(other.unhandled)

    def totals(self) -> tuple[int, int]:
        return sum(self.written.values()), sum(self.dropped.values())

    def report(self) -> None:
        types = sorted(
            set(self.written) | set(self.dropped),
            key=lambda t: (-(self.written[t] + self.dropped[t]), t),
        )
        print("\n  Items by type (written / dropped):")
        for t in types:
            print(f"    {t or '(none)':<14} {self.written[t]:>5} / {self.dropped[t]}")
        for t, n in sorted(self.unhandled.items()):
            print(
                f"  [WARN] {n} item(s) of unhandled type '{t}' have content "
                f"but were dropped"
            )


def _render_chapter_items(
    chapter_items: Sequence[tuple[int, dict, _VolumeSegment]],
    ch: ChapterConfig,
    image_decisions: dict[tuple[Path, int], str | None],
    plugins: Sequence[ExportPlugin],
) -> tuple[list[str], _ItemStats]:
    lines: list[str] = []
    stats = _ItemStats()
    skip = _leading_title_count(chapter_items, ch)
    for n, (item_idx, item, segment) in enumerate(chapter_items):
        t = item.get("type", "")
        md = None
        if n >= skip:
            md = _item_to_md(
                item,
                image_out_name=image_decisions.get((segment.path, item_idx)),
                plugins=plugins,
            )
        if md is not None:
            stats.written[t] += 1
            lines.append(md)
            lines.append("")
            continue
        stats.dropped[t] += 1
        if n >= skip and t not in _HANDLED_TYPES | _SKIP_TYPES and _has_content(item):
            stats.unhandled[t] += 1
    return lines, stats


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
                if item.get("type") not in _IMAGE_TYPES:
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

    book_stats = _ItemStats()
    for uid, chapter_list in vol_chapters.items():
        segments = segments_by_uid[uid]
        print(f"  Volume {uid}: {len(segments)} segment(s)")
        for segment in segments:
            print(f"    - {segment.path.name}: {len(segment.items)} items")

        boundaries: list[tuple[tuple[int, int], ChapterConfig]] = []
        missing: list[ChapterConfig] = []
        cursor: tuple[int, int] | None = None
        for ch in chapter_list:
            toc_limit = ch.toc_max_page if ch.toc_max_page is not None else config.toc_max_page
            loc = _find_chapter_boundary(segments, ch, cursor, toc_limit)
            if loc is None:
                missing.append(ch)
                print(f"  [WARN] boundary not found: {ch.title}")
                continue
            boundaries.append((loc, ch))
            cursor = loc
        if missing and not config.allow_missing_boundaries:
            missing_titles = ", ".join(ch.title for ch in missing)
            raise RuntimeError(
                f"Chapter boundaries not found for volume {uid}: {missing_titles}"
            )

        for i, (start, ch) in enumerate(boundaries):
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else None
            chapter_items = list(_iter_chapter_items(segments, start, end))

            body, stats = _render_chapter_items(
                chapter_items, ch, image_decisions, plugins,
            )
            book_stats.add(stats)
            lines: list[str] = [f"# {ch.title}", "", *body]

            for plugin in plugins:
                lines = plugin.on_chapter_done(ch.slug, lines)

            out_path = chapters_out / f"{ch.slug}.md"
            out_path.write_text("\n".join(lines), encoding="utf-8")
            written, dropped = stats.totals()
            print(
                f"  Wrote {out_path.name}  ({len(chapter_items)} items)"
                f"  written {written}, dropped {dropped}"
            )

    book_stats.report()
    print(f"\nDone. Output in {docs_out}")

    for plugin in plugins:
        plugin.on_export_done(docs_out)
