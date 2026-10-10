# 云端抓取与部署

这一页覆盖两个有副作用的功能：

- `minerupress fetch` 调用 MinerU 云端 API
- `cf_pages` 插件部署到 Cloudflare Pages

## MinerU 云端 API

如果你不想先在本地准备 MinerU 输出，而是希望直接上传 PDF 并拿回解析结果，可以在 `book.yml` 中配置 `api:`：

```yaml
source: official_api

api:
  token: ""
  enable_formula: true
  enable_table: true
  model_version: vlm
  poll_timeout: 600   # 等待解析的最长秒数，默认 600
  sources:
    javaweb: resources/pdfs/javaweb.pdf
```

推荐把敏感信息放到 `.env`：

```bash
MINERU_API_TOKEN=...
```

MineruPress 会读取 `book.yml` 所在目录下的 `.env`，找不到的变量再从当前目录的 `.env` 补。shell 里已经设置的同名环境变量优先，不会被 `.env` 覆盖。

然后执行：

```bash
minerupress fetch book.yml
```

不要直接在工具链仓库根目录跑真实书稿。推荐先创建独立工作区，再在里面执行 `minerupress fetch`。完整示例见 [实战工作流](workflow-run-a-book.md)。

## `minerupress fetch` 做了什么

它会：

1. 读取 `api.sources`
2. 对每个 PDF 调用 MinerU API
3. 如果页数超限，自动拆成多个 PDF 分片
4. 上传分片，并把批次 ID 记到 `.minerupress/fetch-state.json`
5. 轮询直到解析完成（最长 `api.poll_timeout` 秒）
6. 下载 ZIP 结果并解压到 `mineru_root`，输出目录直接命名为 `volume_uid_full` 或 `volume_uid_partN`
7. 清理同一 `volume_uid` 旧的 `full/part` 输出
8. 最后再走正常导出流程

`fetch` 一次跑通并不要求 `chapters` 已经写对：新书模板里只有一个占位章节，导出阶段找不到边界时，`fetch` 会以非零退出码结束，并提示来源已就绪、下一步运行 `minerupress headings`、修改 `chapters`、再 `minerupress export`。已经下载好的结果不会丢，重跑 `fetch` 也不会重新上传。

## 中断后续跑

上传成功后，每个分片的批次 ID、状态和输出目录会立刻写入工作区的 `.minerupress/fetch-state.json`（模板的 `.gitignore` 已忽略它）。同一份源 PDF（路径、大小、修改时间一致）且 API 选项没变时，重跑 `minerupress fetch book.yml`：

- 还有未完成的批次：不会重新上传，直接轮询并只下载缺的分片
- 所有分片都已完整落在 `mineru_root`：整体跳过，并提示如何强制重跑
- 保存的批次在服务端查不到或已过期：报错并建议 `--force`
- 某个批次被 MinerU 标记为失败：下次运行只重新上传这个分片

想忽略记录、重新上传并解析：

```bash
minerupress fetch book.yml --force
```

源 PDF 被替换、移动，或 `enable_formula`、`enable_table`、`model_version` 改变后，旧记录会被自动忽略。

### 超时

`api.poll_timeout` 是每次运行等待所有分片解析完成的总秒数，默认 600。分片是并行解析的，通常几分钟内完成，不需要按分片数放大。超时报错会列出每个未完成分片的 batch_id；MinerU 那边仍在解析，重跑 `minerupress fetch` 就会接着等。书很大或服务繁忙时再调大它。

### 下载失败

ZIP 下载遇到瞬时网络错误（连接重置、TLS 中断、5xx）会自动做有限次指数退避重试。仍然失败时，报错会写明失败的 host，并说明解析结果已在服务端就绪，重跑 `fetch` 会直接续跑下载。

结果 ZIP 来自 CDN 域名（例如 `cdn-mineru.openxlab.org.cn`），和 API 域名 `mineru.net` 不是同一个 host。本机代理或 DNS 规则可能只拦截前者，表现为 API 查询正常、下载时 TLS 握手被断开。遇到这种情况请检查该 host 的代理规则或 DNS 解析，再重跑 `fetch`；MineruPress 不会改动你的代理设置。

## 推荐工作方式：先隔离，再抓取

如果 PDF 位于网盘目录、共享目录，或者你不希望把这本书的配置和生成物混进仓库根目录，推荐这样做：

1. 用 `minerupress init` 创建独立目录，或仓库内的临时目录
2. 把源 PDF 复制到工作区内的 `resources/pdfs/`
3. 在工作区写 `.env` 和 `book.yml`
4. 运行 `minerupress fetch book.yml`

这样做的好处：

- 源 PDF 路径稳定，续跑记录（`.minerupress/fetch-state.json`）按路径和修改时间识别它
- `resources/mineru/`、`docs/`、`site/`、`reports/` 都能和别的项目隔离
- 方便 AI agent 或脚本重复执行同一流程

## PDF 自动拆分

MinerU API 对单文件页数有限制。MineruPress 会在超限时自动拆分，并保证：

- 每个分片页数控制在安全阈值内
- 分片 PDF 写到系统临时目录，上传结束（无论成功或失败）后清理，不会写到源 PDF 所在目录
- `fetch()` 返回的目录顺序与 PDF 分片顺序一致
- 章节仍只需要使用原来的逻辑 `volume_uid`

这意味着你不需要在 `book.yml` 手工维护 `part1`、`part2` 之类的章节配置。

## `minerupress export --fetch`

如果你已经有部分本地输出，但还想在导出前按当前 `source` 重新准备内容，可以用：

```bash
minerupress export --fetch book.yml
```

它的行为和 `minerupress fetch` 类似（同样支持续跑，`--force` 用法相同），但命令入口仍然是导出命令：

- `source: official_api` 时会调用 MinerU 官方 API
- `source: local_toolchain` 时会调用你单独安装的 `mineru` CLI
- `source: uploaded_result` 时不会额外抓取，只直接使用已有 `mineru_root`

## Cloudflare Pages 部署

启用 `cf_pages` 插件：

```yaml
plugins:
  - cf_pages

deploy:
  pages_project: my-book
  site_dir: site
  branch: main
  wrangler_cmd: npx wrangler
```

环境变量通常需要：

```bash
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
PAGES_PROJECT=my-book
```

说明：

- `pages_project` 可以写在 `deploy:` 中，也可以用 `PAGES_PROJECT`
- `CLOUDFLARE_API_TOKEN` 不存在时，插件会直接跳过部署
- 插件会先跑 `mkdocs build --strict`，构建失败就不会继续部署

## 部署时机

`cf_pages` 是 `on_export_done()` 阶段触发的，所以只要插件开启，执行一次 `minerupress export` 就可能触发一次部署。

因此建议：

- 本地排查时先不要启用 `cf_pages`
- 或者至少不要在带生产凭据的环境里随手运行

## 什么时候不该用这些功能

以下场景建议先不要执行：

- 你还没确认 `book.yml` 章节边界是否稳定
- 你不确定 `.env` 里是否带着生产环境凭据
- 你只是想本地试验导出效果
- 你当前在 CI 或共享机器上，不希望消耗云端资源
