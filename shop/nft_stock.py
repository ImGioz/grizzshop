"""Gifts sitting on the owner's profile, offered for sale through the bot.

Reading and transferring them goes through a Telegram Business connection: the owner adds the
bot in Settings → Telegram Business → Chatbots and grants "transfer and upgrade gifts".
The connection id arrives in a business_connection update and is stored in settings.
"""

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from aiogram import Bot

from shop import db, nft_market

logger = logging.getLogger(__name__)

SETTING_BUSINESS_ID = "business_connection_id"


class StockError(Exception):
    pass


@dataclass
class StockGift:
    owned_gift_id: str
    collection: str           # base_name, e.g. "Joyful Bundle"
    number: int
    model: str | None
    symbol: str | None
    backdrop: str | None
    transfer_star_count: int
    floor_ton: Decimal | None = None
    price_uah: Decimal | None = None

    @property
    def title(self) -> str:
        return f"{self.collection} #{self.number}"

    @property
    def details(self) -> str:
        parts = [self.title] + [p for p in (self.model, self.symbol, self.backdrop) if p]
        return " · ".join(parts)

    @property
    def link(self) -> str:
        """Public page of this exact gift — the slug is the collection without spaces."""
        return f"https://t.me/nft/{self.collection.replace(' ', '')}-{self.number}"


async def business_id() -> str | None:
    return (await db.get_settings()).get(SETTING_BUSINESS_ID)


async def save_business_id(connection_id: str) -> None:
    await db.set_setting(SETTING_BUSINESS_ID, connection_id)


def _to_gift(owned) -> StockGift | None:
    gift = getattr(owned, "gift", None)
    if gift is None or not getattr(gift, "number", None):
        return None       # regular (non-unique) gifts cannot be transferred on

    return StockGift(
        owned_gift_id=owned.owned_gift_id,
        collection=gift.base_name,
        number=gift.number,
        model=gift.model.name if gift.model else None,
        symbol=gift.symbol.name if gift.symbol else None,
        backdrop=gift.backdrop.name if gift.backdrop else None,
        transfer_star_count=owned.transfer_star_count or 0,
    )


async def available(bot: Bot, limit: int = 100) -> list[StockGift]:
    """Unique gifts that can be handed over right now.

    Telegram holds a freshly received gift for weeks; `can_be_transferred` is how the API says
    whether that period is over, so anything still locked never reaches the shop window.
    """
    connection = await business_id()
    if not connection:
        raise StockError("бизнес-связка не настроена — подключите бота в Telegram Business")

    owned = await bot.get_business_account_gifts(business_connection_id=connection,
                                                 exclude_unique=False, limit=limit)
    gifts = []
    for item in owned.gifts:
        if not getattr(item, "can_be_transferred", False):
            continue
        gift = _to_gift(item)
        if gift:
            gifts.append(gift)

    logger.info("stock: %s of %s gifts are transferable", len(gifts), owned.total_count)
    return gifts


async def price_gift(gift: StockGift, markup_percent: Decimal, ton_rate: Decimal) -> StockGift:
    """Price a gift we already own, from the marketplace floor for its model.

    Deliberately the model floor and not the exact trait combination: this gift is already
    ours, so the floor is a valuation, not a cost we have to cover. Pricing off the closest
    comparable inflated it badly — a rare backdrop with no listings of its own pushed one
    Flying Broom to 20 TON while any Colorless could be had for 14.

    Orders from the marketplace are the opposite case and keep the strict search: there the
    gift still has to be bought, so the price of the actual substitute is what matters.
    """
    from shop import price_cache

    floor_ton = await price_cache.floor_ton(gift.collection, gift.model)

    if floor_ton:
        gift.floor_ton = floor_ton
        gift.price_uah = (floor_ton * ton_rate * (1 + markup_percent / 100)).quantize(Decimal("1"))
    return gift


async def transfer(bot: Bot, gift: StockGift, new_owner_chat_id: int) -> None:
    """Hand the gift over to the buyer. Costs stars from the connected account."""
    connection = await business_id()
    if not connection:
        raise StockError("бизнес-связка не настроена")

    logger.info("transferring %s to %s (%s stars)", gift.details, new_owner_chat_id,
                gift.transfer_star_count)
    try:
        await bot.transfer_gift(business_connection_id=connection,
                                owned_gift_id=gift.owned_gift_id,
                                new_owner_chat_id=new_owner_chat_id,
                                star_count=gift.transfer_star_count or None)
    except Exception as error:
        raise StockError(f"передача не удалась: {error}") from error


async def by_id(bot: Bot, owned_gift_id: str) -> StockGift | None:
    """Re-read a gift right before handing it over.

    The showcase may be minutes old and the gift could have been sold or sent elsewhere, so the
    transfer always works from fresh data rather than from what the customer saw.
    """
    for gift in await available(bot):
        if gift.owned_gift_id == owned_gift_id:
            return gift
    return None
