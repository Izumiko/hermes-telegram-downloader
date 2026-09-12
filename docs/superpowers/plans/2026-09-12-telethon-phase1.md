# Telethon 迁移阶段 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Telethon 替换用户客户端的批量下载路径（历史遍历、download_media、进度、FloodWait、重连），Bot/转发本阶段不可用。

**Architecture:** 新增 `module/tg/` 适配层（client/download/history/errors）。`media_downloader.py` 改为走该适配层。不双栈。旧 Pyrogram session 不读不删。

**Tech Stack:** Telethon >=1.38、cryptg、python-socks、现有 Flask WebUI / task_store

**规格:** `docs/superpowers/specs/2026-09-12-telethon-migration-design.md`

**工作目录:** `D:\WorkSpace\HobbyProjects\hermes-telegram-downloader`，分支 `uv`

**注意:** 工作区可能有与本迁移无关的未提交改动。每个 commit **只暂存本任务文件**，不要 `git add -A`。

阶段 2/3（Bot、转发、listen）不在本计划内。

---

### Task 1: 替换依赖

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`（`uv lock` 生成）

- [ ] **Step 1: 改 `pyproject.toml` 依赖**

删除：

```toml
    # pyrogram 补丁 fork（上游不可用，保持直连）
    "pyrogram @ https://github.com/tangyoha/pyrogram/archive/refs/heads/patch.zip",
```

和 `"pytgcrypto>=1.2.7",`

在 dependencies 列表加入（保持其余依赖不变）：

```toml
    "telethon>=1.38",
    "cryptg>=0.4",
    "pysocks>=1.7",
    "python-socks[asyncio]>=2.0",
```

删除 `[tool.hatch.metadata] allow-direct-references = true` 整段（不再需要 zip 直连）。

- [ ] **Step 2: 锁定并安装**

Run: `uv lock && uv sync`

Expected: 成功；`uv.lock` 含 telethon、不含 pyrogram/pytgcrypto。

- [ ] **Step 3: 验证 Telethon 可 import**

Run: `uv run python -c "import telethon; print(telethon.__version__)"`

Expected: 打印 1.38+ 版本号，无 traceback。

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: 依赖从 pyrogram 换成 telethon"
```

---

### Task 2: tg 适配层 — proxy 与错误映射（TDD）

**Files:**
- Create: `tests/test_tg_client.py`
- Create: `src/hermes_telegram_downloader/module/tg/__init__.py`
- Create: `src/hermes_telegram_downloader/module/tg/errors.py`
- Create: `src/hermes_telegram_downloader/module/tg/client.py`

- [ ] **Step 1: 写失败测试**

`tests/test_tg_client.py`：

```python
from hermes_telegram_downloader.module.tg.client import proxy_from_config
from hermes_telegram_downloader.module.tg.errors import (
    is_file_ref_expired,
    wait_seconds_from_flood,
)


def test_proxy_from_config_none():
    assert proxy_from_config(None) is None
    assert proxy_from_config({}) is None


def test_proxy_from_config_pyrogram_shape():
    assert proxy_from_config(
        {"scheme": "socks5", "hostname": "127.0.0.1", "port": 1080}
    ) == {
        "proxy_type": "socks5",
        "addr": "127.0.0.1",
        "port": 1080,
        "username": None,
        "password": None,
    }


def test_proxy_keeps_auth():
    out = proxy_from_config(
        {
            "scheme": "http",
            "hostname": "10.0.0.1",
            "port": 8080,
            "username": "u",
            "password": "p",
        }
    )
    assert out["username"] == "u"
    assert out["password"] == "p"


class _Flood:
    seconds = 12


def test_wait_seconds_from_flood():
    assert wait_seconds_from_flood(_Flood()) == 12


class _Expired:
    pass


def test_is_file_ref_expired():
    from telethon.errors import FileReferenceExpiredError

    assert is_file_ref_expired(FileReferenceExpiredError())
    assert not is_file_ref_expired(RuntimeError("x"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_tg_client.py -v`

Expected: FAIL，`ModuleNotFoundError: No module named 'hermes_telegram_downloader.module.tg'`

- [ ] **Step 3: 实现**

`src/hermes_telegram_downloader/module/tg/__init__.py`：

```python
"""Telegram client adapter (Telethon)."""
```

`src/hermes_telegram_downloader/module/tg/errors.py`：

```python
from telethon.errors import FileReferenceExpiredError, FloodWaitError


def wait_seconds_from_flood(err) -> int:
    return int(getattr(err, "seconds", 0) or 0)


def is_file_ref_expired(err) -> bool:
    return isinstance(err, FileReferenceExpiredError)


def is_flood_wait(err) -> bool:
    return isinstance(err, FloodWaitError)
```

`src/hermes_telegram_downloader/module/tg/client.py`：

```python
import os

from telethon import TelegramClient

USER_SESSION_NAME = "media_downloader_telethon"
BOT_SESSION_NAME = "media_downloader_bot_telethon"


def proxy_from_config(proxy: dict | None) -> dict | None:
    if not proxy:
        return None
    scheme = proxy.get("scheme") or proxy.get("proxy_type")
    host = proxy.get("hostname") or proxy.get("addr")
    port = proxy.get("port")
    if not scheme or not host or not port:
        return None
    return {
        "proxy_type": scheme,
        "addr": host,
        "port": int(port),
        "username": proxy.get("username"),
        "password": proxy.get("password"),
    }


def create_user_client(app) -> TelegramClient:
    os.makedirs(app.session_file_path, exist_ok=True)
    session_path = os.path.join(app.session_file_path, USER_SESSION_NAME)
    return TelegramClient(
        session_path,
        api_id=int(app.api_id),
        api_hash=str(app.api_hash),
        proxy=proxy_from_config(app.proxy) or None,
        flood_sleep_threshold=0,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_tg_client.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_tg_client.py src/hermes_telegram_downloader/module/tg/
git commit -m "feat: Telethon 适配层 client/proxy/errors"
```

---

### Task 3: history 与 download 适配（TDD）

**Files:**
- Create: `tests/test_tg_download.py`
- Create: `src/hermes_telegram_downloader/module/tg/history.py`
- Create: `src/hermes_telegram_downloader/module/tg/download.py`

- [ ] **Step 1: 写失败测试**

`tests/test_tg_download.py`：

```python
import asyncio
from types import SimpleNamespace

import pytest

from hermes_telegram_downloader.module.tg.download import download_message_media
from hermes_telegram_downloader.module.tg.history import iter_chat_messages


class _FakeClient:
    def __init__(self):
        self.downloaded = []
        self.refetched = []
        self.fail_first = False

    async def download_media(self, message, file=None, progress_callback=None):
        self.downloaded.append((message.id, file))
        if progress_callback:
            progress_callback(10, 100)
        return file

    async def get_messages(self, entity, ids=None):
        self.refetched.append((entity, ids))
        return SimpleNamespace(id=ids)

    def iter_messages(self, entity, min_id=0, max_id=0, reverse=True):
        async def _gen():
            yield SimpleNamespace(id=min_id + 1)

        return _gen()


@pytest.mark.asyncio
async def test_download_message_media_calls_telethon():
    client = _FakeClient()
    msg = SimpleNamespace(id=7, chat_id=1)
    path = await download_message_media(client, msg, "out.bin")
    assert path == "out.bin"
    assert client.downloaded == [(7, "out.bin")]


@pytest.mark.asyncio
async def test_iter_chat_messages():
    client = _FakeClient()
    ids = [m.id async for m in iter_chat_messages(client, 123, min_id=5)]
    assert ids == [6]
```

若 pytest-asyncio 未安装：不要新增依赖。把测试改成：

```python
def test_download_message_media_calls_telethon():
    client = _FakeClient()
    msg = SimpleNamespace(id=7, chat_id=1)
    path = asyncio.run(download_message_media(client, msg, "out.bin"))
    assert path == "out.bin"
```

（`iter_chat_messages` 同理用 `asyncio.run` 包一层。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_tg_download.py -v`

Expected: FAIL，找不到 `download` / `history` 模块

- [ ] **Step 3: 实现**

`src/hermes_telegram_downloader/module/tg/history.py`：

```python
async def iter_chat_messages(client, chat_id, min_id=0, max_id=0, reverse=True):
    kwargs = {"min_id": min_id, "reverse": reverse}
    if max_id:
        kwargs["max_id"] = max_id
    async for message in client.iter_messages(chat_id, **kwargs):
        yield message
```

`src/hermes_telegram_downloader/module/tg/download.py`：

```python
from hermes_telegram_downloader.module.tg.errors import is_file_ref_expired


async def download_message_media(
    client, message, file_path, progress_callback=None, retries=3
):
    last_err = None
    for attempt in range(retries):
        try:
            return await client.download_media(
                message,
                file=file_path,
                progress_callback=progress_callback,
            )
        except Exception as err:
            last_err = err
            if is_file_ref_expired(err) and attempt + 1 < retries:
                chat = getattr(message, "chat_id", None) or getattr(
                    getattr(message, "chat", None), "id", None
                )
                refreshed = await client.get_messages(chat, ids=message.id)
                if refreshed:
                    message = refreshed
                continue
            raise
    raise last_err
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_tg_download.py tests/test_tg_client.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_tg_download.py src/hermes_telegram_downloader/module/tg/history.py src/hermes_telegram_downloader/module/tg/download.py
git commit -m "feat: Telethon history/download 适配"
```

---

### Task 4: media_downloader 接入 Telethon 用户客户端

**Files:**
- Modify: `src/hermes_telegram_downloader/media_downloader.py`
- Modify: `src/hermes_telegram_downloader/__init__.py`（删除 pyrogram event-loop 垫片）
- Modify: `tests/test_smoke.py`（去掉 pyrogram_extension / get_chat_history_v2 / send_media_group_v2 若它们仍 import pyrogram 导致失败——阶段 1 这些文件可暂留，但 smoke 不要再 import 它们）

- [ ] **Step 1: 删除 `__init__.py` 垫片**

`src/hermes_telegram_downloader/__init__.py` 只保留：

```python
"""Hermes Telegram Downloader."""

__version__ = "1.0.0"
```

- [ ] **Step 2: 改 `main()` 创建客户端**

在 `media_downloader.py`：

- 删除 `import pyrogram` 以及 `from pyrogram.types import ...`（本阶段下载路径改用 Telethon message 对象；媒体类型用 `message.photo` / `message.document` / `message.video` 等 Telethon 属性，在 `_get_media` 处适配，不要再引用 `pyrogram.types.Audio` 等）
- 删除 `from hermes_telegram_downloader.module.pyrogram_extension import HookClient, ...` 中仅用于启动的 HookClient / set_max_concurrent_transmissions。阶段 1 若 `download_media` 仍调用 `fetch_message`，改为 `client.get_messages`
- 删除 `main()` 里 `TCP.TIMEOUT` 补丁和 `Message._parse` ChannelInvalid 补丁整段
- 把 `HookClient("media_downloader", ...)` 换成：

```python
from hermes_telegram_downloader.module.tg.client import create_user_client

client = create_user_client(app)
```

- `start_server`：`await client.start()`（Telethon）
- `stop_server`：`await client.disconnect()`
- 若 `app.bot_token`：打 `logger.warning("Bot 尚未迁移到 Telethon，跳过 start_download_bot")`，**不要**调用 `start_download_bot`

- [ ] **Step 3: 改下载调用**

现有 `client.download_media(message, file_name=..., progress=..., progress_args=...)` 改为：

```python
from hermes_telegram_downloader.module.tg.download import download_message_media


def _progress(current, total, *_, node=node, message=message):
    # 把 current/total 转给现有 download_stat.update_download_status
    update_download_status(current, total, node, message, None)


await download_message_media(
    client,
    message,
    file_name,
    progress_callback=lambda c, t: _progress(c, t),
)
```

`update_download_status` 原签名若仍是 `(down_byte, total_size, client, message, node)`：保留调用，`client` 传 Telethon client；函数内部若调用 `client.stop_transmission()`，改为设置 `node` 上的 cancel 标志或忽略（暂停改为 Task.cancel，见下一 task）。**不要**为对齐而继续依赖 pyrogram Client 类型注解——改成不注解或 `Any`。

- [ ] **Step 4: 改历史遍历**

所有 `get_chat_history_v2(...)` 改为：

```python
from hermes_telegram_downloader.module.tg.history import iter_chat_messages

async for message in iter_chat_messages(
    client, chat_id, min_id=last_read, max_id=end_id or 0
):
    ...
```

保留 last_read / 过滤器 / 入队 worker 的业务逻辑。

- [ ] **Step 5: 改重连**

`_force_release_session_lock` 中 session 路径改为：

```python
from hermes_telegram_downloader.module.tg.client import USER_SESSION_NAME

session_path = os.path.join(app.session_file_path, USER_SESSION_NAME + ".session")
```

删除对 `client.storage.conn` / `client.session.connection` / `client.is_initialized` 的 Pyrogram 内部字段操作。重连改为：

```python
await client.disconnect()
await client.connect()
```

若 `connect` 后未授权：`await client.start()`。

- [ ] **Step 6: 更新 smoke 测试**

`tests/test_smoke.py` 的 `SUBMODULES` 删除：

- `hermes_telegram_downloader.module.pyrogram_extension`
- `hermes_telegram_downloader.module.get_chat_history_v2`
- `hermes_telegram_downloader.module.send_media_group_v2`

加入：

- `hermes_telegram_downloader.module.tg.client`
- `hermes_telegram_downloader.module.tg.download`
- `hermes_telegram_downloader.module.tg.history`

`test_import_main_module` 仍 import `media_downloader` 并断言 `cli` callable。

- [ ] **Step 7: 验证**

Run:

```
uv run pytest tests/ -v
uv run ruff check
uv run python -c "import hermes_telegram_downloader.media_downloader; print('ok')"
```

Expected: pytest 全过；ruff 全过；打印 ok。`media_downloader.py` 中不再 `import pyrogram`。

若 `bot.py` / `web.py` 仍 import pyrogram：阶段 1 **允许**这些文件留着，只要 `media_downloader` 启动路径不执行它们（bot 已跳过）。`test_smoke` 不要 import `module.bot` 若它会因为没有 pyrogram 而失败——若失败，从 SUBMODULES 去掉 `module.bot`，并在测试文件注释「阶段 2 恢复」。

- [ ] **Step 8: Commit**

```bash
git add src/hermes_telegram_downloader/media_downloader.py src/hermes_telegram_downloader/__init__.py tests/test_smoke.py src/hermes_telegram_downloader/module/download_stat.py
git commit -m "feat: 用户客户端下载路径切换到 Telethon"
```

（仅 add 实际改过的文件。）

---

### Task 5: 暂停改为 Task.cancel；文档

**Files:**
- Modify: `src/hermes_telegram_downloader/module/download_stat.py` 和/或 `module/web.py` 中 `stop_transmission` 调用
- Modify: `README.md` 手动安装之后加一句重新登录说明

- [ ] **Step 1: 替换 stop_transmission**

搜索 `stop_transmission`。每一处改为取消对应下载 Task（现有 worker 里的 download task），没有 task 则 no-op。不要调用已不存在的 pyrogram API。

- [ ] **Step 2: README 登录说明**

在「手动安装」`uv run media-downloader` 后加：

```markdown
首次运行会创建 `sessions/media_downloader_telethon.session`，需完成 Telegram 验证码登录。旧的 Pyrogram `.session` 文件不会被读取或覆盖。
```

中英文 README 同步（`README_CN.md` 若有对应段落也改）。

- [ ] **Step 3: 最终验证**

```
uv run pytest tests/ -v
uv run ruff check
uv run python -c "import pyrogram" ; echo exit:$LASTEXITCODE
```

Expected: pytest/ruff 通过。`import pyrogram` 应失败（已卸载）。`rg -n "import pyrogram" src/hermes_telegram_downloader/media_downloader.py` 无匹配。

- [ ] **Step 4: Commit**

```bash
git add src/hermes_telegram_downloader/module/download_stat.py src/hermes_telegram_downloader/module/web.py README.md README_CN.md
git commit -m "fix: 下载暂停改为 Task.cancel；文档注明 Telethon 需重新登录"
```

---

## Self-Review

- 规格阶段 1 覆盖：依赖、session 文件名、proxy、download_media、iter_messages、FloodWait 关自动 sleep、重连、禁用 Bot、删垫片、不转换旧 session、测试
- 阶段 2/3 不在本计划（规格要求分阶段提交）
- 无 TBD；新模块代码完整写出
