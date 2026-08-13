"""Admin panel: everything behind /adminka, driven by inline buttons.

Callback data is `adm:<section>:<action>:<arg>` so one parser covers the whole panel.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from shop import broadcast, db, localtime, runtime
from shop.config import ADMIN_IDS
from shop.keyboards import product_label
from shop.delivery import DeliveryError, deliver_gram, deliver_stars
from shop.prices import (PREMIUM_PRICES, PRICE_PER_STAR_CUSTOM, SETTING_PER_STAR,
                         PRICE_PER_STAR_BULK, BULK_STARS_FROM, SETTING_BULK_RATE, SETTING_BULK_FROM,
                         SETTING_PREFIX, SETTING_PREMIUM_PREFIX, SETTING_TON_PRICE,
                         TON_PRICE_UAH, STAR_PRICES, apply_overrides)

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(event) -> bool:
    """Checked per update, not baked in at import: admins can be added while the bot runs."""
    return bool(event.from_user) and runtime.is_admin(event.from_user.id)


router.message.filter(_is_admin)
router.callback_query.filter(_is_admin)

ADMIN_LANGUAGE = "ru"   # the panel itself is Russian-only

PAGE_SIZE = 6
UNDELIVERED = ("paid", "failed")
REVIEW = ("review",)
ACTIVE = ("pending", "awaiting_check")

STATUS_LABELS = {
    "pending": "🕐 создан",
    "awaiting_check": "⏳ ждёт оплаты",
    "paid": "💰 оплачен, не выдан",
    "delivered": "✅ выдан",
    "failed": "❌ ошибка выдачи",
    "review": "🔍 на проверке",
    "expired": "🚫 просрочен",
    "cancelled": "✖️ отменён",
}

class AdminStates(StatesGroup):
    edit_price = State()
    edit_per_star = State()
    edit_setting = State()
    broadcast_message = State()
    broadcast_confirm = State()
    add_admin = State()
    edit_premium = State()
    edit_ton = State()
    edit_bulk = State()
    edit_nft_markup = State()


def button(text: str, *parts) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=":".join(("adm", *map(str, parts))))


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("📦 Заказы", "orders", "list", "all", 0),
         button("💎 Кошелёк", "wallet", "show")],
        [button("📊 Статистика", "stats", "show"),
         button("💵 Цены", "prices", "show")],
        [button("📢 Рассылка", "cast", "show"),
         button("⚙️ Настройки", "settings", "show")],
        [button("👮 Администраторы", "admins", "show")],
    ])


def back_keyboard(*extra_rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[*extra_rows, [button("⬅️ В меню", "menu", "show")]])


async def render(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    """edit_text throws when the text is identical; a refresh button makes that easy to hit."""
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
    await callback.answer()


# --------------------------------------------------------------------------- entry point

@router.message(Command("adminka"))
async def open_panel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("<b>Админ-панель</b>\nВыберите раздел:", parse_mode="HTML",
                         reply_markup=main_keyboard())


@router.callback_query(F.data == "adm:menu:show")
async def show_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await render(callback, "<b>Админ-панель</b>\nВыберите раздел:", main_keyboard())


# --------------------------------------------------------------------------- orders

FILTER_TITLES = {
    "all": ("Все заказы", None),
    "success": ("Успешные", db.SUCCESSFUL_STATUSES),
    "undelivered": ("Оплачены, но не выданы", UNDELIVERED),
    "review": ("На проверке (оплата по PDF)", REVIEW),
    "active": ("Активные (ждут оплаты)", ACTIVE),
}


def order_product(order) -> str:
    """Stars, months or nanotons all live in `quantity`, so never print it raw."""
    return product_label(ADMIN_LANGUAGE, order.product, order.quantity, order.details)


def order_target(order) -> str:
    """A gram order goes to a wallet, everything else to a @username."""
    return order.wallet_address or order.recipient if order.product == "gram" else f"@{order.recipient}"


def short_target(order) -> str:
    target = order_target(order)
    return f"{target[:6]}…{target[-4:]}" if len(target) > 24 else target


def orders_keyboard(orders, filter_name: str, page: int, total: int) -> InlineKeyboardMarkup:
    rows = [[button(f"#{o.id} · {order_product(o)} · {short_target(o)} · "
                    f"{STATUS_LABELS.get(o.status, o.status)}", "orders", "card", o.id)]
            for o in orders]

    nav = []
    if page > 0:
        nav.append(button("◀️", "orders", "list", filter_name, page - 1))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(button("▶️", "orders", "list", filter_name, page + 1))
    if nav:
        rows.append(nav)

    def tab(label: str, name: str):
        return button(("• " if name == filter_name else "") + label, "orders", "list", name, 0)

    rows.append([tab("📋 Все", "all"), tab("✅ Успешные", "success")])
    rows.append([tab("💰 Не выданы", "undelivered"), tab("🔍 На проверке", "review")])
    rows.append([tab("⏳ Активные", "active")])
    rows.append([button("⬅️ В меню", "menu", "show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("adm:orders:list:"))
async def list_orders(callback: CallbackQuery):
    _, _, _, filter_name, page = callback.data.split(":")
    page = int(page)

    title, statuses = FILTER_TITLES.get(filter_name, FILTER_TITLES["all"])
    total = await db.count_orders(statuses)
    orders = await db.orders_page(statuses, page * PAGE_SIZE, PAGE_SIZE)

    if not orders:
        text = f"<b>{title}</b>\n\nПусто."
    else:
        text = (f"<b>{title}</b>\nВсего: {total}, страница {page + 1}\n\n"
                "Нажмите на заказ, чтобы открыть карточку.")

    await render(callback, text, orders_keyboard(orders, filter_name, page, total))


def order_card_keyboard(order) -> InlineKeyboardMarkup:
    rows = []
    if order.status in UNDELIVERED:
        rows.append([button("🚀 Выдать сейчас", "orders", "deliver", order.id)])
        rows.append([button("✅ Отметить выданным", "orders", "mark", order.id)])
    if order.status in REVIEW:
        rows.append([button("👁 Показать квитанцию", "orders", "receipt", order.id)])
        rows.append([button("✅ Подтвердить и выдать", "orders", "approve", order.id),
                     button("❌ Отклонить", "orders", "reject", order.id)])
    if order.status in ACTIVE:
        rows.append([button("🚫 Отменить заказ", "orders", "cancel", order.id)])
    rows.append([button("⬅️ К списку", "orders", "list", "all", 0),
                 button("🏠 В меню", "menu", "show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def order_card_text(order) -> str:
    receiver = (f"Кошелёк: <code>{order.wallet_address or order.recipient}</code>"
                if order.product == "gram" else f"Получатель: @{order.recipient}")

    # У заказа на TON получателем записан адрес кошелька, а не человек, поэтому имя
    # покупателя берём из профиля — иначе по такому заказу видно только числовой id.
    user = await db.get_user(order.user_id)
    username = user["username"] if user else None
    buyer = f"@{username} · <code>{order.user_id}</code>" if username else f"<code>{order.user_id}</code>"

    lines = [
        f"<b>Заказ #{order.id}</b>",
        f"Статус: {STATUS_LABELS.get(order.status, order.status)}",
        f"Товар: {order_product(order)}",
        receiver,
        f"Сумма: {order.price} грн",
        f"Покупатель: {buyer}",
        f"Создан: {localtime.stamp(order.created_at)}",
    ]
    if order.sender_name:
        lines.append(f"ФИО плательщика: {order.sender_name}")
    if order.receipt_id:
        lines.append(f"Квитанция: <code>{order.receipt_id}</code>")
    if order.paid_at:
        lines.append(f"Оплачен: {localtime.stamp(order.paid_at)}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("adm:orders:card:"))
async def order_card(callback: CallbackQuery):
    order = await db.get_order(int(callback.data.split(":")[-1]))
    if not order:
        return await callback.answer("Заказ не найден", show_alert=True)
    await render(callback, await order_card_text(order), order_card_keyboard(order))


@router.callback_query(F.data.startswith("adm:orders:deliver:"))
async def deliver_order(callback: CallbackQuery, bot: Bot):
    order = await db.get_order(int(callback.data.split(":")[-1]))
    if not order:
        return await callback.answer("Заказ не найден", show_alert=True)
    if order.status not in UNDELIVERED:
        return await callback.answer(f"Статус {order.status}, выдача не требуется", show_alert=True)

    await callback.answer("Выдаю...")
    await callback.message.edit_text(f"{await order_card_text(order)}\n\n⏳ Выдаю {order_product(order)}...",
                                     parse_mode="HTML")

    try:
        if order.product == "gram":
            spent = await deliver_gram(order.wallet_address, order.quantity)
        else:
            spent = await deliver_stars(order.recipient, order.quantity, order.product)
    except DeliveryError as error:
        await db.update_order(order.id, status="failed")
        failed = await db.get_order(order.id)
        return await callback.message.edit_text(
            f"{await order_card_text(failed)}\n\n❌ Не удалось: {error}",
            parse_mode="HTML", reply_markup=order_card_keyboard(failed))

    from shop.handlers import cost_in_uah
    await db.update_order(order.id, status="delivered", cost_uah=str(await cost_in_uah(spent)))
    delivered = await db.get_order(order.id)
    await callback.message.edit_text(f"{await order_card_text(delivered)}\n\n✅ Выдано.",
                                     parse_mode="HTML", reply_markup=order_card_keyboard(delivered))

    try:
        await bot.send_message(order.user_id,
                               f"Ваш заказ #{order.id} выдан: {order_product(order)} → {order_target(order)}")
    except Exception:
        logger.warning("cannot notify buyer %s about order %s", order.user_id, order.id)


@router.callback_query(F.data.startswith("adm:orders:mark:"))
async def mark_delivered(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[-1])
    await db.update_order(order_id, status="delivered")
    order = await db.get_order(order_id)
    await callback.answer("Отмечен выданным")
    await render(callback, await order_card_text(order), order_card_keyboard(order))


@router.callback_query(F.data.startswith("adm:orders:cancel:"))
async def cancel_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[-1])
    await db.update_order(order_id, status="expired")
    order = await db.get_order(order_id)
    await callback.answer("Заказ отменён")
    await render(callback, await order_card_text(order), order_card_keyboard(order))


# --------------------------------------------------------------------------- wallet

@router.callback_query(F.data == "adm:wallet:show")
async def show_wallet(callback: CallbackQuery):
    from main import load_mnemonics
    from wallet.Transactions import Transactions, effective_api_key

    await callback.answer("Запрашиваю баланс...")
    try:
        address, nano = await Transactions.get_balance(load_mnemonics())
        text = (f"<b>Кошелёк</b>\n\n<code>{address}</code>\n"
                f"Баланс: <b>{nano / 10 ** 9:.4f} TON</b>\n"
                f"toncenter: {'ключ активен' if effective_api_key() else 'анонимно (~1 rps)'}")
    except Exception as error:
        text = f"<b>Кошелёк</b>\n\nНе удалось получить баланс:\n<code>{error}</code>"

    await render(callback, text, back_keyboard([button("🔄 Обновить", "wallet", "show")]))


# --------------------------------------------------------------------------- stats

STATS_PERIODS = {
    "all": "За всё время",
    "today": "Сегодня",
    "week": "7 дней",
    "month": "30 дней",
}


def period_start(period: str) -> datetime | None:
    """Everything is measured from this moment; None means no limit."""
    now = localtime.now()
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    if period == "week":
        return (now - timedelta(days=7)).astimezone(timezone.utc)
    if period == "month":
        return (now - timedelta(days=30)).astimezone(timezone.utc)
    return None


def stats_keyboard(period: str) -> InlineKeyboardMarkup:
    tabs = [button(("• " if name == period else "") + title, "stats", "show", name)
            for name, title in STATS_PERIODS.items()]
    return InlineKeyboardMarkup(inline_keyboard=[
        tabs[:2], tabs[2:],
        [button("🔄 Обновить", "stats", "show", period)],
        [button("⬅️ В меню", "menu", "show")],
    ])


@router.callback_query(F.data.startswith("adm:stats:show"))
async def show_stats(callback: CallbackQuery):
    parts = callback.data.split(":")
    period = parts[3] if len(parts) > 3 and parts[3] in STATS_PERIODS else "all"
    since = period_start(period)

    # sold stars and revenue count paid and delivered orders only
    stats = await db.shop_stats(db.SUCCESSFUL_STATUSES, since)
    review_count, review_avg = await db.review_stats(since)
    by_status = "\n".join(f"  {STATUS_LABELS.get(status, status)}: {count}"
                          for status, count in sorted(stats["by_status"].items())) or "  —"

    average = f" (средняя {review_avg:.1f} ⭐️)" if review_count else ""

    # margin only over orders whose real cost is known
    cost, priced_revenue, priced = stats["cost"], stats["priced_revenue"], stats["priced"]
    margin = priced_revenue - cost
    percent = f" ({margin / priced_revenue * 100:.0f}%)" if priced_revenue else ""
    margin_block = (f"\nСебестоимость: {cost:.0f} грн\n"
                    f"Маржа: {margin:.0f} грн{percent}\n"
                    f"<i>по {priced} заказам из {stats['orders']}</i>\n") if priced else ""
    title = "Статистика" if period == "all" else f"Статистика · {STATS_PERIODS[period]}"
    people = "Пользователей" if period == "all" else "Новых пользователей"

    text = (f"<b>{title}</b>\n\n"
            f"{people}: {stats['users']}\n"
            f"Звёзд продано: {stats['stars']}\n"
            f"Выручка: {stats['revenue']:.0f} грн\n"
            + margin_block +
            f"Отзывов: {review_count}{average}\n\n"
            f"Заказы по статусам:\n{by_status}")

    await render(callback, text, stats_keyboard(period))


# --------------------------------------------------------------------------- prices

def prices_keyboard() -> InlineKeyboardMarkup:
    star_buttons = [button(f"{quantity} ⭐ — {price} грн", "prices", "edit", quantity)
                    for quantity, price in sorted(STAR_PRICES.items())]
    rows = [star_buttons[i:i + 2] for i in range(0, len(star_buttons), 2)]
    rows.append([button(f"Цена за звезду (своё кол-во) — {PRICE_PER_STAR_CUSTOM}", "prices", "edit", "custom")])
    rows += [[button(f"Premium {months} мес. — {price} грн", "prices", "edit", f"premium{months}")]
             for months, price in sorted(PREMIUM_PRICES.items())]
    rows.append([button(f"Опт: от {BULK_STARS_FROM} ⭐ по {PRICE_PER_STAR_BULK} грн",
                        "prices", "edit", "bulk")])
    rows.append([button(f"Курс TON — {TON_PRICE_UAH} грн", "prices", "edit", "ton")])
    rows.append([button(f"Наценка на подарки — {runtime.nft_markup_percent()}%",
                        "prices", "edit", "nft")])
    rows.append([button("⬅️ В меню", "menu", "show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "adm:prices:show")
async def show_prices(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await render(callback, "<b>Цены</b>\n\nНажмите на позицию, чтобы изменить.", prices_keyboard())


@router.callback_query(F.data.startswith("adm:prices:edit:"))
async def edit_price(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":")[-1]
    await callback.answer()

    if target == "bulk":
        await state.set_state(AdminStates.edit_bulk)
        return await callback.message.edit_text(
            f"Оптовая ставка: <b>{PRICE_PER_STAR_BULK}</b> грн за звезду сверх "
            f"<b>{BULK_STARS_FROM}</b> ⭐\n\n"
            f"Пришлите два числа через пробел: порог и ставку.\n"
            f"Например: <code>3000 0.72</code>", parse_mode="HTML")

    if target == "nft":
        await state.set_state(AdminStates.edit_nft_markup)
        return await callback.message.edit_text(
            f"Наценка на подарки: <b>{runtime.nft_markup_percent()}%</b> сверх цены маркета.\n\n"
            f"Действует и на подарки с маркета, и на подарки из профиля.\n"
            f"Пришлите новое значение числом, например <code>15</code>.", parse_mode="HTML")

    if target == "ton":
        await state.set_state(AdminStates.edit_ton)
        return await callback.message.edit_text(
            f"Курс TON: <b>{TON_PRICE_UAH}</b> грн за 1 TON\nПришлите новое значение числом.",
            parse_mode="HTML")

    if target.startswith("premium"):
        months = int(target[len("premium"):])
        await state.update_data(premium_months=months)
        await state.set_state(AdminStates.edit_premium)
        return await callback.message.edit_text(
            f"Premium <b>{months} мес.</b>, текущая цена {PREMIUM_PRICES[months]} грн\n"
            f"Пришлите новую цену числом.", parse_mode="HTML")

    if target == "custom":
        await state.set_state(AdminStates.edit_per_star)
        return await callback.message.edit_text(
            f"Текущая цена за одну звезду: <b>{PRICE_PER_STAR_CUSTOM}</b> грн\n"
            f"Пришлите новое значение числом (например 0.95).", parse_mode="HTML")

    await state.update_data(quantity=int(target))
    await state.set_state(AdminStates.edit_price)
    await callback.message.edit_text(
        f"Пакет <b>{target} ⭐</b>, текущая цена {STAR_PRICES[int(target)]} грн\n"
        f"Пришлите новую цену числом.", parse_mode="HTML")


def _parse_price(text: str) -> Decimal | None:
    try:
        value = Decimal(text.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None
    return value if value > 0 else None


@router.message(AdminStates.edit_price)
async def save_price(message: Message, state: FSMContext):
    price = _parse_price(message.text or "")
    if price is None:
        return await message.answer("Нужно положительное число. Попробуйте ещё раз.")

    quantity = (await state.get_data())["quantity"]
    await db.set_setting(f"{SETTING_PREFIX}{quantity}", str(price))
    apply_overrides(await db.get_settings())

    await state.clear()
    await message.answer(f"Цена пакета {quantity} ⭐ теперь <b>{price}</b> грн", parse_mode="HTML",
                         reply_markup=prices_keyboard())


@router.message(AdminStates.edit_nft_markup)
async def save_nft_markup(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(",", ".").rstrip("%")
    try:
        percent = Decimal(raw)
    except InvalidOperation:
        return await message.answer("Нужно число, например 15. Попробуйте ещё раз.")

    # Ноль — законная наценка (продажа по цене маркета), а вот отрицательная означала бы
    # продажу дешевле закупки, и почти наверняка это опечатка.
    if not 0 <= percent <= 200:
        return await message.answer("Наценка должна быть от 0 до 200 процентов.")

    # Кэш маркета трогать не нужно: там лежат цены в TON, наценка накладывается поверх при
    # каждом показе, поэтому новое значение действует сразу.
    await db.set_setting(runtime.KEY_NFT_MARKUP, str(percent))
    await reload_runtime()

    await state.clear()
    await message.answer(f"Наценка на подарки теперь <b>{percent}%</b>", parse_mode="HTML",
                         reply_markup=prices_keyboard())


@router.message(AdminStates.edit_per_star)
async def save_per_star(message: Message, state: FSMContext):
    price = _parse_price(message.text or "")
    if price is None:
        return await message.answer("Нужно положительное число. Попробуйте ещё раз.")

    await db.set_setting(SETTING_PER_STAR, str(price))
    apply_overrides(await db.get_settings())

    await state.clear()
    await message.answer(f"Цена за звезду теперь <b>{price}</b> грн", parse_mode="HTML",
                         reply_markup=prices_keyboard())


# --------------------------------------------------------------------------- settings

EDITABLE = {
    "card": (runtime.KEY_CARD_NUMBER, "Номер карты",
             "Пришлите номер карты (16 цифр, можно с пробелами)."),
    "holder": (runtime.KEY_CARD_HOLDER, "Получатель",
               "Пришлите имя получателя, как показывать клиентам."),
    "timeout": (runtime.KEY_ORDER_TIMEOUT, "Таймаут заказа",
                "Через сколько минут отменять неоплаченный заказ? Пришлите число."),
    "tolerance": (runtime.KEY_PAYMENT_TOLERANCE, "Допуск времени платежа",
                  "Максимальный разрыв между созданием заказа и временем платежа, в минутах."),
    "pdf_limit": (runtime.KEY_PDF_AUTO_LIMIT, "Лимит автовыдачи по PDF",
                  "До какой суммы в гривнах выдавать автоматически по PDF-квитанции? "
                  "Заказы дороже уйдут вам на подтверждение. Пришлите число."),
}


async def reload_runtime():
    runtime.apply(await db.get_settings())


@router.callback_query(F.data == "adm:settings:show")
async def show_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    auto = runtime.auto_delivery()
    testing = runtime.test_mode()

    text = (f"<b>Настройки</b>\n\n"
            + ("🧪 <b>ТЕСТОВЫЙ РЕЖИМ</b> — заказы проходят полностью (оплата, статусы, отзыв), "
               "но звёзды не выдаются и TON не тратятся.\n\n" if testing else "")
            + f"Автовыдача звёзд: <b>{'включена' if auto else 'выключена'}</b>\n"
            f"Карта: <code>{runtime.masked_card()}</code>\n"
            f"Получатель: {runtime.card_holder() or '—'}\n"
            f"Таймаут заказа: {runtime.order_timeout_minutes()} мин\n"
            f"Допуск времени платежа: {runtime.payment_tolerance_minutes()} мин\n"
            f"Автовыдача по PDF: до {runtime.pdf_auto_limit()} грн\n\n"
            f"Номер карты фиксируется в заказе при создании, поэтому смена карты "
            f"не ломает уже открытые заказы.")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [button("🔴 Выключить автовыдачу" if auto else "🟢 Включить автовыдачу", "settings", "toggle_auto")],
        [button("🧪 Выключить тестовый режим" if testing else "🧪 Включить тестовый режим",
                "settings", "toggle_test")],
        [button("💳 Карта", "settings", "edit", "card"),
         button("👤 Получатель", "settings", "edit", "holder")],
        [button("🕐 Таймаут заказа", "settings", "edit", "timeout"),
         button("⏱ Допуск платежа", "settings", "edit", "tolerance")],
        [button("📄 Лимит PDF", "settings", "edit", "pdf_limit")],
        [button("⬅️ В меню", "menu", "show")],
    ])
    await render(callback, text, keyboard)


@router.callback_query(F.data == "adm:settings:toggle_auto")
async def toggle_auto_delivery(callback: CallbackQuery, state: FSMContext):
    await db.set_setting(runtime.KEY_AUTO_DELIVERY, "0" if runtime.auto_delivery() else "1")
    await reload_runtime()
    await callback.answer("Автовыдача включена" if runtime.auto_delivery() else "Автовыдача выключена")
    await show_settings(callback, state)


@router.callback_query(F.data == "adm:settings:toggle_test")
async def toggle_test_mode(callback: CallbackQuery, state: FSMContext):
    await db.set_setting(runtime.KEY_TEST_MODE, "0" if runtime.test_mode() else "1")
    await reload_runtime()
    await callback.answer("Тестовый режим включён" if runtime.test_mode() else "Тестовый режим выключен")
    await show_settings(callback, state)


@router.callback_query(F.data.startswith("adm:settings:edit:"))
async def edit_setting(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[-1]
    if field not in EDITABLE:
        return await callback.answer("Неизвестная настройка", show_alert=True)

    _, title, prompt = EDITABLE[field]
    await state.update_data(field=field)
    await state.set_state(AdminStates.edit_setting)
    await callback.answer()
    await callback.message.edit_text(f"<b>{title}</b>\n\n{prompt}", parse_mode="HTML")


@router.message(AdminStates.edit_setting)
async def save_setting(message: Message, state: FSMContext):
    field = (await state.get_data())["field"]
    key, title, _ = EDITABLE[field]
    value = (message.text or "").strip()

    if field == "card":
        digits = re.sub(r"\D", "", value)
        if len(digits) < 12:
            return await message.answer("Не похоже на номер карты. Пришлите 16 цифр.")
        value = digits
    elif field == "pdf_limit":
        if _parse_price(value) is None:
            return await message.answer("Нужно положительное число (сумма в гривнах).")
        value = str(_parse_price(value))
    elif field in ("timeout", "tolerance"):
        if not value.isdigit() or not 1 <= int(value) <= 1440:
            return await message.answer("Нужно целое число минут от 1 до 1440.")
    elif not value:
        return await message.answer("Пустое значение не подходит.")

    await db.set_setting(key, value)
    await reload_runtime()
    await state.clear()

    shown = runtime.masked_card() if field == "card" else value
    await message.answer(f"<b>{title}</b> обновлено: {shown}", parse_mode="HTML",
                         reply_markup=main_keyboard())


# --------------------------------------------------------------------------- broadcast

# One broadcast at a time per admin, kept so the stop button can reach it.
_running: dict[int, broadcast.Progress] = {}


@router.callback_query(F.data == "adm:cast:show")
async def show_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    counts = {name: len(await db.broadcast_recipients(name)) for name in db.BROADCAST_AUDIENCES}
    rows = [[button(f"{title.capitalize()} — {counts[name]}", "cast", "pick", name)]
            for name, (title, _) in db.BROADCAST_AUDIENCES.items()]
    rows.append([button("⬅️ В меню", "menu", "show")])

    await render(callback, "<b>Рассылка</b>\n\nКому отправляем?",
                 InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:cast:pick:"))
async def pick_audience(callback: CallbackQuery, state: FSMContext):
    audience = callback.data.split(":")[-1]
    if audience not in db.BROADCAST_AUDIENCES:
        return await callback.answer("Неизвестная аудитория", show_alert=True)

    title, _ = db.BROADCAST_AUDIENCES[audience]
    recipients = await db.broadcast_recipients(audience)
    if not recipients:
        return await callback.answer("В этой аудитории никого нет", show_alert=True)

    await state.update_data(audience=audience)
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()
    await callback.message.edit_text(
        f"<b>Рассылка {title}</b> ({len(recipients)} чел.)\n\n"
        f"Пришлите сообщение — текст, фото, видео, что угодно. "
        f"Оно уйдёт получателям ровно в том виде, в каком вы его отправите.",
        parse_mode="HTML")


@router.message(AdminStates.broadcast_message)
async def preview_broadcast(message: Message, state: FSMContext):
    data = await state.get_data()
    audience = data["audience"]
    title, _ = db.BROADCAST_AUDIENCES[audience]
    recipients = await db.broadcast_recipients(audience)

    await state.update_data(message_id=message.message_id, chat_id=message.chat.id)
    await state.set_state(AdminStates.broadcast_confirm)

    await message.answer(
        f"👆 Так это увидят получатели.\n\n"
        f"Аудитория: <b>{title}</b>, {len(recipients)} чел.\n"
        f"Примерное время: ~{max(1, round(len(recipients) * broadcast.SEND_INTERVAL / 60))} мин.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [button("🚀 Отправить", "cast", "go")],
            [button("✖️ Отмена", "menu", "show")],
        ]))


@router.callback_query(F.data == "adm:cast:go")
async def start_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()

    admin_id = callback.from_user.id
    if admin_id in _running:
        return await callback.answer("Рассылка уже идёт", show_alert=True)

    recipients = await db.broadcast_recipients(data["audience"])
    progress = broadcast.Progress(total=len(recipients))
    _running[admin_id] = progress

    await callback.answer()
    status = await callback.message.edit_text(
        f"📢 Рассылка запущена: 0 из {progress.total}", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button("⏹ Остановить", "cast", "stop")]]))

    async def on_progress(current: broadcast.Progress):
        try:
            await status.edit_text(
                f"📢 Рассылка идёт: {current.done} из {current.total}\n{current.summary()}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[button("⏹ Остановить", "cast", "stop")]]))
        except TelegramBadRequest:
            pass  # identical text, nothing to update

    async def worker():
        try:
            await broadcast.run(bot, recipients,
                                broadcast.copier(bot, data["chat_id"], data["message_id"]),
                                progress, on_progress)
        except Exception:
            logger.exception("broadcast crashed")
        finally:
            _running.pop(admin_id, None)
            try:
                await status.edit_text(f"📢 <b>Рассылка завершена</b>\n\n{progress.summary()}",
                                       parse_mode="HTML", reply_markup=main_keyboard())
            except TelegramBadRequest:
                pass

    asyncio.create_task(worker())


@router.callback_query(F.data == "adm:cast:stop")
async def stop_broadcast(callback: CallbackQuery):
    progress = _running.get(callback.from_user.id)
    if not progress:
        return await callback.answer("Активной рассылки нет", show_alert=True)

    progress.cancel()
    await callback.answer("Останавливаю...")


@router.callback_query(F.data.startswith("adm:orders:receipt:"))
async def show_receipt(callback: CallbackQuery, bot: Bot):
    order = await db.get_order(int(callback.data.split(":")[-1]))
    if not order or not order.receipt_file_id:
        return await callback.answer("Квитанция не сохранена", show_alert=True)

    await callback.answer()
    await bot.send_document(callback.from_user.id, order.receipt_file_id,
                            caption=f"Квитанция к заказу #{order.id}")


@router.callback_query(F.data.startswith("adm:orders:approve:"))
async def approve_order(callback: CallbackQuery, bot: Bot):
    order = await db.get_order(int(callback.data.split(":")[-1]))
    if not order:
        return await callback.answer("Заказ не найден", show_alert=True)
    if order.status not in REVIEW:
        return await callback.answer(f"Статус {order.status}, подтверждение не нужно", show_alert=True)

    await db.update_order(order.id, status="paid")
    await deliver_order(callback, bot)  # answers the callback itself


@router.callback_query(F.data.startswith("adm:orders:reject:"))
async def reject_order(callback: CallbackQuery, bot: Bot):
    order = await db.get_order(int(callback.data.split(":")[-1]))
    if not order:
        return await callback.answer("Заказ не найден", show_alert=True)

    await db.update_order(order.id, status="failed")
    rejected = await db.get_order(order.id)
    await callback.answer("Отклонено")
    await render(callback, f"{await order_card_text(rejected)}\n\n❌ Отклонено администратором.",
                 order_card_keyboard(rejected))

    try:
        from shop.texts import t as translate
        language = await db.get_language(order.user_id) or "uk"
        await bot.send_message(order.user_id, translate(language, "order_rejected", order_id=order.id))
    except Exception:
        logger.warning("cannot notify buyer %s about rejected order %s", order.user_id, order.id)


# --------------------------------------------------------------------------- admins

async def reload_admins():
    runtime.apply_admins(await db.admin_ids())


def admins_keyboard(rows_data) -> InlineKeyboardMarkup:
    rows = [[button(f"🗑 {row['user_id']}" + (f" · {row['note']}" if row["note"] else ""),
                    "admins", "remove", row["user_id"])] for row in rows_data]
    rows.append([button("➕ Добавить админа", "admins", "add")])
    rows.append([button("⬅️ В меню", "menu", "show")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "adm:admins:show")
async def show_admins(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    added = await db.list_admins()

    owners = "\n".join(f"  <code>{uid}</code>" for uid in sorted(ADMIN_IDS)) or "  —"
    text = (f"<b>Администраторы</b>\n\n"
            f"Из <code>.env</code> (постоянные, снять нельзя):\n{owners}\n\n"
            f"Добавленные из панели: {len(added)}\n"
            f"Нажмите на запись, чтобы удалить её.")

    await render(callback, text, admins_keyboard(added))


@router.callback_query(F.data == "adm:admins:add")
async def ask_admin_id(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_admin)
    await callback.answer()
    await callback.message.edit_text(
        "Пришлите Telegram ID нового администратора числом.\n\n"
        "Можно добавить подпись через пробел, например:\n<code>123456789 Олег, поддержка</code>\n\n"
        "Свой ID человек может узнать у @userinfobot.", parse_mode="HTML")


@router.message(AdminStates.add_admin)
async def save_admin(message: Message, state: FSMContext):
    parts = (message.text or "").strip().split(maxsplit=1)
    if not parts or not parts[0].lstrip("-").isdigit():
        return await message.answer("Нужен числовой Telegram ID. Попробуйте ещё раз.")

    user_id = int(parts[0])
    note = parts[1] if len(parts) > 1 else None

    if runtime.is_admin(user_id):
        await state.clear()
        return await message.answer("Этот пользователь уже администратор.",
                                    reply_markup=main_keyboard())

    added = await db.add_admin(user_id, note, message.from_user.id)
    await reload_admins()
    await state.clear()

    logger.info("admin %s added %s as admin", message.from_user.id, user_id)
    await message.answer(f"{'Добавлен' if added else 'Уже есть'}: <code>{user_id}</code>",
                         parse_mode="HTML", reply_markup=admins_keyboard(await db.list_admins()))


@router.callback_query(F.data.startswith("adm:admins:remove:"))
async def drop_admin(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[-1])

    if runtime.is_owner(user_id):
        return await callback.answer("Это админ из .env, снять его отсюда нельзя", show_alert=True)

    await db.remove_admin(user_id)
    await reload_admins()
    logger.info("admin %s removed %s", callback.from_user.id, user_id)

    await callback.answer("Удалён")
    await show_admins(callback, state)


@router.message(AdminStates.edit_premium)
async def save_premium_price(message: Message, state: FSMContext):
    price = _parse_price(message.text or "")
    if price is None:
        return await message.answer("Нужно положительное число. Попробуйте ещё раз.")

    months = (await state.get_data())["premium_months"]
    await db.set_setting(f"{SETTING_PREMIUM_PREFIX}{months}", str(price))
    apply_overrides(await db.get_settings())

    await state.clear()
    await message.answer(f"Premium {months} мес. теперь <b>{price}</b> грн", parse_mode="HTML",
                         reply_markup=prices_keyboard())


@router.message(AdminStates.edit_ton)
async def save_ton_price(message: Message, state: FSMContext):
    price = _parse_price(message.text or "")
    if price is None:
        return await message.answer("Нужно положительное число. Попробуйте ещё раз.")

    await db.set_setting(SETTING_TON_PRICE, str(price))
    apply_overrides(await db.get_settings())

    await state.clear()
    await message.answer(f"Курс TON теперь <b>{price}</b> грн", parse_mode="HTML",
                         reply_markup=prices_keyboard())


# --------------------------------------------------------------------------- test payment

TEST_TON = Decimal("0.1")


@router.message(Command("testpay"))
async def test_payment(message: Message, state: FSMContext):
    """Create a throwaway order to exercise the crypto flow end to end.

    Priced in TON directly and never delivered — the point is to verify that a payment is
    detected, not to move goods. The real price list is untouched.
    """
    from shop import crypto
    from shop.keyboards import crypto_check_keyboard
    from shop.texts import t

    parts = (message.text or "").split()
    tons = Decimal(parts[1].replace(",", ".")) if len(parts) > 1 else TEST_TON

    rate = await asyncio.to_thread(crypto.market_rate)
    price = (tons * rate).quantize(Decimal("0.01"))

    order_id = await db.create_order(message.from_user.id, "test", "—", 1, price,
                                     card_number=runtime.card_number(),
                                     details=f"тестовая оплата {tons} TON")
    await db.update_order(order_id, payment_method="crypto", status="awaiting_check")
    await state.update_data(order_id=order_id)

    address = await crypto.wallet_address()
    await message.answer(
        f"🧪 <b>Тестовый заказ #{order_id}</b>\n\n"
        + t(ADMIN_LANGUAGE, "crypto_details", wallet=address,
            amount=crypto.amount_ton(price, rate), rate=f"{rate:.2f}",
            comment=crypto.comment_for(order_id), product=f"тест {tons} TON",
            timeout=runtime.order_timeout_minutes())
        + "\n\n<i>Ничего не будет выдано — проверяется только приём оплаты.</i>",
        parse_mode="HTML", reply_markup=crypto_check_keyboard(ADMIN_LANGUAGE, order_id))


@router.message(AdminStates.edit_bulk)
async def save_bulk_rate(message: Message, state: FSMContext):
    parts = (message.text or "").replace(",", ".").split()
    if len(parts) != 2 or not parts[0].isdigit() or _parse_price(parts[1]) is None:
        return await message.answer("Нужны два числа: порог и ставка. Например: 3000 0.72")

    threshold, rate = int(parts[0]), _parse_price(parts[1])
    await db.set_setting(SETTING_BULK_FROM, str(threshold))
    await db.set_setting(SETTING_BULK_RATE, str(rate))
    apply_overrides(await db.get_settings())

    await state.clear()
    await message.answer(f"Сверх <b>{threshold}</b> ⭐ ставка теперь <b>{rate}</b> грн за звезду",
                         parse_mode="HTML", reply_markup=prices_keyboard())
