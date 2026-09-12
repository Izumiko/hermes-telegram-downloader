# Pyrogram → Telethon 迁移设计文档

日期：2026-09-12
状态：已获用户批准（分阶段保功能；三阶段写进同一份规格；阶段间允许 Bot/转发暂不可用）

参考实现：`D:\WorkSpace\HobbyProjects\telegram_media_downloader`（Telethon 1.38+ 重写）

## 背景

Hermes 当前依赖已停更的 `tangyoha/pyrogram` fork（zip 直连）+ `pytgcrypto`。该 fork 在 Python 3.14 下 `asyncio.get_event_loop()` 会在 import 时崩溃，已用包 `__init__.py` 垫片绕过。参考 fork 已完成 Pyrogram → Telethon 迁移，但那是一次**简化重写**（批量下载 + 收件箱 Bot），不含 Hermes 的转发、listen_forward、相册重传、统一 FloodWait、WebUI 任务系统。

本项目目标：在**不砍 Hermes 功能**的前提下换成 Telethon，分三阶段落地；阶段之间 Bot/转发可以暂不可用，不长期双栈。

## 决策记录

| 决策点 | 结论 |
|---|---|
| 范围 | 分阶段保功能，不简化成参考 fork |
| 规格 | 三阶段写进同一份规格，实现按阶段提交 |
| 过渡期 | 不双栈。阶段 1 完成后仅批量下载可用；Bot/转发等后续阶段 |
| 架构 | 客户端门面 + Telethon 后端，上层不再直接 import pyrogram/telethon 类型（尽量） |
| Session | 不转换旧 Pyrogram session；新文件名；首次重新登录 |
| WebUI | 不改外观，不引入 NiceGUI；只改 Telegram 调用点 |
| 配置 | 不改 config.yaml 业务字段 |

## 目标架构

```
src/hermes_telegram_downloader/
├── module/
│   ├── tg/                      # 新增：Telegram 适配层
│   │   ├── __init__.py
│   │   ├── client.py            # 创建用户/Bot TelegramClient、proxy、session
│   │   ├── download.py          # download_media + 进度 + file-ref 刷新
│   │   ├── history.py           # iter_messages 替代 get_chat_history_v2
│   │   ├── errors.py            # FloodWait / FileReferenceExpired 映射
│   │   └── send.py              # 阶段 3：发送/相册/转发
│   ├── pyrogram_extension.py    # 逐步掏空后删除
│   ├── get_chat_history_v2.py   # 阶段 1 后删除
│   └── send_media_group_v2.py   # 阶段 3 后删除
```

上层（`media_downloader.py` / `bot.py` / `web.py` / `download_stat.py`）只依赖 `module.tg` 与现有业务模块，不直接依赖 pyrogram。

## 依赖

删除：

- `pyrogram @ https://github.com/tangyoha/pyrogram/archive/refs/heads/patch.zip`
- `pytgcrypto`

新增：

- `telethon>=1.38`
- `cryptg`（下载加速，与参考 fork 一致）
- `python-socks[asyncio]` + `pysocks`（代理）

删除 `src/hermes_telegram_downloader/__init__.py` 里为 pyrogram.sync 准备的 event-loop 垫片（Telethon 不需要）。

## Session 与登录

| 角色 | 新路径 | 登录 |
|---|---|---|
| 用户客户端 | `sessions/media_downloader_telethon.session` | `await client.start()`（首次验证码） |
| Bot 客户端 | `sessions/media_downloader_bot_telethon.session` | `await client.start(bot_token=...)`（阶段 2） |

- 旧 `sessions/media_downloader.session` / `media_downloader_bot.session` **保留不删、不读取**
- Docker 仍挂载 `./sessions:/app/sessions`
- Proxy：把现有 Pyrogram 形状 `{scheme, hostname, port, username?, password?}` 转成 Telethon `{proxy_type, addr, port, username, password}`

## 进度、暂停、FloodWait、重连

| 原 Pyrogram | Telethon |
|---|---|
| `progress=` + `progress_args=` | `progress_callback(current, total)`，用闭包带 node/task 上下文 |
| `client.stop_transmission()` | `asyncio.Task.cancel()`（WebUI 暂停/删除走这条） |
| `FloodWait.value` + `_unified_flood_wait` | 捕获 `FloodWaitError`，**关闭** Telethon 自动 sleep（`flood_sleep_threshold=0` 或等价），继续用现有统一冷却 + WebUI 展示 |
| `HookClient.stop()/start()` + sqlite lock 清理 | `disconnect()` / `connect()`；必要时删 Telethon session 的 `-journal/-wal/-shm` |
| `TCP.TIMEOUT = 900` | 映射到 Telethon 连接 timeout / 不补丁 class attribute |
| `Message._parse` ChannelInvalid 垫片 | 阶段 1 删除（无 listen）；阶段 3 Telethon 不预取 reply，通常不需要 |

Watchdog（300s 无进度回调 → cancel）保留，改为监听 Telethon `progress_callback`。

## 阶段 1 — 用户客户端下载

**目标：** `uv run media-downloader` 能用 Telethon 批量下载 config.yaml 里的 chat。Bot/转发/listen 不可用。

包含：

- `module/tg/client.py`：创建用户 `TelegramClient`
- `module/tg/download.py`：`client.download_media(message, file=path, progress_callback=...)`
- `FileReferenceExpiredError`：`get_messages` 刷新后重试（最多 3 次，与现逻辑一致）
- `module/tg/history.py`：`iter_messages(chat_id, min_id=last_read, reverse=True)` 替代 `get_chat_history_v2`
- 改写 `media_downloader.py` 下载管道、worker、reconnect、main()（去掉 TCP / Message._parse 补丁、HookClient）
- `download_stat.py` 进度回调签名适配
- `bot_token` 若配置：打日志「Bot 尚未迁移到 Telethon」并跳过 `start_download_bot`
- 冒烟测试：import `module.tg`、不 import pyrogram
- `pyproject.toml` 换依赖并 `uv lock`

不包含：Bot client、任何 `events.NewMessage`、转发、相册上传。

阶段 1 结束时允许暂时无法 import 的文件：`bot.py` 中 pyrogram 引用可先用条件/延迟导入，或让 `start_download_bot` 直接 return。不要为了编译通过而实现半套 Bot。

## 阶段 2 — Bot 命令与媒体/链接

**目标：** Bot 可响应现有命令中不依赖转发/listen 的部分；WebUI retry 的 `get_messages` / `parse_link` 可用。

包含：

- 第二个 `TelegramClient` + `start(bot_token=)`
- `events.NewMessage` 替代 Pyrogram `MessageHandler` + filters
- 命令：`/start` `/help` `/download` `/get_info` `/set_language` `/add_filter` `/add_ad` `/remove_ad` `/add_replace_ad` `/remove_replace_ad` `/set_ad` `/stop`
- 媒体消息、`t.me` 链接下载（用户 client 解析私有频道，与现逻辑一致：链接走用户会话）
- 白名单 `allowed_user_ids` 在 handler 内检查
- WebUI：`parse_link`、retry `get_messages`、bot `send_message` 通知
- Bot 重连：同一 `TelegramClient` 对象上 `disconnect`/`connect`，handler 保持

不包含：`/forward` `/forward_to_comments` `/listen_forward`、保护内容重传、相册 `SendMultiMedia`。

这些命令若被调用：回复「尚未迁移」而不是崩溃。

## 阶段 3 — 转发与 listen_forward

**目标：** 转发、评论区转发、listen_forward、保护频道下载再上传、相册发送，行为与现网一致。

包含：

- `module/tg/send.py`：`send_file` / 相册列表替代 `send_media_group_v2`
- 保护内容：`has_protected_content` → 下载再上传（不 copy/forward）
- 普通转发：Telethon `forward_messages`（或等价）
- `/forward` `/forward_to_comments`（`GetDiscussionMessage` / reply_to）
- 用户 client `events.NewMessage`：`/listen_forward` + config.yaml 频道监听
- 广告过滤/替换继续作用在 caption 上；caption entity 用 Telethon html/md helpers 重写，不再用 Pyrogram Parser
- 删除 `pyrogram_extension.py`、`get_chat_history_v2.py`、`send_media_group_v2.py` 及所有 pyrogram import
- 测试与文档：README 注明需重新登录；DEPLOY 注明新 session 文件名

## 测试与验证

每阶段结束必须：

1. `uv run pytest tests/ -v` 通过
2. `uv run ruff check` 通过
3. 该阶段相关模块可 import，且代码中不再出现本阶段应删除的 pyrogram API（阶段 3 结束时全仓库 `rg pyrogram` 仅文档/历史提及）

阶段 1 额外：无 config 时 `uv run media-downloader` 仍走 `_check_config` 友好失败。

手工验证（有 session 时）：下一个小频道下载 1–2 个文件，进度出现在 WebUI。

## 明确不做

- 不转换、不覆盖旧 Pyrogram `.session`
- 不引入 NiceGUI、不重做 WebUI
- 不改 config.yaml 业务 schema（chat 列表、过滤器、广告规则等）
- 不拆分 `media_downloader.py` / `bot.py` 的非 Telegram 业务结构（只换调用）
- 阶段 1 不实现 Bot/转发的临时兼容层

## 风险

- Telethon 与 Pyrogram 的 message id / chat id（`-100...`）通常兼容，但 `t.me/c/` 解析必须用 `telethon.utils.get_peer_id` 对齐现 `parse_link`
- 相册/保护内容是语义差距最大处，放在阶段 3，避免阻塞下载主路径
- 首次部署必须重新登录；文档必须写清楚
