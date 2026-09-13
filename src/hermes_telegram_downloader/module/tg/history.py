from hermes_telegram_downloader.module.tg.compat import wrap_message


def _raw(client):
    return getattr(client, "_c", client)


async def iter_chat_messages(
    client, chat_id, min_id=0, max_id=0, reverse=True, limit=None
):
    kwargs = {"min_id": min_id, "reverse": reverse}
    if max_id:
        kwargs["max_id"] = max_id
    if limit:
        kwargs["limit"] = limit
    async for message in _raw(client).iter_messages(chat_id, **kwargs):
        if message is None:
            continue
        yield wrap_message(message)
