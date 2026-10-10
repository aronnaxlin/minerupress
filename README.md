# MineruPress

把 MinerU 解析结果整理成可以发布的 MkDocs Material 图书站点。

MineruPress 适合处理扫描教材、课程讲义、内部手册和长 PDF 知识库迁移：输入 MinerU 生成的 `content_list.json` 与图片，输出按章节拆分的 Markdown、图片资源和可直接部署的静态站点。

![《软件测试方法和技术》示例站点](docs/assets/software-testing-methods-site.png)

英文 README：[docs/README_EN.md](docs/README_EN.md)

## 快速开始

先安装发布包，再用内置模板创建一本独立的新书工作区：

```bash
pip install "minerupress[all]"
minerupress init my-book
cd my-book
mkdocs serve
```

模板默认使用 `source: uploaded_result`，也就是你已经有 MinerU 解析结果。把解析结果放到 `resources/mineru/` 后运行：

```bash
minerupress export book.yml
```

如果你是从 PDF 开始，推荐在 `book.yml` 里选择 `source: official_api`，配置 `api.sources`，然后运行：

```bash
minerupress fetch book.yml
```

标准链路如下：

```text
PDF / Office / 图片
        |
        v
MinerU 官方 API / 外部安装的本地 MinerU CLI / 已上传解析结果
        |
        v
resources/mineru/*_content_list.json 与图片
        |
        v
docs/chapters/*.md 与 docs/images/
        |
        v
MkDocs Material 图书站点
```

## 解决什么问题

- 长 PDF 经 MinerU 解析后，结果通常是一堆 JSON、图片和松散文本；MineruPress 把它们整理成稳定的图书工程。
- 一本书可以被拆成多个 PDF 分片，导出时仍按同一个逻辑分册连续匹配章节。
- 章节边界优先由标题自动推导，减少手写正则；遇到目录页、附录、项目制教材和中英文标题时也能更稳。
- 导出过程可重复执行，每次重建章节 Markdown 和图片目录，避免旧文件混进新站点。
- 插件系统负责二维码过滤、中西文间距、导出后部署等差异化工作，不把某本书的规则写死进核心代码。

## 安装

要求 Python `>=3.11`。

普通使用推荐直接安装 PyPI 发布包：

```bash
pip install "minerupress[all]"
```

`[all]` 已经包含 `qr_filter`、`cjk_spacing` 需要的依赖，以及本地预览和构建站点用的 `mkdocs`、`mkdocs-material`（版本限定在 `mkdocs>=1.6,<2`、`mkdocs-material>=9.5,<10`，避免被 MkDocs 2.0 的不兼容变更影响）。只需要站点依赖时可以装 `minerupress[site]`。

如果你更希望把 CLI 隔离到独立环境，推荐使用 `pipx`：

```bash
pipx install 'minerupress[all]'
pipx inject minerupress mkdocs --include-apps
```

第二条命令只是把已经装进虚拟环境的 `mkdocs` 命令暴露到 `PATH`，不会改动版本。

升级时分别使用：

```bash
pip install -U "minerupress[all]"
```

或：

```bash
pipx upgrade minerupress
pipx inject minerupress mkdocs --include-apps
```

如果你是在开发或修改工具链本身，而不是普通使用，请看后面的“贡献者开发”。

可选依赖：

| 依赖组 | 依赖 | 用途 |
|---|---|---|
| `qr` | `opencv-python` | `qr_filter` 二维码图片过滤 |
| `cjk` | `pangu` | `cjk_spacing` 中西文间距处理 |
| `site` | `mkdocs>=1.6,<2`、`mkdocs-material>=9.5,<10` | `mkdocs serve` / `mkdocs build --strict` 预览和构建站点 |
| `all` | 上面三组 | 常见完整环境 |

## 新书工作区

建议每本书使用独立目录，不要直接把某本书的生成物放进工具链仓库。pip 安装后模板不在当前目录里，直接用 `minerupress init` 生成工作区即可：

```bash
minerupress init ~/dev/my-book/
cd ~/dev/my-book/
```

模板里已经包含：

- `book.yml`：书籍配置、章节列表、来源选择、MinerU API / 本地工具链和部署配置。
- `mkdocs.yml`：MkDocs Material 站点配置。
- `.env.example`：敏感环境变量示例。
- `Makefile`：常用导出、校验、构建命令。

常见工作区结构：

```text
my-book/
  book.yml
  mkdocs.yml
  resources/mineru/
  docs/
  site/
```

`resources/`、`docs/`、`site/` 通常是某本书自己的输入和输出，不应提交到 MineruPress 工具链仓库；如果你在独立图书仓库中维护成品站点，再按那个仓库的规则决定是否纳入版本控制。

## 推荐工作流

新项目只选一种来源模式，不要混用：

| 起点 | `source` | 命令 | 说明 |
|---|---|---|---|
| 已有 MinerU 解析结果 | `uploaded_result` | `minerupress export book.yml` | 模板默认模式，把结果目录放进 `resources/mineru/` |
| 只有 PDF，想走云端 | `official_api` | `minerupress fetch book.yml` | 使用 MinerU 官方 API，抓取后会自动导出 |
| 只有 PDF，想本机解析 | `local_toolchain` | `minerupress fetch book.yml` | 调用你单独安装的 `mineru` CLI，MineruPress 不内置 MinerU |

稳定跑书通常分两轮：

1. 先准备来源，拿到 `resources/mineru/`。
2. 用 `minerupress headings` 看真实标题结构，修好 `chapters`。
3. 再执行 `minerupress export book.yml` 和 `mkdocs build --strict`。

## 常用命令

已有 MinerU 解析结果，直接导出：

```bash
minerupress export book.yml
```

按 `source` 准备来源后导出：

```bash
minerupress fetch book.yml
```

用导出命令先准备来源再导出：

```bash
minerupress export --fetch book.yml
```

`official_api` 模式下，上传后的批次记录在 `.minerupress/fetch-state.json`。下载失败或轮询超时后重跑 `minerupress fetch` 会续跑，不会重新上传；`minerupress fetch --force` 忽略记录并重新上传。详见 [云端抓取与部署](docs/guide/cloud-api-and-deploy.md)。`.env`（`MINERU_API_TOKEN`、`CLOUDFLARE_*`）放在 `book.yml` 同一目录即可，shell 里已有的同名环境变量优先。

分析 MinerU 输出中的正文大标题，生成章节配置草稿：

```bash
minerupress headings resources/mineru --volume-uid javaweb --format yaml --body-only
```

严格构建站点：

```bash
mkdocs build --strict
```

打印章节的 `mkdocs.yml` nav 片段，或检查现有 nav 是否和 `book.yml` 一致（只读，不改写 `mkdocs.yml`）：

```bash
minerupress nav book.yml
minerupress nav book.yml --check
```

`--check` 发现章节没进 nav、nav 指向 `book.yml` 里没有的章节文件、或章节顺序不一致时以非零退出。`mkdocs build --strict` 对 nav 漏掉的页面只给 INFO，不会失败，所以章节增删后建议跑一次。

生成或比对文档指纹：

```bash
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

## `book.yml` 示例

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
  - slug: appendix-a
    title: 附录A 部分习题的解答
```

来源选择：

- `uploaded_result`：直接读取 `mineru_root` 下已有的 MinerU 结果目录。新模板默认使用这个模式，因为它不会触发上传、下载或本机解析。
- `official_api`：使用 `api:` 配置走 MinerU 官方 API，适合从 PDF 开始。
- `local_toolchain`：调用你单独安装的 `mineru` CLI。MineruPress 不内置 MinerU 依赖，只做外部适配。

如果你选择 `local_toolchain`，请先按 MinerU 官方说明单独安装。常见方式是：

```bash
uv pip install -U "mineru[all]"
```

本地 MinerU 是可选外部工具，不会随 MineruPress 安装。按需扩展、轻量客户端、CLI 参数和源码开发方式请以 MinerU 官方文档为准：

- [Quick Start](https://opendatalab.github.io/MinerU/quick_start/)
- [Extension Modules Installation Guide](https://opendatalab.github.io/MinerU/quick_start/extension_modules/)
- [CLI Tools Usage Instructions](https://opendatalab.github.io/MinerU/usage/cli_tools/)

边界匹配建议：

- 优先只写 `title`。章号和章名被 MinerU 拆成两行、或章号被 OCR 丢掉时，会依次回退到"只有章号"和"只有章名"的整行匹配，并打印提示供核对。
- MinerU 标题存在别名时加 `aliases`。
- 必须手工控制正则时再写 `start_pattern` 或 `start_patterns`。
- 正式导出保持 `allow_missing_boundaries: false`，避免章节错位后继续生成。

所有相对路径都以 `book.yml` 所在目录为基准解析，所以可以从任意目录执行：

```bash
minerupress export /path/to/my-book/book.yml
```

CLI 现已统一为 `minerupress <subcommand>`，例如：

- `minerupress export`
- `minerupress fetch`
- `minerupress headings`
- `minerupress nav`
- `minerupress fingerprint`

旧入口 `minerupress-export`、`minerupress-fetch`、`minerupress-headings` 以及 `mineru-export`、`mineru-fetch` 仍然保留，便于旧项目平滑迁移。

## 内置插件

- `qr_filter`：使用 OpenCV 检测并过滤小尺寸二维码图片。对原图和放大、加白边、二值化后的版本分别检测，并要求检出的方块占图片大部分面积且接近正方形，因此教材里的矩阵、棋盘、图结构小插图不会被误删。被丢弃的图片会在导出日志里逐行打印文件名和尺寸。
- `cjk_spacing`：使用 `pangu` 为中西文混排补空格，并保护 LaTeX 公式片段。
- `cf_pages`：执行 `mkdocs build --strict` 后部署到 Cloudflare Pages；项目不存在时会自动创建后重试。

需要给插件传参时，把插件名写成单键映射；纯字符串写法继续可用：

```yaml
plugins:
  - qr_filter:
      max_side: 250     # 长边超过该值的图片不做二维码检测（默认 250）
  - cjk_spacing
  - cf_pages            # 仍然从 deploy: 段读取参数
```

参数名写错时导出会直接报错并列出该插件接受的参数。自定义插件的 `__init__` 参数同样可以这样传入。

自定义插件继承 `ExportPlugin`：

```python
from pathlib import Path
from minerupress import ExportPlugin


class MyPlugin(ExportPlugin):
    def on_image(self, item: dict, img_path: Path | None) -> bool:
        return True

    def on_text(self, item: dict, text: str) -> str:
        return text

    def on_chapter_done(self, slug: str, lines: list[str]) -> list[str]:
        return lines

    def on_export_done(self, docs_out: Path) -> None:
        pass
```

然后在 `book.yml` 中引用：

```yaml
plugins:
  - mypackage.mymodule.MyPlugin
```

## 贡献者开发

如果你要修改 MineruPress 自身，而不是只用它跑书，再 clone 仓库并做开发安装：

```bash
git clone https://github.com/aronnaxlin/minerupress.git
cd minerupress
pip install -e ".[dev]"
```

本地验证：

```bash
pytest
python -m compileall minerupress
```

仓库已配置 GitHub Actions，在 Python 3.11 和 3.12 上运行 `compileall` 与 `pytest`。如果你只是使用工具链，优先安装发布包；如果你要参与开发，再使用 GitHub 开发安装。

## 文档

- [总览与术语](docs/index.md)
- [快速开始](docs/guide/getting-started.md)
- [安装与升级](docs/guide/install-and-upgrade.md)
- [实战工作流](docs/guide/workflow-run-a-book.md)
- [配置详解](docs/guide/configuration.md)
- [导出流程](docs/guide/export-pipeline.md)
- [插件系统](docs/guide/plugins.md)
- [云端抓取与部署](docs/guide/cloud-api-and-deploy.md)
- [校验、指纹与排障](docs/guide/validation-and-troubleshooting.md)
- [发布与分发](docs/guide/release.md)

## Agent Skill 安装

仓库内置了可给外部 agent 安装的 Skill：

```text
skills/minerupress/
```

使用者可以从这个仓库获取：

```bash
npx skills add aronnaxlin/minerupress --skill minerupress
```

安装后，agent 可以按同一套流程处理图书配置、MinerU 抓取、章节导出、构建校验、排障和 Cloudflare Pages 部署。维护工具链时，如果流程行为改变，也要同步更新 `skills/minerupress/`。

## 仓库边界

这个仓库是通用工具链，`docs/` 用来放项目文档，`book_template/` 用来放新书模板。某本书的本地工作区、MinerU 输出、站点构建结果和敏感配置应保持隔离，不要提交到这里。

通常不要提交：

- 本地图书工作区目录
- `resources/`
- `site/`
- `reports/`
- `.env`
- `.wrangler/`

## 致谢

- [MinerU](https://github.com/opendatalab/MinerU)
- [MkDocs](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [Cloudflare Pages](https://pages.cloudflare.com/)
- [Vercel Agent Skills](https://vercel.com/docs/agent-resources/skills)

## 许可证

Apache License 2.0，见 [LICENSE](LICENSE)。
