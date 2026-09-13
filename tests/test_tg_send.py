from types import SimpleNamespace

from hermes_telegram_downloader.module.tg.send import is_bot_user, is_protected_chat


def test_is_protected_chat():
    assert is_protected_chat(SimpleNamespace(noforwards=True))
    assert not is_protected_chat(SimpleNamespace())
    assert not is_protected_chat(SimpleNamespace(noforwards=False))


def test_is_bot_user():
    assert is_bot_user(SimpleNamespace(bot=True))
    assert not is_bot_user(SimpleNamespace(bot=False))
    assert not is_bot_user(SimpleNamespace())
