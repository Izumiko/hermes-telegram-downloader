import os

from telethon import TelegramClient

USER_SESSION_NAME = "media_downloader_telethon"
BOT_SESSION_NAME = "media_downloader_bot_telethon"
USER_SESSION_BOT_ERROR = (
    "用户客户端当前是 Bot 账号。请删除 "
    f"sessions/{USER_SESSION_NAME}.session 后重新运行，"
    "登录时输入手机号（不要填写 bot token）。Bot token 只用于 config.yaml 的 bot_token。"
)


def looks_like_bot_token(value: str) -> bool:
    if not value or ":" not in value:
        return False
    prefix, _, _token = value.strip().partition(":")
    return prefix.isdigit() and len(prefix) >= 5


def prompt_user_phone() -> str:
    value = input("请输入手机号（不要填写 bot token）: ").strip()
    if looks_like_bot_token(value):
        raise ValueError(USER_SESSION_BOT_ERROR)
    return value


def assert_not_bot_user(me) -> None:
    if getattr(me, "bot", False):
        raise RuntimeError(USER_SESSION_BOT_ERROR)


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
