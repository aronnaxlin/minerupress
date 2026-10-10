# 发布与分发

MineruPress 已具备标准 Python 包分发能力。对最终用户，推荐使用发布包安装；对维护者，保留 GitHub 开发安装。

用户安装：

```bash
pip install "minerupress[all]"
```

CLI 隔离安装：

```bash
pipx install 'minerupress[all]'
```

维护者开发安装：

```bash
git clone https://github.com/aronnaxlin/minerupress.git
cd minerupress
pip install -e ".[all]"
```

## 发布前检查

正式发布 Release 或 PyPI 包前，至少完成这些检查：

- `python -m compileall minerupress`
- `pytest`
- 用一个本地 MinerU fixture 跑 `minerupress export`
- 用 `minerupress headings` 验证章节边界草稿输出
- 确认 README、`docs/`、`skills/minerupress/` 已同步更新

这些检查要在合并到 `main` 之前完成，因为合并之后会自动发布。

## 构建包

推荐使用 `build`：

```bash
python -m pip install build twine
python -m build
twine check dist/*
```

构建结果会出现在：

- `dist/*.whl`
- `dist/*.tar.gz`

## 版本号

版本号只存在于 git tag（`vX.Y.Z`），不要手动改版本号。仓库里 `pyproject.toml` 的版本是占位的 `0.0.0.dev0`，发布时由 CI 在 runner 里用 `scripts/stamp-version.py` 写入真实版本，不会提交回仓库。所以从源码安装（`pip install -e .`）看到的版本是 `0.0.0.dev0`，从 PyPI 安装的才是真实版本。

规则是“一次推到 `main` 算一个小版本号”：

- 推送到 `main`，且自上一个 tag 之后有新提交：测试通过后自动发布下一个 **patch** 版本。版本号由 `scripts/next-version.sh` 计算，取现有最高的 `vX.Y.Z` tag，把 patch 加一。
- 一次推送里有多个提交（例如合并一个 PR）只发一个版本。
- 最新提交的标题（第一行）里带 `[skip release]` 则不发布；只在正文里提到不算。合并 PR 时要把它写进合并提交的标题。
- 需要发 minor / major：先推一个带 `[skip release]` 的提交，再对该提交打 tag，并只推送 tag：

```bash
git tag v0.2.0
git push origin v0.2.0   # 推送 v* tag 会精确发布这个版本
```

版本号策略遵循 [SemVer](https://semver.org/lang/zh-CN/)：

- 修复 bug 或文档更新 → patch（自动）
- 新增功能或新命令 → minor（手动打 tag）
- 不兼容变更 → major（手动打 tag）

## 自动发布流程

`.github/workflows/release.yml` 在推送到 `main` 或推送 `v*` tag 时运行，依次是：

1. `test`：调用 `ci.yml`，跑和 PR 相同的测试。测试不过就不发布。
2. `version`：决定要发布的版本号；没有新内容或带 `[skip release]` 时为空，后面的 job 全部跳过。
3. `build`：把版本号写进 `pyproject.toml`，构建 `wheel` 和 `sdist`，并用 `twine check` 检查。
4. `github-release`：在这次推送的提交上创建 tag 和 GitHub Release，附上构建产物和自动生成的说明。
5. `publish-pypi`：通过 Trusted Publishing 上传到 PyPI。

注意：合并到 `main` 就等于发布到 PyPI，而 PyPI 上的版本号发出去就不能重用。不想发布的改动要么带 `[skip release]`，要么先别合并。

发布完成后做一次烟雾验证：

```bash
pip install -U "minerupress[all]"
minerupress --help
```

## PyPI Trusted Publishing 配置

发布依赖这些约定，改名会让发布失败：

- workflow 文件名：`release.yml`
- GitHub Environment：`pypi`
- 发布 job：`publish-pypi`

第一次配置：

1. 在 GitHub 仓库进入 `Settings -> Environments`，新建名为 `pypi` 的 environment。
2. 如果想在每次发布前人工确认，给这个 environment 加 `Required reviewers`。加了之后，自动发布会停在 `publish-pypi` 等待批准。
3. 在 PyPI 项目的 Trusted Publisher 里确认这些值一致：
   - Owner: `aronnaxlin`
   - Repository: `minerupress`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

## 手工构建和发布

平时不需要。CI 不可用时可以在本地做同样的事：

```bash
python scripts/stamp-version.py 0.1.3   # 只在本地工作区里改，不要提交
python -m build
twine check dist/*
twine upload dist/*
git checkout pyproject.toml
```

## 用户怎样升级

用户不需要 `git pull`：

- `pip install -U "minerupress[all]"`
- `pipx upgrade minerupress`
