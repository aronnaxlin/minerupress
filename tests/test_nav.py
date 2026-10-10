from pathlib import Path

import pytest
import yaml

from minerupress import nav
from minerupress.cli import root_main
from minerupress.core import BookConfig, ChapterConfig


def _config(tmp_path: Path, *slugs: str) -> BookConfig:
    return BookConfig(
        chapters=[
            ChapterConfig(slug=s, title=f"第{i}章 {s}", volume_uid="demo")
            for i, s in enumerate(slugs, 1)
        ],
        mineru_root=tmp_path / "resources" / "mineru",
        docs_out=tmp_path / "docs",
    )


def _write_mkdocs(tmp_path: Path, nav_block: str, header: str = "") -> Path:
    mkdocs_yml = tmp_path / "mkdocs.yml"
    mkdocs_yml.write_text(
        f"site_name: Demo\n{header}\nnav:\n{nav_block}\n", encoding="utf-8"
    )
    return mkdocs_yml


def _write_book(tmp_path: Path, slugs: list[str]) -> Path:
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(
        yaml.safe_dump(
            {
                "volume_uid": "demo",
                "plugins": [],
                "chapters": [{"slug": s, "title": f"第{i}章 概述"} for i, s in enumerate(slugs, 1)],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return book_yml


NAV_OK = """\
  - 首页: index.md
  - 各章内容:
      - 第1章 a: chapters/a.md
      - 第2章 b: chapters/b.md
"""


def test_render_snippet_is_pasteable_and_round_trips(tmp_path: Path) -> None:
    config = _config(tmp_path, "a", "b")
    config.chapters[0].title = "第1章: 引论 # 概述"  # characters YAML must quote

    snippet = nav.render_nav_snippet(config)

    parsed = yaml.safe_load("nav:\n" + snippet)
    assert parsed == {
        "nav": [
            {"各章内容": [{"第1章: 引论 # 概述": "chapters/a.md"}, {"第2章 b": "chapters/b.md"}]}
        ]
    }
    assert snippet.startswith("  - 各章内容:\n      - ")


def test_in_sync_nav_has_no_problems(tmp_path: Path) -> None:
    mkdocs_yml = _write_mkdocs(tmp_path, NAV_OK)

    assert nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b")) == []


def test_chapter_missing_from_nav(tmp_path: Path) -> None:
    mkdocs_yml = _write_mkdocs(tmp_path, NAV_OK)

    problems = nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b", "c"))

    assert len(problems) == 1
    assert "'c'" in problems[0] and "missing from" in problems[0]


def test_nav_entry_for_unknown_chapter_file(tmp_path: Path) -> None:
    mkdocs_yml = _write_mkdocs(tmp_path, NAV_OK + "      - 附录: chapters/appendix.md\n")

    problems = nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b"))

    assert len(problems) == 1
    assert "chapters/appendix.md" in problems[0] and "does not exist" in problems[0]


def test_nav_order_mismatch(tmp_path: Path) -> None:
    mkdocs_yml = _write_mkdocs(
        tmp_path,
        "  - 各章内容:\n      - B: chapters/b.md\n      - A: chapters/a.md\n",
    )

    problems = nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b"))

    assert len(problems) == 1
    assert "order" in problems[0]


def test_nested_and_dot_slash_entries_are_understood(tmp_path: Path) -> None:
    mkdocs_yml = _write_mkdocs(
        tmp_path,
        "  - Part I:\n      - ./chapters/a.md\n  - Part II:\n      - Intro: chapters/b.md\n",
    )

    assert nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b")) == []


def test_material_python_name_tags_are_tolerated(tmp_path: Path) -> None:
    header = (
        "markdown_extensions:\n"
        "  - pymdownx.emoji:\n"
        "      emoji_index: !!python/name:material.extensions.emoji.twemoji\n"
        "      emoji_generator: !!python/name:material.extensions.emoji.to_svg\n"
        "site_url: !ENV [SITE_URL, 'http://localhost']\n"
    )
    mkdocs_yml = _write_mkdocs(tmp_path, NAV_OK, header)
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(mkdocs_yml.read_text(encoding="utf-8"))

    assert nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b")) == []


def test_mkdocs_without_nav_has_nothing_to_compare(tmp_path: Path) -> None:
    mkdocs_yml = tmp_path / "mkdocs.yml"
    mkdocs_yml.write_text("site_name: Demo\n", encoding="utf-8")

    assert nav.check_nav(mkdocs_yml, _config(tmp_path, "a", "b")) == []


def test_custom_docs_dir_is_taken_into_account(tmp_path: Path) -> None:
    config = _config(tmp_path, "a")
    config.docs_out = tmp_path / "content"
    mkdocs_yml = _write_mkdocs(tmp_path, "  - A: chapters/a.md\n", header="docs_dir: content")

    assert nav.check_nav(mkdocs_yml, config) == []

    mkdocs_yml = _write_mkdocs(tmp_path, "  - A: chapters/a.md\n", header="docs_dir: other")
    assert any("docs_dir" in p for p in nav.check_nav(mkdocs_yml, config))


def test_warn_if_nav_drift_prints_warnings(tmp_path: Path, capsys) -> None:
    book_yml = _write_book(tmp_path, ["a", "b", "c"])
    _write_mkdocs(tmp_path, NAV_OK)

    nav.warn_if_nav_drift(book_yml, _config(tmp_path, "a", "b", "c"))

    out = capsys.readouterr().out
    assert "[WARN]" in out and "'c'" in out


def test_warn_if_nav_drift_is_silent_without_mkdocs_yml(tmp_path: Path, capsys) -> None:
    nav.warn_if_nav_drift(tmp_path / "book.yml", _config(tmp_path, "a"))

    assert capsys.readouterr().out == ""


def test_warn_if_nav_drift_never_raises(tmp_path: Path, capsys) -> None:
    (tmp_path / "mkdocs.yml").write_text("nav: [unclosed\n  - : :\n", encoding="utf-8")

    nav.warn_if_nav_drift(tmp_path / "book.yml", _config(tmp_path, "a"))
    nav.warn_if_nav_drift(tmp_path / "book.yml", None)  # type: ignore[arg-type]

    assert "[WARN]" in capsys.readouterr().out


def test_cli_prints_snippet(tmp_path: Path, capsys) -> None:
    book_yml = _write_book(tmp_path, ["a", "b"])

    assert root_main(["nav", str(book_yml)]) == 0

    assert "chapters/a.md" in capsys.readouterr().out


def test_cli_check_exit_codes(tmp_path: Path, capsys) -> None:
    book_yml = _write_book(tmp_path, ["a", "b", "c"])
    mkdocs_yml = _write_mkdocs(tmp_path, NAV_OK)

    assert root_main(["nav", str(book_yml), "--check"]) == 1
    assert "'c'" in capsys.readouterr().out

    book_yml = _write_book(tmp_path, ["a", "b"])
    assert root_main(["nav", str(book_yml), "--check", "--mkdocs-yml", str(mkdocs_yml)]) == 0

    mkdocs_yml.unlink()
    assert root_main(["nav", str(book_yml), "--check"]) == 2
