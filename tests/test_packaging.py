import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = [ROOT / "book_template", ROOT / "minerupress" / "book_template"]


def _extras() -> dict[str, list[str]]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["optional-dependencies"]


def test_site_extra_bounds_mkdocs_below_2() -> None:
    site = _extras()["site"]

    assert "mkdocs>=1.6,<2" in site
    assert "mkdocs-material>=9.5,<10" in site


def test_all_extra_includes_every_other_extra() -> None:
    extras = _extras()

    for name in ("qr", "cjk", "site"):
        assert set(extras[name]) <= set(extras["all"]), name


def test_template_mathjax_is_pinned_to_a_patch_version() -> None:
    for template in TEMPLATES:
        text = (template / "mkdocs.yml").read_text(encoding="utf-8")
        urls = re.findall(r"^\s*-\s*(\S*mathjax\S*)\s*$", text, flags=re.MULTILINE)

        assert urls, template
        for url in urls:
            assert re.search(r"mathjax@3\.\d+\.\d+/", url), url


def test_docs_do_not_recommend_unpinned_mkdocs_install() -> None:
    bare = re.compile(r"pip install\s+mkdocs\b")
    offenders = []
    candidates = [ROOT / "README.md", ROOT / "AGENTS.md"]
    for sub in ("docs", "skills"):
        candidates.extend((ROOT / sub).rglob("*.md"))
    for path in candidates:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if bare.search(line) and "Do not tell users" not in line:
                offenders.append(f"{path.relative_to(ROOT)}:{number}")

    assert offenders == []
