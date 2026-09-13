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


def test_resume_offset(tmp_path):
    from hermes_telegram_downloader.module.tg.download import resume_offset

    p = tmp_path / "part.bin"
    p.write_bytes(b"x" * 50)
    assert resume_offset(str(p), 100) == 50
    assert resume_offset(str(p), 50) == 0
    assert resume_offset(str(p), 0) == 0


def test_resume_download_appends(tmp_path):
    from hermes_telegram_downloader.module.tg.download import download_message_media

    dest = tmp_path / "out.bin"
    dest.write_bytes(b"hello")

    class _ResumeClient:
        async def iter_download(self, message, offset=0):
            assert offset == 5
            yield b" world"

        async def download_media(self, *args, **kwargs):
            raise AssertionError("full download should not run")

    msg = SimpleNamespace(id=1, chat_id=1, file=SimpleNamespace(size=11))
    path = asyncio.run(download_message_media(_ResumeClient(), msg, str(dest)))
    assert path == str(dest)
    assert dest.read_bytes() == b"hello world"


def test_iter_chat_messages():
    client = _FakeClient()

    async def _collect():
        return [m.id async for m in iter_chat_messages(client, 123, min_id=5) if m]

    ids = asyncio.run(_collect())
    assert ids == [6]
