from types import SimpleNamespace

from hermes_telegram_downloader.module.tg.media import (
    PLACEHOLDER_FILE_NAME,
    media_filename,
    resolve_result_file_name,
)


def test_media_filename_from_file():
    msg = SimpleNamespace(file=SimpleNamespace(name="cat.png"), document=None)
    assert media_filename(msg) == "cat.png"


def test_media_filename_from_document_attribute():
    msg = SimpleNamespace(
        file=None,
        document=SimpleNamespace(
            file_name=None,
            attributes=[SimpleNamespace(file_name="orig.jpg")],
        ),
        video=None,
        audio=None,
        photo=None,
    )
    assert media_filename(msg) == "orig.jpg"


def test_resolve_replaces_placeholder():
    msg = SimpleNamespace(id=9, file=SimpleNamespace(name="a.png"), document=None)
    assert resolve_result_file_name(PLACEHOLDER_FILE_NAME, msg) == "a.png"


def test_resolve_keeps_real_name():
    msg = SimpleNamespace(id=9, file=SimpleNamespace(name="a.png"))
    assert resolve_result_file_name("kept.bin", msg) == "kept.bin"
