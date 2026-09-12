import os

from telethon import TelegramClient

USER_SESSION_NAME = "media_downloader_telethon"
BOT_SESSION_NAME = "media_downloader_bot_telethon"


def proxy_from_config(proxy: dict | None) -> dict | None:
    if not proxy:
        return None
    scheme = proxy.get("scheme") or proxy.get("proxy_type")
    host = proxy.get("hostname") or proxy.get("addr")
    port = proxy.get("port")
    if not scheme or not host or not port:
        return None
    return {
        "proxy_type": scheme,
        "addr": host,
        "port": int(port),
        "username": proxy.get("username"),
        "password": proxy.get("password"),
    }


def create_user_client(app) -> TelegramClient:
    os.makedirs(app.session_file_path, exist_ok=True)
    session_path = os.path.join(app.session_file_path, USER_SESSION_NAME)
    return TelegramClient(
        session_path,
        api_id=int(app.api_id),
        api_hash=str(app.api_hash),
        proxy=proxy_from_config(app.proxy) or None,
        flood_sleep_threshold=0,
    )


def create_bot_client(app) -> TelegramClient:
    os.makedirs(app.session_file_path, exist_ok=True)
    session_path = os.path.join(app.session_file_path, BOT_SESSION_NAME)
    return TelegramClient(
        session_path,
        api_id=int(app.api_id),
        api_hash=str(app.api_hash),
        proxy=proxy_from_config(app.proxy) or None,
        flood_sleep_threshold=0,
    )
