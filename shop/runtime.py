"""Settings that the admin panel can change while the bot runs.

Values in .env are the defaults; anything edited from the panel is stored in the `settings`
table and cached here. Single process, single writer — a plain module-level cache is enough.
"""

from decimal import Decimal

from shop import config

KEY_CARD_NUMBER = "card_number"
KEY_CARD_HOLDER = "card_holder"
KEY_ORDER_TIMEOUT = "order_timeout"
KEY_PAYMENT_TOLERANCE = "payment_tolerance"
KEY_AUTO_DELIVERY = "auto_delivery"
KEY_PDF_AUTO_LIMIT = "pdf_auto_limit"
KEY_TEST_MODE = "test_mode"
KEY_NFT_MARKUP = "nft_markup"
# Момент включения обязательных отзывов; заказы старше него ничего не требуют.
KEY_REVIEW_SINCE = "review_required_since"

_overrides: dict[str, str] = {}

# Admins added from the panel. Those in .env are permanent and cannot be removed from the UI,
# so there is always a way back in if someone deletes the wrong entry.
_extra_admins: set[int] = set()


def apply(settings: dict[str, str]) -> None:
    """Reload the cache from the settings table. Called at startup and after every edit."""
    _overrides.clear()
    _overrides.update(settings)


def apply_admins(user_ids) -> None:
    _extra_admins.clear()
    _extra_admins.update(user_ids)


def admin_ids() -> set[int]:
    return set(config.ADMIN_IDS) | _extra_admins


def is_admin(user_id: int) -> bool:
    return user_id in admin_ids()


def is_owner(user_id: int) -> bool:
    """Owners come from .env and are not editable from the panel."""
    return user_id in config.ADMIN_IDS


def card_number() -> str:
    return _overrides.get(KEY_CARD_NUMBER) or config.CARD_NUMBER


def card_holder() -> str:
    return _overrides.get(KEY_CARD_HOLDER) or config.CARD_HOLDER


def order_timeout_minutes() -> int:
    return int(_overrides.get(KEY_ORDER_TIMEOUT) or config.ORDER_TIMEOUT_MINUTES)


def payment_tolerance_minutes() -> int:
    return int(_overrides.get(KEY_PAYMENT_TOLERANCE) or config.PAYMENT_TOLERANCE_MINUTES)


def auto_delivery() -> bool:
    stored = _overrides.get(KEY_AUTO_DELIVERY)
    return config.STARS_AUTO_DELIVERY if stored is None else stored == "1"


def pdf_auto_limit() -> Decimal:
    """Orders up to this sum are delivered automatically on a matching PDF; above it an
    admin confirms by hand, because a PDF text layer can be edited."""
    return Decimal(_overrides.get(KEY_PDF_AUTO_LIMIT) or config.PDF_AUTO_LIMIT)


def test_mode() -> bool:
    """Dry run: verify receipts and report the result, but never charge or deliver."""
    stored = _overrides.get(KEY_TEST_MODE)
    return config.TEST_MODE if stored is None else stored == "1"


def nft_markup_percent() -> Decimal:
    """Наценка на подарки поверх цены маркета, в процентах.

    Читается при каждом расчёте цены, а не один раз при импорте: иначе смена наценки в
    админке доходила бы до клиентов только после перезапуска бота.
    """
    stored = _overrides.get(KEY_NFT_MARKUP)
    return Decimal(stored) if stored is not None else config.NFT_MARKUP_PERCENT


def masked_card() -> str:
    card = card_number()
    return f"{card[:4]} **** {card[-4:]}" if len(card) >= 8 else (card or "не задана")
