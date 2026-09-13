import inspect
import os

from hermes_telegram_downloader.module.tg.errors import is_file_ref_expired


def resume_offset(path, total) -> int:
    if not path or not total or total <= 0 or not os.path.exists(path):
        return 0
    size = os.path.getsize(path)
    if 0 < size < total:
        return size
    return 0


def _media_total_size(message) -> int:
    file_obj = getattr(message, "file", None)
    return int(getattr(file_obj, "size", 0) or 0)


async def _emit_progress(progress_callback, current, total):
    if not progress_callback:
        return
    result = progress_callback(current, total)
    if inspect.isawaitable(result):
        await result


async def _resume_download(
    client, message, file_path, offset, total, progress_callback
):
    raw = getattr(client, "_c", client)
    downloaded = offset
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    with open(file_path, "ab") as out:
        async for chunk in raw.iter_download(message, offset=offset):
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            await _emit_progress(progress_callback, downloaded, total)
    return file_path


async def download_message_media(
    client, message, file_path, progress_callback=None, retries=3
):
    last_err = None
    total = _media_total_size(message)
    for attempt in range(retries):
        try:
            offset = resume_offset(file_path, total)
            if offset:
                return await _resume_download(
                    client, message, file_path, offset, total, progress_callback
                )
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
                    total = _media_total_size(message)
                continue
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("download failed")
