# uv 现代化改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 hermes-telegram-downloader 改造为 uv 管理的现代 Python 工程（src 布局 + Python 3.14 + 最新依赖）。

**Architecture:** 代码整体迁入 `src/hermes_telegram_downloader/`（`module/`、`utils/`、`media_downloader.py` 保持内部结构不变），import 机械改写为包绝对导入；依赖由 `pyproject.toml` + `uv.lock` 管理；Docker 构建改用 uv。

**Tech Stack:** uv、hatchling、Python 3.14、ruff、pytest、Docker

**设计文档:** `docs/superpowers/specs/2026-09-12-uv-modernization-design.md`

**全局注意：**
- 所有命令在仓库根目录 `D:\WorkSpace\HobbyProjects\hermes-telegram-downloader` 下执行（Windows PowerShell 7+）
- 不改任何业务逻辑
- 每个 Task 结束后单独 commit

---

### Task 1: 初始化 uv 工程文件

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Modify: `.gitignore`（删除第 18 行 `.python-version`）

- [ ] **Step 1: 创建 `.python-version`**

内容（就一行）：

```
3.14
```

- [ ] **Step 2: 创建 `pyproject.toml`**

```toml
[project]
name = "hermes-telegram-downloader"
version = "1.0.0"
description = "Telegram 媒体下载 / 转发 / 监听工具，带任务持久化 + 崩溃恢复 + 现代 WebUI"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.14"
dependencies = [
    # pyrogram 补丁 fork（上游不可用，保持直连）
    "pyrogram @ https://github.com/tangyoha/pyrogram/archive/refs/heads/patch.zip",
    "pyyaml>=6.0.2",
    "rich>=13.0",
    "pytgcrypto>=1.2.7",
    "loguru>=0.7",
    "werkzeug>=3.0",
    "flask>=3.0",
    "ply>=3.11",
    "ruamel.yaml>=0.18",
    "flask-login>=0.6.3",
    "pycryptodome>=3.20",
    "requests>=2.32",
]

[project.scripts]
media-downloader = "hermes_telegram_downloader.media_downloader:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hermes_telegram_downloader"]

[dependency-groups]
dev = [
    "ruff>=0.8",
    "pytest>=8.0",
]

[tool.ruff]
target-version = "py314"
src = ["src"]

[tool.ruff.lint]
select = ["F"]
ignore = ["F401", "F841", "F811"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

说明：
- ruff 只启用 `F` 规则族（pyflakes），其中 `F821`（未定义名称）可验证 import 改写正确性；`F401/F841/F811` 存量代码大量触发，先忽略，不强行清理
- 依赖给最低版本约束，具体版本由 `uv.lock` 锁定

- [ ] **Step 3: 修改 `.gitignore`**

删除第 18 行（`.python-version`），保留其余内容不变。

- [ ] **Step 4: 验证 uv 识别项目**

Run: `uv python pin 3.14`（确认 .python-version 生效）；`uv python find`
Expected: 输出某个 3.14.x 解释器路径（uv 会自动下载托管的 3.14，无需系统安装）

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .python-version .gitignore
git commit -m "chore: 初始化 uv 工程文件（pyproject.toml + Python 3.14）"
```

---

### Task 2: 依赖锁定与兼容性门禁

**Files:**
- Create: `uv.lock`（uv 自动生成）

- [ ] **Step 1: 锁定依赖**

Run: `uv lock`
Expected: 生成 `uv.lock`，无报错

**可能的失败与处理：**
- **pyrogram zip 下载失败**（网络/代理）：配置代理后重试，`$env:HTTPS_PROXY="http://127.0.0.1:1080"`（按本机实际代理）
- **pyrogram fork 构建失败**（其打包元数据不兼容 uv 的构建隔离）：先试 `uv lock` 是否只是元数据解析；若 fork 缺少 pyproject，uv 会回落 setup.py。若彻底失败，**停下来报告用户**，备选方案：fork 仓库本地 clone 后以路径依赖引用
- **pytgcrypto 无 cp314 wheel**：`uv lock` 本身不构建，问题会在 Task 6 `uv sync` 暴露，届时见 Task 6 的处理

- [ ] **Step 2: Commit**

```bash
git add uv.lock
git commit -m "chore: uv.lock 依赖锁定"
```

---

### Task 3: 编写冒烟测试（先失败）

**Files:**
- Create: `tests/test_smoke.py`
- Create: `tests/__init__.py`（空文件）

- [ ] **Step 1: 写测试**

`tests/__init__.py` 内容为空。

`tests/test_smoke.py`：

```python
"""冒烟测试：验证包结构与 import 改写正确。"""

import importlib

import pytest

SUBMODULES = [
    "hermes_telegram_downloader.module.app",
    "hermes_telegram_downloader.module.bot",
    "hermes_telegram_downloader.module.cloud_drive",
    "hermes_telegram_downloader.module.download_stat",
    "hermes_telegram_downloader.module.filter",
    "hermes_telegram_downloader.module.get_chat_history_v2",
    "hermes_telegram_downloader.module.language",
    "hermes_telegram_downloader.module.pyrogram_extension",
    "hermes_telegram_downloader.module.send_media_group_v2",
    "hermes_telegram_downloader.module.task_store",
    "hermes_telegram_downloader.module.web",
    "hermes_telegram_downloader.utils.format",
    "hermes_telegram_downloader.utils.log",
    "hermes_telegram_downloader.utils.meta",
    "hermes_telegram_downloader.utils.meta_data",
    "hermes_telegram_downloader.utils.platform",
]


def test_import_package():
    import hermes_telegram_downloader

    assert hermes_telegram_downloader.__version__


def test_import_main_module():
    """主模块 import 时执行模块级 Application()，已确认无文件 IO，不会崩溃。"""
    import hermes_telegram_downloader.media_downloader

    assert callable(hermes_telegram_downloader.media_downloader.cli)


@pytest.mark.parametrize("mod", SUBMODULES)
def test_import_submodule(mod):
    importlib.import_module(mod)
```

注意：`utils/platform.py` 模块名与标准库 `platform` 冲突，但在包内以绝对导入访问无冲突。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --no-sync pytest tests/ -v`（`--no-sync` 因为项目代码尚未迁移，只装了 dev 工具；若 pytest 不可用则先 `uv sync --no-install-project`）
Expected: FAIL，`ModuleNotFoundError: No module named 'hermes_telegram_downloader'`

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: 新增包结构冒烟测试（当前失败，等待代码迁移）"
```

---

### Task 4: 迁移代码到 src 布局

**Files:**
- Move: `module/` → `src/hermes_telegram_downloader/module/`
- Move: `utils/` → `src/hermes_telegram_downloader/utils/`
- Move: `media_downloader.py` → `src/hermes_telegram_downloader/media_downloader.py`
- Create: `src/hermes_telegram_downloader/__init__.py`
- Create: `src/hermes_telegram_downloader/__main__.py`

- [ ] **Step 1: git mv 迁移（保留 git 历史）**

```powershell
New-Item -ItemType Directory -Path "src\hermes_telegram_downloader"
git mv module src/hermes_telegram_downloader/module
git mv utils src/hermes_telegram_downloader/utils
git mv media_downloader.py src/hermes_telegram_downloader/media_downloader.py
```

Expected: 三个目录/文件出现在 `src/hermes_telegram_downloader/` 下，根目录不再有它们

- [ ] **Step 2: 创建包 `__init__.py`**

`src/hermes_telegram_downloader/__init__.py`：

```python
"""Hermes Telegram Downloader."""

__version__ = "1.0.0"
```

- [ ] **Step 3: 新增 `cli()` 入口包装**

修改 `src/hermes_telegram_downloader/media_downloader.py` 末尾（原 1329-1331 行）：

```python
def cli():
    """Console script / module entry point."""
    if _check_config():
        main()


if __name__ == "__main__":
    cli()
```

（即：把原来的 `if __name__ == "__main__": if _check_config(): main()` 改为上面形式）

- [ ] **Step 4: 创建 `__main__.py`**

`src/hermes_telegram_downloader/__main__.py`：

```python
"""支持 python -m hermes_telegram_downloader 运行。"""

from hermes_telegram_downloader.media_downloader import cli

if __name__ == "__main__":
    cli()
```

- [ ] **Step 5: Commit**

```bash
git add src/
git commit -m "refactor: 迁移代码到 src/hermes_telegram_downloader 布局"
```

---

### Task 5: import 改写

**Files:**
- Modify: `src/hermes_telegram_downloader/**/*.py`（全部）
- Create-then-delete: `_migrate_imports.py`（一次性脚本，用完即删；该文件名已被 .gitignore 的 `_*` 规则忽略，不会误提交——确认 `.gitignore` 中 `_fix_*.py` 不匹配它，若担心可用 `migrate_imports_tmp.py`）

- [ ] **Step 1: 写改写脚本**

在项目根创建 `migrate_imports_tmp.py`：

```python
"""一次性脚本：把 module/utils 顶层导入改写为包内绝对导入。"""

import re
from pathlib import Path

PKG = "hermes_telegram_downloader"
ROOT = Path("src") / PKG

PATTERNS = [
    (re.compile(r"(?m)^(\s*)from module\."), rf"\g<1>from {PKG}.module."),
    (re.compile(r"(?m)^(\s*)from utils\."), rf"\g<1>from {PKG}.utils."),
    (re.compile(r"(?m)^(\s*)from module import"), rf"\g<1>from {PKG}.module import"),
    (re.compile(r"(?m)^(\s*)from utils import"), rf"\g<1>from {PKG}.utils import"),
    (re.compile(r"(?m)^(\s*)import utils$"), rf"\g<1>from {PKG} import utils"),
    (re.compile(r"(?m)^(\s*)import module$"), rf"\g<1>from {PKG} import module"),
]

changed = 0
for py in sorted(ROOT.rglob("*.py")):
    text = py.read_text(encoding="utf-8")
    new = text
    for pat, repl in PATTERNS:
        new = pat.sub(repl, new)
    if new != text:
        py.write_text(new, encoding="utf-8", newline="")
        changed += 1
        print(f"updated: {py}")
print(f"done, {changed} files updated")
```

- [ ] **Step 2: 运行脚本**

Run: `uv run --no-sync python migrate_imports_tmp.py`
Expected: 输出若干 `updated:` 行（预期覆盖 media_downloader.py、module/app.py、module/bot.py、module/cloud_drive.py、module/download_stat.py、module/filter.py、module/pyrogram_extension.py、module/web.py 等），最后 `done, N files updated`

- [ ] **Step 3: 验证无残留旧导入**

Run: `rg -n "from module\.|from utils\.|from module import|from utils import|^\s*import utils$|^\s*import module$" src/`
Expected: 无任何输出（0 匹配）

再人工抽查：`rg -n "hermes_telegram_downloader" src/hermes_telegram_downloader/media_downloader.py` 应看到顶部 import 已全部带包前缀。

- [ ] **Step 4: 删除一次性脚本**

```powershell
Remove-Item migrate_imports_tmp.py
```

- [ ] **Step 5: Commit**

```bash
git add src/
git commit -m "refactor: import 改写为 hermes_telegram_downloader 包绝对导入"
```

---

### Task 6: uv sync 与 import 冒烟验证

**Files:**
- 无文件修改（纯验证；若触发依赖调整则 Modify `pyproject.toml`）

- [ ] **Step 1: 安装全部依赖（含项目 editable 安装）**

Run: `uv sync`
Expected: 创建 `.venv/`，安装全部依赖 + 项目本身（editable）

**可能的失败与处理：**
- **pytgcrypto 无 cp314 wheel 且源码编译失败**（Windows 需 MSVC）：从 `pyproject.toml` 移除 `pytgcrypto` 依赖（它是 pyrogram 的可选加速库，没有也能正常运行），重新 `uv lock && uv sync`，并在 commit message 中记录
- **pyrogram fork 在 Python 3.14 下构建/运行失败**：**停下来报告用户**，备选方案：Python 降到 3.13/3.12（修改 `.python-version`、`requires-python`、ruff target-version，重新 lock）

- [ ] **Step 2: pyrogram 兼容性门禁**

Run: `uv run python -c "import pyrogram; print(pyrogram.__version__)"`
Expected: 打印版本号（如 `2.0.106` 或 fork 自定义版本），无异常。失败则按上一条处理。

- [ ] **Step 3: 主模块 import 冒烟**

Run: `uv run python -c "import hermes_telegram_downloader.media_downloader; print('ok')"`
Expected: 打印 `ok`。常见失败：某个 import 漏改 → `ModuleNotFoundError`，回到 Task 5 补齐。

- [ ] **Step 4: Commit（若有 pyproject.toml 调整）**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: 依赖兼容性调整（uv sync 验证通过）"
```

---

### Task 7: pytest 冒烟测试通过

**Files:**
- 无文件修改（纯验证）

- [ ] **Step 1: 运行测试**

Run: `uv run pytest tests/ -v`
Expected: 18 个测试全部 PASS（1 包 + 1 主模块 + 16 子模块）

**可能失败：** 子模块 import 触发旧式顶层导入残留 → 回 Task 5 Step 3 检查。`module.web` import 会创建 Flask app 实例，属正常。

- [ ] **Step 2: 无需 commit（若改了代码则按实际内容提交）**

---

### Task 8: ruff 检查通过

**Files:**
- Modify: `pyproject.toml`（仅当需要调整规则时）

- [ ] **Step 1: 运行 ruff**

Run: `uv run ruff check`
Expected: 无 F821/F823 类错误。若出现 `F821 undefined name`，说明 import 改写遗漏，修复对应文件（不是改配置）。

- [ ] **Step 2: 若存在难以立即修复的存量 F 类错误**

在 `pyproject.toml` 的 `[tool.ruff.lint]` 的 `ignore` 列表追加对应规则码（只加忽略，不改业务代码），并在 commit message 说明。改完重跑 `uv run ruff check` 必须通过。

- [ ] **Step 3: Commit（若有配置调整）**

```bash
git add pyproject.toml
git commit -m "chore: ruff 存量规则豁免"
```

---

### Task 9: 更新 run_local.py

**Files:**
- Modify: `run_local.py:15-18`

- [ ] **Step 1: 修改 template/static 路径**

把：

```python
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "module", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "module", "static"),
    static_url_path="/module/static",
)
```

改为：

```python
app = Flask(
    __name__,
    template_folder=os.path.join(
        os.path.dirname(__file__),
        "src",
        "hermes_telegram_downloader",
        "module",
        "templates",
    ),
    static_folder=os.path.join(
        os.path.dirname(__file__),
        "src",
        "hermes_telegram_downloader",
        "module",
        "static",
    ),
    static_url_path="/module/static",
)
```

- [ ] **Step 2: 验证开发服务器可启动**

Run: `uv run python run_local.py`
Expected: 输出 `Telegram Media Downloader - Dev Mode` 横幅并监听 5000 端口。浏览器或 `curl http://localhost:5000/get_app_version` 应返回 `2.2.7-dev`。Ctrl+C 停止。

- [ ] **Step 3: Commit**

```bash
git add run_local.py
git commit -m "fix: run_local.py 适配 src 布局路径"
```

---

### Task 10: Dockerfile 与 docker-compose 更新

**Files:**
- Modify: `Dockerfile`（整体重写）
- Modify: `docker-compose.yaml:26-35`（挂载路径）

- [ ] **Step 1: 重写 Dockerfile**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.14-alpine AS build

WORKDIR /app

# Build deps for packages that need compilation
RUN apk add --no-cache --virtual .build-deps gcc musl-dev

# Install python deps (locked) — layer cached until lockfile changes
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project --no-dev

# Install project itself (editable, so bind-mount source override still works)
COPY src ./src
RUN uv sync --locked --no-dev

# Install rclone (runtime binary)
RUN apk add --no-cache rclone


FROM python:3.14-alpine AS runtime

WORKDIR /app

# Copy venv and rclone from build stage
COPY --from=build /app/.venv /app/.venv
COPY --from=build /usr/bin/rclone /app/rclone/rclone

# Copy app source (editable install points here; compose bind mounts override)
COPY src /app/src

CMD ["/app/.venv/bin/python", "-m", "hermes_telegram_downloader"]
```

- [ ] **Step 2: 更新 docker-compose.yaml 挂载路径**

把 `docker-compose.yaml` 第 26-35 行：

```yaml
      # 模块文件覆盖
      - "./module/download_stat.py:/app/module/download_stat.py"
      - "./module/web.py:/app/module/web.py"
      - "./module/templates/index.html:/app/module/templates/index.html"
      - "./module/static:/app/module/static"
      - "./module/bot.py:/app/module/bot.py"
      - "./module/pyrogram_extension.py:/app/module/pyrogram_extension.py"
      - "./module/task_store.py:/app/module/task_store.py"
      - "./module/app.py:/app/module/app.py"
      - "./media_downloader.py:/app/media_downloader.py"
```

改为：

```yaml
      # 模块文件覆盖
      - "./src/hermes_telegram_downloader/module/download_stat.py:/app/src/hermes_telegram_downloader/module/download_stat.py"
      - "./src/hermes_telegram_downloader/module/web.py:/app/src/hermes_telegram_downloader/module/web.py"
      - "./src/hermes_telegram_downloader/module/templates/index.html:/app/src/hermes_telegram_downloader/module/templates/index.html"
      - "./src/hermes_telegram_downloader/module/static:/app/src/hermes_telegram_downloader/module/static"
      - "./src/hermes_telegram_downloader/module/bot.py:/app/src/hermes_telegram_downloader/module/bot.py"
      - "./src/hermes_telegram_downloader/module/pyrogram_extension.py:/app/src/hermes_telegram_downloader/module/pyrogram_extension.py"
      - "./src/hermes_telegram_downloader/module/task_store.py:/app/src/hermes_telegram_downloader/module/task_store.py"
      - "./src/hermes_telegram_downloader/module/app.py:/app/src/hermes_telegram_downloader/module/app.py"
      - "./src/hermes_telegram_downloader/media_downloader.py:/app/src/hermes_telegram_downloader/media_downloader.py"
```

- [ ] **Step 3: Docker 构建验证（可选，取决于本机 Docker 可用性）**

Run: `docker build -t hermes-telegram-downloader:test .`
Expected: 构建成功。若本机无 Docker 或网络受限，跳过并在最终汇报中注明未验证。

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yaml
git commit -m "build: Docker 构建迁移到 uv，compose 挂载适配 src 布局"
```

---

### Task 11: 删除杂项文件与文档更新

**Files:**
- Delete: `package.json`
- Delete: `requirements.txt`
- Modify: `README.md:209-228`、`README_CN.md:209-228`（手动安装/本地开发段落）

- [ ] **Step 1: 删除文件**

```powershell
git rm package.json requirements.txt
```

- [ ] **Step 2: 更新 README.md 与 README_CN.md**

两份文件内容相同段落，把：

```markdown
### 手动安装

```bash
git clone https://github.com/MangoIsIllegal/hermes-telegram-downloader.git
cd hermes-telegram-downloader
pip install -r requirements.txt

cp config.yaml.example config.yaml
# 编辑 config.yaml...

python media_downloader.py
```

### 本地开发模式

```bash
# 无需 Telegram 账号，Mock 数据启动 WebUI
python run_local.py
# 访问 http://localhost:5000
```
```

改为：

```markdown
### 手动安装

需要 [uv](https://docs.astral.sh/uv/) 与 Python 3.14+（uv 会自动管理 Python 版本）：

```bash
git clone https://github.com/MangoIsIllegal/hermes-telegram-downloader.git
cd hermes-telegram-downloader
uv sync

cp config.yaml.example config.yaml
# 编辑 config.yaml...

uv run media-downloader
```

### 本地开发模式

```bash
# 无需 Telegram 账号，Mock 数据启动 WebUI
uv run python run_local.py
# 访问 http://localhost:5000
```
```

同时检查两份 README 中是否还有 `requirements.txt` / `media_downloader.py` 路径的其它引用（Run: `rg -n "requirements|media_downloader\.py" README.md README_CN.md`），如有则按上下文同步更新（如架构说明中的文件路径）。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: 文档更新为 uv 工作流；删除 package.json 与 requirements.txt"
```

---

### Task 12: 最终验证

**Files:**
- 无文件修改（纯验证）

- [ ] **Step 1: 干净环境全量验证**

```powershell
Remove-Item -Recurse -Force .venv
uv sync
uv run pytest tests/ -v
uv run ruff check
uv run python -c "import hermes_telegram_downloader.media_downloader; print('import ok')"
```

Expected: 全部通过

- [ ] **Step 2: 入口命令验证（无 config.yaml 时应给出友好提示而非崩溃）**

Run: `uv run media-downloader`
Expected: `_check_config()` 检测到无 config.yaml，打印提示并退出（不 traceback）；若已有 config.yaml 会真正启动，用 Ctrl+C 停止即可

- [ ] **Step 3: 确认 git 状态干净**

Run: `git status --short`
Expected: 无未提交变更（所有改动已在前面 task 提交）

---

## Self-Review 记录

- **Spec 覆盖：** src 布局（Task 4）、import 改写（Task 5）、pyproject/uv.lock（Task 1-2）、Python 3.14（Task 1）、最新依赖（Task 1-2）、cli() 入口（Task 4）、ruff+pytest（Task 1/3/7/8）、run_local.py（Task 9）、Docker/compose（Task 10）、删文件+文档（Task 11）、验证清单（Task 12）——全覆盖
- **Placeholder 扫描：** 无 TBD；每个代码步骤含完整代码
- **一致性：** 包名统一 `hermes_telegram_downloader`；入口函数统一 `cli`；测试引用的模块路径与 Task 4 迁移结果一致
