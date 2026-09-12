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

    try:
        err = FileReferenceExpiredError()
    except TypeError:
        err = FileReferenceExpiredError(None)
    assert is_file_ref_expired(err)
    assert not is_file_ref_expired(RuntimeError("x"))
