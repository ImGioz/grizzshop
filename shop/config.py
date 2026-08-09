"""Settings for the shop bot, read from .env next to the project root."""

import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int_set(name: str) -> set[int]:
    return {int(part) for part in os.getenv(name, "").replace(" ", "").split(",") if part}


# A separate token is recommended: the same token cannot poll from two processes at once,
# so reusing bot.py's token means only one of the two bots can run.
BOT_TOKEN = os.getenv("SHOP_BOT_TOKEN") or os.getenv("BOT_TOKEN")
ADMIN_IDS = _int_set("ADMIN_IDS")

# Channel the user must be subscribed to. The bot has to be an administrator there,
# otherwise get_chat_member raises and every check fails.
CHANNEL_ID = os.getenv("CHANNEL_ID", "@XAR1ZMA_SHOP")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/XAR1ZMA_SHOP")

# Card the customer transfers to. CARD_HOLDER is shown in the payment details.
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_HOLDER = os.getenv("CARD_HOLDER", "")

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "shop.db"))

# An unpaid order is expired by the janitor after this many minutes.
ORDER_TIMEOUT_MINUTES = int(os.getenv("ORDER_TIMEOUT_MINUTES", "30"))

# Allowed gap between order creation and the payment timestamp on the receipt.
# The spec suggested 5 minutes; that is tight for a real customer (open the bank app, pay,
# copy the receipt link), so the default is wider and configurable.
PAYMENT_TOLERANCE_MINUTES = int(os.getenv("PAYMENT_TOLERANCE_MINUTES", "15"))

# Star purchases go out through the Fragment/TON wallet built in FragmentApi + wallet/.
STARS_AUTO_DELIVERY = os.getenv("STARS_AUTO_DELIVERY", "1") == "1"
MIN_STARS = int(os.getenv("MIN_STARS", "50"))

# A PDF receipt is user-supplied and its text layer is editable, so orders above this
# sum wait for an admin to confirm. Monobank check links are not affected.
PDF_AUTO_LIMIT = os.getenv("PDF_AUTO_LIMIT", "200")

# Dry run: receipts are verified in full and reported, but nothing is charged,
# no order changes status and no stars are sent. Toggled from the admin panel.
TEST_MODE = os.getenv("TEST_MODE", "0") == "1"

# NFT gift marketplaces. All of them are behind auth: the token is the initData of
# their Telegram Mini App session. Without a token the price is set by an admin.
TONNEL_AUTH = os.getenv("TONNEL_AUTH") or None
PORTALS_AUTH = os.getenv("PORTALS_AUTH") or None
MRKT_AUTH = os.getenv("MRKT_AUTH") or None
# Percent added on top of the marketplace floor price.
NFT_MARKUP_PERCENT = Decimal(os.getenv("NFT_MARKUP_PERCENT", "10"))

# Channel where reviews are published. The bot must be an administrator there.
REVIEWS_CHANNEL_ID = os.getenv("REVIEWS_CHANNEL_ID", "@xar1zma_test")
# Added to the review id so numbering does not start from 1 on a fresh shop.
REVIEW_NUMBER_OFFSET = int(os.getenv("REVIEW_NUMBER_OFFSET", "0"))

# Anonymous toncenter allows ~1 request/second, which a single delivery already exceeds.
# Get a free key from @tonapibot in Telegram.
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY") or None
TONCENTER_RPS = float(os.getenv("TONCENTER_RPS", "8" if TONCENTER_API_KEY else "1"))


def validate() -> list[str]:
    """Return a list of misconfigurations, empty when the bot is safe to start."""
    problems = []
    if not BOT_TOKEN:
        problems.append("SHOP_BOT_TOKEN (или BOT_TOKEN) не задан в .env")
    if not ADMIN_IDS:
        problems.append("ADMIN_IDS не задан в .env: некому присылать уведомления о заказах")
    if not CARD_NUMBER:
        problems.append("CARD_NUMBER не задан в .env: нечего показать в реквизитах оплаты")
    if not CARD_HOLDER:
        problems.append("CARD_HOLDER не задан в .env: нечего показать в реквизитах оплаты")
    return problems
