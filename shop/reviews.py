"""Collecting a review after a delivered order and publishing it to the reviews channel."""

import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from shop import localtime
from shop.config import REVIEWS_CHANNEL_ID, REVIEW_NUMBER_OFFSET

logger = logging.getLogger(__name__)

MAX_RATING = 5

# Telegram caps a photo caption at 1024 characters, so a long comment gets trimmed.
MAX_COMMENT = 600


def render(review_id: int, client_name: str, rating: int, comment: str | None,
           stars: int, total_stars: int, moment: datetime | None = None,
           product: str = "stars", details: str | None = None) -> str:
    moment = moment or localtime.now()
    if product == "premium":
        delivered = f"Telegram Premium, {stars} міс."
    elif product == "gram":
        delivered = f"{stars / 10 ** 9:g} TON"
    elif product in ("nft", "nft_stock"):
        # продажа NFT убрана, но отзывы на прошлые заказы остаются в канале
        delivered = details or "NFT"
    else:
        delivered = f"{stars} ⭐️"

    # No comment means no comment line at all, rather than a placeholder.
    text = (comment or "").strip()
    if len(text) > MAX_COMMENT:
        text = text[:MAX_COMMENT].rstrip() + "…"
    comment_line = f"💬Коментар:\n{html.escape(text)}\n" if text else ""

    return (
        f"📊Відгук №{review_id + REVIEW_NUMBER_OFFSET}\n\n"
        f"👤Клієнт: {html.escape(client_name)}\n"
        f"{comment_line}"
        f"⭐️Оцінка: {'⭐️' * rating}\n\n"
        f"🗓Дата: {moment:%d.%m.%Y}\n\n"
        f"🌟Виведено: {delivered}\n"
        f"📈Всього виведено: {total_stars} ⭐️"
    )


async def publish(bot: Bot, text: str, photo_file_id: str | None) -> bool:
    """Post to the reviews channel. False when the bot cannot post there."""
    try:
        if photo_file_id:
            await bot.send_photo(REVIEWS_CHANNEL_ID, photo_file_id, caption=text, parse_mode="HTML")
        else:
            await bot.send_message(REVIEWS_CHANNEL_ID, text, parse_mode="HTML")
        return True
    except Exception:
        logger.exception("cannot publish a review to %s — is the bot an admin there?",
                         REVIEWS_CHANNEL_ID)
        return False


def client_name(user) -> str:
    """The account's display name; @username is only a fallback for accounts without one."""
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    if full_name:
        return full_name
    return f"@{user.username}" if user.username else str(user.id)
