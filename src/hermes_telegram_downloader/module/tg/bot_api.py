import asyncio
import os

from loguru import logger

from hermes_telegram_downloader.module.tg.errors import (
    is_flood_wait,
    wait_seconds_from_flood,
)
from hermes_telegram_downloader.utils.format import extract_info_from_link


async def parse_link(client, link_str: str):
    link = extract_info_from_link(link_str)
    if link.comment_id:
        try:
            chat = await client.get_entity(link.group_id)
            linked = getattr(chat, "linked_chat", None) or getattr(
                chat, "linked_chat_id", None
            )
            if linked is not None:
                linked_id = getattr(linked, "id", linked)
                return linked_id, link.comment_id, link.topic_id
        except Exception as e:
            logger.warning(f"parse_link linked_chat failed: {e}")
    return link.group_id, link.post_id, link.topic_id


async def retry(func, args: tuple = (), max_attempts=3, wait_second=15):
    for _ in range(1, max_attempts + 1):
        try:
            return await func(*args)
        except Exception as e:
            if is_flood_wait(e):
                await asyncio.sleep(wait_seconds_from_flood(e) or wait_second)
            else:
                logger.exception("Error: {}", e)
                await asyncio.sleep(wait_second)
    return None


def _task_matches(entry: dict, node) -> bool:
    tid = str(entry.get("task_id", ""))
    display = str(entry.get("task_id_display", ""))
    mine = {str(node.task_id), str(getattr(node, "task_id_display", "") or "")}
    return tid in mine or display in mine


def build_bot_status_text(node, download_result: dict | None) -> str:
    from hermes_telegram_downloader.module.language import _t
    from hermes_telegram_downloader.module.tg.media import PLACEHOLDER_FILE_NAME
    from hermes_telegram_downloader.utils.format import create_progress_bar, format_byte

    lines = [f"🆔 task: {getattr(node, 'task_id_display', node.task_id)}"]
    progress_lines = []
    completed_lines = []
    if download_result and node.chat_id in download_result:
        for idx, value in download_result[node.chat_id].items():
            if not _task_matches(value, node):
                continue
            total = value.get("total_size", 0) or 0
            down = value.get("down_byte", 0) or 0
            fname = os.path.basename(value.get("file_name") or "")
            if fname == PLACEHOLDER_FILE_NAME:
                fname = f"msg {idx}"
            if total > 1 and down >= total:
                completed_lines.append(f"  ✅ {fname} ({format_byte(total)})")
                continue
            pct = int(down / total * 100) if total > 0 else 0
            speed = format_byte(value.get("download_speed", 0) or 0)
            progress_lines.append(
                f" ├─ 📁 {fname}\n"
                f" │   ├─ 📏 {format_byte(total)}\n"
                f" │   ├─ ⚡ {speed}/s\n"
                f" │   └─ 📊 [{create_progress_bar(pct)}] ({pct}%)"
            )
    if progress_lines:
        lines.append(f"📥 {_t('Download Progresses')}:")
        lines.extend(progress_lines)
    if completed_lines:
        lines.append(f"📄 {_t('Files')}:")
        lines.extend(completed_lines)
    if getattr(node, "failed_download_task", 0) > 0:
        lines.append(f"❌ {_t('Failed')}: {node.failed_download_task}")
    return "\n".join(lines)


async def report_bot_status(bot, node, immediate_reply=False):
    if not bot or not getattr(node, "reply_message_id", 0) or not node.from_user_id:
        return
    if not immediate_reply and not node.can_reply():
        return
    from hermes_telegram_downloader.module.download_stat import get_download_result

    text = build_bot_status_text(node, get_download_result())
    if text == node.last_edit_msg:
        return
    if not immediate_reply:
        total = 0
        weighted = 0
        result = get_download_result()
        if node.chat_id in result:
            for value in result[node.chat_id].values():
                if not _task_matches(value, node):
                    continue
                ts = value.get("total_size", 0) or 0
                if ts > 1:
                    total += ts
                    weighted += value.get("down_byte", 0) or 0
        current_pct = int(weighted / total * 100) if total > 0 else 0
        bucket = (current_pct // 20) * 20
        prev = (
            (node.last_progress_pct // 20) * 20 if node.last_progress_pct >= 0 else -1
        )
        if bucket == prev and node.last_progress_pct >= 0:
            return
        node.last_progress_pct = current_pct
    try:
        await bot.edit_message_text(node.from_user_id, node.reply_message_id, text)
        node.last_edit_msg = text
    except Exception as e:
        logger.debug("report_bot_status edit failed: {}", e)


async def fetch_message(client, chat_id, message_id):
    msg = await client.get_messages(chat_id, ids=message_id)
    if isinstance(msg, list):
        return msg[0] if msg else None
    return msg
