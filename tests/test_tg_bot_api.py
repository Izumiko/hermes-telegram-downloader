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
    assert BOT_SESSION_NAME in str(client.session.filename)


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
