# 快速开始

## 环境要求

- Python `>=3.11`
- `minerupress[all]` 一次装好 `mkdocs`、`mkdocs-material` 以及二维码过滤、中西文间距处理的可选依赖

推荐直接安装 PyPI 发布包：

```bash
pip install "minerupress[all]"
```

只想要本地预览/构建站点的依赖时，可以改装 `minerupress[site]`。

如果你更喜欢独立 CLI 环境，也可以用 `pipx`：

```bash
pipx install 'minerupress[all]'
pipx inject minerupress mkdocs --include-apps
```

如果你是在开发工具链本身，而不是普通使用，请改看 [安装与升级](install-and-upgrade.md) 里的开发安装一节。

## 创建一本新书工作区

MineruPress 仓库本身是工具链，不建议把真实图书内容直接塞进仓库根目录。pip 安装后也不需要找到源码里的 `book_template/`，直接生成独立工作区：

```bash
minerupress init ~/dev/my-book/
cd ~/dev/my-book/
```

新建后的模板包含占位首页和占位章节，可以先运行：

```bash
mkdocs serve
```

模板里包含：

- `book.yml`：导出配置
- `mkdocs.yml`：站点配置
- `.env.example`：环境变量示例
- `Makefile`：常用命令包装

## 选择输入来源

新书工作区只选择一种来源。模板默认是 `source: uploaded_result`，适合已经有 MinerU 解析结果的情况：

```text
resources/mineru/
```

每个分册目录下通常应包含：

- `*_content_list.json`
- `images/`

如果同一个逻辑分册被拆成多个物理目录，也没关系。只要它们目录名前缀都能匹配到同一个 `volume_uid`，导出器就会按自然顺序接起来处理。

如果你只有 PDF，可以改用下面两种之一：

- `source: official_api`：配置 `api.sources` 后运行 `minerupress fetch book.yml`，由 MinerU 官方 API 解析。
- `source: local_toolchain`：先单独安装 MinerU 的 `mineru` CLI，再配置 `local_toolchain.sources` 后运行 `minerupress fetch book.yml`。

本地 MinerU 工具链是可选外部依赖，MineruPress 不会内置或自动安装它。

## 第一次导出

1. 编辑 `book.yml`
2. 选择一种 `source`
3. 准备 MinerU 输出，或通过 `minerupress fetch book.yml` 生成输出
4. 按章节填写 `slug` 和 `title`
5. 运行导出

```bash
minerupress export book.yml
```

导出结果默认会写到：

- `docs/chapters/`
- `docs/images/`

然后用 MkDocs 本地预览：

```bash
mkdocs serve
```

如果你是从一份原始 PDF 开始，而不是已经有本地 MinerU 输出，建议直接按 [实战工作流](workflow-run-a-book.md) 里的“隔离工作区 + `minerupress fetch`”路线操作。

## 常见命令

本地导出：

```bash
minerupress export book.yml
```

`official_api` 或 `local_toolchain` 模式下，先准备来源再导出：

```bash
minerupress fetch book.yml
```

如果希望从导出命令里顺手准备来源：

```bash
minerupress export --fetch book.yml
```

严格构建检查：

```bash
mkdocs build --strict
```

生成文档指纹：

```bash
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

## 目录建议

一个典型图书工作区通常长这样：

```text
my-book/
├── .env
├── book.yml
├── mkdocs.yml
├── docs/
├── resources/
│   ├── mineru/
│   └── pdfs/
├── reports/
└── site/
```

其中：

- `docs/`、`site/`、`reports/` 通常是生成物
- `.env` 放敏感配置，不要提交
- `resources/mineru/` 放 MinerU 输出
- `resources/pdfs/` 常用于云端 API 上传源 PDF

## 从任意目录执行

所有相对路径都以 `book.yml` 所在目录解析，因此下面这种调用是安全的：

```bash
minerupress export /absolute/path/to/my-book/book.yml
```

这意味着你不需要依赖当前 shell 所在目录来保证配置正确解析。
