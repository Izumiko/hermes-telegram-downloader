# uv 现代化改造设计文档

日期：2026-09-12
状态：已获用户批准（含修正：Python 3.14 + 依赖升级最新）

## 背景

当前项目是扁平布局的旧式 Python 工程：

- `media_downloader.py`（主入口，约 1331 行）在根目录
- `module/`、`utils/` 两个包在根目录
- 依赖由 `requirements.txt` 管理（含一个 GitHub zip 直连的 pyrogram fork）
- Dockerfile 用 pip 安装依赖
- 根目录有一个疑似误提交的 `package.json`（内容为无关的 Hermes Agent electron 项目）

目标：改造为 uv 管理的现代 Python 工程（src 布局）。

## 决策记录

| 决策点 | 结论 |
|---|---|
| 目录结构 | 迁移到 src 布局 |
| 包名 | `hermes_telegram_downloader` |
| Python 版本 | 3.14（`.python-version`、`requires-python`、Docker 基础镜像统一） |
| 依赖版本 | 尽量升级到最新（见下文例外） |
| 开发工具链 | ruff + pytest（dev 依赖组） |
| Docker | 构建与运行都改用 uv |
| 杂项文件 | 删除 `package.json` 和 `requirements.txt` |

## 目标目录结构

```
hermes-telegram-downloader/
├── pyproject.toml              # 元数据 + 依赖 + ruff/pytest 配置
├── uv.lock                     # uv 生成的锁定文件（提交到 git）
├── .python-version             # 3.14（需从 .gitignore 中解除忽略）
├── src/
│   └── hermes_telegram_downloader/
│       ├── __init__.py
│       ├── __main__.py         # 支持 python -m hermes_telegram_downloader
│       ├── media_downloader.py # 原根目录主入口文件
│       ├── module/             # 原 module/ 整体迁入（含 static/ templates/）
│       └── utils/              # 原 utils/ 整体迁入
├── tests/                      # pytest 骨架 + import 冒烟测试
├── run_local.py                # 保留根目录，内部路径指向 src/
├── Dockerfile                  # 改用 uv 构建
├── docker-compose.yaml         # 挂载路径同步更新
├── config.yaml.example
├── docs/、README.md、README_CN.md、DEPLOY.md（运行命令同步更新）
└── （删除 package.json、requirements.txt）
```

## import 改写

约 41 处，纯机械替换：

- `from module.xxx import ...` → `from hermes_telegram_downloader.module.xxx import ...`
- `from utils.xxx import ...` / `import utils` → `from hermes_telegram_downloader.utils.xxx import ...` / `from hermes_telegram_downloader import utils`
- `module/__init__.py`、`utils/__init__.py` 内容也需检查同步
- Flask 的 `static_folder='static'` / templates 基于模块 `__name__` 相对解析，`module/` 整体搬迁后无需改动
- 不改任何业务逻辑

## pyproject.toml

- `name = "hermes-telegram-downloader"`，`requires-python = ">=3.14"`
- 构建后端：`hatchling`（uv 默认，src 布局零配置）
- 依赖：不写死版本，给名称或最低版本约束，由 `uv lock` 解析最新并锁定到 `uv.lock`
  - **例外 1**：pyrogram 保持 GitHub fork 直连 `https://github.com/tangyoha/pyrogram/archive/refs/heads/patch.zip`（项目依赖该 fork 的补丁，上游不可用）
  - **例外 2**：`PyYAML==5.3.1` 必须升级（在 3.11+ 无 wheel 且源码构建与 Cython 3 不兼容），升到最新 6.x
  - **风险**：旧 pin（如 rich 12.x、flask 2.x）升到最新可能有 API 变化。处理策略：升级后跑冒烟验证（import 全部模块 + `python -m` 入口启动到读配置阶段），若发现不兼容则对该依赖加回上限约束并在文档中记录
- `[project.scripts]`：`media-downloader = "hermes_telegram_downloader.media_downloader:cli"`
  - 需在 `media_downloader.py` 新增 `cli()` 包装函数（现有 `_check_config()` 只在 `__main__` 块调用，console script 不会触发）：
    ```python
    def cli():
        if _check_config():
            main()
    ```
  - `__main__` 块改为调用 `cli()`
- `[dependency-groups]` dev：`ruff`、`pytest`
- `[tool.ruff]`：`target-version = "py314"`，基础规则集（E/F/I），对存量代码只要求新配置可用，不做大规模格式化
- `[tool.pytest.ini_options]`：`testpaths = ["tests"]`

## 入口与运行方式

- 本地运行：`uv run media-downloader`（等价 `uv run python -m hermes_telegram_downloader`）
- 前端调试：`uv run python run_local.py`（`run_local.py` 保留在根目录，内部 template/static 路径改指 `src/hermes_telegram_downloader/module/...`）
- config.yaml / data.yaml / log/ / sessions/ / temp/ 等运行时路径基于 CWD，从项目根运行行为不变

## Docker

- 构建阶段：`ghcr.io/astral-sh/uv:python3.14-alpine`，`uv sync --locked`（保留 gcc/musl-dev 编译依赖，保留 rclone 安装）
- 运行阶段：拷贝 `.venv` 与 `src`，项目以 editable 方式安装（uv 默认），保证 docker-compose 挂载单个源码文件覆盖的现有调试工作流继续生效
- CMD：`/app/.venv/bin/python -m hermes_telegram_downloader`
- docker-compose.yaml 挂载路径同步改为 `./src/hermes_telegram_downloader/module/...:/app/src/hermes_telegram_downloader/module/...`

## 测试与验证

- `tests/` 新增冒烟测试：import 包及关键子模块
- 验证清单：
  1. `uv sync` 成功
  2. `uv run python -c "import hermes_telegram_downloader.media_downloader"` 成功（已确认 `Application.__init__` 不做文件 IO，import 时无 config.yaml 不会崩溃）
  3. `uv run ruff check` 通过
  4. `uv run pytest` 通过
  5. `docker build` 成功（可选，视本机 Docker 可用性）

## 文档同步

- README.md / README_CN.md 快速开始、DEPLOY.md 中的 `pip install -r requirements.txt`、`python media_downloader.py` 等命令更新为 uv 等价命令

## 明确不做

- 不拆分 `media_downloader.py`（1331 行）的内部结构
- 不改动任何业务逻辑、配置格式、数据文件格式
- 不引入 mypy / pre-commit
- 不大规模格式化存量代码
