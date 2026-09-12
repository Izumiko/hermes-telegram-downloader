from hermes_telegram_downloader.module.tg.errors import is_file_ref_expired


async def download_message_media(client, message, file_path, progress_callback=None, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            return await client.download_media(
                message,
                file=file_path,
                progress_callback=progress_callback,
            )
        except Exception as err:
            last_err = err
            if is_file_ref_expired(err) and attempt + 1 < retries:
                chat = getattr(message, "chat_id", None) or getattr(
                    getattr(message, "chat", None), "id", None
                )
                refreshed = await client.get_messages(chat, ids=message.id)
                if refreshed:
                    message = refreshed
                continue
            raise
    raise last_err
