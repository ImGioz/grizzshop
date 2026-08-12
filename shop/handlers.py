"""All bot handlers: onboarding, menu, star purchase, payment verification."""

import asyncio
import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from monobank_receipt import ReceiptError, fetch_receipt
from shop import crypto
from shop import db
from shop import nft_market
from shop import nft_stock
from shop import price_cache
from shop import reviews
from shop import runtime
from shop.config import ADMIN_IDS, CHANNEL_ID, MIN_STARS
from shop.delivery import (DeliveryError, check_recipient, deliver_gram, deliver_stars,
                           parse_ton_address)
from shop.keyboards import (calculator_again_keyboard, calculator_keyboard,
                            check_payment_keyboard, crypto_check_keyboard,
                            language_keyboard, main_menu,
                            months_keyboard, nft_buy_keyboard, nft_confirm_keyboard,
                            nft_type_keyboard,
                            payment_method_keyboard, product_label, stock_keyboard,
                            quantity_keyboard, recipient_keyboard, retry_keyboard,
                            subscription_keyboard)
from shop.prices import (GRAM_ENABLED, MIN_TON, PREMIUM_ENABLED, TON_PRICE_UAH,
                         gram_price, premium_price, star_price, star_rate, stars_for_budget)
from shop.texts import DEFAULT_LANGUAGE, t

logger = logging.getLogger(__name__)
router = Router()

USERNAME_PATTERN = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
RECEIPT_PATTERN = re.compile(r"check\.monobank(?:\.com)?\.ua/p/[^\s]+")
SUBSCRIBED_STATUSES = {"member", "administrator", "creator"}

# Each gift in the window costs one Portals request to price, and Portals rate-limits.
STOCK_LIMIT = 12


class Calculator(StatesGroup):
    stars = State()
    uah = State()


class Purchase(StatesGroup):
    friend_username = State()
    custom_quantity = State()
    sender_name = State()
    receipt_link = State()
    gram_wallet = State()
    gram_amount = State()
    nft_request = State()
    nft_confirm = State()


def nft_price(floor_ton: Decimal, rate: Decimal | None = None) -> Decimal:
    """Marketplace floor in TON converted to UAH with the shop markup on top.

    The market rate is the cost basis, not TON_PRICE_UAH: the latter is the price we *sell*
    TON at, so using it here multiplied the Gram margin by the NFT markup — a declared 10%
    turned into nearly 40%.
    """
    rate = rate or crypto.market_rate()
    total = floor_ton * rate * (1 + runtime.nft_markup_percent() / 100)
    return total.quantize(Decimal("1"), rounding=ROUND_CEILING)


def _stock_payload(gift) -> dict:
    """What the confirmation card and the order need; the gift itself is re-read before transfer."""
    return {"price": str(gift.price_uah), "details": gift.details, "link": gift.link,
            "collection": gift.title, "model": gift.model or "—",
            "symbol": gift.symbol or "—", "backdrop": gift.backdrop or "—"}


async def cost_in_uah(nanotons: int) -> Decimal:
    """Convert what we spent into hryvnia at the live rate, for margin reporting."""
    if not nanotons:
        return Decimal(0)
    rate = await asyncio.to_thread(crypto.market_rate)
    return ((Decimal(nanotons) / Decimal(10 ** 9)) * rate).quantize(Decimal("0.01"))


def nft_details(listing) -> str:
    parts = [listing.name] + [p for p in (listing.model, listing.symbol, listing.backdrop) if p]
    return " · ".join(parts)


async def language_of(user_id: int) -> str:
    return await db.get_language(user_id) or DEFAULT_LANGUAGE


async def is_subscribed(bot: Bot, user_id: int) -> bool | None:
    """True/False, or None when Telegram would not tell us (bot not admin, channel wrong)."""
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
    except TelegramBadRequest as error:
        logger.error("subscription check failed for %s: %s", user_id, error)
        return None
    return member.status in SUBSCRIBED_STATUSES


def payment_ok_text(language: str, product: str) -> str:
    """"Issuing stars" would be wrong for a Premium or TON order."""
    suffix = f"_{product}" if product in ("premium", "gram", "nft", "nft_stock") else ""
    return t(language, f"payment_ok{suffix}")


async def notify_admins(bot: Bot, text: str):
    for admin_id in runtime.admin_ids():
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            logger.exception("cannot notify admin %s", admin_id)


# --------------------------------------------------------------------------- onboarding

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await db.upsert_user(message.from_user.id, message.from_user.username)

    language = await db.get_language(message.from_user.id)
    if not language:
        return await message.answer(t(DEFAULT_LANGUAGE, "choose_language"), reply_markup=language_keyboard())

    await enter_shop(message, message.from_user.id, language)


async def enter_shop(message: Message, user_id: int, language: str):
    """Someone already marked as subscribed goes straight to the menu."""
    user = await db.get_user(user_id)
    if user and user["subscribed"]:
        return await message.answer(t(language, "main_menu"), reply_markup=main_menu(language))

    await send_subscription_gate(message, language)


async def send_subscription_gate(message: Message, language: str):
    await message.answer(t(language, "subscribe_required"), reply_markup=subscription_keyboard(language))


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery):
    language = callback.data.split(":", 1)[1]
    await db.upsert_user(callback.from_user.id, callback.from_user.username)
    await db.set_language(callback.from_user.id, language)

    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(t(language, "language_set"))
    await enter_shop(callback.message, callback.from_user.id, language)


@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery, bot: Bot):
    language = await language_of(callback.from_user.id)
    subscribed = await is_subscribed(bot, callback.from_user.id)

    if subscribed is None:
        return await callback.answer(t(language, "subscription_check_failed"), show_alert=True)
    if not subscribed:
        return await callback.answer(t(language, "not_subscribed"), show_alert=True)

    await db.set_subscribed(callback.from_user.id, True)
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(t(language, "subscription_ok"), reply_markup=main_menu(language))


# --------------------------------------------------------------------------- gate for everything else

async def require_access(message: Message, bot: Bot) -> str | None:
    """Return the language when the user may proceed, otherwise re-show the gate and return None."""
    language = await db.get_language(message.from_user.id)
    if not language:
        await message.answer(t(DEFAULT_LANGUAGE, "choose_language"), reply_markup=language_keyboard())
        return None

    subscribed = await is_subscribed(bot, message.from_user.id)
    if subscribed is None:
        await message.answer(t(language, "subscription_check_failed"))
        return None
    if not subscribed:
        await db.set_subscribed(message.from_user.id, False)
        await send_subscription_gate(message, language)
        return None

    return language


# --------------------------------------------------------------------------- menu

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    language = await language_of(message.from_user.id)
    await message.answer(t(language, "cancelled"), reply_markup=main_menu(language))


@router.message(F.text.in_({t("uk", "menu_stars"), t("ru", "menu_stars")}))
async def menu_stars(message: Message, state: FSMContext, bot: Bot):
    language = await require_access(message, bot)
    if not language:
        return
    await state.clear()
    await state.update_data(product="stars")
    await message.answer(t(language, "stars_for_whom"), reply_markup=recipient_keyboard(language))


@router.message(F.text.in_({t("uk", "menu_premium"), t("ru", "menu_premium")}))
async def menu_premium(message: Message, state: FSMContext, bot: Bot):
    language = await require_access(message, bot)
    if not language:
        return
    if not PREMIUM_ENABLED:
        return await message.answer(t(language, "premium_soon"))

    await state.clear()
    await state.update_data(product="premium")
    await message.answer(t(language, "premium_for_whom"), reply_markup=recipient_keyboard(language))


@router.message(F.text.in_({t("uk", "menu_gram"), t("ru", "menu_gram")}))
async def menu_gram(message: Message, state: FSMContext, bot: Bot):
    language = await require_access(message, bot)
    if not language:
        return
    if not GRAM_ENABLED:
        return await message.answer(t(language, "gram_soon"))

    await state.clear()
    await state.update_data(product="gram")
    await state.set_state(Purchase.gram_wallet)
    await message.answer(t(language, "gram_ask_wallet"), parse_mode="HTML")


@router.message(Purchase.gram_wallet)
async def set_gram_wallet(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)

    wallet = parse_ton_address(message.text or "")
    if not wallet:
        return await message.answer(t(language, "gram_bad_wallet"))

    await state.update_data(wallet=wallet)
    await state.set_state(Purchase.gram_amount)
    await message.answer(t(language, "gram_ask_amount", wallet=wallet,
                           min_ton=MIN_TON, rate=TON_PRICE_UAH), parse_mode="HTML")


@router.message(Purchase.gram_amount)
async def set_gram_amount(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)

    amount = _positive_number(message.text)
    if amount is None or amount < MIN_TON:
        return await message.answer(t(language, "gram_bad_amount", min_ton=MIN_TON))

    # stored as nanotons so the integer quantity column keeps the amount exactly
    nanotons = int(amount * 10 ** 9)
    await state.set_state(None)
    await create_order_message(message, message.from_user.id, state, nanotons, language)


@router.message(F.text.in_({t("uk", "menu_calculator"), t("ru", "menu_calculator")}))
async def menu_calculator(message: Message, state: FSMContext, bot: Bot):
    language = await require_access(message, bot)
    if not language:
        return
    await state.clear()
    await message.answer(t(language, "calc_choose"), parse_mode="HTML",
                         reply_markup=calculator_keyboard(language))


@router.callback_query(F.data == "calc:menu")
async def calculator_menu(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.clear()
    await callback.answer()
    await callback.message.answer(t(language, "calc_choose"), parse_mode="HTML",
                                  reply_markup=calculator_keyboard(language))


@router.callback_query(F.data.in_({"calc:to_uah", "calc:to_stars"}))
async def calculator_direction(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    to_uah = callback.data.endswith("to_uah")

    await state.set_state(Calculator.stars if to_uah else Calculator.uah)
    await callback.answer()
    await callback.message.edit_text(t(language, "calc_ask_stars" if to_uah else "calc_ask_uah"))


def _positive_number(text: str) -> Decimal | None:
    try:
        value = Decimal((text or "").strip().replace(",", "."))
    except InvalidOperation:
        return None
    return value if value > 0 else None


@router.message(Calculator.stars)
async def calculate_to_uah(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    quantity = _positive_number(message.text)
    if quantity is None or quantity != quantity.to_integral_value():
        return await message.answer(t(language, "calc_bad_number"))

    quantity = int(quantity)
    price = star_price(quantity)
    text = t(language, "calc_result_to_uah", quantity=quantity, price=price,
             rate=star_rate(quantity))
    if quantity < MIN_STARS:
        text += t(language, "calc_min_note", min_stars=MIN_STARS)

    await state.clear()
    await message.answer(text, parse_mode="HTML", reply_markup=calculator_again_keyboard(language))


@router.message(Calculator.uah)
async def calculate_to_stars(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    amount = _positive_number(message.text)
    if amount is None:
        return await message.answer(t(language, "calc_bad_number"))

    quantity = stars_for_budget(amount)
    if quantity < 1:
        text = t(language, "calc_result_to_stars", amount=amount, quantity=0, price=0,
                 rate=star_rate(1))
    else:
        text = t(language, "calc_result_to_stars", amount=amount, quantity=quantity,
                 price=star_price(quantity), rate=star_rate(quantity))
    if quantity < MIN_STARS:
        text += t(language, "calc_min_note", min_stars=MIN_STARS)

    await state.clear()
    await message.answer(text, parse_mode="HTML", reply_markup=calculator_again_keyboard(language))


@router.message(F.text.in_({t("uk", "menu_profile"), t("ru", "menu_profile")}))
async def menu_profile(message: Message, bot: Bot):
    language = await require_access(message, bot)
    if not language:
        return

    paid_orders, total_stars = await db.profile_stats(message.from_user.id)
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    await message.answer(
        t(language, "profile", user_id=message.from_user.id, username=username,
          language=language, paid_orders=paid_orders, total_stars=total_stars),
        parse_mode="HTML")


# --------------------------------------------------------------------------- buying stars

@router.callback_query(F.data.startswith("who:"))
async def choose_recipient(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await callback.answer()

    if callback.data.endswith("friend"):
        await state.set_state(Purchase.friend_username)
        return await callback.message.edit_text(t(language, "ask_friend_username"))

    username = callback.from_user.username
    if not username:
        await state.clear()
        return await callback.message.edit_text(t(language, "no_username"))

    await state.update_data(recipient=username)
    await state.set_state(None)
    await show_amount_choice(callback.message, state, language, edit=True)


@router.message(Purchase.friend_username)
async def set_friend_username(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    match = USERNAME_PATTERN.match((message.text or "").strip())
    if not match:
        return await message.answer(t(language, "bad_username"))

    await state.update_data(recipient=match.group(1))
    await state.set_state(None)
    await show_amount_choice(message, state, language, edit=False)


async def show_amount_choice(message: Message, state: FSMContext, language: str, edit: bool):
    """Stars pick a quantity, Premium picks a subscription length."""
    data = await state.get_data()
    product = data.get("product", "stars")
    send = message.edit_text if edit else message.answer

    if product == "premium":
        # Fragment откажет уже после оплаты, если у получателя есть подписка, поэтому
        # спрашиваем его заранее — деньги за то, что нельзя выдать, брать нельзя.
        recipient = data.get("recipient", "")
        problem = await check_recipient(recipient, "premium")
        if problem:
            await state.clear()
            key = {"already_premium": "premium_already",
                   "not_a_user": "premium_recipient_not_user"}.get(
                       problem, "premium_recipient_unknown")
            return await send(t(language, key, recipient=recipient), parse_mode="HTML")

        text, keyboard = t(language, "choose_months"), months_keyboard(language)
    else:
        text, keyboard = t(language, "choose_quantity"), quantity_keyboard(language)

    await send(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("months:"))
async def choose_months(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await callback.answer()
    await create_order_message(callback.message, callback.from_user.id, state,
                               int(callback.data.split(":", 1)[1]), language)


@router.callback_query(F.data.startswith("qty:"))
async def choose_quantity(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    if choice == "custom":
        await state.set_state(Purchase.custom_quantity)
        return await callback.message.edit_text(t(language, "ask_custom_quantity", min_stars=MIN_STARS))

    await create_order_message(callback.message, callback.from_user.id, state, int(choice), language)


@router.message(Purchase.custom_quantity)
async def set_custom_quantity(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < MIN_STARS:
        return await message.answer(t(language, "bad_quantity", min_stars=MIN_STARS))

    await state.set_state(None)
    await create_order_message(message, message.from_user.id, state, int(text), language)


async def create_order_message(message: Message, user_id: int, state: FSMContext,
                               quantity: int, language: str):
    data = await state.get_data()
    # a gram order goes to a wallet address, so there is no @username to collect
    recipient = data.get("recipient") or data.get("wallet", "")
    if not recipient:
        return await message.answer(t(language, "no_active_order"))

    product = data.get("product", "stars")
    price = {"premium": premium_price, "gram": gram_price}.get(product, star_price)(quantity)

    # snapshot the card so a later change in the admin panel cannot desync this order
    order_id = await db.create_order(user_id, product, recipient, quantity, price,
                                     card_number=runtime.card_number(),
                                     wallet_address=data.get("wallet"))
    await state.update_data(order_id=order_id)

    text = t(language, "order_created", recipient=f"@{recipient}",
             product=product_label(language, product, quantity), price=price)
    await message.answer(text, parse_mode="HTML",
                         reply_markup=payment_method_keyboard(language, order_id))


@router.callback_query(F.data.startswith("pay:"))
async def choose_payment_method(callback: CallbackQuery, state: FSMContext):
    _, method, order_id = callback.data.split(":")
    order_id = int(order_id)
    language = await language_of(callback.from_user.id)
    await callback.answer()

    if method == "crypto":
        order = await db.get_order(order_id)
        if not order or order.status not in db.PENDING_STATUSES:
            return await callback.message.answer(t(language, "order_expired"))

        await db.update_order(order_id, payment_method="crypto", status="awaiting_check")
        await state.update_data(order_id=order_id)

        rate = await asyncio.to_thread(crypto.market_rate)
        amount = crypto.amount_ton(order.price, rate)
        address = await crypto.wallet_address()
        return await callback.message.edit_text(
            t(language, "crypto_details", wallet=address, amount=amount,
              rate=f"{rate:.2f}", comment=crypto.comment_for(order_id),
              product=product_label(language, order.product, order.quantity, order.details),
              timeout=runtime.order_timeout_minutes()),
            parse_mode="HTML", reply_markup=crypto_check_keyboard(language, order_id))

    order = await db.get_order(order_id)
    if not order or order.status not in db.PENDING_STATUSES:
        return await callback.message.answer(t(language, "order_expired"))

    await db.update_order(order_id, payment_method="transfer", status="awaiting_check")
    await state.update_data(order_id=order_id)

    await callback.message.edit_text(
        t(language, "payment_details", card=order.card_number or runtime.card_number(),
          holder=runtime.card_holder(), price=order.price,
          product=product_label(language, order.product, order.quantity, order.details),
          order_id=order_id, timeout=runtime.order_timeout_minutes()),
        parse_mode="HTML", reply_markup=check_payment_keyboard(language, order_id))


# --------------------------------------------------------------------------- payment verification

@router.callback_query(F.data.startswith("crypto:"))
async def crypto_check(callback: CallbackQuery, state: FSMContext, bot: Bot):
    order_id = int(callback.data.split(":", 1)[1])
    language = await language_of(callback.from_user.id)

    order = await db.get_order(order_id)
    if not order or order.status not in db.PENDING_STATUSES:
        return await callback.answer(t(language, "order_expired"), show_alert=True)

    await callback.answer()
    status = await callback.message.answer(t(language, "crypto_checking"))

    rate = await asyncio.to_thread(crypto.market_rate)
    amount = crypto.amount_ton(order.price, rate)
    payment = await crypto.find_payment(order_id, amount, order.created_at)
    if not payment:
        return await status.edit_text(
            t(language, "crypto_not_found", comment=crypto.comment_for(order_id)),
            parse_mode="HTML", reply_markup=crypto_check_keyboard(language, order_id))

    if not await db.mark_paid(order.id, payment.receipt_id,
                              {"source": "ton", "lt": payment.lt, "amount": str(payment.tons)}):
        return await status.edit_text(t(language, "receipt_already_used"))

    await state.clear()
    await status.edit_text(payment_ok_text(language, order.product))
    await notify_admins(bot, f"💎 Заказ <code>{order.id}</code> оплачен в TON: "
                             f"{payment.tons} TON, {order.price} грн")
    await fulfil_order(callback.message, bot, order, language, state)


@router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":", 1)[1])
    language = await language_of(callback.from_user.id)

    order = await db.get_order(order_id)
    if not order or order.user_id != callback.from_user.id:
        return await callback.answer(t(language, "no_active_order"), show_alert=True)
    if order.status not in db.PENDING_STATUSES:
        # already paid: cancelling here would drop an order someone has money in
        return await callback.answer(t(language, "order_expired"), show_alert=True)

    # Kept, not deleted: a customer may pay right after cancelling, and a payment whose order
    # no longer exists cannot be matched to anything — the money just sits on the wallet.
    await db.update_order(order_id, status="cancelled")
    await state.clear()
    logger.info("order %s cancelled by user %s", order_id, callback.from_user.id)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t(language, "order_cancelled", order_id=order_id),
                                  reply_markup=main_menu(language))


@router.callback_query(F.data.startswith("check:"))
async def start_check(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":", 1)[1])
    language = await language_of(callback.from_user.id)
    await callback.answer()

    order = await db.get_order(order_id)
    if not order or order.status not in db.PENDING_STATUSES:
        return await callback.message.answer(t(language, "order_expired"))

    await state.update_data(order_id=order_id)
    await state.set_state(Purchase.sender_name)
    await callback.message.answer(t(language, "ask_sender_name"))


@router.message(Purchase.sender_name)
async def set_sender_name(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    name = (message.text or "").strip()
    if len(name.split()) < 2:
        return await message.answer(t(language, "ask_sender_name"))

    data = await state.get_data()
    await db.update_order(data["order_id"], sender_name=name)
    await state.set_state(Purchase.receipt_link)
    await message.answer(t(language, "ask_receipt_any"))


MAX_PDF_MB = 10


@router.message(Purchase.receipt_link, F.document)
async def set_receipt_pdf(message: Message, state: FSMContext, bot: Bot):
    """A PDF receipt works for any bank: we search it for values we already expect."""
    from shop import pdf_receipt
    from shop.verification import verify_pdf

    language = await language_of(message.from_user.id)
    document = message.document

    if not (document.file_name or "").lower().endswith(".pdf") and document.mime_type != "application/pdf":
        return await message.answer(t(language, "bad_receipt_link"))
    if document.file_size and document.file_size > MAX_PDF_MB * 1024 * 1024:
        return await message.answer(t(language, "pdf_too_big", limit=MAX_PDF_MB))

    data = await state.get_data()
    order = await db.get_order(data["order_id"])
    if not order or order.status not in db.PENDING_STATUSES:
        await state.clear()
        return await message.answer(t(language, "order_expired"))

    status = await message.answer(t(language, "checking_receipt"))
    logger.info("order %s: checking a PDF receipt (%s, %s bytes)",
                order.id, document.file_name, document.file_size)

    buffer = await bot.download(document.file_id)
    try:
        receipt = await asyncio.to_thread(pdf_receipt.parse, buffer.read())
    except pdf_receipt.PdfReceiptError as error:
        key = "pdf_no_text" if "нет текста" in str(error) else "pdf_error"
        return await status.edit_text(t(language, key, error=error),
                                      reply_markup=retry_keyboard(language, order.id))

    result = verify_pdf(receipt, order)
    if not result.ok:
        return await status.edit_text(t(language, result.reason_key, **(result.details or {})),
                                      reply_markup=retry_keyboard(language, order.id))

    details = result.details
    fingerprint = receipt.fingerprint(details["amount"], details["moment"], details["last4"])
    if not await db.mark_paid(order.id, fingerprint, {"source": "pdf",
                                                      "receiptNumber": receipt.receipt_number,
                                                      "amount": str(details["amount"]),
                                                      "paymentDate": details["moment"].isoformat()}):
        return await status.edit_text(t(language, "receipt_already_used"))

    await db.update_order(order.id, receipt_file_id=document.file_id)
    await state.clear()

    # a PDF text layer is editable, so large sums stop for a human
    if Decimal(order.price) > runtime.pdf_auto_limit():
        await db.update_order(order.id, status="review")
        await status.edit_text(t(language, "order_on_review", limit=runtime.pdf_auto_limit()))
        return await notify_admins(bot, f"🔍 Заказ <code>{order.id}</code> оплачен по PDF на "
                                        f"{order.price} грн — нужна проверка.\n"
                                        f"{order.quantity} ⭐ → @{order.recipient}\n"
                                        f"Откройте /adminka → Заказы → На проверке.")

    await status.edit_text(payment_ok_text(language, order.product))
    await notify_admins(bot, f"💰 Заказ <code>{order.id}</code> оплачен по PDF: {order.quantity} ⭐ "
                             f"для @{order.recipient}, {order.price} грн")
    await fulfil_order(message, bot, order, language, state)


@router.message(Purchase.receipt_link)
async def set_receipt_link(message: Message, state: FSMContext, bot: Bot):
    from shop.verification import verify_payment  # imported here to keep module import cheap

    language = await language_of(message.from_user.id)
    match = RECEIPT_PATTERN.search(message.text or "")
    if not match:
        return await message.answer(t(language, "ask_receipt_any"))

    data = await state.get_data()
    order = await db.get_order(data["order_id"])
    if not order or order.status not in db.PENDING_STATUSES:
        await state.clear()
        return await message.answer(t(language, "order_expired"))

    logger.info("order %s: checking receipt %s (sender_name=%r, expected %s UAH)",
                order.id, match.group(0), order.sender_name, order.price)

    status = await message.answer(t(language, "checking_receipt"))
    try:
        receipt = await fetch_receipt(match.group(0))
    except ReceiptError as error:
        return await status.edit_text(t(language, "receipt_error", error=error),
                                      reply_markup=retry_keyboard(language, order.id))

    result = verify_payment(receipt, order)
    if not result.ok:
        return await status.edit_text(t(language, result.reason_key, **(result.details or {})),
                                      reply_markup=retry_keyboard(language, order.id))

    if not await db.mark_paid(order.id, receipt.receipt_id, receipt.to_dict()):
        return await status.edit_text(t(language, "receipt_already_used"))

    await state.clear()
    await status.edit_text(payment_ok_text(language, order.product))
    await notify_admins(bot, f"💰 Заказ <code>{order.id}</code> оплачен: {order.quantity} ⭐ "
                             f"для @{order.recipient}, {order.price} грн")

    await fulfil_order(message, bot, order, language, state)


async def fulfil_order(message: Message, bot: Bot, order, language: str, state: FSMContext):
    what = product_label(language, order.product, order.quantity, order.details)
    target = order.wallet_address if order.product == "gram" else f"@{order.recipient}"

    if not runtime.auto_delivery():  # toggled live from the admin panel
        await notify_admins(bot, f"⚠️ Ручная выдача: заказ <code>{order.id}</code>, "
                                 f"{what} → {target}")
        return await message.answer(t(language, "delivery_failed"))

    if order.product == "test":
        # a payment-flow rehearsal: confirm receipt and stop, nothing is delivered
        await db.update_order(order.id, status="delivered")
        return await message.answer("🧪 Тестовая оплата принята. Ничего не выдано.")

    if order.product == "nft_stock":
        # Telegram currently withholds can_transfer_and_upgrade_gifts from business bots, so the
        # automatic path is attempted first and falls back to a manual handover when refused.
        # Once the restriction is lifted this starts working on its own, with no code change.
        try:
            gift = await nft_stock.by_id(bot, order.wallet_address)
            if not gift:
                raise nft_stock.StockError("подарок больше не доступен к передаче")
            await nft_stock.transfer(bot, gift, order.user_id)
        except nft_stock.StockError as error:
            logger.warning("automatic transfer unavailable for order %s: %s", order.id, error)
            await db.update_order(order.id, status="paid")
            await notify_admins(bot, f"🖼 Заказ <code>{order.id}</code> оплачен: {order.details}\n"
                                     f"Покупатель @{order.recipient} (<code>{order.user_id}</code>).\n"
                                     f"Автопередача недоступна: {error}\n"
                                     f"Передайте подарок вручную.")
            return await message.answer(t(language, "delivery_ok_nft"))

        await db.update_order(order.id, status="delivered")
        await message.answer(t(language, "delivery_ok_nft_stock", details=order.details),
                             parse_mode="HTML")
        return await ask_for_review(message, state, order, language)

    if order.product == "nft":
        # nothing to automate: the gift is transferred by hand from the manager's profile
        await notify_admins(bot, f"🖼 Заказ <code>{order.id}</code> оплачен: {what}\n"
                                 f"Покупатель @{order.recipient}. Нужна ручная передача подарка.")
        await db.update_order(order.id, status="paid")
        return await message.answer(t(language, "delivery_ok_nft"))

    try:
        if order.product == "gram":
            spent = await deliver_gram(order.wallet_address, order.quantity)
        else:
            spent = await deliver_stars(order.recipient, order.quantity, order.product)
    except DeliveryError as error:
        logger.error("delivery failed for order %s: %s", order.id, error)
        await db.update_order(order.id, status="failed")
        await notify_admins(bot, f"❌ Заказ <code>{order.id}</code> оплачен, но выдача упала: {error}\n"
                                 f"Нужна ручная выдача: {what} → {target}")
        return await message.answer(t(language, "delivery_failed"))

    # record what the delivery actually cost, so the margin can be reported later
    await db.update_order(order.id, status="delivered", cost_uah=str(await cost_in_uah(spent)))

    if order.product == "gram":
        done = t(language, "delivery_ok_gram", amount=f"{order.quantity / 10 ** 9:g}",
                 wallet=order.wallet_address)
    else:
        done_key = "delivery_ok_premium" if order.product == "premium" else "delivery_ok"
        done = t(language, done_key, quantity=order.quantity, recipient=f"@{order.recipient}")

    await message.answer(done, parse_mode="HTML")
    await ask_for_review(message, state, order, language)


# --------------------------------------------------------------------------- reviews

class Review(StatesGroup):
    comment = State()
    photo = State()


def rating_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️" * n, callback_data=f"rev:rate:{n}") for n in (1, 2, 3)],
        [InlineKeyboardButton(text="⭐️" * n, callback_data=f"rev:rate:{n}") for n in (4, 5)],
    ])


def skip_keyboard(language: str, step: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(language, "review_skip"), callback_data=f"rev:skip:{step}")],
    ])


async def ask_for_review(message: Message, state: FSMContext, order, language: str):
    """Offered right after a successful delivery; ignoring it simply leaves no review."""
    if await db.has_review(order.id):
        return
    await state.set_state(None)
    await state.update_data(review_order_id=order.id, review_stars=order.quantity,
                            review_product=order.product, review_details=order.details)
    await message.answer(t(language, "review_ask_rating"), reply_markup=rating_keyboard(language))


@router.callback_query(F.data.startswith("rev:rate:"))
async def review_rating(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    data = await state.get_data()
    if not data.get("review_order_id"):
        return await callback.answer()

    await state.update_data(review_rating=int(callback.data.split(":")[-1]))
    await state.set_state(Review.comment)
    await callback.answer()
    await callback.message.edit_text(t(language, "review_ask_comment"),
                                     reply_markup=skip_keyboard(language, "comment"))


@router.message(Review.comment)
async def review_comment(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    await state.update_data(review_comment=(message.text or "").strip())
    await state.set_state(Review.photo)
    await message.answer(t(language, "review_ask_photo"),
                         reply_markup=skip_keyboard(language, "photo"))


@router.message(Review.photo, F.photo)
async def review_photo(message: Message, state: FSMContext, bot: Bot):
    language = await language_of(message.from_user.id)
    await finish_review(message, state, bot, language, message.photo[-1].file_id)


@router.message(Review.photo)
async def review_photo_wrong(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    await message.answer(t(language, "review_need_photo"),
                         reply_markup=skip_keyboard(language, "photo"))


@router.callback_query(F.data.startswith("rev:skip:"))
async def review_skip(callback: CallbackQuery, state: FSMContext, bot: Bot):
    language = await language_of(callback.from_user.id)
    step = callback.data.split(":")[-1]
    await callback.answer()

    if step == "comment":
        await state.update_data(review_comment="")
        await state.set_state(Review.photo)
        return await callback.message.edit_text(t(language, "review_ask_photo"),
                                                reply_markup=skip_keyboard(language, "photo"))

    await callback.message.edit_reply_markup(reply_markup=None)
    await finish_review(callback.message, state, bot, language, None,
                        user=callback.from_user)


async def finish_review(message: Message, state: FSMContext, bot: Bot, language: str,
                        photo_file_id: str | None, user=None):
    data = await state.get_data()
    await state.clear()

    order_id = data.get("review_order_id")
    if not order_id:
        return

    user = user or message.from_user
    _, total_stars = await db.profile_stats(user.id)

    review_id = await db.create_review(
        order_id=order_id, user_id=user.id, client_name=reviews.client_name(user),
        rating=data.get("review_rating", reviews.MAX_RATING),
        comment=data.get("review_comment") or None, photo_file_id=photo_file_id,
        stars=data.get("review_stars", 0), total_stars=total_stars)

    if review_id is None:  # a review for this order already exists
        return

    text = reviews.render(review_id, reviews.client_name(user), data.get("review_rating", 5),
                          data.get("review_comment"), data.get("review_stars", 0), total_stars,
                          product=data.get("review_product", "stars"),
                          details=data.get("review_details"))
    published = await reviews.publish(bot, text, photo_file_id)

    await message.answer(t(language, "review_thanks" if published else "review_not_published"),
                         reply_markup=main_menu(language))


@router.business_connection()
async def business_connected(connection, bot: Bot):
    """The owner attached the bot to their account: remember the id, gifts flow through it."""
    if connection.is_enabled:
        await nft_stock.save_business_id(connection.id)
        rights = connection.rights
        can_transfer = bool(rights and rights.can_transfer_and_upgrade_gifts)
        logger.info("business connection %s enabled, can transfer gifts: %s",
                    connection.id, can_transfer)
        note = ("" if can_transfer else
                "\n\n⚠️ Не выдано право «Передавать и улучшать подарки» — "
                "выдача из списка работать не будет.")
        await notify_admins(bot, f"🔗 Бизнес-связка подключена: <code>{connection.id}</code>{note}")
    else:
        logger.warning("business connection %s disabled", connection.id)
        await notify_admins(bot, "🔌 Бизнес-связка отключена — продажа NFT из списка остановлена.")


# --------------------------------------------------------------------------- NFT

@router.message(F.text.in_({t("uk", "menu_nft"), t("ru", "menu_nft")}))
async def menu_nft(message: Message, state: FSMContext, bot: Bot):
    language = await require_access(message, bot)
    if not language:
        return
    await state.clear()
    await message.answer(t(language, "nft_choose_type"), reply_markup=nft_type_keyboard(language))


@router.callback_query(F.data == "nft:list")
async def nft_from_list(callback: CallbackQuery, state: FSMContext, bot: Bot):
    language = await language_of(callback.from_user.id)
    await callback.answer()

    try:
        gifts = await nft_stock.available(bot)
    except nft_stock.StockError as error:
        logger.warning("stock unavailable: %s", error)
        return await callback.message.answer(t(language, "nft_stock_error", error=error))

    if not gifts:
        return await callback.message.answer(t(language, "nft_stock_empty"))

    market = await asyncio.to_thread(crypto.market_rate)
    priced = []
    for gift in gifts[:STOCK_LIMIT]:
        await nft_stock.price_gift(gift, runtime.nft_markup_percent(), market)
        if gift.price_uah:
            priced.append(gift)

    if not priced:
        return await callback.message.answer(t(language, "nft_stock_empty"))

    await state.update_data(stock={g.owned_gift_id: _stock_payload(g) for g in priced})
    await callback.message.edit_text(t(language, "nft_stock_title"), parse_mode="HTML",
                                     reply_markup=stock_keyboard(priced))


@router.callback_query(F.data.startswith("nft:take:"))
async def nft_take_from_stock(callback: CallbackQuery, state: FSMContext):
    """Show the gift itself before committing: traits and a link, not just a line in a list."""
    language = await language_of(callback.from_user.id)
    chosen = callback.data.split(":", 2)[2]
    payload = (await state.get_data()).get("stock", {}).get(chosen)
    if not payload:
        return await callback.answer(t(language, "nft_stock_gone"), show_alert=True)

    await callback.answer()
    await callback.message.edit_text(
        t(language, "nft_stock_card", collection=payload["collection"], model=payload["model"],
          symbol=payload["symbol"], backdrop=payload["backdrop"], link=payload["link"],
          price=payload["price"]),
        parse_mode="HTML", disable_web_page_preview=False,
        reply_markup=nft_buy_keyboard(language, chosen))


@router.callback_query(F.data == "nft:decline")
async def nft_decline(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.clear()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t(language, "nft_declined"), reply_markup=main_menu(language))


@router.callback_query(F.data.startswith("nft:buy:"))
async def nft_buy_from_stock(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    chosen = callback.data.split(":", 2)[2]
    payload = (await state.get_data()).get("stock", {}).get(chosen)
    if not payload:
        return await callback.answer(t(language, "nft_stock_gone"), show_alert=True)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    price = Decimal(payload["price"])
    recipient = callback.from_user.username or str(callback.from_user.id)
    order_id = await db.create_order(callback.from_user.id, "nft_stock", recipient, 1, price,
                                     card_number=runtime.card_number(),
                                     details=payload["details"], wallet_address=chosen)
    await state.update_data(order_id=order_id)

    await callback.message.answer(
        t(language, "order_created", recipient=f"@{recipient}",
          product=product_label(language, "nft", 1, payload["details"]), price=price),
        parse_mode="HTML", reply_markup=payment_method_keyboard(language, order_id))


@router.callback_query(F.data == "nft:market")
async def nft_market_start(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.set_state(Purchase.nft_request)
    await callback.answer()
    await callback.message.edit_text(t(language, "nft_market_hello"), parse_mode="HTML")


@router.message(Purchase.nft_request)
async def nft_search(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)

    request = nft_market.parse_request(message.text or "")
    if not request:
        return await message.answer(t(language, "nft_bad_input"))

    status = await message.answer(t(language, "nft_searching"))
    try:
        if request["kind"] == "link":
            # the link identifies one gift; read its traits and look for another one like it
            gift = await asyncio.to_thread(nft_market.gift_from_link, request["slug"], request["number"])
            if not gift:
                return await status.edit_text(t(language, "nft_not_found"))
            request = gift

        listing, quality, _ = await price_cache.find(
            request["model"], request["symbol"], request["backdrop"])
    except nft_market.MarketError as error:
        logger.warning("nft search failed: %s", error)
        return await status.edit_text(t(language, "nft_market_error", error=error))

    if not listing:
        return await status.edit_text(t(language, "nft_not_found"))

    price = nft_price(listing.price)
    await state.update_data(product="nft", nft_price=str(price),
                            nft_details=nft_details(listing), nft_link=listing.link)
    await state.set_state(Purchase.nft_confirm)

    # say plainly when this is not the same gift: the traits change the value, and a customer
    # must not think they are buying exactly what they linked
    if quality == "exact":
        header = t(language, "nft_header_exact")
    else:
        header = t(language, "nft_header_similar", model=request["model"] or "—",
                   symbol=request["symbol"] or "—", backdrop=request["backdrop"] or "—")

    await status.edit_text(
        header + t(language, "nft_card", collection=listing.name, model=listing.model or "—",
                   symbol=listing.symbol or "—", backdrop=listing.backdrop or "—",
                   price=price),
        parse_mode="HTML", reply_markup=nft_confirm_keyboard(language))


@router.callback_query(F.data == "nft:drop")
async def nft_drop(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.clear()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t(language, "nft_cancelled"), reply_markup=main_menu(language))


@router.callback_query(F.data == "nft:order")
async def nft_order(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    data = await state.get_data()
    if not data.get("nft_price"):
        return await callback.answer(t(language, "no_active_order"), show_alert=True)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    price = Decimal(data["nft_price"])
    recipient = callback.from_user.username or str(callback.from_user.id)
    order_id = await db.create_order(callback.from_user.id, "nft", recipient, 1, price,
                                     card_number=runtime.card_number(),
                                     details=data["nft_details"])
    await state.update_data(order_id=order_id)

    await callback.message.answer(
        t(language, "order_created", recipient=f"@{recipient}",
          product=product_label(language, "nft", 1, data["nft_details"]), price=price),
        parse_mode="HTML", reply_markup=payment_method_keyboard(language, order_id))
