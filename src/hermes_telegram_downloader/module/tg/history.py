async def iter_chat_messages(client, chat_id, min_id=0, max_id=0, reverse=True):
    kwargs = {"min_id": min_id, "reverse": reverse}
    if max_id:
        kwargs["max_id"] = max_id
    async for message in client.iter_messages(chat_id, **kwargs):
        yield message
