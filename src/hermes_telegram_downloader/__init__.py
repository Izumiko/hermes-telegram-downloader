"""Hermes Telegram Downloader."""

import asyncio

__version__ = "1.0.0"

# pyrogram.sync 在 import 时调用 asyncio.get_event_loop()。
# Python 3.12+ 无当前 loop 时会抛 RuntimeError，预先设置一个。
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
