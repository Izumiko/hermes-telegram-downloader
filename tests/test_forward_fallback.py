import asyncio
from types import SimpleNamespace

from hermes_telegram_downloader.module.bot import fetch_media_message
from hermes_telegram_downloader.module.tg.compat import wrap_message


def test_fetch_media_message_returns_none_on_error():
    class _C:
        async def get_messages(self, *_args, **_kwargs):
            raise ValueError("Could not find the input entity")

    assert asyncio.run(fetch_media_message(_C(), -1001, 9, timeout=1)) is None


def test_fetch_media_message_skips_no_media():
    class _C:
        async def get_messages(self, *_args, **_kwargs):
            return SimpleNamespace(id=9, media=None)

    assert asyncio.run(fetch_media_message(_C(), -1001, 9, timeout=1)) is None


def test_fetch_media_message_ok():
    msg = SimpleNamespace(id=9, media=object())

    class _C:
        async def get_messages(self, chat_id, msg_id):
            assert chat_id == -1001
            assert msg_id == 9
            return msg

    assert asyncio.run(fetch_media_message(_C(), -1001, 9, timeout=1)) is msg


def test_wrap_message_forward_requires_peer_id():
    raw = SimpleNamespace(
        id=3,
        message="",
        media=object(),
        sender_id=111,
        fwd_from=SimpleNamespace(channel_post=88, from_id=None, from_name="x"),
    )
    w = wrap_message(raw)
    assert w.forward_from_chat is None
    assert w.forward_from_message_id == 88
