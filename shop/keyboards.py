"""Inline keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from shop import projects
from shop.config import CHANNEL_URL, DEVELOPER_URL, MIN_STARS, REVIEWS_CHANNEL_URL
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


def main_menu(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "menu_stars"), callback_data="menu:stars"),
         InlineKeyboardButton(text=t(language, "menu_premium"), callback_data="menu:premium")],
        [InlineKeyboardButton(text=t(language, "menu_gram"), callback_data="menu:gram"),
         InlineKeyboardButton(text=t(language, "menu_calculator"), callback_data="menu:calc")],
        [InlineKeyboardButton(text=t(language, "menu_more"), callback_data="menu:more")],
        # alone in its row, so Telegram stretches it across the full width
        [InlineKeyboardButton(text=t(language, "menu_profile"), callback_data="menu:profile")],
    ])


def home_row(language: str) -> list[InlineKeyboardButton]:
    """Возврат в главное меню. Нижней строкой на каждом экране, куда из меню уходят."""
    return [InlineKeyboardButton(text=t(language, "menu_main"), callback_data="menu:home")]


def home_keyboard(language: str) -> InlineKeyboardMarkup:
    """Для экранов, которые ждут ввода текстом и своих кнопок не имеют."""
    return InlineKeyboardMarkup(inline_keyboard=[home_row(language)])


def recipient_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "for_myself"), callback_data="who:self"),
         InlineKeyboardButton(text=t(language, "for_friend"), callback_data="who:friend")],
        home_row(language),
    ])


def quantity_keyboard(language: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=f"{quantity} ⭐ — {star_price(quantity)} грн",
                                    callback_data=f"qty:{quantity}")
               for quantity in sorted(STAR_PRICES)]

    # the tier list is long, so two per row keeps it readable
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text=t(language, "custom_quantity"), callback_data="qty:custom")])
    rows.append(home_row(language))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def calculator_keyboard(language: str) -> InlineKeyboardMarkup:
    """Первый экран калькулятора: что считаем — звёзды или TON."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "calc_pick_stars"), callback_data="calc:stars"),
         InlineKeyboardButton(text=t(language, "calc_pick_ton"), callback_data="calc:ton")],
        home_row(language),
    ])


def stars_calculator_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "calc_to_uah"), callback_data="calc:to_uah")],
        [InlineKeyboardButton(text=t(language, "calc_to_stars"), callback_data="calc:to_stars")],
        [InlineKeyboardButton(text=t(language, "calc_back"), callback_data="calc:menu")],
        home_row(language),
    ])


def ton_calculator_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "calc_ton_to_uah"), callback_data="calc:ton_to_uah")],
        [InlineKeyboardButton(text=t(language, "calc_to_ton"), callback_data="calc:to_ton")],
        [InlineKeyboardButton(text=t(language, "calc_back"), callback_data="calc:menu")],
        home_row(language),
    ])


def calculator_again_keyboard(language: str, section: str) -> InlineKeyboardMarkup:
    """`section` — «stars» или «ton»: «Посчитать ещё» возвращает в тот же калькулятор."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "calc_again"), callback_data=f"calc:{section}")],
        home_row(language),
    ])


def months_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "months_label", months=months, price=price),
                              callback_data=f"months:{months}")]
        for months, price in sorted(PREMIUM_PRICES.items())
    ] + [home_row(language)])


def more_keyboard(language: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t(language, "menu_support"), callback_data="more:support")],
            [InlineKeyboardButton(text=t(language, "menu_projects"), callback_data="more:projects")]]
    # без публичной ссылки кнопка была бы битой, поэтому её просто нет
    if REVIEWS_CHANNEL_URL:
        rows.insert(0, [InlineKeyboardButton(text=t(language, "menu_reviews"),
                                             url=REVIEWS_CHANNEL_URL)])
    rows.append([InlineKeyboardButton(text=t(language, "menu_developer"), url=DEVELOPER_URL)])
    rows.append(home_row(language))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def projects_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=projects.title(key, language), callback_data=f"proj:{key}")]
        for key in projects.CATEGORIES
    ] + [home_row(language)])


def project_category_keyboard(language: str, key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, url=url)]
        for label, url in projects.items(key, language)
    ] + [[InlineKeyboardButton(text=t(language, "projects_back"), callback_data="more:projects")],
         home_row(language)])


def product_label(language: str, product: str, quantity: int, details: str | None = None) -> str:
    if product == "test":
        return details or "тестовая оплата"
    if product in ("nft", "nft_stock"):   # продажа NFT убрана, остались прошлые заказы
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
