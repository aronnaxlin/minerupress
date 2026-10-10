import json
from pathlib import Path

import yaml

from minerupress.headings import analyze_headings, main, print_yaml


def _text(text: str, page: int, level: int | None = None) -> dict:
    item = {"type": "text", "text": text, "page_idx": page}
    if level is not None:
        item["text_level"] = level
    return item


def _header(text: str, page: int) -> dict:
    return {"type": "header", "text": text, "page_idx": page}


def _book() -> list[tuple[str, list[dict]]]:
    """Label items at mixed levels, plus chapters whose label was lost to OCR."""
    return [
        (
            "book_part1",
            [
                _text("第1章 绪论 …… 3", 2, 1),
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _header("第1章 绪论", 20),
                _header("第1章 绪论", 22),
                _text("第2章", 30),
                _text("递 推 法", 30, 2),
                _header("第 2 章 递推法", 32),
                _header("第 2 章 递推法", 34),
                {"type": "image", "img_path": "images/a.jpg", "page_idx": 40},
                _text("减治法", 40, 2),
                _text("3.1 减治法概述", 41, 2),
                _header("第 3 章 减治法", 42),
                _header("第 3 章 减治法", 44),
            ],
        )
    ]


def test_standalone_labels_are_found_at_any_text_level() -> None:
    candidates = analyze_headings(_book(), toc_max_page=10, include_toc=False)

    chapters = [c for c in candidates if c.kind == "chapter"]
    assert [c.label for c in chapters] == ["1", "2", "3"]
    assert [c.item_idx for c in chapters] == [1, 5, 10]
    assert chapters[0].level == 2
    assert chapters[1].level is None


def test_chapter_without_label_is_located_from_running_headers() -> None:
    candidates = analyze_headings(_book(), toc_max_page=10, include_toc=False)

    third = [c for c in candidates if c.kind == "chapter" and c.label == "3"][0]
    assert third.item_idx == 10
    assert third.title == "减治法"
    assert third.start_pattern == r"^\s*减治法\s*$"


def test_yaml_output_has_full_titles_and_round_trips(capsys) -> None:
    candidates = analyze_headings(_book(), toc_max_page=10, include_toc=False)

    print_yaml(candidates)
    data = yaml.safe_load(capsys.readouterr().out)

    assert [c["title"] for c in data["chapters"]] == [
        "第1章 绪论", "第2章 递推法", "第3章 减治法",
    ]
    assert [c["slug"] for c in data["chapters"]] == ["ch01", "ch02", "ch03"]
    assert data["chapters"][2]["start_pattern"] == r"^\s*减治法\s*$"


def test_yaml_quotes_special_characters(capsys) -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _text("It's: C++ # 入门", 18, 1),
                _text("第2章", 40, 2),
                _text("true", 40, 1),
            ],
        )
    ]

    print_yaml(analyze_headings(segments, toc_max_page=10, include_toc=False))
    data = yaml.safe_load(capsys.readouterr().out)

    assert data["chapters"][0]["title"] == "第1章 It's: C++ # 入门"
    assert data["chapters"][1]["title"] == "第2章 true"


def test_name_opener_search_starts_after_the_previous_chapter() -> None:
    segments = [
        (
            "book",
            [
                _text("减治法", 5, 2),  # preface line, before chapter 1
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _header("第1章 绪论", 20),
                _header("第1章 绪论", 22),
                _text("减治法", 40, 2),
                _header("第2章 减治法", 42),
                _header("第2章 减治法", 44),
            ],
        )
    ]
    warnings: list[str] = []

    candidates = analyze_headings(
        segments, toc_max_page=10, include_toc=False, warnings=warnings
    )

    second = [c for c in candidates if c.label == "2"][0]
    assert second.item_idx == 5
    assert warnings == []


def test_heading_level_line_wins_over_plain_paragraph_for_the_opener() -> None:
    segments = [
        (
            "book",
            [
                _text("第12章", 20, 2),
                _text("复杂性", 20, 1),
                _text("近似算法", 30),  # plain paragraph
                _text("近似算法", 38, 1),
                _header("第 13 章 近似算法", 40),
                _header("第 13 章 近似算法", 42),
            ],
        )
    ]
    warnings: list[str] = []

    candidates = analyze_headings(segments, include_toc=False, warnings=warnings)

    thirteenth = [c for c in candidates if c.label == "13"][0]
    assert thirteenth.item_idx == 3
    # The exporter's explicit pattern has no level check, so the plain
    # paragraph would be hit first; that has to be called out.
    assert any("第13章: start_pattern" in w and "book:2" in w for w in warnings)


def test_equal_heading_lines_before_header_are_reported() -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _text("近似算法", 30, 2),
                _text("近似算法", 38, 1),
                _header("第 2 章 近似算法", 40),
                _header("第 2 章 近似算法", 42),
            ],
        )
    ]
    warnings: list[str] = []

    candidates = analyze_headings(segments, include_toc=False, warnings=warnings)

    assert [c.item_idx for c in candidates] == [0, 2]
    assert any("2 lines equal" in w and "book:2" in w for w in warnings)


def test_numbering_gap_is_warned_not_written_to_yaml(tmp_path: Path, capsys) -> None:
    root = tmp_path / "mineru"
    vol = root / "book_full"
    vol.mkdir(parents=True)
    items = [
        _text("第1章", 18, 2),
        _text("绪论", 18, 1),
        _text("第3章", 40, 2),
        _text("进阶", 40, 1),
    ]
    (vol / "x_content_list.json").write_text(json.dumps(items), encoding="utf-8")

    assert main([str(root), "--format", "yaml", "--body-only"]) == 0
    captured = capsys.readouterr()

    assert "missing 第2章" in captured.err
    assert "missing" not in captured.out
    assert [c["title"] for c in yaml.safe_load(captured.out)["chapters"]] == [
        "第1章 绪论", "第3章 进阶",
    ]


def test_repeated_chapter_number_is_warned() -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _text("第1章", 90, 2),
                _text("答案", 90, 1),
            ],
        )
    ]
    warnings: list[str] = []

    analyze_headings(segments, include_toc=False, warnings=warnings)

    assert any("more than once" in w for w in warnings)


def test_chapter_with_unlocatable_opener_is_still_listed_with_a_warning(capsys) -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _header("第 2 章 复杂性", 30),
                _header("第 2 章 复杂性", 32),
            ],
        )
    ]
    warnings: list[str] = []

    candidates = analyze_headings(segments, include_toc=False, warnings=warnings)
    print_yaml(candidates)
    data = yaml.safe_load(capsys.readouterr().out)

    assert data["chapters"][1]["title"] == "第2章 复杂性"
    assert "start_pattern" not in data["chapters"][1]
    assert any("no opening line" in w for w in warnings)


def test_single_running_header_does_not_invent_a_chapter() -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _header("第 17 章 绪论", 20),  # OCR slip
                _header("第1章 绪论", 22),
                _header("第1章 绪论", 24),
            ],
        )
    ]
    warnings: list[str] = []

    candidates = analyze_headings(segments, include_toc=False, warnings=warnings)

    assert [c.label for c in candidates if c.kind == "chapter"] == ["1"]
    assert any("single running header" in w for w in warnings)


def test_repeated_label_line_is_reported() -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _text("绪论", 18, 1),
                _text("第2章", 25),  # stray line the exporter would hit first
                _text("第2章", 30, 2),
                _text("递推", 30, 1),
            ],
        )
    ]
    warnings: list[str] = []

    analyze_headings(segments, include_toc=False, warnings=warnings)

    assert any("第2章 appears more than once" in w for w in warnings)


def test_leading_chapter_number_above_one_is_only_informational() -> None:
    segments = [("book_part2", [_text("第11章", 20, 2), _text("广度优先搜索", 20, 1)])]
    warnings: list[str] = []

    analyze_headings(segments, include_toc=False, warnings=warnings)

    assert warnings == [
        "first chapter found is 第11章; 第1章 and earlier are not in the inspected segments"
    ]


def test_label_candidate_borrows_title_from_headers_when_name_item_is_missing() -> None:
    segments = [
        (
            "book",
            [
                _text("第1章", 18, 2),
                _header("第1章 绪论", 20),
                _header("第1章 绪论", 22),
            ],
        )
    ]

    candidates = analyze_headings(segments, include_toc=False)

    assert candidates[0].title == "绪论"


def test_section_like_level_two_text_is_not_a_chapter() -> None:
    segments = [
        (
            "book",
            [
                _text("3.1.1 模拟法的设计思想", 48, 2),
                _text("第3章讨论了模拟法", 49, 2),
                _text("见第3章 的内容", 50),
            ],
        )
    ]

    assert analyze_headings(segments, include_toc=False) == []


def test_first_chapter_on_a_toc_page_is_flagged_for_toc_max_page() -> None:
    # Inspecting a later part alone: the exporter would skip page 0 as TOC
    # unless book.yml sets toc_max_page: 0.
    segments = [("book_part2", [_text("第11章", 0, 2), _text("广度优先搜索", 0, 1)])]
    warnings: list[str] = []

    analyze_headings(segments, include_toc=False, warnings=warnings)

    assert any("toc_max_page" in w for w in warnings)
