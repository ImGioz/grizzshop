"""Paying an order in TON, straight to the shop wallet.

The payment is recognised by a comment the customer attaches to the transfer: it is the only
thing that reliably ties an incoming transaction to an order, since amounts repeat and senders
are unknown in advance.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from main import load_mnemonics
from wallet.Transactions import Transactions

logger = logging.getLogger(__name__)

# A payment sent while the rate moved slightly must still be accepted.
UNDERPAY_TOLERANCE = Decimal("0.98")
SCAN_LIMIT = 40


@dataclass
class Payment:
    lt: int
    nanotons: int
    comment: str

    @property
    def receipt_id(self) -> str:
        """Key for the used-receipts table: `lt` is unique per account."""
        return f"ton:{self.lt}"

    @property
    def tons(self) -> Decimal:
        return (Decimal(self.nanotons) / Decimal(10 ** 9)).quantize(Decimal("0.0001"))


RATE_CACHE_SECONDS = 300
_rate_cache: dict = {"value": None, "at": 0.0}


def comment_for(order_id: int) -> str:
    return f"XAR{order_id}"


def _coingecko_uah() -> Decimal | None:
    """Direct TON/UAH pair — the reference that matches what wallets and exchanges show."""
    import requests

    data = requests.get("https://api.coingecko.com/api/v3/simple/price",
                        params={"ids": "the-open-network", "vs_currencies": "uah"},
                        timeout=15).json()
    return Decimal(str(data["the-open-network"]["uah"]))


def _coingecko_usd_nbu() -> Decimal | None:
    """Same source in dollars, converted through the official USD/UAH rate.

    Binance's TONUSDT is deliberately not used here: its last price sits frozen at 1.60 and
    produced a rate ~17% above the real one.
    """
    import requests

    data = requests.get("https://api.coingecko.com/api/v3/simple/price",
                        params={"ids": "the-open-network", "vs_currencies": "usd"},
                        timeout=15).json()
    usd = requests.get("https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange",
                       params={"valcode": "USD", "json": ""}, timeout=15).json()
    return Decimal(str(data["the-open-network"]["usd"])) * Decimal(str(usd[0]["rate"]))


def market_rate() -> Decimal:
    """Live TON/UAH, cached briefly.

    The shop's own TON_PRICE_UAH is a selling price with margin baked in; charging a crypto
    payment at that rate would quietly over- or undercharge depending on where the market is.
    """
    import time

    if _rate_cache["value"] and time.time() - _rate_cache["at"] < RATE_CACHE_SECONDS:
        return _rate_cache["value"]

    for source in (_coingecko_uah, _coingecko_usd_nbu):
        try:
            rate = source()
        except Exception as error:
            logger.warning("rate source %s failed: %s", source.__name__, error)
            continue
        if rate and rate > 0:
            _rate_cache.update(value=rate, at=time.time())
            logger.info("TON rate from %s: %.2f UAH", source.__name__, rate)
            return rate

    from shop.prices import TON_PRICE_UAH
    logger.error("no rate source available, falling back to the shop rate %s", TON_PRICE_UAH)
    return TON_PRICE_UAH


def amount_ton(price_uah: Decimal, ton_rate: Decimal | None = None) -> Decimal:
    """Rounded up, so a rounding error never leaves the shop short."""
    rate = ton_rate or market_rate()
    return (Decimal(price_uah) / rate).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)


def _value_of(info) -> int | None:
    """Nanotons carried by an incoming message.

    `value_coins` is a plain int here; reading it as an object (`.grams`) silently yielded None
    and made every crypto payment invisible.
    """
    value = getattr(info, "value_coins", None)
    if isinstance(value, int):
        return value
    return getattr(getattr(info, "value", None), "grams", None)


def _comment_of(message) -> str:
    try:
        slice_ = message.body.begin_parse()
        if slice_.remaining_bits >= 32 and slice_.load_uint(32) == 0:
            return slice_.load_snake_string()
    except Exception:
        pass
    return ""


async def find_payment(order_id: int, expected_ton: Decimal,
                       since: datetime | None = None) -> Payment | None:
    """Look through recent incoming transfers for the one carrying this order's comment."""
    wanted = comment_for(order_id)
    minimum = int((expected_ton * UNDERPAY_TOLERANCE * Decimal(10 ** 9))
                  .quantize(Decimal("1"), rounding=ROUND_FLOOR))
    cutoff = int(since.timestamp()) if since else 0

    async with Transactions.session(load_mnemonics()) as (client, wallet):
        transactions = await client.get_transactions(wallet.address, limit=SCAN_LIMIT)

    for transaction in transactions:
        incoming = transaction.in_msg
        if not incoming or not getattr(incoming, "info", None):
            continue

        value = _value_of(incoming.info)
        if not value:
            continue
        if cutoff and transaction.now < cutoff:
            continue

        comment = _comment_of(incoming).strip()
        if comment != wanted:
            continue

        logger.info("order %s: found payment lt=%s value=%s comment=%r",
                    order_id, transaction.lt, value, comment)
        if value < minimum:
            logger.warning("order %s: underpaid, got %s need %s", order_id, value, minimum)
            return None

        return Payment(lt=transaction.lt, nanotons=value, comment=comment)

    return None


async def wallet_address() -> str:
    address, _ = await Transactions.get_balance(load_mnemonics())
    return address
