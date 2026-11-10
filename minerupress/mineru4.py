"""
MinerU 4.x compatibility.

MinerU 2.x writes ``*_content_list.json`` next to the images. MinerU 4.x no longer
writes that file; a result directory holds ``markdown.md``, ``middle_json.json``,
``structured_content.json`` and ``images/``. The content list only exists as a
render target of ``middle_json.json``.

MineruPress keeps reading the content-list shape, so for a 4.x directory it asks
the installed ``mineru`` package to render it from ``middle_json.json``, in memory.
Nothing is written into the result directory.
"""

from __future__ import annotations

import json
from pathlib import Path

MIDDLE_JSON_NAME = "middle_json.json"


def find_content_list(vol_dir: Path) -> Path | None:
    """Return the 2.x ``*_content_list.json`` in *vol_dir* (v1 preferred), if any."""
    candidates = sorted(vol_dir.glob("*_content_list.json"))
    if not candidates:
        return None
    non_v2 = [p for p in candidates if "v2" not in p.name]
    return non_v2[0] if non_v2 else candidates[0]


def find_middle_json(vol_dir: Path) -> Path | None:
    path = vol_dir / MIDDLE_JSON_NAME
    return path if path.is_file() else None


def has_mineru_output(vol_dir: Path) -> bool:
    return find_content_list(vol_dir) is not None or find_middle_json(vol_dir) is not None


def render_content_list_from_middle_json(middle_json_path: Path) -> list[dict]:
    """Render the flat content list from a MinerU 4.x ``middle_json.json``."""
    try:
        from mineru.parser.base import ParseResult
        from mineru.render.content_list import render_content_list
    except ImportError as exc:
        raise RuntimeError(
            f"{middle_json_path.parent} is a MinerU 4.x result (middle_json.json, no "
            "*_content_list.json). MineruPress needs the `mineru` Python package to "
            "turn it into a content list, but it cannot be imported in this "
            "environment. Install it next to MineruPress:\n"
            "  pip install mineru\n"
            "or use MinerU 2.x output, which already contains *_content_list.json."
        ) from exc

    result = ParseResult.from_json(middle_json_path.read_text(encoding="utf-8"))
    return render_content_list(result.middle_json)


def load_content_list(vol_dir: Path) -> list[dict]:
    """Load the content list of one result directory (MinerU 2.x or 4.x)."""
    path = find_content_list(vol_dir)
    if path is not None:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    middle = find_middle_json(vol_dir)
    if middle is not None:
        return render_content_list_from_middle_json(middle)
    raise FileNotFoundError(
        f"No *_content_list.json or {MIDDLE_JSON_NAME} found in {vol_dir}"
    )
