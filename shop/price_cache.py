"""Cached marketplace lookups.

Pricing one gift costs up to four Portals requests, and Portals rate-limits, so a showcase of
a dozen gifts would keep a customer waiting a minute. Prices are therefore looked up once,
stored, and refreshed in the background.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from shop import db, nft_market

logger = logging.getLogger(__name__)

# How long a stored floor price is considered good enough to show.
MAX_AGE = timedelta(minutes=30)


def key_of(model: str | None, symbol: str | None, backdrop: str | None) -> str:
    return "|".join((model or "", symbol or "", backdrop or "")).lower()


def _pack(listing, quality: str) -> dict:
    return {
        "collection": listing.name,
        "model": listing.model,
        "symbol": listing.symbol,
        "backdrop": listing.backdrop,
        "price": str(listing.price),
        "quality": quality,
    }


def _unpack(payload: dict) -> tuple[nft_market.Listing, str]:
    listing = nft_market.Listing(
        name=payload["collection"], model=payload["model"], symbol=payload["symbol"],
        backdrop=payload["backdrop"], price=Decimal(payload["price"]),
        floor_price=None, tg_id=None, photo_url=None)
    return listing, payload["quality"]


async def find(model: str | None, symbol: str | None, backdrop: str | None,
               max_age: timedelta = MAX_AGE, refresh: bool = False):
    """Cached `nft_market.find_similar`. Returns (listing, quality, from_cache)."""
    key = key_of(model, symbol, backdrop)

    if not refresh:
        stored = await db.cached_price(key)
        if stored:
            payload, updated_at = stored
            if datetime.now(timezone.utc) - updated_at < max_age:
                if payload.get("quality") == "none":
                    return None, "none", True
                listing, quality = _unpack(payload)
                return listing, quality, True

    listing, quality = await asyncio.to_thread(nft_market.find_similar, model, symbol, backdrop)
    await db.store_price(key, _pack(listing, quality) if listing else {"quality": "none"})
    return listing, quality, False


async def warm(gifts, delay: float = 0.5) -> int:
    """Refresh prices for a batch of gifts, pacing the calls so Portals does not throttle us."""
    updated = 0
    for gift in gifts:
        try:
            await find(gift.model, gift.symbol, gift.backdrop, refresh=True)
            updated += 1
        except nft_market.MarketError as error:
            logger.warning("cannot refresh price for %s: %s", gift.details, error)
        await asyncio.sleep(delay)
    return updated
