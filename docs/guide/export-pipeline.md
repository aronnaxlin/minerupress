# 导出流程

这一页说明 `minerupress export` 在内部做了什么，方便你定位问题或判断应该改配置、改插件，还是改源数据。

## 整体流程

1. 读取 `book.yml`
2. 解析章节配置、插件配置和可选 `api:` 配置
3. 根据章节里出现的 `volume_uid` 收集逻辑分册
4. 在 `mineru_root` 下发现所有匹配前缀的物理目录
5. 读取每个目录里的 `*_content_list.json`
6. 复制图片到 `docs/images/`，并让插件先决定是否保留
7. 依次查找每章边界
8. 把章节区间内的 item 转成 Markdown
9. 把每章结果写到 `docs/chapters/<slug>.md`
10. 调用插件的整章后处理和导出完成后处理

## 分册发现与排序

导出器会扫描 `mineru_root` 下所有子目录，并按目录名自然排序。对于章节使用的每个逻辑 `volume_uid`：

- 只要目录名以该 UID 开头，就会被视为同一逻辑分册的一部分
- 如果一个目录同时匹配多个 UID，会直接报错
- 如果某个 UID 找不到任何目录，也会报错

这保证了多分片 PDF 在导出时能按顺序连接起来。

## 图片处理

导出开始时，`docs/images/` 会被整体重建。随后：

- 对每个带 `img_path` 的 `image` / `chart` item，先调用所有插件的 `on_image()`
- 只有全部插件都返回 `True` 时，图片才会被复制
- 如果不同分册里图片重名，导出器会自动为冲突文件加上分册目录名前缀

因此：

- 不要把手工图片放在 `docs/images/`
- 如果要过滤二维码、水印或噪声图，优先写插件

## 章节边界查找

对每个逻辑分册，导出器会按 `book.yml` 中章节的顺序依次向后查找边界。

关键点：

- 第一个章节会应用 `toc_max_page` 目录页过滤
- 后续章节从上一章边界后继续向后找
- 只在文本型边界 item 中匹配章节边界，目前包括 `type == "text"` 和 `type == "aside_text"`
- 如果边界缺失且 `allow_missing_boundaries: false`，整个导出会失败

这能最大限度避免章节错位后继续静默生成错误内容。

如果你还没有稳定的章节配置，可以先运行：

```bash
minerupress headings resources/mineru --volume-uid <uid> --format yaml --body-only
```

它会读取 MinerU 的 `text_level == 1` 条目，标注目录页候选和正文候选，并给出一份可继续编辑的 `chapters:` 草稿。

## Item 到 Markdown 的转换

当前内置转换逻辑大致如下：

- `image`、`chart`：输出 Markdown 图片；caption 读取 `image_caption`（兼容旧字段 `img_caption`）或 `chart_caption`，作为 alt 并附带斜体说明，没有 caption 时 alt 是文件名；footnote 读取 `image_footnote` / `chart_footnote`，作为图后的普通段落。图被插件过滤时，caption 和 footnote 一并丢弃
- `equation`：转为 `$$ ... $$`
- `table`：保留 `table_body`，`table_caption` 转为加粗标题，`table_footnote` 作为表后的普通段落
- `code`：优先读取 `code_body`，保留已带 fence 的代码块；`code_caption` 转为代码块前的加粗标题
- `list`：`list_items` 渲染成 Markdown 列表，条目已带 `-`、`1.` 等前缀时不会重复添加
- `text`：根据 `text_level` 转成标题或正文
- 其他文本型 item：按普通文本输出
- `page_number`、`header`、`footer`、`page_footnote`：直接跳过

### 章首标题去重

每章开头由导出器写一行 `# {title}`。边界 item 及其后连续的、同一页上的短文本如果去掉空白后只是章标题（或 `aliases`）的一部分（例如 `第4章`、`递 推 法`），就会被跳过，避免同一页出现多个标题。边界 item 命中的如果是一段正文，则原样保留。

## 导出统计

导出过程只在控制台输出统计，不写文件：

- 每章一行 `Wrote ...`，末尾附带该章写出 / 丢弃的 item 数
- 全书汇总按 item 类型列出 `written / dropped`；`page_footnote` 等默认跳过的类型也会计入 `dropped`
- 遇到没有任何转换分支、但带有内容的 item 类型时，会输出 `[WARN]` 提示

## 文本处理细节

文本进入 Markdown 前，会先依次经过所有插件的 `on_text()`。之后：

- 普通正文中的 `<tag>` 会被自动转义成 `&lt;tag&gt;`
- 这样教材里讨论 HTML/XML 标签时不会被 Markdown 当真 HTML 渲染
- OCR 文本里形如 `next[j](1≤j≤m-1)` 的片段会被转义成 `next[j\](1≤j≤m-1)`，避免被渲染成链接
- `$...$`、`$$...$$` 等公式内部不做任何转义，保证 MathJax 看到的是原始公式
- 表格的 `table_body` 不做这一层转义，保留表格原始结构

## 输出目录行为

每次导出都会重建：

- `docs/chapters/`
- `docs/images/`

这意味着：

- 里面不适合存放手工长期维护内容
- 如果你发现某章导出不对，应该修 `book.yml`、MinerU 输入或插件，而不是直接手改生成文件

## 插件调用顺序

一次完整导出中，插件 hook 的顺序是：

1. `on_image(item, img_path)`
2. `on_text(item, text)`
3. `on_chapter_done(slug, lines)`
4. `on_export_done(docs_out)`

这让插件可以分别处理：

- 单张图片是否保留
- 文本清洗
- 整章级别后处理
- 导出完成后的副作用，例如部署
