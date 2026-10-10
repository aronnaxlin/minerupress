from __future__ import annotations
import re
import warnings

from .base import ExportPlugin

try:
    import pangu as _pangu
    _AVAILABLE = True
except ImportError:
    _pangu = None
    _AVAILABLE = False

# Protect LaTeX spans from pangu so spaces aren't inserted inside formulas
_LATEX_BLOCK  = re.compile(r'\$\$[\s\S]*?\$\$')
_LATEX_INLINE = re.compile(r'\$[^$\n]+?\$')

# pangu 4.x exposes spacing_text(); pangu 5+/6.x renamed it to space_text().
_SPACING_FUNC_NAMES = ("space_text", "spacing_text")


def _find_spacing_func(module):
    for name in _SPACING_FUNC_NAMES:
        func = getattr(module, name, None)
        if callable(func):
            return func
    return None


def _spacing(text: str) -> str:
    if not _AVAILABLE or not text:
        return text
    func = _find_spacing_func(_pangu)
    if func is None:
        raise RuntimeError(
            "installed pangu exposes neither space_text() nor spacing_text()"
        )
    placeholders: list[str] = []

    def stash(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00L{len(placeholders)-1}\x00"

    protected = _LATEX_BLOCK.sub(stash, text)
    protected = _LATEX_INLINE.sub(stash, protected)
    spaced = func(protected)
    for i, original in enumerate(placeholders):
        spaced = spaced.replace(f"\x00L{i}\x00", original)
    return spaced


class CJKSpacingPlugin(ExportPlugin):
    """
    Insert spaces between CJK characters and ASCII/Latin text using pangu.

    LaTeX inline ($...$) and block ($$...$$) spans are protected and
    passed through unchanged.  Works with both the pangu 4.x
    (spacing_text) and 5+/6.x (space_text) APIs.  If pangu fails on a
    text, that text is returned unchanged and a warning is printed once.
    """

    def __init__(self) -> None:
        self._warned = False
        if not _AVAILABLE:
            warnings.warn(
                "pangu not installed; CJKSpacingPlugin is disabled. "
                "Run: pip install pangu",
                stacklevel=2,
            )

    def on_text(self, item: dict, text: str) -> str:
        try:
            return _spacing(text)
        except Exception as exc:
            if not self._warned:
                self._warned = True
                print(
                    f"  [WARN] cjk_spacing: pangu failed ({type(exc).__name__}: {exc}); "
                    "leaving text unchanged"
                )
            return text
