# AGENTS.md

这份说明给在 MineruPress 仓库中协作的 coding agent 使用。目标不是记录某个开发者的本地习惯，而是帮助 agent 正确支持两类任务：

- 使用者：安装 MineruPress，创建图书工作区，把 MinerU 结果导出成 MkDocs Material 站点。
- 贡献者：修改 MineruPress 工具链、文档、模板、测试、发布流程。

## 项目定位

MineruPress 是通用的 `MinerU -> Markdown -> MkDocs Material` 图书发布工具链。

核心流程：

1. 从 `book.yml` 读取图书配置、来源模式、逻辑分册 UID、章节边界、插件列表和可选部署配置。
2. 按 `source` 准备或读取 MinerU 输出。
3. 从 `resources/mineru/` 下读取 `*_content_list.json` 和图片；同一个逻辑 UID 可以对应多个拆分 part。
4. 按章节边界导出 Markdown 到 `docs/chapters/`，图片复制到 `docs/images/`。
5. 可选插件处理图片、文本、整章后处理和导出完成后的部署。

## 正确使用工作流

普通用户优先使用发布包，不需要 clone 工具链仓库（`[all]` 已包含 `mkdocs>=1.6,<2` 和 `mkdocs-material>=9.5,<10`；只要站点依赖可以装 `minerupress[site]`）：

```bash
pip install "minerupress[all]"
minerupress init my-book
cd my-book
```

每个图书工作区只选择一种来源模式：

- `uploaded_result`：已有 MinerU 解析结果。模板默认模式，把结果放到 `resources/mineru/` 后运行 `minerupress export book.yml`。
- `official_api`：从 PDF 走 MinerU 官方 API。配置 `api.sources` 和 `MINERU_API_TOKEN` 后运行 `minerupress fetch book.yml`。
- `local_toolchain`：调用用户单独安装的本地 `mineru` CLI。配置 `local_toolchain.sources` 后运行 `minerupress fetch book.yml`。

`local_toolchain` 是外部可选能力。MineruPress 不内置 MinerU，也不应把 MinerU 作为强依赖；安装方式和 CLI 参数以 MinerU 官方文档为准。

稳定跑书通常分两轮：

1. 准备来源，拿到 `resources/mineru/`。
2. 运行 `minerupress headings resources/mineru --volume-uid <uid> --format yaml --body-only`，根据真实标题结构修 `chapters`。
3. 运行 `minerupress export book.yml`。
4. 运行 `minerupress nav book.yml --check` 确认 `mkdocs.yml` 的 nav 没漏章节（`mkdocs build --strict` 对 nav 漏章只给 INFO）。
5. 运行 `mkdocs build --strict`。
6. 需要留痕时运行 `minerupress fingerprint --docs-dir docs --out reports/fingerprints.json`。

## 贡献者工作流

只有在修改 MineruPress 自身时才使用源码安装：

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

如果本地没有测试依赖，至少运行 `python -m compileall minerupress`，并在交付说明中明确说明哪些验证没有执行。

## 主要目录

- `minerupress/`：Python 包源码。
- `minerupress/core.py`：导出引擎，负责分册发现、章节边界查找、item 转 Markdown、图片复制和插件 hook。
- `minerupress/loader.py`：解析 `book.yml`，组装 `BookConfig`、插件实例和 `SourceConfig`。
- `minerupress/cli.py`：统一 CLI 入口，支持 `minerupress init|export|fetch|headings|nav|fingerprint`，并兼容旧命令。
- `minerupress/nav.py`：根据 `book.yml` 章节生成 `mkdocs.yml` 的 nav 片段，检查现有 nav 是否漏章、指向不存在的章节或顺序不一致；只读，不改写 `mkdocs.yml`。
- `minerupress/api_client.py`：MinerU API 客户端，包含上传、轮询、下载和 PDF 分片。
- `minerupress/fingerprint.py`：对 `docs/` 下 Markdown 生成 SHA-256 指纹并输出差异。
- `minerupress/plugins/`：内置插件和 `ExportPlugin` 基类。
- `book_template/`：仓库内的新书模板副本。
- `minerupress/book_template/`：随 PyPI 包发布的模板副本，供 `minerupress init` 复制。
- `docs/`：项目文档，不是某一本书的生成目录。
- `skills/minerupress/`：给外部 AI agent 安装的 MineruPress Skill。

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

## `book.yml` 约定

关键字段：

- `source`：`uploaded_result`、`official_api` 或 `local_toolchain`。
- `mineru_root`：MinerU 输出根目录，默认 `resources/mineru`。
- `docs_out`：MkDocs 文档目录，默认 `docs`。
- `volume_uid`：顶层默认逻辑分册 UID。章节不写 `volume_uid` 时继承它。
- `toc_max_page`：查找每个逻辑 UID 的第一个章节边界时跳过的目录页阈值；`0` 表示不跳过。
- `allow_missing_boundaries`：默认 `false`。严格模式下任一章节边界缺失会失败。
- `page_footnotes`：默认 `skip`。设为 `paragraph` 时把以脚注标记开头的 `page_footnote` 作为引用块放在所在页最后一个完整段落之后。
- `plugins`：内置插件名或自定义插件 dotted import 路径。需要传参时写成单键映射，例如 `- qr_filter: {max_side: 250}`（块写法为 `- qr_filter:` 下缩进 `max_side: 250`）；纯字符串写法继续可用。`cf_pages` 仍从 `deploy:` 段取参数，写在插件项里的同名参数优先。参数名不被插件的 `__init__` 接受时加载会报错。
- `chapters`：章节列表，必须包含 `slug` 和 `title`。

`volume_uid` 是 MinerU 输出目录名的可匹配前缀，不一定是完整 UUID。单 PDF 自动拆分后会形成 `volume_uid_part1`、`volume_uid_part2` 等目录，章节仍使用同一个逻辑 `volume_uid`。

章节边界优先从 `title` 自动推导；只有 MinerU 标题异常、目录页抢先命中或存在歧义时，再写 `aliases`、`start_pattern` 或 `start_patterns`。

所有相对路径按 `book.yml` 所在目录解析，不依赖调用命令时的当前工作目录。

## 插件开发约定

插件继承 `minerupress.plugins.base.ExportPlugin`，按需覆盖：

- `on_image(item, img_path) -> bool`：返回 `False` 丢弃图片。
- `on_text(item, text) -> str`：处理文本、caption、alt 等。
- `on_chapter_done(slug, lines) -> list[str]`：整章后处理。
- `on_export_done(docs_out) -> None`：导出完成后的副作用，例如部署。

新增内置插件时：

1. 放在 `minerupress/plugins/`。
2. 在 `loader.py` 的 `_BUILTIN_PLUGINS` 注册短名。
3. 如需公开导入，再更新 `minerupress/plugins/__init__.py` 或 `minerupress/__init__.py`。
4. 更新 README、`docs/`、模板 `book.yml`、`AGENTS.md` 和 `skills/minerupress/`。

插件应尽量容错：缺可选依赖或运行时出错时警告（同一问题只警告一次）并退化为 no-op/返回原文，避免让普通导出流程崩掉。`cjk_spacing` 同时兼容 pangu 4.x 的 `spacing_text` 与 6.x 的 `space_text`。`qr_filter` 丢弃图片时会逐行打印文件名和尺寸；它不依赖图注文字，不要把某本书的标签（如“课件”“源代码”）写进插件。

## 代码与文档风格

- 使用标准库 `pathlib.Path` 处理路径。
- 保持现有 dataclass 配置风格，不为简单字段引入重型配置框架。
- 导出引擎应尽量保持书籍无关；书籍差异放在 `book.yml` 或插件中。
- 不要把特定教材的清洗规则写死进 `core.py`。
- 对会触发网络、上传、部署或大量生成文件的命令保持克制，先确认用户意图。
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
