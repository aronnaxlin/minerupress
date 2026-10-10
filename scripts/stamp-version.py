#!/usr/bin/env python3
"""Write a release version into pyproject.toml.

The committed pyproject.toml carries a placeholder version. The release
workflow runs this inside the runner right before building, so a published
package reports its real version. The result is never committed.

Usage: scripts/stamp-version.py X.Y.Z [pyproject.toml]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_VERSION_LINE = re.compile(r'^version = "[^"]*"$', re.MULTILINE)


def stamp(version: str, pyproject: Path) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"Not a release version (expected X.Y.Z): {version!r}")
    text = pyproject.read_text(encoding="utf-8")
    stamped, count = _VERSION_LINE.subn(f'version = "{version}"', text, count=1)
    if count != 1:
        raise SystemExit(f"No `version = \"...\"` line found in {pyproject}")
    pyproject.write_text(stamped, encoding="utf-8")
    print(f"{pyproject}: version = {version}")


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    stamp(argv[1], Path(argv[2]) if len(argv) == 3 else Path("pyproject.toml"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
