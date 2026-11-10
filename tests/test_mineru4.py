"""MinerU 4.x compatibility, using synthetic result directories and a fake `mineru` package."""
import json
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest

from minerupress import cli, mineru4


def _fake_mineru(monkeypatch, items):
    """Install a stand-in for the `mineru` package that renders *items*."""
    seen = {}

    class _Result:
        middle_json = object()

        @staticmethod
        def from_json(text):
            seen["json"] = text
            return _Result()

    pkg = types.ModuleType("mineru")
    parser = types.ModuleType("mineru.parser")
    base = types.ModuleType("mineru.parser.base")
    base.ParseResult = _Result
    render = types.ModuleType("mineru.render")
    cl = types.ModuleType("mineru.render.content_list")
    cl.render_content_list = lambda middle: items
    for name, mod in {
        "mineru": pkg, "mineru.parser": parser, "mineru.parser.base": base,
        "mineru.render": render, "mineru.render.content_list": cl,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return seen


def test_load_content_list_prefers_2x_file(tmp_path: Path) -> None:
    (tmp_path / "a_content_list.json").write_text(json.dumps([{"type": "text"}]), encoding="utf-8")
    (tmp_path / "middle_json.json").write_text("{}", encoding="utf-8")
    assert mineru4.load_content_list(tmp_path) == [{"type": "text"}]


def test_load_content_list_renders_4x_middle_json(tmp_path: Path, monkeypatch) -> None:
    items = [{"type": "text", "text": "hi", "page_idx": 0}]
    seen = _fake_mineru(monkeypatch, items)
    (tmp_path / "middle_json.json").write_text('{"x": 1}', encoding="utf-8")
    assert mineru4.load_content_list(tmp_path) == items
    assert seen["json"] == '{"x": 1}'
    assert not list(tmp_path.glob("*_content_list.json"))  # nothing written back


def test_load_content_list_4x_without_mineru_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "mineru", None)
    (tmp_path / "middle_json.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="pip install mineru"):
        mineru4.load_content_list(tmp_path)


def test_load_content_list_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="middle_json.json"):
        mineru4.load_content_list(tmp_path)


def test_discover_generated_output_dirs_finds_4x_results(tmp_path: Path) -> None:
    (tmp_path / "book" / "auto").mkdir(parents=True)
    (tmp_path / "book" / "auto" / "middle_json.json").write_text("{}", encoding="utf-8")
    assert cli._discover_generated_output_dirs(tmp_path) == [tmp_path / "book" / "auto"]


def test_local_command_2x_keeps_dash_p_for_input() -> None:
    cmd = cli._local_command("/bin/mineru", ["-b", "pipeline"], Path("in.pdf"), Path("out"))
    assert cmd == ["/bin/mineru", "-b", "pipeline", "-p", "in.pdf", "-o", "out"]


def test_local_command_kit_uses_parse_subcommand_and_zip() -> None:
    cmd = cli._local_command("/bin/mineru-kit", ["--tier", "standard"], Path("in.pdf"), Path("out"))
    assert cmd[:2] == ["/bin/mineru-kit", "parse"]
    assert "-p" not in cmd
    assert cmd[-1] == "in.pdf"
    assert cmd[cmd.index("-f") + 1] == "zip"
    assert Path(cmd[cmd.index("-o") + 1]) == Path("out") / "result.zip"


def test_unpack_kit_zips_extracts_next_to_archive(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "result.zip", "w") as zf:
        zf.writestr("middle_json.json", "{}")
        zf.writestr("images/a.png", b"png")
    cli._unpack_kit_zips(tmp_path)
    assert not (tmp_path / "result.zip").exists()
    assert (tmp_path / "result" / "images" / "a.png").exists()
    assert cli._discover_generated_output_dirs(tmp_path) == [tmp_path / "result"]


def test_prepare_with_kit_executable_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """Fake `mineru-kit` writes a zip; the result lands in mineru_root as <uid>_full."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF")
    root = tmp_path / "mineru"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        with zipfile.ZipFile(cmd[cmd.index("-o") + 1], "w") as zf:
            zf.writestr("middle_json.json", "{}")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    config = types.SimpleNamespace(mineru_root=root)
    local = types.SimpleNamespace(executable="mineru-kit", args=[], sources={"book": str(pdf)})
    cli._do_local_toolchain_prepare(config, local)
    assert (root / "book_full" / "middle_json.json").exists()
    assert calls[0][1] == "parse"


def test_prepare_hints_mineru_kit_when_4x_rejects_dash_p(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "No such option: -p"),
    )
    config = types.SimpleNamespace(mineru_root=tmp_path / "mineru")
    local = types.SimpleNamespace(executable="mineru", args=[], sources={"book": str(pdf)})
    with pytest.raises(RuntimeError, match="mineru-kit"):
        cli._do_local_toolchain_prepare(config, local)


def test_real_4x_middle_json_renders_content_list(tmp_path: Path) -> None:
    """tests/data/mineru4_middle_json.json is real `mineru-kit parse` output of a synthetic page."""
    pytest.importorskip("mineru")
    data = Path(__file__).parent / "data" / "mineru4_middle_json.json"
    (tmp_path / "middle_json.json").write_bytes(data.read_bytes())
    items = mineru4.load_content_list(tmp_path)
    assert [i["type"] for i in items] == ["text", "text", "chart"]
    assert items[0]["text"] == "Chapter 1 Introduction"
    assert items[0]["text_level"] == 2
    assert items[2]["img_path"] == "images/page_0_chart_2.jpg"
    assert items[2]["chart_footnote"] == ["Figure 1 Synthetic bar chart"]
