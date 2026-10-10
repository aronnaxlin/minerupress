import json
from pathlib import Path

import pytest

from minerupress.core import BookConfig, ChapterConfig, export
from minerupress.loader import load_book_config


def _export(tmp_path: Path, items: list[dict], **config) -> str:
    seg = tmp_path / "mineru" / "demo_full"
    seg.mkdir(parents=True)
    (seg / "demo_content_list.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )
    export(
        BookConfig(
            chapters=[ChapterConfig(slug="ch01", title="第1章 概述", volume_uid="demo")],
            mineru_root=tmp_path / "mineru",
            docs_out=tmp_path / "docs",
            toc_max_page=0,
            **config,
        )
    )
    return (tmp_path / "docs" / "chapters" / "ch01.md").read_text(encoding="utf-8")


def _blocks(md: str) -> list[str]:
    return [block.strip() for block in md.split("\n\n") if block.strip()]


_OPENER = {"type": "text", "text": "第1章 概述", "text_level": 1, "page_idx": 0}


def test_page_footnotes_are_skipped_by_default(tmp_path: Path) -> None:
    md = _export(tmp_path, [
        _OPENER,
        {"type": "text", "text": "正文一。", "page_idx": 0},
        {"type": "page_footnote", "text": "① 脚注内容。", "page_idx": 0},
    ])

    assert "脚注内容" not in md


def test_footnote_follows_a_finished_paragraph_in_place(tmp_path: Path) -> None:
    md = _export(tmp_path, [
        _OPENER,
        {"type": "text", "text": "正文一 $^{①}$ 结束。", "page_idx": 0},
        {"type": "page_number", "text": "1", "page_idx": 0},
        {"type": "page_footnote", "text": "① 脚注内容。", "page_idx": 0},
        {"type": "text", "text": "正文二。", "page_idx": 1},
    ], page_footnotes="paragraph")

    assert _blocks(md)[1:] == ["正文一 $^{①}$ 结束。", "> ① 脚注内容。", "正文二。"]


def test_footnote_waits_for_a_paragraph_that_continues_on_the_next_page(tmp_path: Path) -> None:
    md = _export(tmp_path, [
        _OPENER,
        {"type": "text", "text": "这一段在页末被截断，没有", "page_idx": 0},
        {"type": "page_footnote", "text": "① 第一条。", "page_idx": 0},
        {"type": "page_footnote", "text": "② 第二条。", "page_idx": 0},
        {"type": "text", "text": "写完的后半句。", "page_idx": 1},
        {"type": "text", "text": "下一段。", "page_idx": 1},
    ], page_footnotes="paragraph")

    assert _blocks(md)[1:] == [
        "这一段在页末被截断，没有",
        "写完的后半句。",
        "> ① 第一条。\n>\n> ② 第二条。",
        "下一段。",
    ]


def test_waiting_footnote_is_placed_before_a_heading(tmp_path: Path) -> None:
    md = _export(tmp_path, [
        _OPENER,
        {"type": "text", "text": "页末没有句号的一段", "page_idx": 0},
        {"type": "page_footnote", "text": "① 脚注。", "page_idx": 0},
        {"type": "text", "text": "1.1 小节", "text_level": 2, "page_idx": 1},
    ], page_footnotes="paragraph")

    assert _blocks(md)[1:] == ["页末没有句号的一段", "> ① 脚注。", "## 1.1 小节"]


def test_waiting_footnote_is_written_at_the_end_of_the_chapter(tmp_path: Path) -> None:
    md = _export(tmp_path, [
        _OPENER,
        {"type": "text", "text": "最后一段没有句号", "page_idx": 0},
        {"type": "page_footnote", "text": "[1] 参考说明。", "page_idx": 0},
    ], page_footnotes="paragraph")

    assert _blocks(md)[-1] == "> [1] 参考说明。"


def test_fragments_without_a_footnote_marker_are_dropped(tmp_path: Path, capsys) -> None:
    md = _export(tmp_path, [
        _OPENER,
        {"type": "text", "text": "正文。", "page_idx": 0},
        {"type": "page_footnote", "text": "double Solve(double p[], int n)\n{", "page_idx": 0},
        {"type": "page_footnote", "text": "$v_{i}$", "page_idx": 0},
        {"type": "page_footnote", "text": "① 真脚注。", "page_idx": 0},
    ], page_footnotes="paragraph")

    assert "double Solve" not in md
    assert "$v_{i}$" not in md
    assert "> ① 真脚注。" in md
    assert "page_footnote      1 / 2" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("value", "expected"),
    [("paragraph", "paragraph"), ("skip", "skip"), ("true", "paragraph"), ("false", "skip")],
)
def test_loader_reads_page_footnotes(tmp_path: Path, value: str, expected: str) -> None:
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(
        f"volume_uid: demo\npage_footnotes: {value}\nchapters:\n  - slug: ch01\n    title: 第1章 概述\n",
        encoding="utf-8",
    )

    config, _plugins, _source = load_book_config(book_yml)

    assert config.page_footnotes == expected


def test_loader_defaults_to_skip_and_rejects_unknown_modes(tmp_path: Path) -> None:
    book_yml = tmp_path / "book.yml"
    chapters = "chapters:\n  - slug: ch01\n    title: 第1章 概述\n"
    book_yml.write_text(f"volume_uid: demo\n{chapters}", encoding="utf-8")
    assert load_book_config(book_yml)[0].page_footnotes == "skip"

    book_yml.write_text(f"volume_uid: demo\npage_footnotes: endnotes\n{chapters}", encoding="utf-8")
    with pytest.raises(ValueError, match="page_footnotes"):
        load_book_config(book_yml)
