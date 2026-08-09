"""Inline and reply keyboards."""

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

from shop.config import CHANNEL_URL, MIN_STARS
from shop.prices import PREMIUM_PRICES, STAR_PRICES, star_price
from shop.texts import t

def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang:uk"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
    ]])


def subscription_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "subscribe_button"), url=CHANNEL_URL)],
        [InlineKeyboardButton(text=t(language, "check_subscription"), callback_data="check_sub")],
    ])


def main_menu(language: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(language, "menu_stars")), KeyboardButton(text=t(language, "menu_premium"))],
            [KeyboardButton(text=t(language, "menu_gram")), KeyboardButton(text=t(language, "menu_nft"))],
            [KeyboardButton(text=t(language, "menu_calculator"))],
            # alone in its row, so Telegram stretches it across the full width
            [KeyboardButton(text=t(language, "menu_profile"))],
        ],
        resize_keyboard=True,
    )


def recipient_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(language, "for_myself"), callback_data="who:self"),
        InlineKeyboardButton(text=t(language, "for_friend"), callback_data="who:friend"),
    ]])


def quantity_keyboard(language: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=f"{quantity} ⭐ — {star_price(quantity)} грн",
                                    callback_data=f"qty:{quantity}")
               for quantity in sorted(STAR_PRICES)]

    # the tier list is long, so two per row keeps it readable
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text=t(language, "custom_quantity"), callback_data="qty:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def calculator_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "calc_to_uah"), callback_data="calc:to_uah")],
        [InlineKeyboardButton(text=t(language, "calc_to_stars"), callback_data="calc:to_stars")],
    ])


def calculator_again_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "calc_again"), callback_data="calc:menu")],
    ])


def months_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "months_label", months=months, price=price),
                              callback_data=f"months:{months}")]
        for months, price in sorted(PREMIUM_PRICES.items())
    ])


def nft_type_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(language, "nft_market"), callback_data="nft:market"),
        InlineKeyboardButton(text=t(language, "nft_from_list"), callback_data="nft:list"),
    ]])


def nft_confirm_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "nft_make_order"), callback_data="nft:order")],
        [InlineKeyboardButton(text=t(language, "nft_cancel_order"), callback_data="nft:drop")],
    ])


def stock_keyboard(gifts) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{gift.title} — {gift.price_uah} грн",
                              callback_data=f"nft:take:{gift.owned_gift_id}")]
        for gift in gifts
    ])


def nft_buy_keyboard(language: str, owned_gift_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "nft_buy"), callback_data=f"nft:buy:{owned_gift_id}")],
        [InlineKeyboardButton(text=t(language, "nft_decline"), callback_data="nft:decline")],
    ])


def product_label(language: str, product: str, quantity: int, details: str | None = None) -> str:
    if product == "test":
        return details or "тестовая оплата"
    if product in ("nft", "nft_stock"):
        return t(language, "product_nft", details=details or "—")
    if product == "gram":
        # gram quantities are stored in nanotons
        return t(language, "product_gram", amount=f"{quantity / 10 ** 9:g}")
    key = "product_premium" if product == "premium" else "product_stars"
    return t(language, key, quantity=quantity)


def payment_method_keyboard(language: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(language, "pay_transfer"), callback_data=f"pay:transfer:{order_id}"),
        InlineKeyboardButton(text=t(language, "pay_crypto"), callback_data=f"pay:crypto:{order_id}"),
    ]])


def _cancel_row(language: str, order_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t(language, "cancel_order"),
                                 callback_data=f"cancel_order:{order_id}")]


def crypto_check_keyboard(language: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "crypto_check"),
                              callback_data=f"crypto:{order_id}")],
        _cancel_row(language, order_id),
    ])


def check_payment_keyboard(language: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "check_payment"), callback_data=f"check:{order_id}")],
        _cancel_row(language, order_id),
    ])


def retry_keyboard(language: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "verify_retry"), callback_data=f"check:{order_id}")],
        _cancel_row(language, order_id),
    ])


MIN_STARS_HINT = MIN_STARS
