import asyncio

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


async def report_bot_status(bot, node, immediate_reply=False):
    return None


async def fetch_message(client, chat_id, message_id):
    msg = await client.get_messages(chat_id, ids=message_id)
    if isinstance(msg, list):
        return msg[0] if msg else None
    return msg
