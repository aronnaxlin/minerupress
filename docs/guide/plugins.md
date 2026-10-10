# 插件系统

MineruPress 把书籍特定清洗和导出后动作放在插件里，而不是塞进 `core.py`。这样导出引擎本身可以保持通用。

## 插件基类

所有插件继承：

```python
from minerupress.plugins.base import ExportPlugin
```

可覆盖的 hook：

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

含义：

- `on_image()`：返回 `False` 时丢弃该图片
- `on_text()`：处理正文、caption、alt 等文本
- `on_chapter_done()`：整章写盘前做最终改写
- `on_export_done()`：导出结束后的副作用处理

## 启用插件

内置插件可以在 `book.yml` 里直接写短名：

```yaml
plugins:
  - qr_filter
  - cjk_spacing
```

自定义插件写 dotted import 路径：

```yaml
plugins:
  - mypackage.mymodule.MyPlugin
```

### 给插件传参

需要覆盖插件的默认参数时，把插件名写成单键映射，值是该插件 `__init__` 的参数：

```yaml
plugins:
  - qr_filter:
      max_side: 250
  - cjk_spacing
  - mypackage.mymodule.MyPlugin:
      threshold: 0.8
```

- 纯字符串写法继续可用，等价于不传参数。
- 一个映射里只能有一个插件名，多个插件各写一行 `- `。
- 参数名写错、或者给不接受参数的插件传参，会在加载 `book.yml` 时报错，并列出该插件接受的参数。
- `cf_pages` 仍然从顶层 `deploy:` 段取参数；写在插件项里的同名参数优先于 `deploy:`。

## 内置插件

### `qr_filter`

作用：

- 用 OpenCV 的 `QRCodeDetector` 检测二维码图片；除了原图，还会在放大、加白边、二值化后的版本上重试，补回小尺寸、没有留白的二维码
- 只有检出的方块占图片面积四成以上且接近正方形才算二维码，所以矩阵、棋盘、图结构这类小插图不会被误删
- 默认只检查边长不超过 `250px` 的小图，可以用 `max_side` 调整
- 每丢弃一张图会在导出日志里打印一行 `[qr_filter] dropped <文件名> (宽x高)`，便于核对
- 不看图注文字，不依赖某本书的“课件”“源代码”之类标签
- 缺少 `opencv-python` 时会警告并退化为 no-op

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `max_side` | `250` | 长边超过该值的图片不做二维码检测 |

适合：

- 教材页边小二维码
- 课程资料里引流码、公众号码这类不希望保留到在线书里的图片

### `cjk_spacing`

作用：

- 使用 `pangu` 在中西文、数字、英文之间补空格
- 自动保护 `$...$` 和 `$$...$$` 里的 LaTeX 公式，不在公式内部插空格
- 同时兼容 pangu 4.x 的 `spacing_text()` 和 6.x 的 `space_text()`
- 缺少 `pangu` 时会警告并退化为 no-op；处理某段文字出错时保留原文，并且只警告一次

适合：

- 中文技术书正文中的中英混排
- 代码标识符、URL、命令和中文说明混排的场景

### `cf_pages`

作用：

- 在导出完成后执行 `mkdocs build --strict`
- 然后调用 `wrangler pages deploy`
- 如果 Pages 项目不存在，会自动尝试创建项目后再重试

注意：

- 没有 `CLOUDFLARE_API_TOKEN` 时会直接跳过，不会误部署
- 这是有副作用的插件，建议只在确认配置正确后启用

## 插件设计建议

- 尽量容错，缺可选依赖时退化为 no-op
- 不要把某一本书的特殊规则写死到核心导出器
- 文本清洗尽量放在 `on_text()`
- 跨段落或整章重排放在 `on_chapter_done()`
- 网络、部署、写外部系统的动作放在 `on_export_done()`

## 什么时候该写插件

适合写插件的情况：

- 固定模式的图片过滤
- 批量文本修正
- 整章统一格式处理
- 导出完成后的自动校验或部署

不适合写插件的情况：

- 单本书某一章的临时人工修补
- 其实可以通过 `title`、`aliases`、`start_patterns` 解决的边界问题
- 应该在源 PDF 或 MinerU 输出层修正的数据问题
