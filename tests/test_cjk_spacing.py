import types

from minerupress.plugins import cjk_spacing
from minerupress.plugins.cjk_spacing import CJKSpacingPlugin


def _fake_pangu(**funcs) -> types.SimpleNamespace:
    return types.SimpleNamespace(**funcs)


def _naive_spacer(text: str) -> str:
    return text.replace("中a", "中 a")


def test_supports_pangu_4_spacing_text(monkeypatch) -> None:
    monkeypatch.setattr(cjk_spacing, "_AVAILABLE", True)
    monkeypatch.setattr(cjk_spacing, "_pangu", _fake_pangu(spacing_text=_naive_spacer))

    assert CJKSpacingPlugin().on_text({}, "中abc") == "中 abc"


def test_supports_pangu_6_space_text(monkeypatch) -> None:
    monkeypatch.setattr(cjk_spacing, "_AVAILABLE", True)
    monkeypatch.setattr(cjk_spacing, "_pangu", _fake_pangu(space_text=_naive_spacer))

    assert CJKSpacingPlugin().on_text({}, "中abc") == "中 abc"


def test_latex_spans_are_protected(monkeypatch) -> None:
    monkeypatch.setattr(cjk_spacing, "_AVAILABLE", True)
    monkeypatch.setattr(cjk_spacing, "_pangu", _fake_pangu(space_text=lambda s: s.replace("a", "a ")))

    out = CJKSpacingPlugin().on_text({}, "a $a+a$ $$a\na$$")

    assert out == "a  $a+a$ $$a\na$$"


def test_unknown_pangu_api_falls_back_and_warns_once(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cjk_spacing, "_AVAILABLE", True)
    monkeypatch.setattr(cjk_spacing, "_pangu", _fake_pangu())
    plugin = CJKSpacingPlugin()

    assert plugin.on_text({}, "中abc") == "中abc"
    assert plugin.on_text({}, "中def") == "中def"

    assert capsys.readouterr().out.count("[WARN] cjk_spacing") == 1


def test_pangu_exception_falls_back_and_warns_once(monkeypatch, capsys) -> None:
    def boom(text: str) -> str:
        raise ValueError("bad input")

    monkeypatch.setattr(cjk_spacing, "_AVAILABLE", True)
    monkeypatch.setattr(cjk_spacing, "_pangu", _fake_pangu(space_text=boom))
    plugin = CJKSpacingPlugin()

    assert plugin.on_text({}, "中abc") == "中abc"
    assert plugin.on_text({}, "中abc") == "中abc"

    assert capsys.readouterr().out.count("[WARN] cjk_spacing") == 1


def test_installed_pangu_inserts_spaces() -> None:
    import pytest

    pytest.importorskip("pangu")

    assert CJKSpacingPlugin().on_text({}, "算法abc分析 $x中y$") == "算法 abc 分析 $x中y$"
