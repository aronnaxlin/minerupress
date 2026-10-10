# 配置详解

`book.yml` 是 MineruPress 的核心配置入口。导出器会把书籍特定差异尽量收敛到这里，而不是写死到代码里。

## 顶层字段

最小示例：

```yaml
source: uploaded_result
mineru_root: resources/mineru
docs_out: docs
volume_uid: javaweb
toc_max_page: 10
allow_missing_boundaries: false

plugins:
  - qr_filter
  - cjk_spacing

chapters:
  - slug: ch01-overview
    title: 第1章 Web开发概述
```

字段说明：

- `source`：来源类型，可选 `uploaded_result`、`official_api`、`local_toolchain`。新模板默认 `uploaded_result`。
- `mineru_root`：MinerU 输出根目录，默认 `resources/mineru`。
- `docs_out`：导出到 MkDocs 的文档目录，默认 `docs`。
- `volume_uid`：顶层默认逻辑分册 UID。章节未单独设置时继承它。
- `toc_max_page`：首次查找章节边界时跳过前几页目录页；`0` 表示不跳过。
- `allow_missing_boundaries`：默认 `false`。任何章节边界缺失都会失败。
- `page_footnotes`：页面脚注的处理方式，默认 `skip`（不输出）。设为 `paragraph` 时保留以脚注标记开头的 `page_footnote`，以引用块形式放在所在页最后一个完整段落之后，详见 [导出流程](export-pipeline.md)。
- `plugins`：插件列表，可以写内置短名或自定义插件 dotted import 路径。需要传参时写成单键映射，例如 `- qr_filter:` 下缩进 `max_side: 250`，详见 [插件系统](plugins.md)。
- `chapters`：章节列表，至少要有 `slug` 和 `title`。

## 章节字段

每个章节支持：

```yaml
chapters:
  - slug: ch01-overview
    title: 第1章 Web开发概述
    volume_uid: javaweb
    toc_max_page: 0
    aliases:
      - 第一章 Web开发概述
      - Chapter 1
    start_pattern: "^第\\s*1\\s*章"
    start_patterns:
      - "^Chapter\\s*1\\b"
```

字段说明：

- `slug`：输出文件名，不带 `.md`。
- `title`：章节显示标题，也是默认边界推导来源。
- `volume_uid`：可选。多逻辑卷时按章节覆盖顶层默认 UID。
- `toc_max_page`：可选。单章覆盖全局目录页过滤阈值。
- `aliases`：章节标题别名，用于补充自动边界推导。
- `start_pattern`：单条正则，兼容旧配置。
- `start_patterns`：多条正则，适合复杂边界控制。

## 章节边界推导规则

如果只写 `title`，MineruPress 会自动生成一组边界匹配模式。当前支持的标题风格包括：

- `第10章 JavaScript`
- `第十章 JavaScript`
- `附录A 习题答案`
- `Chapter 3 Arrays`
- `Chap. 3: Arrays`
- `Unit 1`
- `Lesson IV Modulation`
- `Appendix B Tables`
- `项目二 尚硅谷书城`
- `10.1 JavaScript 简介`

推荐优先级：

1. 只写 `title`
2. 标题存在别名时加 `aliases`
3. 只有在 OCR 或标题异常时再写 `start_pattern` / `start_patterns`

从原始 MinerU 输出起步时，可以先让工具生成草稿：

```bash
minerupress headings resources/mineru --volume-uid javaweb --format yaml --body-only
```

它会优先使用正文页上的独立章号行生成 `start_pattern`，降低目录页 TOC 误匹配的概率，并输出形如 `第7章 减治法` 的完整 `title`。

- 独立的章号行（`第1章`）不论 `text_level` 是几都会识别。
- 章号被 OCR 丢掉的章节，会根据页眉（`type: header`）里的"章号 + 章名"找回：在该章页眉首次出现之前、上一章之后，取文本等于章名（忽略空白）的行作为开篇。
- 章号不连续、重复，或某个 `start_pattern` 在导出时会命中别的行，会在 stderr 给出 `warning:`，不会混进 YAML 正文。

### 分级回退

边界查找不要求 MinerU 把章号和章名放在同一行。每一章依次尝试三级模式，只有更强的一级在剩余范围内找不到时才回退：

1. 强模式：显式 `start_pattern` / `start_patterns`、完整标题、"章号 + 章名"（`第1章 绪论`）。
2. 只有章号的整行（`第1章`）。
3. 只有章名的整行，允许字间空白（`递 推 法`），且这一行必须带 `text_level`（是标题而不是正文段落）。

用到回退时，导出会打印一行 `[NOTE] boundary fallback ...`，包含章节、级别、命中的文本和页码，请据此核对。如果第 2、3 级命中的行在之后还会再出现，会额外打印 `[WARN]`，说明第一个命中可能是某个小节标题或交叉引用，此时用 `start_pattern` 钉住正确的行。

为避免把附录习题答案区的孤立 `第1章`、`Chapter 1`、`10.1` 等误判为正文边界，只有在第 1 级找不到时才会考虑它们；单独一个整数（如 `1 绪论` 里的 `1`）不会作为第 2 级模式。

## `source` 选择

每个工作区推荐只选择一种来源模式：

- `uploaded_result`：已有 MinerU 输出，直接读取 `mineru_root` 下的结果目录。运行 `minerupress export book.yml`。
- `official_api`：从 PDF 通过 MinerU 官方 API 获取解析结果。配置 `api:` 后运行 `minerupress fetch book.yml`。
- `local_toolchain`：从 PDF、图片或 Office 文件调用你单独安装的本地 `mineru` CLI。配置 `local_toolchain:` 后运行 `minerupress fetch book.yml`。

`minerupress export --fetch book.yml` 是便捷入口，会先按当前 `source` 准备来源，再导出；普通文档里优先使用更清楚的 `fetch` 或 `export` 两步。

## 关于 `volume_uid`

`volume_uid` 匹配的是目录名前缀，不要求完整 UUID。比如：

```text
resources/mineru/
├── javaweb_part1/
├── javaweb_part2/
└── javaweb_part3/
```

只要章节使用：

```yaml
volume_uid: javaweb
```

导出器就会把这些物理目录按自然顺序拼接成一个逻辑分册来寻找边界和导出内容。

多个 `volume_uid` 互为前缀时（如 `vol1` 和 `vol10`），目录归属于匹配最长的那个 UID。

只配置一个 `algo3` 时，`algo30_full` 这类无关目录也会因为前缀相同被并入。当 `volume_uid` 已有 `algo3`、`algo3_full`、`algo3_partN` 这样规整的目录，又匹配到其他名字的目录时，导出会打印 `[WARN]` 列出它们；用更长的 `volume_uid`，或把无关目录移出 `mineru_root`。

## `api:` 配置

当 `source: official_api` 时，可直接调用 MinerU 云端 API：

```yaml
api:
  token: ""
  enable_formula: true
  enable_table: true
  model_version: vlm
  poll_timeout: 600
  sources:
    javaweb: resources/pdfs/javaweb.pdf
```

说明：

- `token` 留空时会读取 `MINERU_API_TOKEN`（可写在 `book.yml` 同目录的 `.env` 里）
- `poll_timeout` 是每次 `fetch` 等待解析完成的最长秒数，默认 `600`；超时不会丢任务，重跑 `fetch` 会接着等
- 上传后的批次记录在 `.minerupress/fetch-state.json`，重跑 `fetch` 会续跑；`minerupress fetch --force` 忽略记录并重新上传
- `sources` 的 key 需要和章节使用的 `volume_uid` 对应
- 相对路径同样按 `book.yml` 所在目录解析

## `local_toolchain:` 配置

当 `source: local_toolchain` 时，MineruPress 会调用你单独安装的 `mineru` CLI，再把输出整理成 `mineru_root/<volume_uid>_full` 或 `_partN` 目录。

```yaml
local_toolchain:
  executable: mineru
  args:
    - -b
    - pipeline
  sources:
    javaweb: resources/pdfs/javaweb.pdf
```

说明：

- MineruPress 不内置 MinerU 依赖；本地工具链需要你按 MinerU 官方文档单独安装
- `executable` 默认为 `mineru`
- `args` 只放额外参数；不要自己写 `-p/--path` 或 `-o/--output`
- `sources` 的 key 同样需要和章节使用的 `volume_uid` 对应
- 相对路径同样按 `book.yml` 所在目录解析

常见安装方式：

```bash
uv pip install -U "mineru[all]"
```

MinerU 的安装方式、扩展后端和 CLI 参数以官方文档为准：

- [MinerU Quick Start](https://opendatalab.github.io/MinerU/quick_start/)
- [MinerU Extension Modules](https://opendatalab.github.io/MinerU/quick_start/extension_modules/)
- [MinerU CLI Tools](https://opendatalab.github.io/MinerU/usage/cli_tools/)

## `deploy:` 配置

启用 `cf_pages` 插件时，可以配置：

```yaml
deploy:
  pages_project: my-book
  site_dir: site
  branch: main
  wrangler_cmd: npx wrangler
```

说明：

- `pages_project` 为空时会回退到环境变量 `PAGES_PROJECT`
- `site_dir` 默认为 `site`
- `branch` 默认为 `main`
- `wrangler_cmd` 支持自定义可执行命令

## 路径解析规则

MineruPress 不依赖当前工作目录。`book.yml` 中所有相对路径都会先相对 `book.yml` 所在目录解析，再转成绝对路径。

这包括：

- `source` 相关块里的路径，例如 `local_toolchain.sources`
- `mineru_root`
- `docs_out`
- `api.sources`

这个规则让 CI、本地 shell、AI agent 在不同工作目录下运行时都更稳定。
