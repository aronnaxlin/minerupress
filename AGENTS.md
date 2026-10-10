# AGENTS.md

这份说明给在 MineruPress 仓库里修改工具链的 coding agent 使用：Python 包、内置模板、文档、测试和发布流程。

怎样用 MineruPress 跑一本书（安装、建工作区、配置 `book.yml`、导出、排障）不在这里，见 `skills/minerupress/`。

## 项目定位

MineruPress 是通用的 `MinerU -> Markdown -> MkDocs Material` 图书发布工具链。

核心流程：

1. 从 `book.yml` 读取图书配置、来源模式、逻辑分册 UID、章节边界、插件列表和可选部署配置。
2. 按 `source` 准备或读取 MinerU 输出。
3. 从 `resources/mineru/` 下读取 `*_content_list.json` 和图片；同一个逻辑 UID 可以对应多个拆分 part。
4. 按章节边界导出 Markdown 到 `docs/chapters/`，图片复制到 `docs/images/`。
5. 可选插件处理图片、文本、整章后处理和导出完成后的部署。

## 开发环境与检查

```bash
git clone https://github.com/aronnaxlin/minerupress.git
cd minerupress
pip install -e ".[dev,all]"
```

修改后至少运行：

```bash
python -m compileall minerupress
pytest
```

CI（`ci.yml`，PR 时运行，发布前由 `release.yml` 调用）跑两种安装：只装 `.[dev]` 的矩阵（Python 3.11、3.12）和装 `.[dev,all]` 的 `test-extras`。两种都必须通过，所以依赖可选包（`cv2`、`numpy`、`pangu`、`mkdocs`）的测试要用 `pytest.importorskip` 跳过，不能在模块顶部直接 import。

如果本地没有测试依赖，至少运行 `python -m compileall minerupress`，并在交付说明中明确说明哪些验证没有执行。

## 版本号与发布

- 版本号只存在于 git tag（`vX.Y.Z`）。`pyproject.toml` 里的 `0.0.0.dev0` 是占位值，不要手动改，也不要提交“bump version”之类的改动。
- 每次推送到 `main`（包括合并 PR）都会在测试通过后自动发布下一个 patch 版本到 GitHub Release 和 PyPI。PyPI 上的版本号不能重用，所以合并前要确认改动可以发布。
- 不想触发发布时，在最新提交的标题里写 `[skip release]`。
- minor / major 版本通过手动推送 `vX.Y.Z` tag 发布。
- 细节见 `docs/guide/release.md`，实现在 `.github/workflows/release.yml`、`scripts/next-version.sh` 和 `scripts/stamp-version.py`。

## 主要目录

- `minerupress/`：Python 包源码。
- `minerupress/core.py`：导出引擎，负责分册发现、章节边界查找、item 转 Markdown、图片复制和插件 hook。
- `minerupress/loader.py`：解析 `book.yml`，组装 `BookConfig`、插件实例和 `SourceConfig`。
- `minerupress/cli.py`：统一 CLI 入口，支持 `minerupress init|export|fetch|headings|nav|fingerprint`，并兼容旧命令。
- `minerupress/headings.py`：`minerupress headings`，从正文标题和页眉里找章节候选并输出 `chapters` YAML。
- `minerupress/nav.py`：根据 `book.yml` 章节生成 `mkdocs.yml` 的 nav 片段，检查现有 nav 是否漏章、指向不存在的章节或顺序不一致；只读，不改写 `mkdocs.yml`。
- `minerupress/api_client.py`：MinerU API 客户端，包含上传、轮询、下载和 PDF 分片。
- `minerupress/fingerprint.py`：对 `docs/` 下 Markdown 生成 SHA-256 指纹并输出差异。
- `minerupress/plugins/`：内置插件和 `ExportPlugin` 基类。
- `book_template/`：仓库内的新书模板副本。
- `minerupress/book_template/`：随 PyPI 包发布的模板副本，供 `minerupress init` 复制。
- `docs/`：项目文档，不是某一本书的生成目录。
- `skills/minerupress/`：给外部 AI agent 安装的 Skill，只讲用户怎样跑书，不讲开发。
- `tests/`：pytest 测试，只用合成数据。
- `scripts/`：发布用的脚本（计算下一个版本号、把版本号写进 `pyproject.toml`）。

## 仓库边界

这个仓库是工具链。真实图书工作区、源 PDF、MinerU 输出、站点构建结果和敏感配置不要提交进工具链仓库，除非用户明确要求维护的是某个独立图书仓库。

通常不要提交：

- `.env`
- `resources/`
- `site/`
- `reports/`
- `.wrangler/`
- 临时图书运行目录

注意：项目文档使用的 `docs/` 是仓库文档目录；新书工作区中的 `docs/` 是生成/维护站点内容的目录。不要把两者混淆。

## 配置语义

`book.yml` 各字段的用法写在 `docs/guide/configuration.md` 和 Skill 的 `references/book-yml.md` 里。改代码时要保持的语义：

- 所有相对路径按 `book.yml` 所在目录解析，不依赖调用命令时的当前工作目录。
- `volume_uid` 是 `mineru_root` 下目录名的前缀，不一定是完整 UUID。单 PDF 拆分后是 `uid_part1`、`uid_part2`，单个结果是 `uid_full`，章节始终使用同一个逻辑 `volume_uid`。
- 默认严格：`allow_missing_boundaries` 为 `false`，任一章节边界缺失都失败。
- 新增选项的默认值不能改变已有图书的输出。
- 插件项可以是字符串，也可以是带参数的单键映射；参数名不被插件的 `__init__` 接受时加载报错。`cf_pages` 仍从 `deploy:` 段取参数，插件项里的同名参数优先。

新增一个 `book.yml` 字段要改的地方：`core.py` 或 `loader.py` 里的 dataclass、`load_book_config` 的解析和 docstring、两份模板的 `book.yml` 注释，以及“行为变更时要同步的地方”列出的文档。

## 插件开发约定

插件继承 `minerupress.plugins.base.ExportPlugin`，按需覆盖：

- `on_image(item, img_path) -> bool`：返回 `False` 丢弃图片。
- `on_text(item, text) -> str`：处理文本、caption、alt 等。
- `on_chapter_done(slug, lines) -> list[str]`：整章后处理。
- `on_export_done(docs_out) -> None`：导出完成后的副作用，例如部署。

`on_text` 拿到的是 MinerU 原文，`<`、`>` 和类链接文本的转义在它之后进行；`on_image` 也会收到带 `img_path` 的 `chart` 条目。

新增内置插件时：

1. 放在 `minerupress/plugins/`。
2. 在 `loader.py` 的 `_BUILTIN_PLUGINS` 注册短名。
3. 如需公开导入，再更新 `minerupress/plugins/__init__.py` 或 `minerupress/__init__.py`。
4. 更新 README、`docs/`、模板 `book.yml`、`AGENTS.md` 和 `skills/minerupress/`。

插件应尽量容错：缺可选依赖或运行时出错时警告（同一问题只警告一次）并退化为 no-op/返回原文，避免让普通导出流程崩掉。`cjk_spacing` 同时兼容 pangu 4.x 的 `spacing_text` 与 6.x 的 `space_text`。`qr_filter` 丢弃图片时会逐行打印文件名和尺寸；它不依赖图注文字，不要把某本书的标签（如“课件”“源代码”）写进插件。

## 测试约定

- 测试一律用合成数据，新行为配新测试。
- 不在测试里调用 MinerU API；`tests/test_fetch.py` 演示了怎样替换客户端的网络方法。
- 合成数据只能证明代码符合作者对 MinerU 输出的假设，而这些假设出过错（字段名、条目类型、章号出现的位置）。改动涉及条目转换或边界查找时，还要拿一份真实的 MinerU 输出验证：工作区放在仓库外，`docs_out` 指到临时目录，对比改动前后每章的条目数、`Items by type` 统计和章节文件的 diff。
- 真实图书的数据不进仓库。验证中发现的问题用最小的合成数据在 `tests/` 里复现。

## 行为变更时要同步的地方

用户能观察到的行为变了，以下内容要一起更新：

- `README.md` 和 `docs/README_EN.md`
- `docs/guide/` 下对应的页面
- 两份模板（`book.yml` 注释、`mkdocs.yml`、`Makefile`）
- `load_book_config` 的 docstring
- 本文件
- `skills/minerupress/`：只更新用户会用到的部分，开发细节留在本文件

## 代码与文档风格

- 使用标准库 `pathlib.Path` 处理路径。
- 保持现有 dataclass 配置风格，不为简单字段引入重型配置框架。
- 导出引擎应尽量保持书籍无关；书籍差异放在 `book.yml` 或插件中。
- 不要把特定教材的清洗规则写死进 `core.py`。
- 会触发网络、上传、部署或删除的行为要能从命令名预料到，并在文档里写明。开发和测试时不要真的去上传或部署。
- 用户文档先讲发布包和 `minerupress init`，再讲贡献者源码安装。
- CLI 主流程统一使用 `minerupress <subcommand>`；旧入口只作为兼容说明出现。

## 当前实现注意事项

- `book_template/` 和 `minerupress/book_template/` 需要保持同步；修改模板时同步两处，并运行相关测试。
- `book_template/Makefile` 是给新书工作区使用的，不代表仓库根目录有 `make` 工作流。
- `api_client.fetch()` 返回 `list[Path]`，顺序必须与原始 PDF chunk 顺序一致。
- `minerupress fetch` 会按 `source` 准备内容后自动导出。
- `minerupress export --fetch` 是兼容/便捷入口；用户文档主流程优先讲清楚 `fetch` 和 `export` 的区别。
- `core.export()` 会根据 UID 前缀在 `mineru_root` 下自动发现一个或多个分册目录，并按自然顺序顺推章节边界。
- `core.export()` 每次都会重建 `docs/chapters/` 和 `docs/images/`，不要在这些目录里放手工长期维护内容。
- `core.export()` 找不到章节边界时抛 `BoundaryNotFoundError`；CLI 捕获后给出下一步提示并以非零退出，不打印 traceback。
- 章节边界按三级回退查找：强模式（显式 `start_pattern`、完整标题、章号+章名）→ 只有章号的整行 → 只有章名且带 `text_level` 的整行；用到回退时打印 `[NOTE]`。
- 多个 `volume_uid` 命中同一目录时取最长前缀。
- `official_api` 的续跑状态在工作区的 `.minerupress/fetch-state.json`；`minerupress fetch --force` 忽略它并重新上传。
- 工作区 `.env` 由 CLI 在加载 `book.yml` 之前读取（先 `book.yml` 所在目录，再当前目录，不覆盖已有环境变量）；直接调用 `load_book_config` 的库用户需要自己加载。
- 图片类条目包括 `image` 和带 `img_path` 的 `chart`，都会走 `on_image`；caption/footnote 同时兼容 `image_*` 和 `img_*` 字段名。
- 导出完成后 CLI 会用 `nav.warn_if_nav_drift` 检查 `mkdocs.yml` 的章节 nav，只警告、不改写。
