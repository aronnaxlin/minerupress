import json
from pathlib import Path

from minerupress.core import (
    BookConfig,
    ChapterConfig,
    _escape_inline_html,
    _item_to_md,
    export,
)
from minerupress.plugins.base import ExportPlugin


def _write_volume(root: Path, name: str, items: list[dict], images: tuple[str, ...] = ()) -> None:
    volume = root / name
    (volume / "images").mkdir(parents=True)
    for image in images:
        (volume / "images" / image).write_bytes(b"img")
    (volume / f"{name}_content_list.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )


def _export_one(
    tmp_path: Path,
    items: list[dict],
    *,
    images: tuple[str, ...] = (),
    plugins: tuple[ExportPlugin, ...] = (),
    title: str = "第1章 绪论",
    aliases: list[str] | None = None,
    start_pattern: str = r"^第\s*1\s*章$",
) -> str:
    mineru_root = tmp_path / "mineru"
    docs_out = tmp_path / "docs"
    _write_volume(mineru_root, "vol", items, images)
    export(
        BookConfig(
            mineru_root=mineru_root,
            docs_out=docs_out,
            toc_max_page=0,
            chapters=[
                ChapterConfig(
                    slug="ch01",
                    title=title,
                    volume_uid="vol",
                    start_pattern=start_pattern,
                    aliases=aliases or [],
                )
            ],
        ),
        plugins,
    )
    return (docs_out / "chapters" / "ch01.md").read_text(encoding="utf-8")


class _DropAll(ExportPlugin):
    def on_image(self, item, img_path):
        return False


class _Upper(ExportPlugin):
    def on_text(self, item, text):
        return text.upper()


_OPENER = {"type": "text", "text_level": 1, "page_idx": 0, "text": "第1章"}


def test_image_caption_and_footnote_accept_both_field_spellings() -> None:
    new = {
        "type": "image", "img_path": "images/a.png",
        "image_caption": ["图1 流程"], "image_footnote": ["课件 1-1"],
    }
    old = {"type": "image", "img_path": "images/a.png", "img_caption": ["图2 旧"]}
    md = _item_to_md(new, "a.png", [])
    assert md == "![图1 流程](../images/a.png)\n*图1 流程*\n\n课件 1-1"
    assert _item_to_md(old, "a.png", []) == "![图2 旧](../images/a.png)\n*图2 旧*"


def test_image_without_caption_keeps_filename_alt() -> None:
    md = _item_to_md({"type": "image", "img_path": "images/a.png"}, "a.png", [])
    assert md == "![a.png](../images/a.png)"


def test_filtered_image_drops_caption_and_footnote(tmp_path: Path) -> None:
    md = _export_one(
        tmp_path,
        [
            _OPENER,
            {"type": "image", "img_path": "images/q.png", "page_idx": 0,
             "image_caption": ["图 二维码"], "image_footnote": ["课件 1-1"]},
            {"type": "text", "page_idx": 0, "text": "正文"},
        ],
        images=("q.png",),
        plugins=(_DropAll(),),
    )
    assert "课件 1-1" not in md
    assert "二维码" not in md
    assert "正文" in md


def test_chart_is_copied_and_rendered_like_an_image(tmp_path: Path) -> None:
    seen: list[str] = []

    class _Spy(ExportPlugin):
        def on_image(self, item, img_path):
            seen.append(item["type"])
            return True

    md = _export_one(
        tmp_path,
        [
            _OPENER,
            {"type": "chart", "img_path": "images/c.png", "page_idx": 0,
             "chart_caption": ["图2-1 增长曲线"], "chart_footnote": ["注：示意"],
             "content": ""},
        ],
        images=("c.png",),
        plugins=(_Spy(),),
    )
    assert seen == ["chart"]
    assert (tmp_path / "docs" / "images" / "c.png").exists()
    assert "![图2-1 增长曲线](../images/c.png)" in md
    assert "*图2-1 增长曲线*" in md
    assert "注：示意" in md


def test_chart_without_image_falls_back_to_text() -> None:
    assert _item_to_md({"type": "chart", "text": "数据"}, None, []) == "数据"


def test_list_items_render_as_markdown_list_through_text_plugins() -> None:
    item = {
        "type": "list", "sub_type": "text",
        "list_items": ["alpha", "- beta", "1. gamma", "2)delta", "  ", "• eps\nzeta"],
    }
    md = _item_to_md(item, None, [_Upper()])
    assert md.split("\n") == [
        "- ALPHA", "- BETA", "1. GAMMA", "2. DELTA", "- EPS ZETA",
    ]


def test_list_with_only_text_still_renders() -> None:
    assert _item_to_md({"type": "list", "text": "- a"}, None, []) == "- a"


def test_code_caption_and_table_footnote() -> None:
    code = {"type": "code", "code_body": "x = 1", "code_caption": ["算法 1.1"]}
    assert _item_to_md(code, None, []) == "**算法 1.1**\n\n```\nx = 1\n```"
    table = {
        "type": "table", "table_caption": ["表1"], "table_body": "<table></table>",
        "table_footnote": ["注：单位 ms"],
    }
    assert _item_to_md(table, None, []) == "**表1**\n\n<table></table>\n\n注：单位 ms"
    assert _item_to_md({"type": "table", "table_footnote": ["孤立"]}, None, []) is None


def test_page_footnote_is_skipped_and_counted(tmp_path: Path, capsys) -> None:
    md = _export_one(
        tmp_path,
        [
            _OPENER,
            {"type": "text", "page_idx": 0, "text": "正文"},
            {"type": "page_footnote", "page_idx": 0, "text": "① 脚注"},
            {"type": "seal", "page_idx": 0, "img_path": "images/s.png"},
        ],
    )
    out = capsys.readouterr().out
    assert "脚注" not in md
    assert "page_footnote" in out and "0 / 1" in out
    assert "[WARN]" in out and "'seal'" in out


def test_leading_title_fragments_are_skipped(tmp_path: Path) -> None:
    md = _export_one(
        tmp_path,
        [
            _OPENER,
            {"type": "text", "page_idx": 0, "text": "绪 论"},
            {"type": "page_number", "page_idx": 0, "text": "1"},
            {"type": "text", "text_level": 2, "page_idx": 0, "text": "1.1 概述"},
            {"type": "text", "page_idx": 0, "text": "绪论"},
        ],
    )
    lines = [line for line in md.split("\n") if line]
    assert lines == ["# 第1章 绪论", "## 1.1 概述", "绪论"]


def test_boundary_prose_is_kept(tmp_path: Path) -> None:
    md = _export_one(
        tmp_path,
        [
            {"type": "text", "page_idx": 0, "text": "第1章讨论了很多问题，本节先介绍背景。"},
            {"type": "text", "page_idx": 0, "text": "第1章"},
        ],
        start_pattern=r"^第1章讨论",
    )
    # The run of skipped fragments ends at the prose, so the later bare
    # "第1章" is not touched either.
    assert [line for line in md.split("\n") if line] == [
        "# 第1章 绪论",
        "第1章讨论了很多问题，本节先介绍背景。",
        "第1章",
    ]


def test_title_fragment_on_other_page_is_kept(tmp_path: Path) -> None:
    md = _export_one(
        tmp_path,
        [_OPENER, {"type": "text", "page_idx": 1, "text": "绪论"}],
    )
    assert [line for line in md.split("\n") if line] == ["# 第1章 绪论", "绪论"]


def test_aliases_extend_the_title_match(tmp_path: Path) -> None:
    md = _export_one(
        tmp_path,
        [_OPENER, {"type": "text", "page_idx": 0, "text": "Introduction"},
         {"type": "text", "page_idx": 0, "text": "正文"}],
        aliases=["Introduction"],
    )
    assert [line for line in md.split("\n") if line] == ["# 第1章 绪论", "正文"]


def test_link_like_ocr_text_is_escaped_outside_math_only() -> None:
    assert _escape_inline_html("见 next[j](1≤j≤m-1) 与 a<b") == (
        "见 next[j\\](1≤j≤m-1) 与 a&lt;b"
    )
    formula = r"$\mathrm{fish[i](0\leqslant i\leqslant 4)}$ 且 $a<b$"
    assert _escape_inline_html(formula) == formula
    mixed = r"$x[i](1)$ 与 y[i](2) 及 $$z[k](3)$$"
    assert _escape_inline_html(mixed) == r"$x[i](1)$ 与 y[i\](2) 及 $$z[k](3)$$"


def test_lone_dollar_signs_do_not_shield_prose() -> None:
    assert _escape_inline_html("价格 $5 与 a[i](x)") == "价格 $5 与 a[i\\](x)"
