from hermes_telegram_downloader.module.tg.compat import wrap_message


def _raw(client):
    return getattr(client, "_c", client)


def _caption(message) -> str:
    return (
        getattr(message, "caption", None)
        or getattr(message, "text", None)
        or getattr(message, "message", None)
        or ""
    )


async def forward_one(client, dest, message, from_chat, reply_to=None):
    raw = _raw(client)
    kwargs = {}
    if reply_to:
        kwargs["top_msg_id"] = reply_to
    return await raw.forward_messages(dest, message.id, from_chat, **kwargs)


async def send_downloaded(client, dest, file_path, caption="", reply_to=None):
    raw = _raw(client)
    return await raw.send_file(
        dest, file_path, caption=caption or None, reply_to=reply_to
    )


async def get_discussion_message(client, chat_id, message_id):
    from telethon.tl.functions.messages import GetDiscussionMessageRequest

    raw = _raw(client)
    result = await raw(GetDiscussionMessageRequest(peer=chat_id, msg_id=message_id))
    if result.messages:
        return wrap_message(result.messages[0])
    return None


def is_protected_chat(entity) -> bool:
    return bool(getattr(entity, "noforwards", False))


def is_bot_user(entity) -> bool:
    return bool(getattr(entity, "bot", False))
