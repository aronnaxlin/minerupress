"""
minerupress.nav
~~~~~~~~~~~~~~~~~~~
Keep the ``nav:`` of mkdocs.yml in step with the chapters in book.yml.

MkDocs only reports pages that are missing from ``nav`` at INFO level, so a
chapter that was added to book.yml but not to mkdocs.yml silently disappears
from the site.  This module generates the chapter nav and checks an existing
mkdocs.yml against book.yml.  It never rewrites mkdocs.yml.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator, Sequence

import yaml

from .core import BookConfig

DEFAULT_SECTION_TITLE = "各章内容"
_CHAPTERS_DIR = "chapters"


# ---------------------------------------------------------------------------
# Reading mkdocs.yml
# ---------------------------------------------------------------------------

class _TolerantLoader(yaml.SafeLoader):
    """SafeLoader that accepts the python/name and !ENV tags used by MkDocs configs."""


def _construct_unknown(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


# "!ENV ..." and "!!python/name:material.extensions.emoji.twemoji" respectively.
_TolerantLoader.add_multi_constructor("!", _construct_unknown)
_TolerantLoader.add_multi_constructor("tag:yaml.org,2002:python/", _construct_unknown)


def load_mkdocs_config(mkdocs_yml: Path) -> dict:
    """Parse mkdocs.yml, tolerating tags that yaml.safe_load rejects."""
    with open(mkdocs_yml, encoding="utf-8") as f:
        data = yaml.load(f, Loader=_TolerantLoader)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{mkdocs_yml} is not a YAML mapping")
    return data


def _nav_leaves(nav) -> Iterator[str]:
    """Yield the page paths of a MkDocs nav in document order."""
    if isinstance(nav, str):
        yield nav
    elif isinstance(nav, dict):
        for value in nav.values():
            yield from _nav_leaves(value)
    elif isinstance(nav, (list, tuple)):
        for entry in nav:
            yield from _nav_leaves(entry)


def _normalize(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


# ---------------------------------------------------------------------------
# Generating the nav
# ---------------------------------------------------------------------------

def chapter_nav(config: BookConfig, prefix: str = _CHAPTERS_DIR) -> list[dict[str, str]]:
    """Nav entries, one ``{title: path}`` per chapter, in book.yml order."""
    return [{ch.title: f"{prefix}/{ch.slug}.md"} for ch in config.chapters]


class _IndentedDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)


def render_nav_snippet(
    config: BookConfig,
    section_title: str = DEFAULT_SECTION_TITLE,
    prefix: str = _CHAPTERS_DIR,
) -> str:
    """
    YAML for a chapter section, indented to be pasted under ``nav:``::

        nav:
          - 首页: index.md
          - 各章内容:
              - 第1章 概述: chapters/ch01-overview.md
    """
    body = yaml.dump(
        [{section_title: chapter_nav(config, prefix)}],
        Dumper=_IndentedDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=10_000,
    )
    return "".join(f"  {line}\n" for line in body.splitlines())


# ---------------------------------------------------------------------------
# Checking an existing nav
# ---------------------------------------------------------------------------

def check_nav(mkdocs_yml: Path, config: BookConfig) -> list[str]:
    """
    Compare the ``nav:`` in mkdocs_yml with config.chapters.

    Returns human-readable problems (empty when in sync): chapters missing
    from the nav, nav entries pointing at chapter files that book.yml does not
    define, and chapters listed in a different order than in book.yml.
    A mkdocs.yml without ``nav:`` lets MkDocs build the nav from the file
    tree, so there is nothing to compare.
    """
    mkdocs_yml = Path(mkdocs_yml)
    mkdocs = load_mkdocs_config(mkdocs_yml)
    problems: list[str] = []

    docs_dir = (mkdocs_yml.parent / str(mkdocs.get("docs_dir") or "docs")).resolve()
    chapters_dir = (config.docs_out / _CHAPTERS_DIR).resolve()
    try:
        prefix = chapters_dir.relative_to(docs_dir).as_posix()
    except ValueError:
        prefix = _CHAPTERS_DIR
        problems.append(
            f"mkdocs.yml docs_dir ({docs_dir}) does not contain book.yml docs_out/chapters "
            f"({chapters_dir}); MkDocs will not see the exported chapters"
        )

    nav = mkdocs.get("nav")
    if not nav:
        return problems

    slug_titles = {ch.slug: ch.title for ch in config.chapters}
    expected = [ch.slug for ch in config.chapters]

    in_nav: list[str] = []  # chapter slugs, in nav order
    for leaf in _nav_leaves(nav):
        path = _normalize(leaf)
        if not path.startswith(prefix + "/") or not path.endswith(".md"):
            continue
        slug = path[len(prefix) + 1:-len(".md")]
        if slug in slug_titles:
            if slug in in_nav:
                problems.append(f"nav lists chapter {slug!r} more than once")
            else:
                in_nav.append(slug)
        else:
            detail = "" if (docs_dir / path).exists() else " and the file does not exist"
            problems.append(
                f"nav points to {path}, which is not a chapter in book.yml{detail}"
            )

    for slug in expected:
        if slug not in in_nav:
            problems.append(
                f"chapter {slug!r} ({slug_titles[slug]}) is in book.yml but missing from "
                f"mkdocs.yml nav (expected {prefix}/{slug}.md)"
            )

    # Order only matters among the chapters that appear on both sides.
    nav_order = [slug for slug in in_nav if slug in slug_titles]
    book_order = [slug for slug in expected if slug in in_nav]
    for pos, (got, want) in enumerate(zip(nav_order, book_order), 1):
        if got != want:
            problems.append(
                f"nav order differs from book.yml at chapter {pos}: "
                f"nav has {got!r} where book.yml has {want!r}"
            )
            break
    return problems


def find_mkdocs_yml(book_yml: Path) -> Path | None:
    """mkdocs.yml (or .yaml) next to book.yml, if any."""
    for name in ("mkdocs.yml", "mkdocs.yaml"):
        candidate = Path(book_yml).parent / name
        if candidate.is_file():
            return candidate
    return None


def warn_if_nav_drift(book_yml: Path, config: BookConfig) -> None:
    """
    Print ``[WARN]`` lines when mkdocs.yml next to book.yml has a nav that
    disagrees with the chapters.  Does nothing without a mkdocs.yml and never
    raises, so it is safe to call at the end of an export.
    """
    try:
        mkdocs_yml = find_mkdocs_yml(Path(book_yml))
        if mkdocs_yml is None:
            return
        problems = check_nav(mkdocs_yml, config)
        for problem in problems:
            print(f"  [WARN] {mkdocs_yml.name}: {problem}")
        if problems:
            print("  [WARN] run `minerupress nav` to print the chapter nav for book.yml")
    except Exception as exc:  # advisory only; never break an export
        try:
            print(f"  [WARN] could not check mkdocs.yml nav: {exc}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(book_yml: Path, mkdocs_yml: Path | None, check: bool) -> int:
    """Implementation of ``minerupress nav``.  Exit codes: 0 ok, 1 drift, 2 error."""
    from .loader import load_book_config

    book_yml = Path(book_yml)
    if not book_yml.exists():
        print(f"Error: {book_yml} not found.", file=sys.stderr)
        return 2
    try:
        config, _plugins, _source = load_book_config(book_yml)
    except Exception as exc:
        print(f"Error: cannot load {book_yml}: {exc}", file=sys.stderr)
        return 2

    if not check:
        sys.stdout.write(render_nav_snippet(config))
        return 0

    target = Path(mkdocs_yml) if mkdocs_yml else find_mkdocs_yml(book_yml)
    if target is None or not target.is_file():
        shown = mkdocs_yml or book_yml.parent / "mkdocs.yml"
        print(f"Error: {shown} not found.", file=sys.stderr)
        return 2
    try:
        problems = check_nav(target, config)
    except Exception as exc:
        print(f"Error: cannot read {target}: {exc}", file=sys.stderr)
        return 2

    if not problems:
        if not load_mkdocs_config(target).get("nav"):
            # Without nav: MkDocs builds the nav from the file tree.
            print(f"{target}: no nav section; nothing to compare with {book_yml.name}")
            return 0
        print(f"{target}: nav is in sync with {len(config.chapters)} chapters in {book_yml.name}")
        return 0
    for problem in problems:
        print(f"{target}: {problem}")
    print(
        f"\n{len(problems)} problem(s). `minerupress nav {book_yml}` prints the chapter nav "
        "to paste into mkdocs.yml.",
        file=sys.stderr,
    )
    return 1


def main(argv: Sequence[str] | None = None, prog: str = "minerupress nav") -> int:
    import argparse

    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("book_yml", nargs="?", default="book.yml")
    parser.add_argument("--mkdocs-yml")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        Path(args.book_yml),
        Path(args.mkdocs_yml) if args.mkdocs_yml else None,
        args.check,
    )
