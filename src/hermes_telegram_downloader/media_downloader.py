"""Downloads media from telegram."""

import asyncio
import logging
import mimetypes
import os
import shutil
import sys
import time
from functools import wraps

from loguru import logger
from rich.logging import RichHandler
from telethon.errors import FileReferenceExpiredError

from hermes_telegram_downloader.module.app import (
    Application,
    ChatDownloadConfig,
    CloudDriveUploadStat,
    DownloadStatus,
    TaskNode,
)
from hermes_telegram_downloader.module.download_stat import (
    add_failed_download as _add_failed_download,
)
from hermes_telegram_downloader.module.download_stat import (
    load_downloads,
    save_downloads,
    set_chat_title,
    update_download_status,
)
from hermes_telegram_downloader.module.language import _t
from hermes_telegram_downloader.module.task_store import (
    update_download_state,
    update_task_progress,
)
from hermes_telegram_downloader.module.tg.client import (
    USER_SESSION_NAME,
    assert_not_bot_user,
    create_user_client,
    prompt_user_phone,
)
from hermes_telegram_downloader.module.tg.download import download_message_media
from hermes_telegram_downloader.module.tg.errors import (
    is_file_ref_expired,
    is_flood_wait,
    wait_seconds_from_flood,
)
from hermes_telegram_downloader.module.tg.history import iter_chat_messages
from hermes_telegram_downloader.module.web import init_web
from hermes_telegram_downloader.utils.format import truncate_filename, validate_title
from hermes_telegram_downloader.utils.log import LogFilter
from hermes_telegram_downloader.utils.meta import print_meta
from hermes_telegram_downloader.utils.meta_data import MetaData

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler()],
)

CONFIG_NAME = "config.yaml"
DATA_FILE_NAME = "data.yaml"
APPLICATION_NAME = "media_downloader"
app = Application(CONFIG_NAME, DATA_FILE_NAME, APPLICATION_NAME)

queue: asyncio.Queue = None  # Created in main() after event loop starts
RETRY_TIME_OUT = 3

# ── Client connection error tracking & auto-reconnect ──
# When download_media hits connection-level errors (TimeoutError, OSError,
# FILE_REFERENCE_EXPIRED) consecutively, the Telethon session's underlying
# TCP connection is likely in a "half-dead" state — socket is alive but
# no data flows. Auto-reconnect forces disconnect()+connect() to build
# a fresh TCP connection + MTProto session, mirroring the manual fix of
# toggling the v2rayA node.
_client_conn_errors = {"count": 0}
_CLIENT_RECONNECT_THRESHOLD = 10
_client_reconnecting = {"active": False}
_client_last_reconnect = {"time": 0.0}
_CLIENT_RECONNECT_COOLDOWN = 300  # 5 min between reconnect attempts
_MAX_WATCHDOG_RETRIES = 2  # watchdog cancel 后最多重试次数
_watchdog_retry_count = {}  # task_id → 已重试次数
_main_client_ref = {"client": None}  # set in start_server()
_active_downloads = (
    0  # 内存计数器：当前正在下载的任务数（worker pick up +1, 完成/失败/cancel -1）
)
# 替代 get_downloading_tasks() JSON 读写做并发守卫，消除 TOCTOU 竞态

logging.getLogger("telethon.network").addFilter(LogFilter())
logging.getLogger("telethon.client.downloads").addFilter(LogFilter())

logging.getLogger("telethon").setLevel(logging.WARNING)

_download_cache: dict = {}
_unified_flood_wait = {"until": 0.0, "reason": ""}


def _check_download_finish(media_size: int, download_path: str, ui_file_name: str):
    """Check download task if finish"""
    download_size = os.path.getsize(download_path)
    if media_size == download_size:
        logger.success(f"{_t('Successfully downloaded')} - {ui_file_name}")
    else:
        logger.warning(
            f"{_t('Media downloaded with wrong size')}: "
            f"{download_size}, {_t('actual')}: "
            f"{media_size}, {_t('file name')}: {ui_file_name}"
        )
        os.remove(download_path)
        raise FileReferenceExpiredError(None)


def _move_to_download_path(temp_download_path: str, download_path: str):
    """Move file to download path"""
    directory, _ = os.path.split(download_path)
    os.makedirs(directory, exist_ok=True)
    shutil.move(temp_download_path, download_path)


def _check_timeout(retry: int, _: int):
    """Check if message download timeout"""
    if retry == 2:
        return True
    return False


def _can_download(_type: str, file_formats: dict, file_format: str | None) -> bool:
    """Check if the given file format can be downloaded."""
    if _type in ["audio", "document", "video"]:
        allowed_formats: list = file_formats[_type]
        if file_format not in allowed_formats and allowed_formats[0] != "all":
            return False
    return True


def _is_exist(file_path: str) -> bool:
    """Check if a file exists and it is not a directory."""
    return not os.path.isdir(file_path) and os.path.exists(file_path)


def remove_download_cache(chat_id, message_id):
    _download_cache.pop((chat_id, message_id), None)


def record_download_status(func):
    @wraps(func)
    async def inner(client, message, media_types, file_formats, node):
        if (
            _download_cache.get((node.chat_id, message.id))
            is DownloadStatus.Downloading
        ):
            return DownloadStatus.Downloading, None, ""
        _download_cache[(node.chat_id, message.id)] = DownloadStatus.Downloading
        status, file_name, error_message = await func(
            client, message, media_types, file_formats, node
        )
        _download_cache[(node.chat_id, message.id)] = status
        return status, file_name, error_message

    return inner


def get_extension(_file_id, mime_type, dot=True) -> str:
    mime_type = (mime_type or "").lower()
    guessed = mimetypes.guess_extension(mime_type) if mime_type else None
    if guessed:
        ext = guessed.lstrip(".")
        if ext == "jpe":
            ext = "jpg"
    elif mime_type.startswith("image/"):
        ext = "jpg"
    elif mime_type.startswith("video/"):
        ext = "mp4"
    elif mime_type.startswith("audio/ogg"):
        ext = "ogg"
    elif mime_type.startswith("audio/"):
        ext = "mp3"
    else:
        ext = "unknown"
    return f".{ext}" if dot else ext


def _media_mime(media_obj) -> str:
    return getattr(media_obj, "mime_type", None) or ""


def _media_size(media_obj, message=None) -> int:
    size = getattr(media_obj, "file_size", None) or getattr(media_obj, "size", None)
    if size:
        return size
    if message is not None:
        file_obj = getattr(message, "file", None)
        if file_obj is not None and getattr(file_obj, "size", None):
            return file_obj.size
    best = 0
    for item in getattr(media_obj, "sizes", None) or []:
        best = max(best, getattr(item, "size", 0) or 0)
    return best


def _media_file_name(media_obj):
    name = getattr(media_obj, "file_name", None)
    if name:
        return name
    for attr in getattr(media_obj, "attributes", None) or []:
        name = getattr(attr, "file_name", None)
        if name:
            return name
    return None


def _media_attr(media_obj, field):
    value = getattr(media_obj, field, None)
    if value is not None:
        return value
    for attr in getattr(media_obj, "attributes", None) or []:
        if hasattr(attr, field):
            return getattr(attr, field)
    return None


def _message_media_attr(message, _type):
    if _type == "animation":
        return getattr(message, "gif", None) or getattr(message, "animation", None)
    media = getattr(message, _type, None)
    if media is None:
        return None
    if _type == "document" and (
        getattr(message, "video", None)
        or getattr(message, "audio", None)
        or getattr(message, "voice", None)
        or getattr(message, "video_note", None)
        or getattr(message, "gif", None)
        or getattr(message, "sticker", None)
    ):
        return None
    return media


def _message_caption(message):
    caption = getattr(message, "caption", None)
    if caption:
        return caption
    if getattr(message, "media", None):
        return getattr(message, "text", None) or getattr(message, "raw_text", None)
    return None


def _message_grouped_id(message):
    return getattr(message, "media_group_id", None) or getattr(
        message, "grouped_id", None
    )


def _message_caption_entities(message):
    return getattr(message, "caption_entities", None) or getattr(
        message, "entities", None
    )


def _is_empty_message(message) -> bool:
    if message is None:
        return True
    if getattr(message, "empty", False):
        return True
    return type(message).__name__ == "MessageEmpty"


async def fetch_message(client, message):
    chat = getattr(message, "chat_id", None)
    if chat is None:
        chat = getattr(getattr(message, "chat", None), "id", None)
    if chat is None:
        return None
    try:
        return await asyncio.wait_for(
            client.get_messages(chat, ids=message.id),
            timeout=60,
        )
    except Exception:
        return None


def set_meta_data(meta_data: MetaData, message, caption: str = None):
    meta_data.message_date = getattr(message, "date", None)
    if caption:
        meta_data.message_caption = caption
    else:
        meta_data.message_caption = _message_caption(message) or ""
    meta_data.message_id = getattr(message, "id", None)
    from_user = getattr(message, "from_user", None) or getattr(message, "sender", None)
    meta_data.sender_id = (
        getattr(from_user, "id", None) or getattr(message, "sender_id", 0) or 0
    )
    meta_data.sender_name = (
        getattr(from_user, "username", None) if from_user else ""
    ) or ""
    meta_data.reply_to_message_id = (
        getattr(message, "reply_to_message_id", None)
        or getattr(message, "reply_to_msg_id", None)
        or 1
    )
    meta_data.message_thread_id = getattr(message, "message_thread_id", 1)
    media_obj = None
    for kind in meta_data.AVAILABLE_MEDIA:
        media_obj = _message_media_attr(message, kind)
        if media_obj is not None:
            meta_data.media_type = kind
            break
    else:
        return
    meta_data.media_file_name = _media_file_name(media_obj) or ""
    meta_data.media_file_size = _media_size(media_obj, message)
    meta_data.media_width = _media_attr(media_obj, "width") or _media_attr(
        media_obj, "w"
    )
    meta_data.media_height = _media_attr(media_obj, "height") or _media_attr(
        media_obj, "h"
    )
    meta_data.media_duration = _media_attr(media_obj, "duration")
    meta_data.file_extension = get_extension(None, _media_mime(media_obj), False)


async def update_cloud_upload_stat(
    transferred,
    total,
    percentage,
    speed,
    eta,
    node: TaskNode,
    message_id: int,
    file_name: str,
):
    node.cloud_drive_upload_stat_dict[message_id] = CloudDriveUploadStat(
        file_name=file_name,
        transferred=transferred,
        total=total,
        percentage=percentage,
        speed=speed,
        eta=eta,
    )


def _cleanup_temp_file(temp_file_name: str):
    """Remove temp file if it exists."""
    if temp_file_name and os.path.exists(temp_file_name):
        try:
            os.remove(temp_file_name)
        except OSError:
            pass


def _cleanup_stale_temp_files():
    """Remove stale temp files on startup.

    Rules:
    - 0-byte .temp files: always delete (empty shells from failed downloads)
    - Non-zero .temp files: delete if corresponding target file exists in downloads/
    - Empty directories in temp/: delete
    """
    temp_dir = app.temp_save_path
    if not os.path.isdir(temp_dir):
        return

    removed = 0
    for root, dirs, files in os.walk(temp_dir, topdown=False):
        for f in files:
            if not f.endswith(".temp"):
                continue
            temp_path = os.path.join(root, f)
            try:
                file_size = os.path.getsize(temp_path)
            except OSError:
                continue

            if file_size == 0:
                # Empty temp file — always remove
                try:
                    os.remove(temp_path)
                    removed += 1
                except OSError:
                    pass
            else:
                # Non-zero: check if target already exists in downloads/
                # temp path: temp/chat_id/filename.ext.temp
                # target path: downloads/chat_id/filename.ext
                rel_path = os.path.relpath(temp_path, temp_dir)
                # Strip .temp suffix to get the target filename
                target_name = f[:-5] if f.endswith(".temp") else f
                target_path = os.path.join(
                    os.path.abspath("."),
                    "downloads",
                    os.path.dirname(rel_path),
                    target_name,
                )
                if os.path.exists(target_path):
                    try:
                        target_size = os.path.getsize(target_path)
                        if target_size >= file_size:
                            os.remove(temp_path)
                            removed += 1
                    except OSError:
                        pass

        # Remove empty directories
        for d in dirs:
            dir_path = os.path.join(root, d)
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
            except OSError:
                pass

    if removed:
        logger.info(f"Startup cleanup: removed {removed} stale temp files")


async def _get_media_meta(
    chat_id: int | str,
    message,
    media_obj,
    _type: str,
) -> tuple[str, str, str | None]:
    """Extract file name and file id from media object."""
    mime = _media_mime(media_obj)
    if _type in ["audio", "document", "video"]:
        file_format: str | None = mime.split("/")[-1] if mime else None
    else:
        file_format = None

    file_name = None
    temp_file_name = None
    dirname = validate_title(f"{chat_id}")
    chat = getattr(message, "chat", None)
    if chat and getattr(chat, "title", None):
        dirname = validate_title(f"{chat.title}")

    if message.date:
        datetime_dir_name = message.date.strftime(app.date_format)
    else:
        datetime_dir_name = "0"

    if _type in ["voice", "video_note"]:
        file_format = mime.split("/")[-1] if mime else "ogg"
        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)
        media_date = getattr(media_obj, "date", None) or message.date
        file_name = f"{message.id} - {_type}_{media_date.isoformat()}.{file_format}"
        file_name = validate_title(file_name)
        temp_file_name = os.path.join(app.temp_save_path, dirname, file_name)
        file_name = os.path.join(file_save_path, file_name)
    else:
        from hermes_telegram_downloader.module.tg.media import media_filename

        file_name = _media_file_name(media_obj) or media_filename(message)
        caption = _message_caption(message)
        grouped_id = _message_grouped_id(message)

        file_name_suffix = ".unknown"
        if not file_name:
            file_name_suffix = get_extension(None, mime)
            if _type == "photo" and file_name_suffix == ".unknown":
                file_name_suffix = ".jpg"
        else:
            _, file_name_without_suffix = os.path.split(os.path.normpath(file_name))
            file_name, file_name_suffix = os.path.splitext(file_name_without_suffix)
            if not file_name_suffix:
                file_name_suffix = get_extension(None, mime)

        if caption:
            caption = validate_title(caption)
            app.set_caption_name(chat_id, grouped_id, caption)
            app.set_caption_entities(
                chat_id, grouped_id, _message_caption_entities(message)
            )
        else:
            caption = app.get_caption_name(chat_id, grouped_id)

        gen_file_name = (
            app.get_file_name(message.id, file_name, caption) + file_name_suffix
        )
        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)
        temp_file_name = os.path.join(app.temp_save_path, dirname, gen_file_name)
        file_name = os.path.join(file_save_path, gen_file_name)
    return truncate_filename(file_name), truncate_filename(temp_file_name), file_format


def _move_task_to_failed(node, message, error_message):
    """移任务到失败列表 + 清理 placeholder + 从 bot_tasks.json 删除。"""
    try:
        from hermes_telegram_downloader.module.download_stat import (
            add_failed_download,
        )
        from hermes_telegram_downloader.module.download_stat import (
            delete_download_result_entry as _ddre,
        )
        from hermes_telegram_downloader.module.task_store import complete_task as _ct

        if node and node.task_id:
            msg_id = message.id if message else 0
            source_link = ""
            if getattr(node, "source_chat_id", 0) and getattr(
                node, "source_message_id", 0
            ):
                sid = node.source_chat_id
                link_id = str(sid)[4:] if str(sid).startswith("-100") else str(sid)
                source_link = f"https://t.me/c/{link_id}/{node.source_message_id}"
            add_failed_download(
                chat_id=node.chat_id,
                msg_id=msg_id,
                task_id=getattr(node, "task_id_display", str(node.task_id)),
                file_name="",
                error_message=error_message,
                total_size=0,
                source_link=source_link,
                from_user_id=str(getattr(node, "from_user_id", "")) or "",
            )
            _ddre(node.chat_id, msg_id)
            _ct(node.task_id)
            _watchdog_retry_count.pop(node.task_id, None)
    except Exception:
        pass


async def _reset_task_for_retry(node, message):
    """重置 node 状态，准备重新入队下载。"""
    import time as _time

    from hermes_telegram_downloader.module.download_stat import (
        delete_download_result_entry as _ddre,
    )

    # 清理 download_cache，防止 record_download_status 装饰器短路返回 Downloading
    # Cache 对象没有 .pop()，用 remove_download_cache 操作 .store 内部 dict
    remove_download_cache(node.chat_id, message.id)
    # 清理 _download_result placeholder
    _ddre(node.chat_id, message.id)
    # 重置 node 状态
    node.total_task = 0
    node.total_download_task = 0
    node.success_download_task = 0
    node.failed_download_task = 0
    node.skip_download_task = 0
    node.download_status = {}
    node.last_reply_time = _time.time()
    node.last_edit_msg = ""
    node.last_progress_pct = -1
    node.initial_progress_reported = False


async def add_download_task(message, node: TaskNode):
    """Add Download task"""
    if _is_empty_message(message):
        return False
    if queue is None:
        logger.error(
            f"add_download_task: queue is None! msg {message.id} cannot be queued"
        )
        return False
    node.download_status[message.id] = DownloadStatus.Downloading
    await queue.put((message, node))
    node.total_task += 1
    logger.info(
        f"add_download_task: put msg {message.id} into queue (size now {queue.qsize()}), task {getattr(node, 'task_id_display', node.task_id)}"
    )
    return True


async def save_msg_to_file(app, chat_id: int | str, message):
    """Write message text into file"""
    dirname = validate_title(
        message.chat.title if message.chat and message.chat.title else str(chat_id)
    )
    datetime_dir_name = message.date.strftime(app.date_format) if message.date else "0"
    file_save_path = app.get_file_save_path("msg", dirname, datetime_dir_name)
    file_name = os.path.join(
        app.temp_save_path,
        file_save_path,
        f"{app.get_file_name(message.id, None, None)}.txt",
    )
    os.makedirs(os.path.dirname(file_name), exist_ok=True)
    if _is_exist(file_name):
        return DownloadStatus.SkipDownload, None
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(message.text or "")
    return DownloadStatus.SuccessDownload, file_name


async def download_task(client, message, node: TaskNode):
    """Download and Forward media"""
    download_status, file_name, error_message = await download_media(
        client, message, app.media_types, app.file_formats, node
    )
    # Backfill source_chat_title from cache (populated during download_media)
    if not node.source_chat_title and getattr(node, "source_chat_id", 0):
        from hermes_telegram_downloader.module.download_stat import (
            get_chat_title as _gct,
        )

        cached = _gct(node.source_chat_id)
        if cached:
            node.source_chat_title = cached
    if app.enable_download_txt and message.text and not message.media:
        download_status, file_name = await save_msg_to_file(app, node.chat_id, message)
    if not node.bot:
        app.set_download_id(node, message.id, download_status)
    node.download_status[message.id] = download_status
    if download_status is not DownloadStatus.Downloading:
        node.stat(download_status)
    file_size = os.path.getsize(file_name) if file_name else 0
    # Record failed downloads to the failed list for webui display
    if download_status is DownloadStatus.FailedDownload:
        # Get task_id_display (format: MMDD-N)
        task_id_display = getattr(node, "task_id_display", "") or str(node.task_id)
        # Build source link from node or message
        source_link = ""
        if getattr(node, "source_chat_id", 0) and getattr(node, "source_message_id", 0):
            # For forwarded messages, use source channel link
            source_id = node.source_chat_id
            if str(source_id).startswith("-100"):
                link_id = str(source_id)[4:]
            else:
                link_id = str(source_id)
            source_link = f"https://t.me/c/{link_id}/{node.source_message_id}"
        elif message and message.chat:
            # For direct messages, use current message link
            chat_id_for_link = message.chat.id
            if hasattr(message.chat, "username") and message.chat.username:
                source_link = f"https://t.me/{message.chat.username}/{message.id}"
            else:
                if str(chat_id_for_link).startswith("-100"):
                    link_id = str(chat_id_for_link)[4:]
                else:
                    link_id = str(chat_id_for_link)
                source_link = f"https://t.me/c/{link_id}/{message.id}"
        _add_failed_download(
            chat_id=node.chat_id,
            msg_id=message.id if message else 0,
            task_id=task_id_display,
            file_name=file_name or "",
            error_message=error_message or "下载失败",
            total_size=file_size,
            source_link=source_link,
            from_user_id=getattr(node, "from_user_id", "") or "",
        )
        # Remove from active download list so it doesn't stay in WebUI forever
        from hermes_telegram_downloader.module.download_stat import (
            delete_download_result_entry as _ddre,
        )

        _ddre(node.chat_id, message.id if message else 0)
    elif download_status is DownloadStatus.SkipDownload:
        # Remove placeholder from active download list
        from hermes_telegram_downloader.module.download_stat import (
            delete_download_result_entry as _ddre,
        )

        _ddre(node.chat_id, message.id if message else 0)
    try:
        from hermes_telegram_downloader.module.tg.send import send_downloaded

        if (
            node.upload_telegram_chat_id
            and download_status is DownloadStatus.SuccessDownload
            and file_name
        ):
            caption = (
                getattr(message, "caption", None)
                or getattr(message, "text", None)
                or ""
            )
            if caption and app.is_match_advertisement(caption):
                caption = ""
            reply_to = getattr(getattr(node, "reply_to_message", None), "id", None)
            await send_downloaded(
                node.upload_user if node.upload_user else client,
                node.upload_telegram_chat_id,
                file_name,
                caption=caption,
                reply_to=reply_to,
            )
    except ImportError:
        pass
    if (
        not node.upload_telegram_chat_id
        and download_status is DownloadStatus.SuccessDownload
    ):
        ui_file_name = file_name
        if app.hide_file_name:
            ui_file_name = f"****{os.path.splitext(file_name)[-1]}"
        if await app.upload_file(
            file_name, update_cloud_upload_stat, (node, message.id, ui_file_name)
        ):
            node.upload_success_count += 1
    try:
        from hermes_telegram_downloader.module.tg.bot_api import report_bot_status

        if node.bot:
            await report_bot_status(node.bot, node)
    except ImportError:
        pass
    # Send final status with full stats immediately for single downloads
    if node.bot and node.is_finish() and not node.is_stop_transmission:
        try:
            from hermes_telegram_downloader.module.tg.bot_api import report_bot_status

            await report_bot_status(node.bot, node, immediate_reply=True)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(
                f"Failed to send final bot status for task {node.task_id}: {e}"
            )
        try:
            from hermes_telegram_downloader.module.task_store import (
                complete_task as _ct,
            )

            _ct(node.task_id)
        except Exception as e:
            logger.warning(f"Failed to complete task {node.task_id}: {e}")


@record_download_status
async def download_media(
    client,
    message,
    media_types: list[str],
    file_formats: dict,
    node: TaskNode,
):
    """Download media from Telegram. Each file retried 3 times with 5s delay.
    Returns: (DownloadStatus, file_name, error_message)
    """
    file_name: str = ""
    ui_file_name: str = ""
    _task_start_time: float = time.time()
    media_size = 0
    _media = None
    error_message = ""  # Track specific error reason
    # Skip the initial fetch_message — the pending consumer already called
    # get_messages seconds ago, so the file reference is fresh. The extra
    # get_messages call here was causing indefinite blocks when TG rate-limits
    # the same chat. If the file reference does expire during download, the
    # retry loop below will call fetch_message to refresh it.

    # Cache chat title from message object
    if message and message.chat:
        chat_title = getattr(message.chat, "title", None) or getattr(
            message.chat, "first_name", None
        )
        if chat_title:
            set_chat_title(message.chat.id, chat_title)
    try:
        for _type in media_types:
            _media = _message_media_attr(message, _type)
            if _media is None:
                continue
            file_name, temp_file_name, file_format = await _get_media_meta(
                node.chat_id, message, _media, _type
            )
            media_size = _media_size(_media, message)
            ui_file_name = file_name
            if app.hide_file_name:
                ui_file_name = f"****{os.path.splitext(file_name)[-1]}"

            if _can_download(_type, file_formats, file_format):
                if _is_exist(file_name):
                    file_size = os.path.getsize(file_name)
                    if media_size > 0 and file_size >= media_size:
                        logger.info(
                            f"id={message.id} {ui_file_name} "
                            f"{_t('already download,download skipped')}."
                        )
                        return DownloadStatus.SkipDownload, None, ""
                    elif 0 < file_size < media_size:
                        os.makedirs(os.path.dirname(temp_file_name), exist_ok=True)
                        os.replace(file_name, temp_file_name)
                        logger.info(
                            f"id={message.id} {ui_file_name} "
                            f"partial file {file_size}/{media_size}, resuming"
                        )
            else:
                return DownloadStatus.SkipDownload, None, ""
            break
    except Exception as e:
        logger.error(
            f"Message[{message.id}]: "
            f"{_t('could not be downloaded due to following exception')}:\n[{e}].",
            exc_info=True,
        )
        return DownloadStatus.SkipDownload, None, ""
    if _media is None:
        logger.warning(
            f"Message[{message.id}]: no media found in message, skipping download"
        )
        return DownloadStatus.SkipDownload, None, ""

    message_id = message.id
    total_wait = 0
    for retry in range(3):
        try:
            temp_download_path = await download_message_media(
                client,
                message,
                temp_file_name,
                progress_callback=lambda c, t, _n=node, _m=message, _c=client: (
                    update_download_status(c, t, _n, _m, _c)
                ),
            )
            if temp_download_path and isinstance(temp_download_path, str):
                _check_download_finish(media_size, temp_download_path, ui_file_name)
                await asyncio.sleep(0.5)
                _move_to_download_path(temp_download_path, file_name)
                # 清除 .bak 备份（下载成功）
                bak_path = file_name + ".bak"
                if os.path.exists(bak_path):
                    try:
                        os.remove(bak_path)
                    except OSError:
                        pass
                _client_conn_errors["count"] = 0  # Reset on success
                return DownloadStatus.SuccessDownload, file_name, ""
            else:
                # download_media returned None or non-str — Telethon couldn't fetch
                # without raising. Log details and set error_message for user.
                reason = (
                    "下载返回为空"
                    if temp_download_path is None
                    else f"下载返回类型异常: {type(temp_download_path).__name__}"
                )
                logger.warning(
                    f"Message[{message.id}] {ui_file_name}: "
                    f"client.download_media returned {repr(temp_download_path)}, "
                    f"retry {retry + 1}/3"
                )
                error_message = reason
                await asyncio.sleep(RETRY_TIME_OUT)
                message = await fetch_message(client, message)
                if message is None:
                    logger.error(
                        f"Message[{message_id}] {ui_file_name}: fetch_message returned None, message may be deleted"
                    )
                    error_message = "消息不存在或已被删除"
                    break
                if _check_timeout(retry, message.id):
                    logger.error(
                        f"Message[{message.id}] {ui_file_name}: "
                        f"download_media returned None/empty after 3 retries."
                    )
                    if error_message:
                        error_message = f"{error_message}（重试3次后失败）"
        except Exception as err:
            if is_file_ref_expired(err):
                _cleanup_temp_file(temp_file_name)
                logger.warning(
                    f"Message[{message.id}]: {_t('file reference expired, refetching')}..."
                )
                error_message = "文件引用过期"
                _client_conn_errors["count"] += 1
                if await _maybe_reconnect_client():
                    error_message = "文件引用过期（触发客户端重连）"
                await asyncio.sleep(RETRY_TIME_OUT)
                message = await fetch_message(client, message)
                if message is None:
                    logger.error(
                        f"Message[{message_id}] {ui_file_name}: fetch_message returned None (file ref expired), message may be deleted"
                    )
                    error_message = "消息不存在或已被删除（文件引用过期）"
                    break
                if _check_timeout(retry, message.id):
                    logger.error(
                        f"Message[{message.id}]: {_t('file reference expired for 3 retries, download skipped.')}"
                    )
                    error_message = "文件引用过期（重试3次后失败）"
                continue
            if is_flood_wait(err):
                _cleanup_temp_file(temp_file_name)
                wait_s = wait_seconds_from_flood(err)
                # 累计 FloodWait 超过600 秒则不再等待
                total_wait += wait_s
                if total_wait > 600:
                    logger.error(
                        f"Message[{message.id}]: {_t('FloodWait total timeout exceeded, download skipped.')}"
                    )
                    error_message = f"频率限制总超时，累计等待{total_wait}秒"
                    break
                _unified_flood_wait["until"] = time.time() + wait_s + 5
                _unified_flood_wait["reason"] = (
                    f"download_media FloodWait {wait_s}s (msg {message.id})"
                )
                if (
                    total_wait == wait_s
                    and node
                    and node.bot
                    and getattr(node, "from_user_id", "")
                ):
                    try:
                        notify_text = (
                            "⏳ 下载遇到 TG 限速\n"
                            f"任务: {getattr(node, 'task_id_display', str(node.task_id))}\n"
                            f"文件: {ui_file_name}\n"
                            f"需等待 {wait_s} 秒后自动重试"
                        )
                        await node.bot.send_message(int(node.from_user_id), notify_text)
                    except Exception:
                        pass
                await asyncio.sleep(wait_s)
                logger.info(
                    "Message[{}]: FlowWait {}s, waiting (total={}s)",
                    message.id,
                    wait_s,
                    total_wait,
                )
                error_message = f"频率限制，等待{wait_s}秒"
                _check_timeout(retry, message.id)
                if node and node.bot and getattr(node, "from_user_id", ""):
                    try:
                        resume_text = (
                            "✅ 限速恢复，继续下载\n"
                            f"任务: {getattr(node, 'task_id_display', str(node.task_id))}\n"
                            f"文件: {ui_file_name}"
                        )
                        await node.bot.send_message(int(node.from_user_id), resume_text)
                    except Exception:
                        pass
                continue
            if isinstance(err, TypeError):
                _cleanup_temp_file(temp_file_name)
                logger.warning(
                    f"{_t('Timeout Error occurred when downloading Message')}[{message.id}], "
                    f"{_t('retrying after')} {RETRY_TIME_OUT} {_t('seconds')}"
                )
                error_message = "下载超时"
                await asyncio.sleep(RETRY_TIME_OUT)
                if _check_timeout(retry, message.id):
                    logger.error(
                        f"Message[{message.id}]: {_t('Timing out after 3 reties, download skipped.')}"
                    )
                    error_message = "下载超时（重试3次后失败）"
                continue
            if isinstance(err, TimeoutError):
                _cleanup_temp_file(temp_file_name)
                backoff = [60, 120, 300][min(retry, 2)]
                _unified_flood_wait["until"] = time.time() + backoff + 5
                _unified_flood_wait["reason"] = f"连接超时疑似限速 (msg {message.id})"
                _client_conn_errors["count"] += 1
                if await _maybe_reconnect_client():
                    backoff = 5
                if (
                    retry == 0
                    and node
                    and node.bot
                    and getattr(node, "from_user_id", "")
                ):
                    try:
                        notify_text = (
                            "⏸️ TG 连接超时，疑似限速\n"
                            f"任务: {getattr(node, 'task_id_display', str(node.task_id))}\n"
                            f"文件: {ui_file_name}\n"
                            f"暂停 {backoff} 秒后自动重试\n"
                            f"原因: Request timed out (非FloodWait)"
                        )
                        await node.bot.send_message(int(node.from_user_id), notify_text)
                    except Exception:
                        pass
                await asyncio.sleep(backoff)
                try:
                    message = await fetch_message(client, message)
                except Exception as fetch_err:
                    logger.warning(
                        f"Message[{message.id}]: fetch_message 也超时: {fetch_err}"
                    )
                error_message = f"连接超时疑似限速（等待{backoff}秒后重试）"
                continue
            if isinstance(err, OSError):
                _cleanup_temp_file(temp_file_name)
                err_str = str(err).lower()
                if "timed out" in err_str or "timeout" in err_str:
                    backoff = [60, 120, 300][min(retry, 2)]
                    _unified_flood_wait["until"] = time.time() + backoff + 5
                    _unified_flood_wait["reason"] = (
                        f"连接超时疑似限速 (msg {message.id})"
                    )
                else:
                    backoff = 10 * (2**retry)
                _client_conn_errors["count"] += 1
                if await _maybe_reconnect_client():
                    backoff = 5
                logger.warning(
                    f"Message[{message.id}] {ui_file_name}: connection error ({type(err).__name__}), "
                    f"retry {retry + 1}/3 after {backoff}s backoff"
                )
                error_message = f"连接错误: {str(err)[:80]}"
                await asyncio.sleep(backoff)
                message = await fetch_message(client, message)
                if message is None:
                    logger.error(
                        f"Message[{message_id}] {ui_file_name}: fetch_message returned None after connection error"
                    )
                    error_message = "连接错误后消息不可用"
                    break
                if _check_timeout(retry, message.id):
                    logger.error(
                        f"Message[{message.id}] {ui_file_name}: connection failed after 3 retries"
                    )
                    error_message = "连接错误（重试3次后失败）"
                continue
            _cleanup_temp_file(temp_file_name)
            error_str = str(err)
            if "doesn't contain any downloadable media" in error_str:
                logger.warning(
                    f"Message[{message.id}] {ui_file_name}: stale file reference "
                    f"(no downloadable media), refreshing message (retry {retry + 1}/3)"
                )
                error_message = "文件引用过期，正在刷新消息"
                await asyncio.sleep(RETRY_TIME_OUT)
                message = await fetch_message(client, message)
                if message is None:
                    logger.error(
                        f"Message[{message_id}] {ui_file_name}: fetch_message returned None (stale file ref)"
                    )
                    error_message = "文件引用过期且消息不可用"
                    break
                if _check_timeout(retry, message.id):
                    logger.error(
                        f"Message[{message.id}] {ui_file_name}: "
                        f"still no downloadable media after 3 retries with message refresh"
                    )
                    error_message = "文件引用过期（刷新消息后重试3次仍失败）"
                continue
            logger.error(
                f"Message[{message.id}]: "
                f"{_t('could not be downloaded due to following exception')}:\n[{err}].",
                exc_info=True,
            )
            error_message = f"下载异常: {error_str[:100]}"
            break
    # 修复：失败前检查文件是否已落盘
    # 场景1: Telethon 已将文件写入 temp 但在返回前抛了异常
    if temp_file_name and os.path.exists(temp_file_name):
        temp_size = os.path.getsize(temp_file_name)
        if media_size > 0 and temp_size >= media_size:
            try:
                _move_to_download_path(temp_file_name, file_name)
                logger.info(
                    f"Message[{message.id}] {ui_file_name}: 下载实际已完成(temp {temp_size}字节)"
                )
                return DownloadStatus.SkipDownload, file_name, ""
            except Exception as e:
                logger.warning(f"Message[{message.id}]: 移动已完成文件失败: {e}")
    _cleanup_temp_file(temp_file_name)
    # 场景2: 目标文件已存在（可能被并发任务或之前的成功下载写入）
    if file_name and _is_exist(file_name):
        file_size = os.path.getsize(file_name)
        if media_size > 0 and file_size >= media_size:
            logger.info(
                f"Message[{message.id}] {ui_file_name}: 文件已存在({file_size}字节)，标记为跳过"
            )
            return DownloadStatus.SkipDownload, None, ""
    # Log the specific failure reason before returning
    final_reason = error_message or "下载失败（未知原因）"
    logger.warning(
        f"Message[{message.id}] {ui_file_name}: download failed after 3 retries, reason: {final_reason}"
    )
    return DownloadStatus.FailedDownload, None, final_reason


def _load_config():
    """Load config"""
    app.load_config()


def _check_config() -> bool:
    """Check config"""
    print_meta(logger)
    try:
        _load_config()

        log_level = str(app.log_level).upper()
        logger.remove()
        logger.add(sys.stderr, level=log_level)
        logger.add(
            os.path.join(app.log_file_path, "tdl.log"),
            rotation="10 MB",
            retention="30 days",
            level=log_level,
        )

        logger.add(
            os.path.join(app.log_file_path, "download.log"),
            rotation="10 MB",
            retention="30 days",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
        )

        load_downloads()
    except Exception as e:
        logger.exception(f"load config error: {e}")
        return False
    return True


async def worker(client):
    """Work for download task

    进度心跳机制：download_task 在独立 Task 中执行，watchdog 每 30s 检查
    _task_heartbeat。如果某任务超过 _TASK_HEARTBEAT_TIMEOUT(300s) 没有任何
    Telethon 进度回调，说明连接已死（不是慢），cancel 该任务释放 worker。
    慢下载（有进度回调）不受影响。
    """
    from hermes_telegram_downloader.module.download_stat import (
        _TASK_HEARTBEAT_TIMEOUT,
        clear_task_heartbeat,
        get_task_heartbeat_age,
    )

    while app.is_running:
        global _active_downloads
        try:
            logger.info("Worker waiting for queue item...")
            item = await queue.get()
            message = item[0]
            node: TaskNode = item[1]
            _active_downloads += 1  # 并发计数 +1
            logger.info(
                f"Worker picked up message {message.id} from chat {node.chat_id} for task {node.task_id_display} (active={_active_downloads})"
            )
            _requeued = (
                False  # 标记是否重新入队（重新入队时不 decrement，因为新 worker 会 +1）
            )
            # Mark task as actively downloading (no longer pending/in-queue)
            if node.task_id:
                try:
                    from hermes_telegram_downloader.module.bot import _bot

                    _bot._in_queue.discard(node.task_id)
                except ImportError:
                    pass
                update_download_state(node.task_id, "downloading")
            if node.is_stop_transmission:
                continue

            target_client = node.client if node.client else client
            composite_key = f"{node.chat_id}_{message.id}"

            # 用 Task 包裹 download_task，配合心跳 watchdog 检测死连接
            dl_task = asyncio.create_task(download_task(target_client, message, node))
            dl_task_start = time.time()
            _MAX_TASK_RUNTIME = 300  # 5分钟最大运行时间（心跳从未设置时的后备超时）
            watchdog_triggered = False
            user_stopped = False
            try:
                while not dl_task.done():
                    await asyncio.wait({dl_task}, timeout=1.0)
                    if dl_task.done():
                        break
                    if node.is_stop_transmission:
                        dl_task.cancel()
                        user_stopped = True
                        break
                    age = get_task_heartbeat_age(composite_key)
                    runtime = time.time() - dl_task_start
                    if age > _TASK_HEARTBEAT_TIMEOUT or (
                        age < 0 and runtime > _MAX_TASK_RUNTIME
                    ):
                        logger.error(
                            f"Worker: task {node.task_id_display} (msg {message.id}) "
                            f"no progress for {int(age)}s (>{_TASK_HEARTBEAT_TIMEOUT}s), "
                            f"cancelling — likely dead TCP connection"
                        )
                        dl_task.cancel()
                        watchdog_triggered = True
                        break
                # 等待 dl_task 完成（正常结束或 cancel）
                await dl_task
                # 正常完成 → 清理重试计数
                _watchdog_retry_count.pop(node.task_id, None)
            except asyncio.CancelledError:
                # dl_task 被 cancel 时 await 会抛 CancelledError
                if user_stopped or node.is_stop_transmission:
                    logger.info(
                        f"Worker: task {node.task_id_display} cancelled by stop_transmission"
                    )
                elif watchdog_triggered:
                    logger.warning(
                        f"Worker: task {node.task_id_display} cancelled by heartbeat watchdog"
                    )
                    # 心跳超时说明 TCP 连接已死，递增错误计数
                    _client_conn_errors["count"] += 3
                    # 同步等待重连结果（不是 fire-and-forget）
                    reconnect_ok = await _maybe_reconnect_client(force=True)
                    retry_count = _watchdog_retry_count.get(node.task_id, 0)
                    if reconnect_ok and retry_count < _MAX_WATCHDOG_RETRIES:
                        # 重连成功 + 还有重试次数 → 重新入队
                        _watchdog_retry_count[node.task_id] = retry_count + 1
                        logger.info(
                            f"Worker: requeue task {node.task_id_display} "
                            f"(retry {retry_count + 1}/{_MAX_WATCHDOG_RETRIES}) after watchdog cancel + reconnect"
                        )
                        await _reset_task_for_retry(node, message)
                        clear_task_heartbeat(composite_key)
                        node.total_task = 1
                        node.is_running = True
                        await queue.put((message, node))
                        _requeued = True
                        continue
                    else:
                        # 重连失败或重试次数用完 → 移到失败列表
                        if not reconnect_ok:
                            err_msg = "下载超时被watchdog取消（重连失败）"
                        else:
                            err_msg = f"下载超时被watchdog取消（重试{_MAX_WATCHDOG_RETRIES}次后仍失败）"
                        logger.warning(
                            f"Worker: moving task {node.task_id_display} to failed: {err_msg}"
                        )
                        _move_task_to_failed(node, message, err_msg)
                else:
                    raise
            finally:
                clear_task_heartbeat(composite_key)
        except Exception as e:
            logger.exception(
                f"Worker exception for task {getattr(node, 'task_id_display', '?')}: {e}"
            )
            # ConnectionError 说明 client 已 stopped，先尝试重连+重试
            error_str = str(e)
            if (
                "Client has not been started" in error_str
                or "ConnectionError" in error_str
            ):
                _client_conn_errors["count"] += 3
                reconnect_ok = await _maybe_reconnect_client(force=True)
                retry_count = _watchdog_retry_count.get(node.task_id, 0)
                if reconnect_ok and retry_count < _MAX_WATCHDOG_RETRIES:
                    _watchdog_retry_count[node.task_id] = retry_count + 1
                    logger.info(
                        f"Worker: requeue task {node.task_id_display} "
                        f"(retry {retry_count + 1}/{_MAX_WATCHDOG_RETRIES}) after exception + reconnect"
                    )
                    await _reset_task_for_retry(node, message)
                    clear_task_heartbeat(
                        f"{node.chat_id}_{message.id}" if message else ""
                    )
                    node.total_task = 1
                    node.is_running = True
                    if message:
                        await queue.put((message, node))
                    _requeued = True
                    continue
            # 移到失败列表
            _move_task_to_failed(node, message, f"Worker异常: {error_str[:80]}")
        finally:
            # 并发计数 -1（重新入队的除外，新 worker 会 +1）
            if not _requeued:
                _active_downloads -= 1


async def download_chat_task(
    client, chat_download_config: ChatDownloadConfig, node: TaskNode
):
    """Download all task"""
    messages_iter = iter_chat_messages(
        client,
        node.chat_id,
        min_id=chat_download_config.last_read_message_id,
        max_id=node.end_offset_id or 0,
    )
    chat_download_config.node = node
    if chat_download_config.ids_to_retry:
        logger.info(f"{_t('Downloading files failed during last run')}...")
        try:
            skipped_messages: list = await asyncio.wait_for(
                client.get_messages(
                    node.chat_id, ids=chat_download_config.ids_to_retry
                ),
                timeout=120,  # 批量获取加 120s 超时，防止半死 TCP 上 hang 15分钟
            )
        except TimeoutError:
            logger.error(
                f"download_chat_task: get_messages timeout (120s) for {len(chat_download_config.ids_to_retry)} "
                f"retry messages in chat {node.chat_id}, skipping retry this run"
            )
            skipped_messages = []
        if skipped_messages is None:
            skipped_messages = []
        elif not isinstance(skipped_messages, list):
            skipped_messages = [skipped_messages]
        for message in skipped_messages:
            await add_download_task(message, node)
    async for message in messages_iter:
        # 让出控制权，避免阻塞 handler
        await asyncio.sleep(0)

        # Cache chat title from message
        if message and message.chat:
            chat_title = getattr(message.chat, "title", None) or getattr(
                message.chat, "first_name", None
            )
            if chat_title:
                set_chat_title(message.chat.id, chat_title)
        meta_data = MetaData()
        caption = _message_caption(message)
        grouped_id = _message_grouped_id(message)
        if caption:
            caption = validate_title(caption)
            app.set_caption_name(node.chat_id, grouped_id, caption)
            app.set_caption_entities(
                node.chat_id, grouped_id, _message_caption_entities(message)
            )
        else:
            caption = app.get_caption_name(node.chat_id, grouped_id)
        set_meta_data(meta_data, message, caption)
        if app.need_skip_message(chat_download_config, message.id):
            continue
        if app.exec_filter(chat_download_config, meta_data):
            if message.media:  # Only add to download queue if message has media
                await add_download_task(message, node)
        else:
            node.download_status[message.id] = DownloadStatus.SkipDownload
        # Update task progress for crash recovery
        update_task_progress(node.task_id, message.id)
        # 降低 last_read_message_id 更新频率：每 200 条消息持久化一次
        # 这样崩溃时最多重复扫描 200 条，而不是每条都更新
        chat_download_config.last_read_message_id = max(
            chat_download_config.last_read_message_id, message.id
        )
        if message.id % 200 == 0:
            app.update_config(immediate=True)
    # 扫描结束后保存最终位置，确保重启时从正确位置继续
    chat_download_config.need_check = True
    chat_download_config.total_task = node.total_task
    node.is_running = True
    app.update_config(immediate=True)


async def download_all_chat(client):
    """Download All chat"""
    from hermes_telegram_downloader.module.task_store import save_task as _save_task

    for key, value in app.chat_download_config.items():
        value.node = TaskNode(chat_id=key)
        _save_task(
            task_id=value.node.task_id,
            chat_id=key,
            url="",
            start_offset_id=value.last_read_message_id,
            end_offset_id=0,
            limit=0,
            download_filter=value.download_filter,
            from_user_id=0,
            task_type="config",
        )
        try:
            await download_chat_task(client, value, value.node)
        except Exception as e:
            logger.warning(f"Download {key} error: {e}")
        finally:
            value.need_check = True
            from hermes_telegram_downloader.module.task_store import complete_task

            complete_task(value.node.task_id)


async def run_until_all_task_finish():
    """Normal download"""
    while True:
        finish = all(
            value.need_check and value.total_task == value.finish_task
            for _, value in app.chat_download_config.items()
        )
        if (not app.bot_token and finish) or app.restart_program:
            break
        await asyncio.sleep(1)


def _exec_loop():
    """Exec loop"""
    app.loop.run_until_complete(run_until_all_task_finish())


async def start_server(client):
    """Start the server"""
    _main_client_ref["client"] = client
    await client.start(phone=prompt_user_phone)
    me = await client.get_me()
    assert_not_bot_user(me)
    logger.info(f"User session logged in as {getattr(me, 'username', None) or me.id}")


async def _reconnect_client():
    """Force-reconnect the main Telethon client to recover from half-dead TCP sessions.

    disconnect() kills the stale TCP connection, connect()/start() builds a fresh
    one using the existing session file (no re-auth needed if still authorized).
    """
    client = _main_client_ref["client"]
    if client is None:
        logger.error("Cannot reconnect: no client reference")
        return False

    _client_reconnecting["active"] = True
    try:
        logger.warning("Client auto-reconnect: disconnect()...")
        try:
            await asyncio.wait_for(client.disconnect(), timeout=30)
        except TimeoutError:
            logger.error("client.disconnect() timed out after 30s, force disconnect")
            _force_release_session_lock(client)
        except Exception as e:
            logger.warning(
                f"client.disconnect() during reconnect failed (continuing): {e}"
            )
            _force_release_session_lock(client)

        logger.warning("Client auto-reconnect: connect()...")
        try:
            await asyncio.wait_for(client.connect(), timeout=30)
            if not await client.is_user_authorized():
                await asyncio.wait_for(client.start(), timeout=30)
            logger.success(
                "Client reconnected successfully — fresh TCP session established"
            )
            _client_conn_errors["count"] = 0
            return True
        except TimeoutError:
            logger.error("client.connect() timed out after 30s, reconnect failed")
            return False
        except Exception as e:
            error_str = str(e)
            if "database is locked" in error_str:
                logger.warning(
                    "client.connect() failed with database is locked, forcing release and retrying..."
                )
                _force_release_session_lock(client)
                try:
                    await asyncio.wait_for(client.connect(), timeout=30)
                    if not await client.is_user_authorized():
                        await asyncio.wait_for(client.start(), timeout=30)
                    logger.success(
                        "Client reconnected successfully on retry — fresh TCP session established"
                    )
                    _client_conn_errors["count"] = 0
                    return True
                except Exception as e2:
                    logger.error(f"client.connect() retry also failed: {e2}")
            logger.error(f"client.connect() during reconnect failed: {e}")
            return False
    finally:
        _client_reconnecting["active"] = False


def _force_release_session_lock(client):
    """强制释放 Telethon session SQLite 锁文件。"""
    try:
        session_path = os.path.join(
            app.session_file_path, USER_SESSION_NAME + ".session"
        )
        for suffix in ["-journal", "-wal", "-shm"]:
            f = session_path + suffix
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"Removed stale SQLite file: {f}")
        logger.info("Reset client session lock files for clean restart")
    except Exception as e:
        logger.warning(f"Failed to release session lock: {e}")


async def _maybe_reconnect_client(force=False):
    """Check if consecutive connection errors warrant a client reconnect.

    Returns True if client is currently connected (either was already connected,
    or reconnect succeeded). Returns False if reconnect failed or was skipped.

    Args:
        force: If True, skip cooldown check (used by watchdog cancel which
               has already determined the connection is dead).
    """
    if _client_conn_errors["count"] < _CLIENT_RECONNECT_THRESHOLD and not force:
        # Below threshold and not forced — assume client is fine
        return True

    if _client_reconnecting["active"]:
        logger.debug("Reconnect already in progress, skipping")
        # Another reconnect is in progress — wait for it to finish, then check result
        # Can't wait here (would block), so return False to be safe
        # Caller will move task to failed, which is correct — task can be retried later
        return False

    now = time.time()
    if not force and now - _client_last_reconnect["time"] < _CLIENT_RECONNECT_COOLDOWN:
        logger.debug(
            f"Reconnect cooldown active ({int(_CLIENT_RECONNECT_COOLDOWN - (now - _client_last_reconnect['time']))}s remaining), skipping"
        )
        # In cooldown — don't reconnect, but check if client is still connected
        client = _main_client_ref.get("client")
        flag = getattr(client, "is_connected", False) if client else False
        if callable(flag):
            try:
                flag = flag()
            except Exception:
                flag = False
        if client and flag:
            return True
        return False

    logger.warning(
        f"Client connection errors reached {_client_conn_errors['count']} "
        f"(threshold {_CLIENT_RECONNECT_THRESHOLD}) — triggering auto-reconnect"
    )
    _client_last_reconnect["time"] = now
    success = await _reconnect_client()
    if not success:
        # Reconnect failed — retry sooner (60s instead of full cooldown)
        _client_last_reconnect["time"] = now - _CLIENT_RECONNECT_COOLDOWN + 60
        return False
    return True


async def stop_server(client):
    """Stop the server"""
    await client.disconnect()


def main():
    """Main function"""
    tasks = []
    client = create_user_client(app)
    try:
        app.pre_run()
        _cleanup_stale_temp_files()
        init_web(app)
        app.loop.run_until_complete(start_server(client))
        # Create queue AFTER event loop is running to ensure it binds to the
        # correct loop. Creating asyncio.Queue at module import time (before
        # loop starts) can cause put/get to use different loop references,
        # resulting in workers never receiving items.
        global queue
        queue = asyncio.Queue()
        logger.success(_t("Successfully started (Press Ctrl+C to stop)"))
        app.loop.create_task(download_all_chat(client))
        # Worker 数量 = max_download_task，物理上限制并发
        # 之前硬编码 6 个 worker，并发守卫有竞态时直接放行超量任务
        _MAX_WORKERS = max(1, getattr(app, "max_download_task", 2))
        logger.info(
            f"Starting {_MAX_WORKERS} workers (max_download_task={_MAX_WORKERS})"
        )
        for _ in range(_MAX_WORKERS):
            tasks.append(app.loop.create_task(worker(client)))
        if app.bot_token:
            from hermes_telegram_downloader.module.bot import (
                start_download_bot,
                stop_download_bot,
            )

            app.loop.run_until_complete(
                start_download_bot(app, client, add_download_task, download_chat_task)
            )
        _exec_loop()
    except KeyboardInterrupt:
        logger.info(_t("KeyboardInterrupt"))
    except Exception as e:
        logger.exception("{}", e)
    finally:
        app.is_running = False
        save_downloads()
        if app.bot_token:
            try:
                from hermes_telegram_downloader.module.bot import stop_download_bot

                app.loop.run_until_complete(stop_download_bot())
            except Exception:
                pass
        app.loop.run_until_complete(stop_server(client))
        for task in tasks:
            task.cancel()
        logger.info(_t("Stopped!"))
        logger.info(f"{_t('update config')}......")
        app.update_config()
        logger.success(
            f"{_t('Updated last read message_id to config file')},"
            f"{_t('total download')} {app.total_download_task}, "
            f"{_t('total upload file')} {app.cloud_drive_config.total_upload_success_file_count}"
        )


def cli():
    """Console script / module entry point."""
    if _check_config():
        main()


if __name__ == "__main__":
    cli()
