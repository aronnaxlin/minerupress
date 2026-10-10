import json
from pathlib import Path

import pytest

from minerupress.core import (
    BookConfig,
    ChapterConfig,
    _VolumeSegment,
    _compile_boundary_tiers,
    _discover_segments,
    _find_chapter_boundary,
    export,
)


def _segment(tmp_path: Path, items: list[dict]) -> list[_VolumeSegment]:
    return [_VolumeSegment(uid="book", path=tmp_path / "book_full", items=items)]


def _text(text: str, page: int, level: int | None = None, **extra) -> dict:
    item = {"type": "text", "text": text, "page_idx": page, **extra}
    if level is not None:
        item["text_level"] = level
    return item


def _write_volume(root: Path, name: str, items: list[dict]) -> Path:
    vol = root / name
    (vol / "images").mkdir(parents=True)
    (vol / f"{name}_content_list.json").write_text(json.dumps(items), encoding="utf-8")
    return vol


# ---------------------------------------------------------------------------
# Tiered boundary fallback
# ---------------------------------------------------------------------------

def test_label_only_line_is_used_when_title_has_separate_name_item(
    tmp_path: Path, capsys
) -> None:
    segments = _segment(
        tmp_path,
        [
            _text("前言", 1, 1),
            _text("第1章", 18, 2),
            _text("算法设计基础", 18, 1),
        ],
    )
    ch = ChapterConfig("ch01", "第1章 算法设计基础", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 1)
    out = capsys.readouterr().out
    assert "tier 2" in out
    assert "第1章 算法设计基础" in out
    assert "'第1章'" in out
    assert "page_idx 18" in out


def test_name_only_line_is_used_when_label_was_lost_and_tolerates_ocr_spacing(
    tmp_path: Path, capsys
) -> None:
    segments = _segment(
        tmp_path,
        [
            _image(10),
            _text("递 推 法", 60, 2),
            _text("4.1 递推法概述", 60, 2),
        ],
    )
    ch = ChapterConfig("ch04", "第4章 递推法", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 1)
    assert "tier 3" in capsys.readouterr().out


def _image(page: int) -> dict:
    return {"type": "image", "img_path": "images/x.jpg", "page_idx": page}


def test_strong_tier_beats_an_earlier_bare_label(tmp_path: Path, capsys) -> None:
    # A bare "第1章" (e.g. an answer key label) must not win over the real
    # "label + name" opening just because it comes first.
    segments = _segment(
        tmp_path,
        [
            _text("第1章", 3, 2),
            _text("第1章 绪论", 20, 1),
        ],
    )
    ch = ChapterConfig("ch01", "第1章 绪论", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 1)
    assert "[NOTE]" not in capsys.readouterr().out


def test_fallback_respects_toc_max_page_for_first_chapter(tmp_path: Path) -> None:
    segments = _segment(
        tmp_path,
        [
            _text("第1章", 2, 2),
            _text("第1章", 18, 2),
        ],
    )
    ch = ChapterConfig("ch01", "第1章 绪论", "book")

    assert _find_chapter_boundary(segments, ch, None, 10) == (0, 1)
    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 0)


def test_fallback_searches_only_after_the_cursor(tmp_path: Path) -> None:
    segments = _segment(
        tmp_path,
        [
            _text("第2章", 30, 2),
            _text("第2章", 50, 2),
        ],
    )
    ch = ChapterConfig("ch02", "第2章 分析", "book")

    assert _find_chapter_boundary(segments, ch, (0, 0), 0) == (0, 1)


def test_name_only_tier_requires_a_heading_level(tmp_path: Path) -> None:
    segments = _segment(
        tmp_path,
        [
            _text("递推法", 10),  # plain paragraph, e.g. a caption or list entry
        ],
    )
    ch = ChapterConfig("ch04", "第4章 递推法", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) is None
    segments[0].items.append(_text("递推法", 60, 2))
    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 1)


def test_name_only_hit_warns_when_the_line_repeats_later(
    tmp_path: Path, capsys
) -> None:
    segments = _segment(
        tmp_path,
        [
            _text("分治法", 80, 2),
            _text("分治法", 88, 2),
        ],
    )
    ch = ChapterConfig("ch06", "第6章 分治法", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 0)
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "item 1" in out


def test_bare_integer_label_is_not_a_fallback(tmp_path: Path) -> None:
    # "1 绪论" has no distinctive label, so a lone "1" must not become a boundary.
    segments = _segment(tmp_path, [_text("1", 5), _text("2", 6)])
    ch = ChapterConfig("sec1", "1 绪论", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) is None


def test_dotted_numbered_label_is_a_fallback(tmp_path: Path) -> None:
    segments = _segment(tmp_path, [_text("10.1", 5, 2), _text("JavaScript 简介", 5, 2)])
    ch = ChapterConfig("sec", "10.1 JavaScript 简介", "book")

    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 0)


def test_explicit_start_pattern_stays_in_the_strong_tier(tmp_path: Path, capsys) -> None:
    segments = _segment(
        tmp_path,
        [
            _text("第7章", 100, 2),
            _text("减治法", 108, 2),
        ],
    )
    ch = ChapterConfig("ch07", "第7章 减治法", "book", start_pattern=r"^\s*减治法\s*$")

    assert _find_chapter_boundary(segments, ch, None, 0) == (0, 1)
    assert "[NOTE]" not in capsys.readouterr().out


def test_tiers_do_not_repeat_patterns(tmp_path: Path) -> None:
    ch = ChapterConfig("ch01", "第1章", "book")
    tiers = _compile_boundary_tiers(ch)

    # Title without a name: the label-only pattern is already the strong tier.
    assert tiers[1].patterns == []
    assert tiers[2].patterns == []


def test_export_resolves_split_label_and_name_chapters_without_patterns(
    tmp_path: Path,
) -> None:
    root = tmp_path / "mineru"
    _write_volume(
        root,
        "book_part1",
        [
            _text("目录", 1, 1),
            _text("第1章", 18, 2),
            _text("算法设计基础", 18, 1),
            _text("正文一", 19),
            _image(30),
            _text("减治法", 31, 2),
            _text("正文二", 32),
        ],
    )
    _write_volume(
        root,
        "book_part2",
        [
            _text("第3章", 0, 2),
            _text("递 推 法", 0, 2),
            _text("正文三", 1),
        ],
    )
    config = BookConfig(
        mineru_root=root,
        docs_out=tmp_path / "docs",
        toc_max_page=10,
        chapters=[
            ChapterConfig("ch01", "第1章 算法设计基础", "book"),
            ChapterConfig("ch02", "第2章 减治法", "book"),
            ChapterConfig("ch03", "第3章 递推法", "book"),
        ],
    )

    export(config)

    chapters = tmp_path / "docs" / "chapters"
    assert "正文一" in (chapters / "ch01.md").read_text(encoding="utf-8")
    assert "正文二" not in (chapters / "ch01.md").read_text(encoding="utf-8")
    assert "正文二" in (chapters / "ch02.md").read_text(encoding="utf-8")
    assert "正文三" in (chapters / "ch03.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# volume_uid prefix matching
# ---------------------------------------------------------------------------

def test_overlapping_uids_use_the_longest_prefix(tmp_path: Path) -> None:
    root = tmp_path / "mineru"
    for name in ("vol1_full", "vol10_full", "vol10_part1"):
        _write_volume(root, name, [_text("x", 0)])

    found = _discover_segments(root, ["vol1", "vol10"])

    assert [s.path.name for s in found["vol1"]] == ["vol1_full"]
    assert [s.path.name for s in found["vol10"]] == ["vol10_full", "vol10_part1"]


def test_short_uuid_prefix_still_matches_without_warning(
    tmp_path: Path, capsys
) -> None:
    root = tmp_path / "mineru"
    _write_volume(root, "73d5b3e7-aaaa-bbbb", [_text("x", 0)])

    found = _discover_segments(root, ["73d5"])

    assert [s.path.name for s in found["73d5"]] == ["73d5b3e7-aaaa-bbbb"]
    assert "[WARN]" not in capsys.readouterr().out


def test_regular_part_names_do_not_warn(tmp_path: Path, capsys) -> None:
    root = tmp_path / "mineru"
    for name in ("algo3_part1", "algo3_part2", "algo3_part10"):
        _write_volume(root, name, [_text("x", 0)])

    found = _discover_segments(root, ["algo3"])

    assert [s.path.name for s in found["algo3"]] == [
        "algo3_part1", "algo3_part2", "algo3_part10",
    ]
    assert "[WARN]" not in capsys.readouterr().out


def test_unrelated_sibling_directory_is_reported(tmp_path: Path, capsys) -> None:
    root = tmp_path / "mineru"
    for name in ("algo3_part1", "algo30_full"):
        _write_volume(root, name, [_text("x", 0)])

    found = _discover_segments(root, ["algo3"])

    # Kept for backwards compatibility with loosely named directories, but loud.
    assert [s.path.name for s in found["algo3"]] == ["algo3_part1", "algo30_full"]
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "algo30_full" in out


def test_missing_uid_still_raises(tmp_path: Path) -> None:
    root = tmp_path / "mineru"
    _write_volume(root, "vol1_full", [_text("x", 0)])

    with pytest.raises(FileNotFoundError):
        _discover_segments(root, ["vol1", "vol2"])
