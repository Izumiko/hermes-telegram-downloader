import asyncio
from types import SimpleNamespace

from hermes_telegram_downloader.module.tg.download import download_message_media
from hermes_telegram_downloader.module.tg.history import iter_chat_messages


class _FakeClient:
    def __init__(self):
        self.downloaded = []
        self.refetched = []

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


def test_download_message_media_calls_telethon():
    client = _FakeClient()
    msg = SimpleNamespace(id=7, chat_id=1)
    path = asyncio.run(download_message_media(client, msg, "out.bin"))
    assert path == "out.bin"
    assert client.downloaded == [(7, "out.bin")]


def test_iter_chat_messages():
    client = _FakeClient()

    async def _collect():
        return [m.id async for m in iter_chat_messages(client, 123, min_id=5)]

    ids = asyncio.run(_collect())
    assert ids == [6]
