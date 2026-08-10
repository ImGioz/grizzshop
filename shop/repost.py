"""Mirroring tagged channel posts to every bot user.

A post in the shop channel carrying one of TRIGGER_TAGS is forwarded to all users looking
exactly as it was published, minus the tag itself.
"""

import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from shop import broadcast, db, runtime
from shop.config import CHANNEL_ID

logger = logging.getLogger(__name__)
router = Router()

TRIGGER_TAGS = ("новина", "гифт", "подарунок", "продажа", "newNFT", "xar1zmaNFT", "продажнфт")

# Tags may be written in any case and are stripped wherever they appear in the post.
TAG_PATTERN = re.compile(r"#(?:" + "|".join(TRIGGER_TAGS) + r")\b", re.IGNORECASE | re.UNICODE)


def has_trigger(text: str) -> bool:
    return bool(text) and bool(TAG_PATTERN.search(text))


def strip_tags(text: str) -> str:
    """Remove the trigger tags and tidy up the whitespace they leave behind."""
    cleaned = TAG_PATTERN.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# <tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji> — the tag wraps a plain fallback emoji.
CUSTOM_EMOJI_PATTERN = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.DOTALL)


def without_custom_emoji(html: str) -> str:
    """Unwrap premium emoji to their plain fallback.

    A bot may only send custom emoji if it bought a username on Fragment, or if its owner has
    Telegram Premium. Without that the API rejects the message, so keep a degraded version ready.
    """
    return CUSTOM_EMOJI_PATTERN.sub(r"\1", html)


def _is_custom_emoji_error(error: Exception) -> bool:
    text = str(error).lower()
    return "custom emoji" in text or "custom_emoji" in text


def _is_shop_channel(message: Message) -> bool:
    channel = str(CHANNEL_ID).lstrip("@").lower()
    return (str(message.chat.id) == str(CHANNEL_ID)
            or (message.chat.username or "").lower() == channel)


@router.channel_post(F.text | F.caption)
async def mirror_post(message: Message, bot: Bot):
    if not _is_shop_channel(message) or not has_trigger(message.text or message.caption or ""):
        return

    # html_text keeps bold/links/etc.; Telegram leaves hashtags as plain text, so a
    # straight substitution cannot damage the markup.
    body = strip_tags(message.html_text)

    if message.caption is not None:
        # media keeps its original file, only the caption is replaced
        def send(user_id, html):
            return bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id,
                                    message_id=message.message_id,
                                    caption=html or None, parse_mode="HTML")
    else:
        def send(user_id, html):
            return bot.send_message(user_id, html, parse_mode="HTML")

    # Falls back to plain emoji on the first rejection and stays there, so one unsupported
    # premium emoji cannot fail the broadcast for everyone.
    current = {"html": body}

    async def deliver(user_id: int):
        try:
            await send(user_id, current["html"])
        except TelegramBadRequest as error:
            if not _is_custom_emoji_error(error):
                raise
            logger.warning("premium emoji rejected, falling back to plain ones: %s", error)
            current["html"] = without_custom_emoji(current["html"])
            await send(user_id, current["html"])

    recipients = await db.broadcast_recipients("all")
    logger.info("mirroring channel post %s to %s users", message.message_id, len(recipients))

    progress = broadcast.Progress(total=len(recipients))
    asyncio.create_task(_run(bot, recipients, deliver, progress, message.message_id))


async def _run(bot: Bot, recipients, deliver, progress, post_id: int):
    try:
        await broadcast.run(bot, recipients, deliver, progress)
    except Exception:
        logger.exception("channel mirror crashed")

    logger.info("channel post %s mirrored: %s", post_id, progress.summary().replace("\n", " | "))
    for admin_id in runtime.admin_ids():
        try:
            await bot.send_message(admin_id, f"📣 Пост из канала разослан подписчикам бота\n"
                                             f"{progress.summary()}", parse_mode="HTML")
        except Exception:
            logger.warning("cannot report the mirror result to %s", admin_id)
