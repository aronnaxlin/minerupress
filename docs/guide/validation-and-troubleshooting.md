# 校验、指纹与排障

这一页分两类检查：图书工作区的导出结果验证，以及贡献者修改工具链后的代码验证。

## 基础检查

贡献者修改工具链后，最轻量的代码检查：

```bash
python -m compileall minerupress
```

图书工作区导出后，建议至少运行：

```bash
minerupress export book.yml
mkdocs build --strict
```

如果涉及 Markdown 内容变更，还可以生成指纹：

```bash
minerupress fingerprint --docs-dir docs --out reports/fingerprints.json
```

## 指纹机制

`minerupress.fingerprint` 会：

- 扫描 `docs/` 下全部 Markdown
- 计算每个文件的 SHA-256
- 如果已有旧指纹文件，则输出新增、删除、变更文件列表
- 最后把当前结果写回 `reports/fingerprints.json`

这适合：

- 跟踪某次清洗是否影响了哪些章节
- 在批量修正规则后快速看影响范围
- 让 CI 或人工检查更聚焦

## 常见问题

## 找不到章节边界

排查顺序建议：

1. 先检查 `title` 是否和 MinerU 实际识别标题接近
2. 查看对应 `*_content_list.json` 中的 `text` item
3. 尝试补 `aliases`
4. 再用 `start_patterns` 写更精确的正则
5. 只在排查过程中临时加 `--allow-missing-boundaries`

生产环境不建议长期依赖 `allow_missing_boundaries: true`，因为这会掩盖章节错位问题。

有一个高频场景要特别注意：如果目录页里已经出现了 `第 1 章 …… 3` 这类 TOC 条目，而你的 `title` 又正好能自动匹配它，导出器可能会在目录页提前命中章节边界。更稳妥的做法是：

- 保留展示用 `title`
- 用 `start_pattern: ^第\\s*1\\s*章$` 这类“正文页章号行”正则锁定真实边界
- 必要时把 `title` 改成纯章节名，避免自动推导出的标题模式和目录页冲突

自动推导边界时，如果标题写成 `第1章 绪论` 这类“章号 + 标题”形式，导出器不会再用它去匹配附录答案区里孤立的 `第1章` 分节。若某本书的真实正文边界确实只有裸 `第 1 章`，请显式写 `start_pattern` 或把 `title` 写成对应裸章号。

可以先跑标题分析命令辅助判断：

```bash
minerupress headings resources/mineru --format report
minerupress headings resources/mineru --format yaml --body-only
```

第一条用于看 TOC 和正文边界如何分布，第二条用于生成 `chapters:` 草稿。

## 导出的代码块不完整

先确认源 `content_list.json` 里是否存在 `type: code` 项。MineruPress 会优先读取：

- `code_body`
- `text`
- `content`

如果 MinerU 已经给了 fenced code block，导出器会尽量原样保留。

## 正文里的 HTML 标签被显示成文本

这是预期行为。普通正文里的 `<span>`、`<table>`、`<div>` 等会被自动转义，避免被 Markdown 误当成真实 HTML。只有表格的 `table_body` 这类结构化内容会保留原始 HTML。

## 图片丢失

常见原因：

- 源目录 `images/` 中对应文件不存在
- 被 `qr_filter` 或自定义插件过滤掉了（`qr_filter` 会在导出日志里逐行打印被丢弃图片的文件名和尺寸）
- 同名图片冲突后文件名被自动改写，而你在外部又手工引用了旧名字

更稳妥的做法是检查导出日志和源 `img_path`，不要手改生成目录。

## 云端抓取时出现权限错误

一个典型报错是自动分片时试图把 `*_part1.pdf`、`*_part2.pdf` 写回原始 PDF 所在目录，但那个目录来自网盘、系统受保护路径或只读挂载。

推荐处理方式不是改代码，而是改工作流：

1. 先把原始 PDF 复制到当前工作区的 `resources/pdfs/`
2. 让 `api.sources` 指向这份本地副本
3. 再执行 `minerupress fetch`

这样分片 PDF、抓取结果和生成物都会落在同一个隔离工作区里。

## 如何判断一次跑书是否真的完成

至少检查这几项：

- `resources/mineru/` 下已经有对应的 `*_full` 或 `*_partN` 目录
- `docs/chapters/` 下的章节文件数量和 `book.yml` 对得上
- `mkdocs build --strict` 成功
- 如需留痕，`reports/fingerprints.json` 已生成

## 章节没有出现在站点导航里

`mkdocs build --strict` 对没有进入 `nav` 的页面只打印 INFO，不会失败，所以漏写的章节会静默缺失。运行：

```bash
minerupress nav book.yml --check
```

它会列出没进 nav 的章节、nav 里指向 `book.yml` 没有的章节文件、以及章节顺序不一致的地方。不带 `--check` 时打印可以直接贴进 `mkdocs.yml` 的章节 nav 片段。

## `mkdocs build --strict` 失败

优先检查：

- `mkdocs.yml` 导航是否引用了不存在的章节文件（`minerupress nav book.yml --check` 可以检查）
- 文档里是否有坏链接
- 生成内容是否包含不合法 Markdown/HTML 结构
- 公式、表格、代码块是否被异常截断

## 什么时候该修配置，什么时候该修代码

优先修配置的情况：

- 只是某一章边界识别不到
- 某本书标题风格特殊
- 只需要加别名或补正则

优先写插件的情况：

- 一类文本清洗会反复出现
- 一类图片都要统一过滤
- 多本书都会遇到同样的问题

优先检查源 MinerU 输出的情况：

- `content_list.json` 本身就缺段、缺图、顺序错乱
- 代码块和表格在源数据里已经坏掉
