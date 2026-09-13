import asyncio
from types import SimpleNamespace

from hermes_telegram_downloader.module.tg.bot_api import parse_link, retry
from hermes_telegram_downloader.module.tg.client import (
    BOT_SESSION_NAME,
    create_bot_client,
)
from hermes_telegram_downloader.module.tg.compat import wrap_message


def test_bot_session_name():
    assert BOT_SESSION_NAME == "media_downloader_bot_telethon"


def test_create_bot_client_uses_bot_session(tmp_path):
    app = SimpleNamespace(
        session_file_path=str(tmp_path),
        api_id="1",
        api_hash="hash",
        proxy={},
    )
    client = create_bot_client(app)
    session = client.session
    assert session is not None
    assert BOT_SESSION_NAME in str(session.filename)


def test_parse_link_public():
    class _C:
        async def get_entity(self, _):
            raise AssertionError("should not resolve")

    group, post, topic = asyncio.run(parse_link(_C(), "https://t.me/somechannel/42"))
    assert group == "somechannel"
    assert post == 42
    assert topic is None or topic == 0


def test_parse_link_private_c():
    class _C:
        async def get_entity(self, _):
            raise AssertionError("should not resolve")

    group, post, _ = asyncio.run(parse_link(_C(), "https://t.me/c/1234567890/7"))
    assert group == -1001234567890
    assert post == 7


def test_retry_success():
    n = {"i": 0}

    async def fn():
        n["i"] += 1
        return "ok"

    assert asyncio.run(retry(fn, max_attempts=2, wait_second=0)) == "ok"
    assert n["i"] == 1


def test_wrap_message_sender():
    raw = SimpleNamespace(
        id=9,
        message="hello",
        media=None,
        sender_id=111,
        fwd_from=None,
    )
    w = wrap_message(raw)
    assert w.id == 9
    assert w.text == "hello"
    assert w.from_user.id == 111
    assert w.media is None


def test_build_bot_status_text_shows_progress():
    from hermes_telegram_downloader.module.tg.bot_api import build_bot_status_text

    node = SimpleNamespace(task_id=1, task_id_display="0913-1", chat_id=10)
    result = {
        10: {
            99: {
                "task_id": 1,
                "task_id_display": "0913-1",
                "file_name": "cat.png",
                "total_size": 1000,
                "down_byte": 400,
                "download_speed": 100,
            }
        }
    }
    text = build_bot_status_text(node, result)
    assert "0913-1" in text
    assert "cat.png" in text
    assert "40%" in text


def test_pending_consumer_starts_without_recovery_tasks():
    from hermes_telegram_downloader.module.bot import DownloadBot

    bot = DownloadBot()

    class _Loop:
        def __init__(self):
            self.n = 0

        def create_task(self, coro):
            self.n += 1
            coro.close()

    bot.app = SimpleNamespace(loop=_Loop())
    bot._ensure_pending_consumer()
    assert bot._pending_loop_started is True
    assert bot.app.loop.n == 1
    bot._ensure_pending_consumer()
    assert bot.app.loop.n == 1
