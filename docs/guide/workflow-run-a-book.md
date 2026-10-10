# 实战工作流

这一页把“一本新的 PDF 从零跑成站点”的完整流程沉淀下来。它采用 `source: official_api` 作为示例；如果你已有 MinerU 输出，请看 [快速开始](getting-started.md) 的 `uploaded_result` 路线；如果你要本机解析，请看 [配置详解](configuration.md) 的 `local_toolchain` 路线。

## 适用场景

适合下面这种起点：

- 你手上只有一份 PDF
- 想直接通过 MinerU 云端 API 抓取解析结果
- 不希望把这本书的配置、输出和其他项目混在一起
- 希望最后拿到完整的 MkDocs 站点和一套可追踪产物

## 推荐目录策略

不要直接在仓库根目录跑一本书。推荐先建立隔离工作区，例如：

```text
.temp/book-runs/software-testing-methods/
```

里面放这本书自己的：

- `book.yml`
- `mkdocs.yml`
- `.env`
- `resources/pdfs/`
- `resources/mineru/`
- `docs/`
- `site/`
- `reports/`

这样能避免：

- 根目录被真实书稿污染
- 多本书相互覆盖生成物
- 云端抓取、分片、排障时文件散落到别处

## 标准步骤

## 1. 复制模板

从现有模板起步：

```bash
minerupress init .temp/book-runs/software-testing-methods
```

然后进入工作区：

```bash
cd .temp/book-runs/software-testing-methods
```

## 2. 把源 PDF 复制进工作区

不要直接让 `api.sources` 指向网盘目录、受保护目录或外部共享路径。更稳妥的方式是：

```text
resources/pdfs/book.pdf
```

原因：网盘同步目录、外部共享路径下的文件，路径、修改时间可能随同步变化；`fetch` 的续跑记录就是按源 PDF 的路径、大小和修改时间识别“同一份文件”的。放进工作区后更稳定，也方便整个目录一起归档。分片 PDF 本身只写到系统临时目录，不会落在源 PDF 旁边。

## 3. 写 `.env`

最小示例：

```bash
MINERU_API_TOKEN=...
```

`.env` 放在 `book.yml` 同一目录。shell 里已设置的同名环境变量优先于它。如果这次不打算部署，不要配置 Cloudflare 相关生产凭据。

## 4. 先写一份“抓取优先”的 `book.yml`

第一轮不要急着把所有章节都填完。推荐先用最小配置把 MinerU 结果拉下来：

```yaml
source: official_api
mineru_root: resources/mineru
docs_out: docs
volume_uid: software-testing-methods
toc_max_page: 20
allow_missing_boundaries: true

api:
  token: ""
  enable_formula: true
  enable_table: true
  model_version: vlm
  poll_timeout: 600   # 等待解析的最长秒数
  sources:
    software-testing-methods: resources/pdfs/software-testing-methods.pdf

plugins:
  - qr_filter
  - cjk_spacing

chapters:
  - slug: placeholder
    title: 软件测试方法和技术
```

这里的重点不是第一次就切章完美，而是先把 `resources/mineru/` 和 `docs/images/` 等基础产物拿到手。

## 5. 执行抓取

```bash
minerupress fetch book.yml
```

这一步通常会自动完成：

1. 检查 PDF 页数
2. 必要时拆分为多个 `part`
3. 上传到 MinerU
4. 轮询任务状态
5. 下载 ZIP 结果
6. 解压到 `resources/mineru/<volume_uid>_partN/`
7. 顺带跑一次导出

如果下载中途失败（网络、代理、DNS），直接重跑同一条命令即可：已上传的批次记录在 `.minerupress/fetch-state.json`，不会重新上传。想强制重新上传解析，用 `minerupress fetch book.yml --force`。

占位章节在第一轮找不到边界是正常的：`fetch` 会以非零退出码结束，并打印“来源已就绪，下一步运行 `headings`”。结果已经在 `resources/mineru/` 里，继续下一步即可。

## 6. 从 MinerU 输出里确认真实章节边界

第一轮导出后，接下来不要直接盲填章节名。更稳妥的做法是去看：

- `resources/mineru/*/*_content_list.json`

现在可以先用内置命令做一轮自动分析：

```bash
minerupress headings resources/mineru --volume-uid software-testing-methods
```

报告里会标出：

- `toc?`：看起来像目录页里的条目
- `body`：看起来像正文里的真实边界
- `confidence`：当前判断的置信度
- `start_pattern`：建议写入 `book.yml` 的边界正则

如果只想拿可复制的章节配置草稿：

```bash
minerupress headings resources/mineru --volume-uid software-testing-methods --format yaml --body-only
```

重点观察：

- 目录页里的章标题长什么样
- 正文页里的真正章号行长什么样
- 是否有 `第 1 章` 和下一行 `引论` 这种分拆标题
- 附录是否写成 `附录 A` 而不是 `附录A`

## 7. 把 `book.yml` 改成正式章节配置

当你确认了真实边界，再写正式 `chapters`。如果目录页会干扰匹配，推荐：

- `title` 用展示友好的纯章节名
- `start_pattern` 精确锁定正文页章号行
- 优先从 `minerupress headings --format yaml --body-only` 的结果开始改

例如：

```yaml
chapters:
  - slug: ch01-introduction
    title: 引论
    start_pattern: ^第\s*1\s*章$

  - slug: ch02-basic-concepts
    title: 软件测试的基本概念
    start_pattern: ^第\s*2\s*章$

  - slug: appendix-a-terms
    title: 软件测试英文术语及中文解释
    start_pattern: ^附录\s*A$
```

这是因为如果直接把 `title` 写成 `第1章 引论`，自动推导出来的边界模式有时会先命中目录页里的 `第1章 引论 …… 3`。

## 8. 更新 `mkdocs.yml` 导航

当章节 `slug` 稳定后，把导航补齐：

```yaml
nav:
  - 首页: index.md
  - 各章内容:
    - 第1章 引论: chapters/ch01-introduction.md
    - 第2章 软件测试的基本概念: chapters/ch02-basic-concepts.md
```

不想手写的话，让 MineruPress 按 `book.yml` 打印章节片段，直接贴进 `mkdocs.yml`：

```bash
minerupress nav book.yml
```

之后每次增删章节，可以用 `--check` 确认 nav 没漏章、没指向不存在的章节文件、顺序和 `book.yml` 一致：

```bash
minerupress nav book.yml --check
```

这一步很值得做：`mkdocs build --strict` 对没有进 `nav` 的页面只给 INFO，不会失败，漏写的章节会静默缺失。`minerupress nav` 只读，不会改写 `mkdocs.yml`；`mkdocs.yml` 里的 `!!python/name:...` 之类 Material 常见标签也能正常解析。

并补一个简单首页 `docs/index.md`。

## 9. 重跑标准导出

```bash
minerupress export book.yml
```

这次检查日志里的每章 item 数量是否合理。一个很实用的经验是：

- 如果很多章都只写出 `1 items`
- 或某一章异常吞掉大量后续内容

通常就是边界仍然匹配错了。

## 10. 建站与留痕

完成导出后，至少再跑两步：

```bash
mkdocs build --strict
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

这样你会得到：

- `site/`：可发布站点
- `reports/fingerprints.json`：这次输出的内容指纹

## 一次成功跑完后，工作区里应该有什么

```text
software-testing-methods/
├── .env
├── book.yml
├── mkdocs.yml
├── docs/
│   ├── index.md
│   ├── chapters/
│   └── images/
├── resources/
│   ├── pdfs/
│   └── mineru/
├── reports/
│   └── fingerprints.json
└── site/
```

## 最常见的两个坑

## 坑 1：PDF 在网盘或外部目录，续跑记录总是失效

现象：

- 每次重跑 `minerupress fetch` 都重新上传，而不是续跑

原因：

- 续跑记录按源 PDF 的路径、大小和修改时间匹配；网盘同步或移动文件会改变其中之一

解决：

- 先把 PDF 复制到工作区内的 `resources/pdfs/`，之后不要再替换它

## 坑 2：目录页抢先命中章节边界

现象：

- 某些章节导出只有 `1 items`
- 某一章吞掉后面很多章的内容

原因：

- 自动边界模式先命中了目录页 TOC 项

解决：

- 用 `start_pattern` 锁定正文页章号行
- 必要时把 `title` 改成纯章节名，避免自动推导模式参与竞争

## 最后建议

把这条流程当成“两阶段工作流”会更稳：

1. 先抓取，确认原始解析结果和真实标题结构
2. 再定章节边界，重跑标准导出和建站

这样比一开始就把完整目录硬写进 `book.yml` 更稳，也更适合复杂教材和 OCR/版式不稳定的 PDF。
