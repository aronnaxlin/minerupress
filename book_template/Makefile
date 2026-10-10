PYTHON     := python3
DOCS_OUT   := docs
REPORTS    := reports

.PHONY: all export fetch nav nav-check lint fmt-check fingerprint serve build deploy clean help

all: build

## export: Run minerupress export with book.yml
export:
	minerupress export book.yml

## fetch: Prepare the configured source, then export
fetch:
	minerupress fetch book.yml

## nav: Print the chapter nav for mkdocs.yml from book.yml
nav:
	minerupress nav book.yml

## nav-check: Fail when the mkdocs.yml nav and book.yml chapters differ
nav-check:
	minerupress nav book.yml --check

## lint: Run markdownlint-cli2 on all docs
lint:
	markdownlint-cli2 "docs/**/*.md"

## fmt-check: Check Markdown formatting with mdformat
fmt-check:
	mdformat --check docs/chapters/

## fmt: Auto-fix Markdown formatting with mdformat
fmt:
	mdformat docs/chapters/

## fingerprint: Generate/diff SHA-256 fingerprints for docs/
fingerprint:
	minerupress fingerprint --docs-dir $(DOCS_OUT) --out $(REPORTS)/fingerprints.json

## serve: Start MkDocs dev server (mkdocs ships with `pip install "minerupress[all]"`)
serve:
	mkdocs serve

## build: Build static site
build:
	mkdocs build --strict

## deploy: Build and deploy to Cloudflare Pages
## Set PAGES_PROJECT to your project name before running.
deploy: build
	-npx wrangler pages project create $(PAGES_PROJECT) --production-branch main
	npx wrangler pages deploy site --project-name $(PAGES_PROJECT) --branch main --commit-dirty=true

## clean: Remove generated docs/chapters, docs/images, site/, reports/
clean:
	rm -rf docs/chapters docs/images site $(REPORTS)/fingerprints.json

## help: Show this help
help:
	@grep -E '^##' Makefile | sed 's/## /  /'
