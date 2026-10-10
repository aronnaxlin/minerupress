"""
minerupress.cli
~~~~~~~~~~~~~~~~~~~
Unified CLI entry points for MineruPress.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Sequence

from .core import export
from .loader import SourceConfig, load_book_config


def _do_official_api_prepare(config, api_cfg) -> None:
    """Upload PDFs via MinerU API and populate mineru_root."""
    from .api_client import MinerUClient

    kwargs = {}
    if api_cfg.token:
        kwargs["token"] = api_cfg.token

    client = MinerUClient(
        enable_formula=api_cfg.enable_formula,
        enable_table=api_cfg.enable_table,
        model_version=api_cfg.model_version,
        **kwargs,
    )

    if not api_cfg.sources:
        raise ValueError(
            "api.sources is empty. "
            "Add volume_uid -> pdf_path entries under 'api.sources' in book.yml."
        )

    config.mineru_root.mkdir(parents=True, exist_ok=True)
    for uid, pdf_str in api_cfg.sources.items():
        pdf_path = Path(pdf_str)
        if not pdf_path.exists():
            raise FileNotFoundError(f"API source PDF not found: {pdf_path}")
        out_dirs = client.fetch(pdf_path=pdf_path, dest=config.mineru_root)
        if not out_dirs:
            raise RuntimeError(f"MinerU fetch returned no output directories for {pdf_path}")
        # Rename every fetched segment so core.export can discover all parts by
        # the logical volume_uid prefix used by book.yml chapters.
        out_dir_resolved = {p.resolve() for p in out_dirs}
        _clear_existing_uid_outputs(config.mineru_root, uid, out_dir_resolved)
        for i, out_dir in enumerate(out_dirs, 1):
            suffix = f"part{i}" if len(out_dirs) > 1 else "full"
            target = config.mineru_root / f"{uid}_{suffix}"
            if out_dir.resolve() == target.resolve():
                continue
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            out_dir.rename(target)
            print(f"  [api] renamed -> {target.name}")


def _do_local_toolchain_prepare(config, local_cfg) -> None:
    """Run a user-installed MinerU CLI and normalize its outputs into mineru_root."""
    if not local_cfg.sources:
        raise ValueError(
            "local_toolchain.sources is empty. "
            "Add volume_uid -> local file/dir entries under 'local_toolchain.sources' in book.yml."
        )
    if any(arg in {"-p", "--path", "-o", "--output"} for arg in local_cfg.args):
        raise ValueError(
            "local_toolchain.args must not include -p/--path or -o/--output. "
            "MineruPress appends those automatically."
        )

    executable = shutil.which(local_cfg.executable)
    if executable is None:
        raise RuntimeError(
            "Local MinerU source selected, but the `mineru` CLI was not found.\n"
            "Install MinerU separately, for example:\n"
            '  uv pip install -U "mineru[all]"\n'
            "or clone https://github.com/opendatalab/MinerU and run:\n"
            "  uv pip install -e .[all]\n"
            "For lighter installs, see:\n"
            "  https://opendatalab.github.io/MinerU/quick_start/extension_modules/"
        )

    config.mineru_root.mkdir(parents=True, exist_ok=True)
    for uid, input_str in local_cfg.sources.items():
        input_path = Path(input_str)
        if not input_path.exists():
            raise FileNotFoundError(f"Local MinerU input not found: {input_path}")

        with tempfile.TemporaryDirectory(prefix=f"minerupress-{uid}-", dir=config.mineru_root) as tmp_dir:
            tmp_root = Path(tmp_dir)
            cmd = [executable, *local_cfg.args, "-p", str(input_path), "-o", str(tmp_root)]
            print(f"  [local] running {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Local MinerU command failed for {input_path} (exit {result.returncode}).\n"
                    f"STDOUT:\n{result.stdout[-2000:]}\n"
                    f"STDERR:\n{result.stderr[-2000:]}"
                )

            out_dirs = _discover_generated_output_dirs(tmp_root)
            if not out_dirs:
                raise RuntimeError(
                    f"Local MinerU produced no *_content_list.json output under {tmp_root}"
                )

            _clear_existing_uid_outputs(config.mineru_root, uid, keep=set())
            for i, out_dir in enumerate(out_dirs, 1):
                suffix = f"part{i}" if len(out_dirs) > 1 else "full"
                target = config.mineru_root / f"{uid}_{suffix}"
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.copytree(out_dir, target)
                print(f"  [local] copied -> {target.name}")


def _do_prepare(config, source_cfg: SourceConfig) -> None:
    if source_cfg.kind == "uploaded_result":
        print("  [source] uploaded_result selected; using existing mineru_root contents")
        return
    if source_cfg.kind == "local_toolchain":
        if source_cfg.local_toolchain is None:
            raise ValueError(
                "source=local_toolchain requires a 'local_toolchain:' block in book.yml."
            )
        _do_local_toolchain_prepare(config, source_cfg.local_toolchain)
        return
    if source_cfg.api is None:
        raise ValueError("source=official_api requires an 'api:' block in book.yml.")
    _do_official_api_prepare(config, source_cfg.api)


def _clear_existing_uid_outputs(
    mineru_root: Path,
    uid: str,
    keep: set[Path],
) -> None:
    part_pattern = re.compile(rf"^{re.escape(uid)}_part\d+$")
    for path in mineru_root.iterdir():
        if path.resolve() in keep:
            continue
        if path.name != f"{uid}_full" and not part_pattern.match(path.name):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _discover_generated_output_dirs(root: Path) -> list[Path]:
    """Collect directories that contain legacy content_list.json output."""
    seen: set[Path] = set()
    found: list[Path] = []
    for json_path in sorted(root.rglob("*_content_list.json"), key=lambda p: str(p.relative_to(root))):
        parent = json_path.parent
        if parent in seen:
            continue
        seen.add(parent)
        found.append(parent)
    return found


def _add_book_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "book_yml",
        nargs="?",
        default="book.yml",
        help="Path to book.yml (default: book.yml)",
    )
    parser.add_argument(
        "--allow-missing-boundaries",
        action="store_true",
        help="Warn instead of failing when a configured chapter boundary is not found.",
    )


def _load_book_runtime(book_yml_arg: str, allow_missing_boundaries: bool):
    book_yml = Path(book_yml_arg)
    if not book_yml.exists():
        print(f"Error: {book_yml} not found.", file=sys.stderr)
        raise SystemExit(1)

    config, plugins, source_cfg = load_book_config(book_yml)
    if allow_missing_boundaries:
        config.allow_missing_boundaries = True
    print(
        f"Loaded: {len(config.chapters)} chapters, {len(plugins)} plugins, "
        f"source={source_cfg.kind}"
    )
    return config, plugins, source_cfg


def _run_export(args: argparse.Namespace) -> int:
    config, plugins, source_cfg = _load_book_runtime(
        args.book_yml,
        args.allow_missing_boundaries,
    )
    if args.fetch:
        _do_prepare(config, source_cfg)
    export(config, plugins)
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    config, plugins, source_cfg = _load_book_runtime(
        args.book_yml,
        args.allow_missing_boundaries,
    )
    _do_prepare(config, source_cfg)
    export(config, plugins)
    return 0


def _run_headings(args: argparse.Namespace) -> int:
    from . import headings

    return headings.main(
        argv=[
            args.mineru_root,
            *([ "--volume-uid", args.volume_uid ] if args.volume_uid else []),
            "--toc-max-page",
            str(args.toc_max_page),
            "--format",
            args.format,
            *(["--body-only"] if args.body_only else []),
            *(["--include-generic"] if args.include_generic else []),
        ],
        prog="minerupress headings",
    )


def _run_fingerprint(args: argparse.Namespace) -> int:
    from . import fingerprint

    return fingerprint.main(
        argv=[
            "--docs-dir",
            args.docs_dir,
            "--out",
            args.out,
        ],
        prog="minerupress fingerprint",
    )


def _run_nav(args: argparse.Namespace) -> int:
    from . import nav

    return nav.run(
        Path(args.book_yml),
        Path(args.mkdocs_yml) if args.mkdocs_yml else None,
        args.check,
    )


def _run_init(args: argparse.Namespace) -> int:
    target = Path(args.directory).expanduser()
    if target.exists() and not target.is_dir():
        print(f"Error: target exists and is not a directory: {target}", file=sys.stderr)
        return 1
    if target.exists() and any(target.iterdir()) and not args.force:
        print(
            f"Error: target directory is not empty: {target}\n"
            "Use --force to merge the template into this directory.",
            file=sys.stderr,
        )
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    template = resources.files("minerupress").joinpath("book_template")
    with resources.as_file(template) as template_path:
        shutil.copytree(template_path, target, dirs_exist_ok=True)

    print(f"Created MineruPress book workspace: {target.resolve()}")
    print("Next steps:")
    print(f"  cd {target}")
    print("  edit book.yml")
    print("  minerupress export book.yml")
    return 0


def _configure_export_parser(parser: argparse.ArgumentParser) -> None:
    _add_book_args(parser)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Prepare the configured source before exporting (official API or local toolchain).",
    )
    parser.set_defaults(handler=_run_export, command="export")


def _configure_fetch_parser(parser: argparse.ArgumentParser) -> None:
    _add_book_args(parser)
    parser.set_defaults(handler=_run_fetch, command="fetch")


def _configure_headings_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("mineru_root", nargs="?", default="resources/mineru")
    parser.add_argument(
        "--volume-uid",
        help="Only inspect segment directories with this prefix.",
    )
    parser.add_argument(
        "--toc-max-page",
        type=int,
        default=20,
        help="Pages below this index are treated as likely table-of-contents pages.",
    )
    parser.add_argument(
        "--format",
        choices=("report", "yaml"),
        default="report",
        help="Output a diagnostic report or book.yml chapter YAML.",
    )
    parser.add_argument(
        "--body-only",
        action="store_true",
        help="Hide heading candidates that look like table-of-contents entries.",
    )
    parser.add_argument(
        "--include-generic",
        action="store_true",
        help="Also show generic MinerU level-1 headings that are not chapters, parts, or appendices.",
    )
    parser.set_defaults(handler=_run_headings, command="headings")


def _configure_fingerprint_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--out", default="reports/fingerprints.json")
    parser.set_defaults(handler=_run_fingerprint, command="fingerprint")


def _configure_nav_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "book_yml",
        nargs="?",
        default="book.yml",
        help="Path to book.yml (default: book.yml)",
    )
    parser.add_argument(
        "--mkdocs-yml",
        help="mkdocs.yml to compare against (default: mkdocs.yml next to book.yml).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare mkdocs.yml nav with the chapters; exit 1 on drift, 2 on errors.",
    )
    parser.set_defaults(handler=_run_nav, command="nav")


def _configure_init_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "directory",
        nargs="?",
        default="my-book",
        help="Directory to create (default: my-book)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Merge the template into an existing non-empty directory.",
    )
    parser.set_defaults(handler=_run_init, command="init")


def build_parser(prog: str = "minerupress") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="MineruPress CLI for initializing, exporting, fetching, heading inspection, nav checks, and fingerprints.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Create a new book workspace from the bundled template.",
        description="Create a new MineruPress book workspace from the bundled template.",
    )
    _configure_init_parser(init_parser)

    export_parser = subparsers.add_parser(
        "export",
        help="Export existing MinerU output to a MineruPress book site.",
        description="Export MinerU content_list.json to a MineruPress book site.",
    )
    _configure_export_parser(export_parser)

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Prepare the configured source, then export.",
        description="Prepare the configured MinerU source, then export a MineruPress book site.",
    )
    _configure_fetch_parser(fetch_parser)

    headings_parser = subparsers.add_parser(
        "headings",
        help="Inspect MinerU output and suggest chapter boundary YAML.",
        description="Inspect MinerU output and suggest chapter boundary YAML.",
    )
    _configure_headings_parser(headings_parser)

    fingerprint_parser = subparsers.add_parser(
        "fingerprint",
        help="Fingerprint docs/ Markdown files.",
        description="Fingerprint docs/ Markdown files.",
    )
    _configure_fingerprint_parser(fingerprint_parser)

    nav_parser = subparsers.add_parser(
        "nav",
        help="Print the chapter nav for mkdocs.yml, or check it against book.yml.",
        description=(
            "Print the mkdocs.yml nav section for the chapters in book.yml, "
            "or with --check report chapters missing from or out of order in mkdocs.yml."
        ),
    )
    _configure_nav_parser(nav_parser)

    return parser


def root_main(argv: Sequence[str] | None = None, *, prog: str = "minerupress") -> int:
    parser = build_parser(prog=prog)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.handler(args)


def _run_parser(
    parser: argparse.ArgumentParser,
    argv: Sequence[str] | None = None,
) -> int:
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    return args.handler(args)


def main() -> None:
    raise SystemExit(root_main())


def export_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minerupress-export",
        description="Export MinerU content_list.json to a MineruPress book site.",
    )
    _configure_export_parser(parser)
    return _run_parser(parser, argv)


def fetch_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minerupress-fetch",
        description="Prepare the configured MinerU source, then export a MineruPress book site.",
    )
    _configure_fetch_parser(parser)
    return _run_parser(parser, argv)


def headings_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minerupress-headings",
        description="Inspect MinerU output and suggest chapter boundary YAML.",
    )
    _configure_headings_parser(parser)
    return _run_parser(parser, argv)


def fingerprint_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minerupress-fingerprint",
        description="Fingerprint docs/ Markdown files.",
    )
    _configure_fingerprint_parser(parser)
    return _run_parser(parser, argv)


def mineru_export_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mineru-export",
        description="Export MinerU content_list.json to a MineruPress book site.",
    )
    _configure_export_parser(parser)
    return _run_parser(parser, argv)


def mineru_fetch_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mineru-fetch",
        description="Prepare the configured MinerU source, then export a MineruPress book site.",
    )
    _configure_fetch_parser(parser)
    return _run_parser(parser, argv)


if __name__ == "__main__":
    main()
