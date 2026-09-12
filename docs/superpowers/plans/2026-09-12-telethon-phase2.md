# Telethon 迁移阶段 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot 用 Telethon 第二个 client 响应下载类命令与媒体/链接；转发/listen 回复「尚未迁移」。

**Architecture:** `create_bot_client` + `events.NewMessage` 分发；用薄代理把 `send_message`/`get_messages`/`get_chat` 对齐旧调用，避免重写 2700 行业务逻辑。

**Tech Stack:** Telethon events、现有 DownloadBot / task_store

**规格:** `docs/superpowers/specs/2026-09-12-telethon-migration-design.md` 阶段 2

---

### Task 1: Bot client + parse_link + retry

**Files:** `module/tg/client.py`, `module/tg/bot_api.py`, `tests/test_tg_bot_api.py`

- [ ] create_bot_client(app) → session `media_downloader_bot_telethon`，`flood_sleep_threshold=0`
- [ ] parse_link(client, link_str) 用 extract_info_from_link；comment_id 时 get_entity 取 linked_chat（没有则退回 group_id）
- [ ] retry() 捕获 FloodWaitError
- [ ] fetch_message(client, chat_id, message_id)
- [ ] 测试后 commit

### Task 2: 消息包装 + Bot/User client 代理

**Files:** `module/tg/compat.py`

- [ ] wrap_message：from_user.id、text、media、forward_from_chat/id
- [ ] BotClientProxy：send_message 把 reply_to_message_id→reply_to，ParseMode→html；stop→disconnect
- [ ] UserClientProxy：get_messages(chat, id) 两参；get_chat→get_entity
- [ ] 测试后 commit

### Task 3: bot.py 改 Telethon 事件分发

- [ ] 去掉 pyrogram import
- [ ] start() 用 create_bot_client + start(bot_token=)
- [ ] 一个 NewMessage：白名单；/forward 等回复尚未迁移；其余走原 handler
- [ ] 不注册 listen_forward
- [ ] 重连 disconnect/connect，不重新 add_handler
- [ ] smoke 恢复 import bot
- [ ] commit

### Task 4: 接回 media_downloader；WebUI parse_link

- [ ] 调用 start_download_bot / stop_download_bot
- [ ] web.py parse_link 改 tg.bot_api
- [ ] pytest + ruff
- [ ] commit
