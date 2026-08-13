"""Реферальная программа: правила начисления в одном месте.

За каждые REFERRALS_PER_REWARD приглашённых, оформивших оплаченный заказ, приглашающему
начисляется STARS_PER_REWARD звёзд. Начисленное копится, пока человек не заберёт его кнопкой.

Заработанное не хранится в базе, а считается из числа зачтённых приглашений: хранить два
счётчика — приглашений и начислений — значит рано или поздно получить их расхождение.
В базе лежит только выданное.
"""

import logging

from shop import db

logger = logging.getLogger(__name__)

REFERRALS_PER_REWARD = 10
STARS_PER_REWARD = 100

# ?start=ref_<user_id>
LINK_PREFIX = "ref_"


def link_payload(user_id: int) -> str:
    return f"{LINK_PREFIX}{user_id}"


def referrer_from_payload(payload: str) -> int | None:
    """Достать id приглашающего из аргумента /start. None, если это не реферальная ссылка."""
    if not payload or not payload.startswith(LINK_PREFIX):
        return None
    tail = payload[len(LINK_PREFIX):]
    return int(tail) if tail.isdigit() else None


def earned(qualified: int) -> int:
    """Сколько звёзд заработано за столько-то зачтённых приглашений."""
    return (qualified // REFERRALS_PER_REWARD) * STARS_PER_REWARD


async def status(user_id: int) -> dict:
    """Всё, что нужно экрану: приглашено, зачтено, заработано, выдано, доступно, до следующей награды."""
    invited, qualified, paid = await db.referral_stats(user_id)
    total = earned(qualified)
    return {
        "invited": invited,
        "qualified": qualified,
        "earned": total,
        "paid": paid,
        "available": max(total - paid, 0),
        "to_next": REFERRALS_PER_REWARD - (qualified % REFERRALS_PER_REWARD),
    }


async def link(bot, user_id: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start={link_payload(user_id)}"


async def attach(user_id: int, payload: str) -> int | None:
    """Привязать новичка к пригласившему. Возвращает id приглашающего, если привязка удалась.

    Себя пригласить нельзя, и переписать уже проставленного приглашающего тоже: обе попытки
    просто ничего не делают.
    """
    referrer_id = referrer_from_payload(payload)
    if referrer_id is None or referrer_id == user_id:
        return None

    if not await db.get_user(referrer_id):
        logger.info("реферальная ссылка на несуществующего пользователя %s", referrer_id)
        return None

    if not await db.set_referrer(user_id, referrer_id):
        return None

    logger.info("пользователь %s пришёл по ссылке %s", user_id, referrer_id)
    return referrer_id
