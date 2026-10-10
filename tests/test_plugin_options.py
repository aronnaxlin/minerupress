from pathlib import Path

import pytest
import yaml

from minerupress.loader import load_book_config
from minerupress.plugins.base import ExportPlugin
from minerupress.plugins.cf_pages import CloudflarePagesPlugin
from minerupress.plugins.cjk_spacing import CJKSpacingPlugin
from minerupress.plugins.qr_filter import QRFilterPlugin


class OptionPlugin(ExportPlugin):
    def __init__(self, label: str = "default", *, flag: bool = False) -> None:
        self.label = label
        self.flag = flag


class KwargsPlugin(ExportPlugin):
    def __init__(self, **options) -> None:
        self.options = options


def _load(tmp_path: Path, plugins, **extra):
    book = {
        "volume_uid": "demo",
        "chapters": [{"slug": "ch01", "title": "第1章 概述"}],
        "plugins": plugins,
        **extra,
    }
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(yaml.safe_dump(book, allow_unicode=True), encoding="utf-8")
    return load_book_config(book_yml)[1]


def test_plain_string_entries_still_work(tmp_path: Path) -> None:
    plugins = _load(tmp_path, ["qr_filter", "cjk_spacing"])

    assert isinstance(plugins[0], QRFilterPlugin)
    assert plugins[0].max_side == 250
    assert isinstance(plugins[1], CJKSpacingPlugin)


def test_single_key_mapping_passes_options(tmp_path: Path) -> None:
    plugins = _load(tmp_path, [{"qr_filter": {"max_side": 180}}, "cjk_spacing"])

    assert isinstance(plugins[0], QRFilterPlugin)
    assert plugins[0].max_side == 180
    assert isinstance(plugins[1], CJKSpacingPlugin)


def test_mapping_without_options_is_allowed(tmp_path: Path) -> None:
    plugins = _load(tmp_path, [{"qr_filter": None}])

    assert plugins[0].max_side == 250


def test_yaml_block_style_from_docs_parses(tmp_path: Path) -> None:
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(
        "volume_uid: demo\n"
        "chapters:\n  - slug: ch01\n    title: 第1章 概述\n"
        "plugins:\n"
        "  - qr_filter:\n"
        "      max_side: 300\n"
        "  - cjk_spacing\n",
        encoding="utf-8",
    )

    plugins = load_book_config(book_yml)[1]

    assert [type(p) for p in plugins] == [QRFilterPlugin, CJKSpacingPlugin]
    assert plugins[0].max_side == 300


def test_empty_plugins_value_is_allowed(tmp_path: Path) -> None:
    assert _load(tmp_path, None) == []


def test_dotted_plugin_receives_options(tmp_path: Path) -> None:
    dotted = f"{__name__}.OptionPlugin"

    plugins = _load(tmp_path, [{dotted: {"label": "custom", "flag": True}}, dotted])

    assert (plugins[0].label, plugins[0].flag) == ("custom", True)
    assert (plugins[1].label, plugins[1].flag) == ("default", False)


def test_dotted_plugin_with_var_keyword_accepts_any_option(tmp_path: Path) -> None:
    plugins = _load(tmp_path, [{f"{__name__}.KwargsPlugin": {"anything": 1}}])

    assert plugins[0].options == {"anything": 1}


def test_unknown_option_name_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as exc:
        _load(tmp_path, [{"qr_filter": {"max_sid": 250}}])

    message = str(exc.value)
    assert "qr_filter" in message and "max_sid" in message and "max_side" in message


def test_options_for_option_less_plugin_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cjk_spacing.*takes no options"):
        _load(tmp_path, [{"cjk_spacing": {"enabled": True}}])


@pytest.mark.parametrize(
    "entry",
    [
        {"qr_filter": {"max_side": 1}, "cjk_spacing": None},
        {"qr_filter": 250},
        ["qr_filter"],
        42,
    ],
)
def test_malformed_entries_are_rejected(tmp_path: Path, entry) -> None:
    with pytest.raises(ValueError):
        _load(tmp_path, [entry])


def test_unknown_plugin_name_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown plugin 'qr_fliter'"):
        _load(tmp_path, ["qr_fliter"])


def test_cf_pages_still_reads_deploy_block(tmp_path: Path) -> None:
    plugins = _load(
        tmp_path,
        ["cf_pages"],
        deploy={"pages_project": "my-book", "site_dir": "out", "branch": "prod"},
    )

    plugin = plugins[0]
    assert isinstance(plugin, CloudflarePagesPlugin)
    assert (plugin.pages_project, plugin.site_dir, plugin.branch) == ("my-book", "out", "prod")
    assert plugin.project_dir == tmp_path.resolve()


def test_cf_pages_inline_options_override_deploy_block(tmp_path: Path) -> None:
    plugins = _load(
        tmp_path,
        [{"cf_pages": {"branch": "preview"}}],
        deploy={"pages_project": "my-book", "branch": "main"},
    )

    assert (plugins[0].pages_project, plugins[0].branch) == ("my-book", "preview")
