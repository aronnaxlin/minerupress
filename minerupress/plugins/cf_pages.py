"""
minerupress.plugins.cf_pages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Post-export plugin that deploys the built MkDocs site to Cloudflare Pages
via `wrangler pages deploy`.

Configuration (book.yml)
------------------------
plugins:
  - cf_pages

deploy:
  pages_project: my-book          # required — CF Pages project name
  site_dir: site                  # optional, default: site
  branch: main                    # optional, default: main
  wrangler_cmd: npx wrangler      # optional, default: npx wrangler

Environment variables (the CLI loads .env from the book.yml directory)
----------------------------------------------------------------------
CLOUDFLARE_ACCOUNT_ID   — required by wrangler
CLOUDFLARE_API_TOKEN    — required by wrangler
PAGES_PROJECT           — fallback if deploy.pages_project not set in book.yml

The plugin runs `mkdocs build` then `wrangler pages deploy` once, after all
chapters have been written, by hooking into on_export_done().  It is a no-op
if CLOUDFLARE_API_TOKEN is not set (so local dev runs are unaffected).
If the Pages project does not exist yet, the plugin creates it and retries.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from .base import ExportPlugin


class CloudflarePagesPlugin(ExportPlugin):
    def __init__(
        self,
        pages_project: str = "",
        site_dir: str = "site",
        branch: str = "main",
        wrangler_cmd: str = "npx wrangler",
        project_dir: Path | str = ".",
    ) -> None:
        self.pages_project = pages_project or os.environ.get("PAGES_PROJECT", "")
        self.site_dir = site_dir
        self.branch = branch
        self.wrangler_cmd = shlex.split(wrangler_cmd)
        self.project_dir = Path(project_dir)
        self._deployed = False

    # ExportPlugin hooks are per-item; deployment happens once at the end.
    # The CLI calls on_export_done() after all chapters are written.

    def on_export_done(self, docs_out: Path) -> None:
        """Called by the export engine after all chapters are written."""
        if self._deployed:
            return

        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        if not api_token:
            print(
                "  [cf_pages] CLOUDFLARE_API_TOKEN not set — skipping deploy.",
                file=sys.stderr,
            )
            return

        if not self.pages_project:
            print(
                "  [cf_pages] pages_project not configured — skipping deploy.\n"
                "  Set deploy.pages_project in book.yml or PAGES_PROJECT env var.",
                file=sys.stderr,
            )
            return

        self._build_site()
        self._deploy()
        self._deployed = True

    # ------------------------------------------------------------------

    def _build_site(self) -> None:
        print("  [cf_pages] building site with mkdocs …")
        result = subprocess.run(
            ["mkdocs", "build", "--strict"],
            check=False,
            cwd=self.project_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"mkdocs build failed (exit {result.returncode}). "
                "Fix build errors before deploying."
            )

    def _deploy(self) -> None:
        site_path = Path(self.site_dir)
        site_path = site_path if site_path.is_absolute() else self.project_dir / site_path
        if not site_path.exists():
            raise RuntimeError(
                f"Site directory '{self.site_dir}' not found. "
                "Run mkdocs build first."
            )

        cmd = [
            *self.wrangler_cmd,
            "pages", "deploy", str(site_path),
            "--project-name", self.pages_project,
            "--branch", self.branch,
            "--commit-dirty=true",
        ]
        print(f"  [cf_pages] deploying to project '{self.pages_project}' …")
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        if result.returncode != 0 and self._is_missing_project(result):
            print(
                f"  [cf_pages] project '{self.pages_project}' not found; creating …"
            )
            self._create_project()
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                cwd=self.project_dir,
            )
        if result.returncode != 0:
            raise RuntimeError(
                "wrangler pages deploy failed "
                f"(exit {result.returncode}).\n{self._output(result)}"
            )
        print(f"  [cf_pages] deployed → {self.pages_project} ({self.branch})")

    def _create_project(self) -> None:
        cmd = [
            *self.wrangler_cmd,
            "pages", "project", "create", self.pages_project,
            "--production-branch", self.branch,
        ]
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        if result.returncode != 0 and not self._is_existing_project(result):
            raise RuntimeError(
                "wrangler pages project create failed "
                f"(exit {result.returncode}).\n{self._output(result)}"
            )
        print(f"  [cf_pages] project ready → {self.pages_project}")

    @staticmethod
    def _output(result: subprocess.CompletedProcess) -> str:
        return "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )

    @classmethod
    def _is_missing_project(cls, result: subprocess.CompletedProcess) -> bool:
        output = cls._output(result).lower()
        return (
            "project not found" in output
            or "could not find" in output
            or "does not exist" in output
        )

    @classmethod
    def _is_existing_project(cls, result: subprocess.CompletedProcess) -> bool:
        output = cls._output(result).lower()
        return (
            "already exists" in output
            or "project exists" in output
            or "name has already been taken" in output
        )
