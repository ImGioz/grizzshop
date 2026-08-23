"""All bot handlers: onboarding, menu, star purchase, payment verification."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, CopyTextButton, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReplyKeyboardRemove)

from monobank_receipt import ReceiptError, fetch_receipt
from shop import crypto
from shop import db
from shop import localtime
from shop import prices
from shop import projects
from shop import referrals
from shop import reviews
from shop import runtime
from shop.config import BASE_DIR, CHANNEL_ID, MIN_STARS
from shop.delivery import (DeliveryError, check_recipient, deliver_gram, deliver_stars,
                           parse_ton_address)
from shop.keyboards import (calculator_again_keyboard, calculator_keyboard,
                            check_payment_keyboard, crypto_check_keyboard,
                            home_keyboard, home_row, language_keyboard, main_menu,
                            months_keyboard, more_keyboard, project_category_keyboard,
                            projects_keyboard,
                            payment_method_keyboard, product_label,
                            quantity_keyboard, recipient_keyboard, retry_keyboard,
                            stars_calculator_keyboard, subscription_keyboard,
                            ton_calculator_keyboard)
from shop.prices import (GRAM_ENABLED, MIN_TON, PREMIUM_ENABLED,
                         gram_price, premium_price, star_price, star_rate, stars_for_budget,
                         ton_for_budget, ton_price)
from shop.texts import DEFAULT_LANGUAGE, t

logger = logging.getLogger(__name__)
router = Router()

USERNAME_PATTERN = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
RECEIPT_PATTERN = re.compile(r"check\.monobank(?:\.com)?\.ua/p/[^\s]+")
SUBSCRIBED_STATUSES = {"member", "administrator", "creator"}

# Картинка меню с надписями на языке клиента; для незнакомого языка берётся русская.
MAIN_MENU_PHOTOS = {"ru": BASE_DIR / "mainmenu.jpg", "uk": BASE_DIR / "mainmenuua.jpg"}


class Calculator(StatesGroup):
    stars = State()
    uah = State()
    ton = State()
    ton_uah = State()


class Support(StatesGroup):
    message = State()


class Purchase(StatesGroup):
    friend_username = State()
    custom_quantity = State()
    sender_name = State()
    receipt_link = State()
    gram_wallet = State()
    gram_amount = State()


async def cost_in_uah(nanotons: int) -> Decimal:
    """Convert what we spent into hryvnia at the live rate, for margin reporting."""
    if not nanotons:
        return Decimal(0)
    rate = await asyncio.to_thread(crypto.market_rate)
    return ((Decimal(nanotons) / Decimal(10 ** 9)) * rate).quantize(Decimal("0.01"))


async def language_of(user_id: int) -> str:
    return await db.get_language(user_id) or DEFAULT_LANGUAGE


# Telegram отдаёт file_id уже загруженной картинки, и повторные отправки идут без файла.
_main_menu_file_ids: dict[str, str] = {}
# Кому в этом запуске уже убрали старую reply-клавиатуру: снимается она отдельным сообщением,
# так что делать это на каждый показ меню значило бы мигать им у клиента постоянно.
_keyboard_cleared: set[int] = set()


async def drop_message(message: Message):
    """Убирает экран, из которого только что ушли, чтобы в чате не копились мёртвые меню."""
    try:
        await message.delete()
    except Exception:
        # сообщение старше 48 часов или уже удалено — не повод ронять переход
        logger.debug("cannot delete message %s", message.message_id, exc_info=True)


async def drop_reply_keyboard(message: Message, user_id: int):
    """Меню теперь инлайновое, но у старых клиентов внизу висит прежняя клавиатура."""
    if user_id in _keyboard_cleared:
        return
    _keyboard_cleared.add(user_id)
    try:
        stub = await message.answer("\u2063", reply_markup=ReplyKeyboardRemove())
        await stub.delete()
    except Exception:
        logger.debug("cannot drop reply keyboard for %s", user_id, exc_info=True)


async def send_main_menu(message: Message, user_id: int, language: str, text: str | None = None):
    """Главное меню: картинка на языке клиента, а подпись под ней несёт инлайн-кнопки."""
    await drop_reply_keyboard(message, user_id)
    caption = text or t(language, "main_menu")
    keyboard = main_menu(language)

    path = MAIN_MENU_PHOTOS.get(language, MAIN_MENU_PHOTOS["ru"])
    photo = _main_menu_file_ids.get(language) or (FSInputFile(path) if path.exists() else None)
    if photo is not None:
        try:
            sent = await message.answer_photo(photo, caption=caption, parse_mode="HTML",
                                              reply_markup=keyboard)
            if sent.photo:
                _main_menu_file_ids[language] = sent.photo[-1].file_id
            return sent
        except Exception:
            # битый file_id или недоступный файл не должны оставлять клиента без меню
            logger.exception("main menu photo failed for %s, falling back to text", language)
            _main_menu_file_ids.pop(language, None)

    return await message.answer(caption, parse_mode="HTML", reply_markup=keyboard)


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
    suffix = f"_{product}" if product in ("premium", "gram") else ""
    return t(language, f"payment_ok{suffix}")


ADMIN_LANGUAGE = "ru"   # уведомления админам, как и панель, только на русском


def order_line(order) -> str:
    """«Что → кому» одной строкой для уведомлений админам.

    Раньше в такие сообщения подставлялись order.quantity и order.recipient напрямую, и заказ
    на TON выглядел как «3200000000 ⭐ для @UQAf4jgnkB3iRLdr…»: в quantity у него нанотоны,
    а в recipient — адрес кошелька, а не человек.
    """
    what = product_label(ADMIN_LANGUAGE, order.product, order.quantity, order.details)
    target = ((order.wallet_address or order.recipient) if order.product == "gram"
              else f"@{order.recipient}")
    return f"{what} → {target}"


async def notify_admins(bot: Bot, text: str, reply_markup=None) -> int:
    """Сколько администраторов сообщение реально получили."""
    delivered = 0
    for admin_id in runtime.admin_ids():
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
            delivered += 1
        except Exception:
            logger.exception("cannot notify admin %s", admin_id)
    return delivered


# --------------------------------------------------------------------------- onboarding

@router.message(CommandStart())
async def start(message: Message, state: FSMContext, command: CommandObject, bot: Bot):
    await state.clear()

    # Приглашающего засчитываем только новичку: иначе постоянный клиент, перейдя по ссылке
    # знакомого, задним числом стал бы чьим-то рефералом.
    is_new = await db.get_user(message.from_user.id) is None
    await db.upsert_user(message.from_user.id, message.from_user.username)
    if is_new and command.args:
        referrer_id = await referrals.attach(message.from_user.id, command.args)
        if referrer_id:
            await notify_referral_joined(bot, referrer_id, message.from_user)

    language = await db.get_language(message.from_user.id)
    if not language:
        return await message.answer(t(DEFAULT_LANGUAGE, "choose_language"), reply_markup=language_keyboard())

    # /start иначе был бы обходом обязательной оценки: очистил состояние — и снова в меню.
    if await review_debt(message, message.from_user.id, state, language):
        return

    await enter_shop(message, message.from_user.id, language)


async def enter_shop(message: Message, user_id: int, language: str):
    """Someone already marked as subscribed goes straight to the menu."""
    user = await db.get_user(user_id)
    if user and user["subscribed"]:
        return await send_main_menu(message, user_id, language)

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
    await send_main_menu(callback.message, callback.from_user.id, language,
                         t(language, "subscription_ok"))


# --------------------------------------------------------------------------- gate for everything else

async def review_cutoff() -> str:
    """С какого момента отзыв обязателен. Проставляется один раз, при первом обращении.

    Без отсечки требование распространилось бы на все прошлые выданные заказы разом, и
    клиенты, купившие месяц назад, упёрлись бы в оценку вместо меню.
    """
    settings = await db.get_settings()
    since = settings.get(runtime.KEY_REVIEW_SINCE)
    if not since:
        since = datetime.now(timezone.utc).isoformat()
        await db.set_setting(runtime.KEY_REVIEW_SINCE, since)
        runtime.apply(await db.get_settings())
        logger.info("обязательные отзывы включены с %s", since)
    return since


async def review_debt(message: Message, user_id: int, state: FSMContext, language: str) -> bool:
    """Есть ли неоценённый заказ. Если есть — снова просит оценку и возвращает True.

    Пока клиент в середине отзыва (пишет комментарий или шлёт фото), не мешаем: оценку он
    уже поставил, а эти шаги необязательные.
    """
    if await state.get_state() in (Review.comment.state, Review.photo.state):
        return False

    order = await db.pending_review(user_id, await review_cutoff())
    if not order:
        return False

    await message.answer(t(language, "review_required"), parse_mode="HTML")
    await ask_for_review(message, state, order, language)
    return True


async def require_access(message: Message, user_id: int, bot: Bot,
                         state: FSMContext | None = None) -> str | None:
    """Return the language when the user may proceed, otherwise re-show the gate and return None.

    message — куда отвечать, user_id — кого проверяем: у колбэка это разные люди, в
    callback.message.from_user лежит сам бот.
    """
    language = await db.get_language(user_id)
    if not language:
        await message.answer(t(DEFAULT_LANGUAGE, "choose_language"), reply_markup=language_keyboard())
        return None

    subscribed = await is_subscribed(bot, user_id)
    if subscribed is None:
        await message.answer(t(language, "subscription_check_failed"))
        return None
    if not subscribed:
        await db.set_subscribed(user_id, False)
        await send_subscription_gate(message, language)
        return None

    if state is not None and await review_debt(message, user_id, state, language):
        return None

    return language


# --------------------------------------------------------------------------- menu

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    language = await language_of(message.from_user.id)
    await send_main_menu(message, message.from_user.id, language, t(language, "cancelled"))


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery, state: FSMContext):
    """Кнопка «Главное меню»: экран, с которого ушли, удаляется, меню приходит заново."""
    await callback.answer()
    await state.clear()
    language = await language_of(callback.from_user.id)
    await drop_message(callback.message)
    await send_main_menu(callback.message, callback.from_user.id, language)


@router.callback_query(F.data == "menu:stars")
async def menu_stars(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return
    await state.clear()
    await state.update_data(product="stars")
    await drop_message(callback.message)
    await callback.message.answer(t(language, "stars_for_whom"),
                                  reply_markup=recipient_keyboard(language))


@router.callback_query(F.data == "menu:premium")
async def menu_premium(callback: CallbackQuery, state: FSMContext, bot: Bot):
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return await callback.answer()
    if not PREMIUM_ENABLED:
        return await callback.answer(t(language, "premium_soon"), show_alert=True)

    await callback.answer()
    await state.clear()
    await state.update_data(product="premium")
    await drop_message(callback.message)
    await callback.message.answer(t(language, "premium_for_whom"),
                                  reply_markup=recipient_keyboard(language))


@router.callback_query(F.data == "menu:gram")
async def menu_gram(callback: CallbackQuery, state: FSMContext, bot: Bot):
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return await callback.answer()
    if not GRAM_ENABLED:
        return await callback.answer(t(language, "gram_soon"), show_alert=True)

    await callback.answer()
    await state.clear()
    await state.update_data(product="gram")
    await state.set_state(Purchase.gram_wallet)
    await drop_message(callback.message)
    await callback.message.answer(t(language, "gram_ask_wallet"), parse_mode="HTML",
                                  reply_markup=home_keyboard(language))


@router.message(Purchase.gram_wallet)
async def set_gram_wallet(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)

    wallet = parse_ton_address(message.text or "")
    if not wallet:
        return await message.answer(t(language, "gram_bad_wallet"))

    await state.update_data(wallet=wallet)
    await state.set_state(Purchase.gram_amount)
    await message.answer(t(language, "gram_ask_amount", wallet=wallet,
                           min_ton=MIN_TON, rate=prices.TON_PRICE_UAH), parse_mode="HTML",
                         reply_markup=home_keyboard(language))


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


@router.callback_query(F.data == "menu:calc")
async def menu_calculator(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return
    await state.clear()
    await drop_message(callback.message)
    await callback.message.answer(t(language, "calc_choose"), parse_mode="HTML",
                                  reply_markup=calculator_keyboard(language))


@router.callback_query(F.data == "calc:menu")
async def calculator_menu(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.clear()
    await callback.answer()
    await drop_message(callback.message)
    await callback.message.answer(t(language, "calc_choose"), parse_mode="HTML",
                                  reply_markup=calculator_keyboard(language))


@router.callback_query(F.data.in_({"calc:to_uah", "calc:to_stars"}))
async def calculator_direction(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    to_uah = callback.data.endswith("to_uah")

    await state.set_state(Calculator.stars if to_uah else Calculator.uah)
    await callback.answer()
    await callback.message.edit_text(t(language, "calc_ask_stars" if to_uah else "calc_ask_uah"),
                                     reply_markup=home_keyboard(language))


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
    await message.answer(text, parse_mode="HTML", reply_markup=calculator_again_keyboard(language, "stars"))


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
    await message.answer(text, parse_mode="HTML", reply_markup=calculator_again_keyboard(language, "stars"))


@router.callback_query(F.data == "calc:stars")
async def calculator_stars(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.clear()
    await callback.answer()
    await drop_message(callback.message)
    await callback.message.answer(t(language, "calc_stars_title"), parse_mode="HTML",
                                  reply_markup=stars_calculator_keyboard(language))


@router.callback_query(F.data == "calc:ton")
async def calculator_ton(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await state.clear()
    await callback.answer()
    await drop_message(callback.message)
    await callback.message.answer(t(language, "calc_ton_title"), parse_mode="HTML",
                                  reply_markup=ton_calculator_keyboard(language))


@router.callback_query(F.data.in_({"calc:ton_to_uah", "calc:to_ton"}))
async def calculator_ton_direction(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    to_uah = callback.data.endswith("ton_to_uah")

    await state.set_state(Calculator.ton if to_uah else Calculator.ton_uah)
    await callback.answer()
    await callback.message.edit_text(t(language, "calc_ask_ton" if to_uah else "calc_ask_uah"),
                                     reply_markup=home_keyboard(language))


@router.message(Calculator.ton)
async def calculate_ton_to_uah(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    amount = _positive_number(message.text)
    if amount is None:
        return await message.answer(t(language, "calc_bad_number"))

    # курс читается через модуль: правка из админки меняет его на лету
    text = t(language, "calc_result_ton_to_uah", amount=f"{amount:g}", price=ton_price(amount),
             rate=prices.TON_PRICE_UAH)
    if amount < MIN_TON:
        text += t(language, "calc_min_note_ton", min_ton=MIN_TON)

    await state.clear()
    await message.answer(text, parse_mode="HTML",
                         reply_markup=calculator_again_keyboard(language, "ton"))


@router.message(Calculator.ton_uah)
async def calculate_to_ton(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    amount = _positive_number(message.text)
    if amount is None:
        return await message.answer(t(language, "calc_bad_number"))

    quantity = ton_for_budget(amount)
    text = t(language, "calc_result_to_ton", amount=f"{amount:g}", quantity=f"{quantity:g}",
             rate=prices.TON_PRICE_UAH)
    if quantity < MIN_TON:
        text += t(language, "calc_min_note_ton", min_ton=MIN_TON)

    await state.clear()
    await message.answer(text, parse_mode="HTML",
                         reply_markup=calculator_again_keyboard(language, "ton"))


@router.callback_query(F.data == "menu:profile")
async def menu_profile(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return

    paid_orders, total_stars = await db.profile_stats(callback.from_user.id)
    username = f"@{callback.from_user.username}" if callback.from_user.username else "—"
    await drop_message(callback.message)
    await callback.message.answer(
        t(language, "profile", user_id=callback.from_user.id, username=username,
          language=language, paid_orders=paid_orders, total_stars=total_stars),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(language, "menu_referral"), callback_data="ref:show")],
            home_row(language)]))


# --------------------------------------------------------------------------- more

@router.callback_query(F.data == "menu:more")
async def menu_more(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return
    await state.clear()
    await drop_message(callback.message)
    await callback.message.answer(t(language, "more_choose"), reply_markup=more_keyboard(language))


@router.callback_query(F.data == "more:projects")
async def other_projects(callback: CallbackQuery):
    language = await language_of(callback.from_user.id)
    await callback.answer()
    await drop_message(callback.message)
    await callback.message.answer(t(language, "other_projects", founder=projects.FOUNDER),
                                  parse_mode="HTML", disable_web_page_preview=True,
                                  reply_markup=projects_keyboard(language))


@router.callback_query(F.data.startswith("proj:"))
async def project_category(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    if key not in projects.CATEGORIES:
        return await callback.answer()

    language = await language_of(callback.from_user.id)
    await callback.answer()
    await drop_message(callback.message)
    await callback.message.answer(
        t(language, "projects_category", title=projects.title(key, language)),
        parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=project_category_keyboard(language, key))


# --------------------------------------------------------------------------- support

@router.callback_query(F.data == "more:support")
async def support_start(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    language = await require_access(callback.message, callback.from_user.id, bot, state)
    if not language:
        return
    await state.clear()
    await state.set_state(Support.message)
    await drop_message(callback.message)
    await callback.message.answer(t(language, "support_ask"), parse_mode="HTML",
                                  reply_markup=home_keyboard(language))


def support_ticket(ticket_id: int, user, text: str) -> str:
    """Карточка обращения для админов. Русский, как и вся служебная переписка."""
    name = user.full_name or "—"
    username = f"@{user.username}" if user.username else "—"
    return (f"🆘 <b>Обращение в поддержку №{ticket_id}</b>\n\n"
            f"👤 {name}\n"
            f"🔗 {username}\n"
            f"🆔 <code>{user.id}</code>\n"
            f"🕒 {localtime.stamp(localtime.now())}\n\n"
            f"💬 {text}")


@router.message(Support.message)
async def support_send(message: Message, state: FSMContext, bot: Bot):
    language = await language_of(message.from_user.id)
    text = (message.text or "").strip()
    if not text:
        # фото и файлы админу переслать некуда: ответ идёт обратно текстом
        return await message.answer(t(language, "support_text_only"))

    await state.clear()
    # Тикет заводится до рассылки: по его номеру админы и договариваются, кто отвечает.
    ticket_id = await db.create_ticket(message.from_user.id, text)
    reply_button = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="✍️ Ответить", callback_data=f"adm:support:reply:{ticket_id}")]])
    delivered = await notify_admins(bot, support_ticket(ticket_id, message.from_user, text),
                                    reply_button)

    if not delivered:
        logger.error("обращение %s от %s никому не доставлено", ticket_id, message.from_user.id)
        return await send_main_menu(message, message.from_user.id, language,
                                    t(language, "support_failed"))

    await send_main_menu(message, message.from_user.id, language, t(language, "support_sent"))


# --------------------------------------------------------------------------- referrals

async def referral_screen(message: Message, bot: Bot, user_id: int, language: str, edit: bool):
    state = await referrals.status(user_id)
    link = await referrals.link(bot, user_id)
    text = t(language, "referral_screen",
             per_reward=referrals.REFERRALS_PER_REWARD,
             stars_per_reward=referrals.STARS_PER_REWARD,
             link=link, **state)

    # copy_text кладёт ссылку в буфер обмена без единого запроса к боту; обработчика ей не нужно.
    rows = [[InlineKeyboardButton(text=t(language, "referral_copy"),
                                  copy_text=CopyTextButton(text=link))],
            [InlineKeyboardButton(text=t(language, "referral_share"),
                                  switch_inline_query=t(language, "referral_share_text", link=link))]]
    rows.append(home_row(language))
    if state["available"]:
        rows.insert(0, [InlineKeyboardButton(
            text=t(language, "referral_claim", available=state["available"]),
            callback_data="ref:claim")])

    send = message.edit_text if edit else message.answer
    await send(text, parse_mode="HTML", disable_web_page_preview=True,
               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "ref:show")
async def show_referrals(callback: CallbackQuery, bot: Bot):
    language = await language_of(callback.from_user.id)
    await callback.answer()
    await referral_screen(callback.message, bot, callback.from_user.id, language, edit=False)


@router.callback_query(F.data == "ref:claim")
async def claim_referral_stars(callback: CallbackQuery, bot: Bot):
    language = await language_of(callback.from_user.id)
    state = await referrals.status(callback.from_user.id)

    if not state["available"]:
        return await callback.answer(t(language, "referral_nothing"), show_alert=True)
    if not callback.from_user.username:
        return await callback.answer(t(language, "referral_no_username"), show_alert=True)

    stars = state["available"]
    await callback.answer()
    status_message = await callback.message.answer(t(language, "referral_sending", stars=stars))

    # Счётчик выданного двигаем до отправки: иначе двойное нажатие успевало бы уйти в выдачу
    # дважды, и бонус выдавался бы два раза.
    await db.add_referral_payout(callback.from_user.id, stars)
    try:
        await deliver_stars(callback.from_user.username, stars)
    except DeliveryError as error:
        await db.add_referral_payout(callback.from_user.id, -stars)
        logger.error("реферальная выплата %s звёзд для %s не прошла: %s",
                     stars, callback.from_user.id, error)
        await notify_admins(bot, f"❌ Реферальный бонус не выдан: {stars} ⭐ "
                                 f"для @{callback.from_user.username} "
                                 f"(<code>{callback.from_user.id}</code>)\n{error}")
        return await status_message.edit_text(t(language, "referral_claim_failed", error=error))

    await status_message.edit_text(t(language, "referral_claimed", stars=stars), parse_mode="HTML")
    await notify_admins(bot, f"🤝 Реферальный бонус выдан: {stars} ⭐ → "
                             f"@{callback.from_user.username} "
                             f"(приглашено с заказами: {state['qualified']})")


async def tell_referrer(bot: Bot, referrer_id: int, key: str, **values) -> None:
    """Написать пригласившему на его языке. Он мог заблокировать бота — это не наша беда."""
    try:
        await bot.send_message(referrer_id, t(await language_of(referrer_id), key, **values),
                               parse_mode="HTML")
    except Exception:
        logger.warning("не удалось написать пригласившему %s (%s)", referrer_id, key)


def who_is(user, fallback_id: int) -> str:
    """Как назвать реферала в сообщении: @username, а без него — просто id."""
    username = user["username"] if user else None
    return f"@{username}" if username else f"ID {fallback_id}"


async def referrer_of(user_id: int) -> int | None:
    user = await db.get_user(user_id)
    return user["referrer_id"] if user else None


async def notify_referral_joined(bot: Bot, referrer_id: int, new_user) -> None:
    await tell_referrer(bot, referrer_id, "referral_joined_notice",
                        who=f"@{new_user.username}" if new_user.username else f"ID {new_user.id}")


async def reward_referrer(bot: Bot, order) -> None:
    """Рассказать пригласившему о покупке его реферала и, если закрылась десятка, о бонусе."""
    referrer_id = await referrer_of(order.user_id)
    if not referrer_id:
        return

    buyer = await db.get_user(order.user_id)
    state = await referrals.status(referrer_id)

    await tell_referrer(bot, referrer_id, "referral_purchase",
                        who=who_is(buyer, order.user_id),
                        product=product_label(await language_of(referrer_id), order.product,
                                              order.quantity, order.details),
                        qualified=state["qualified"],
                        stars=referrals.STARS_PER_REWARD,
                        to_next=state["to_next"])

    # Бонус — только когда этот заказ у покупателя первый успешный: приглашение засчитывается
    # один раз, сколько бы он потом ни покупал.
    if await db.successful_order_count(order.user_id) != 1:
        return
    if state["qualified"] % referrals.REFERRALS_PER_REWARD:
        return

    await tell_referrer(bot, referrer_id, "referral_reward",
                        qualified=state["qualified"], stars=referrals.STARS_PER_REWARD)


# --------------------------------------------------------------------------- buying stars

@router.callback_query(F.data.startswith("who:"))
async def choose_recipient(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await callback.answer()

    if callback.data.endswith("friend"):
        await state.set_state(Purchase.friend_username)
        return await callback.message.edit_text(t(language, "ask_friend_username"),
                                                reply_markup=home_keyboard(language))

    username = callback.from_user.username
    if not username:
        await state.clear()
        return await callback.message.edit_text(t(language, "no_username"))

    await state.update_data(recipient=username, recipient_from="self")
    await state.set_state(None)
    await show_amount_choice(callback.message, state, language, edit=True)


@router.message(Purchase.friend_username)
async def set_friend_username(message: Message, state: FSMContext):
    language = await language_of(message.from_user.id)
    match = USERNAME_PATTERN.match((message.text or "").strip())
    if not match:
        return await message.answer(t(language, "bad_username"))

    await state.update_data(recipient=match.group(1), recipient_from="friend")
    await state.set_state(None)
    await show_amount_choice(message, state, language, edit=False)


async def premium_refusal(language: str, recipient: str) -> str | None:
    """Текст отказа, если этому получателю Premium подарить нельзя, иначе None.

    Выдача упёрлась бы в тот же отказ уже после оплаты, поэтому спрашиваем заранее — брать
    деньги за то, что невозможно выдать, нельзя.
    """
    problem = await check_recipient(recipient, "premium")
    if not problem:
        return None

    key = {"already_premium": "premium_already",
           "not_a_user": "premium_recipient_not_user"}.get(problem, "premium_recipient_unknown")
    return t(language, key, recipient=recipient)


async def show_amount_choice(message: Message, state: FSMContext, language: str, edit: bool):
    """Stars pick a quantity, Premium picks a subscription length."""
    data = await state.get_data()
    product = data.get("product", "stars")
    send = message.edit_text if edit else message.answer

    if product == "premium":
        # Чужой username проверяем сразу: опечатку разумнее показать здесь, а не после
        # выбора срока. Свой аккаунт проверяется позже, в choose_months.
        if data.get("recipient_from") == "friend":
            refusal = await premium_refusal(language, data.get("recipient", ""))
            if refusal:
                await state.clear()
                return await send(refusal, parse_mode="HTML")

        text, keyboard = t(language, "choose_months"), months_keyboard(language)
    else:
        text, keyboard = t(language, "choose_quantity"), quantity_keyboard(language)

    await send(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("months:"))
async def choose_months(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    await callback.answer()

    data = await state.get_data()
    if data.get("recipient_from") == "self":
        refusal = await premium_refusal(language, data.get("recipient", ""))
        if refusal:
            await state.clear()
            return await callback.message.edit_text(refusal, parse_mode="HTML")

    await create_order_message(callback.message, callback.from_user.id, state,
                               int(callback.data.split(":", 1)[1]), language)


@router.callback_query(F.data.startswith("qty:"))
async def choose_quantity(callback: CallbackQuery, state: FSMContext):
    language = await language_of(callback.from_user.id)
    choice = callback.data.split(":", 1)[1]
    await callback.answer()

    if choice == "custom":
        await state.set_state(Purchase.custom_quantity)
        return await callback.message.edit_text(t(language, "ask_custom_quantity", min_stars=MIN_STARS),
                                                reply_markup=home_keyboard(language))

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
    await db.close_order(order_id, "cancelled")
    await state.clear()
    logger.info("order %s cancelled by user %s", order_id, callback.from_user.id)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_main_menu(callback.message, callback.from_user.id, language,
                         t(language, "order_cancelled", order_id=order_id))


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
                                        f"{order_line(order)}\n"
                                        f"Откройте /adminka → Заказы → На проверке.")

    await status.edit_text(payment_ok_text(language, order.product))
    await notify_admins(bot, f"💰 Заказ <code>{order.id}</code> оплачен по PDF: "
                             f"{order_line(order)}, {order.price} грн")
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
    await notify_admins(bot, f"💰 Заказ <code>{order.id}</code> оплачен: "
                             f"{order_line(order)}, {order.price} грн")

    await fulfil_order(message, bot, order, language, state)


async def fulfil_order(message: Message, bot: Bot, order, language: str, state: FSMContext):
    what = product_label(language, order.product, order.quantity, order.details)
    summary = order_line(order)

    # Оплата состоялась — самое время засчитать приглашение тому, кто привёл покупателя.
    await reward_referrer(bot, order)

    if not runtime.auto_delivery():  # toggled live from the admin panel
        await notify_admins(bot, f"⚠️ Ручная выдача: заказ <code>{order.id}</code>, "
                                 f"{summary}")
        return await message.answer(t(language, "delivery_failed"))

    if order.product == "test":
        # a payment-flow rehearsal: confirm receipt and stop, nothing is delivered
        await db.update_order(order.id, status="delivered")
        return await message.answer("🧪 Тестовая оплата принята. Ничего не выдано.")

    try:
        if order.product == "gram":
            spent = await deliver_gram(order.wallet_address, order.quantity)
        else:
            spent = await deliver_stars(order.recipient, order.quantity, order.product)
    except DeliveryError as error:
        logger.error("delivery failed for order %s: %s", order.id, error)
        await db.update_order(order.id, status="failed")
        await notify_admins(bot, f"❌ Заказ <code>{order.id}</code> оплачен, но выдача упала: {error}\n"
                                 f"Нужна ручная выдача: {summary}")
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

    await send_main_menu(message, user.id, language,
                         t(language, "review_thanks" if published else "review_not_published"))


# --------------------------------------------------------------------------- legacy reply keyboard

# Меню переехало в инлайн-кнопки, но у клиента, не заходившего с тех пор, старая клавиатура
# всё ещё открыта. Её нажатие приходит обычным текстом и без этого не делало бы ничего.
# Регистрируется последним, чтобы не перехватывать ввод у тех, кто сейчас в середине заказа.
LEGACY_MENU_TEXTS = {t(language, key)
                     for language in ("uk", "ru")
                     for key in ("menu_stars", "menu_premium", "menu_gram", "menu_more",
                                 "menu_calculator", "menu_profile")}
LEGACY_MENU_TEXTS.add("🖼 Список NFT")   # раздел убран, но кнопка ещё висит у старых клиентов


@router.message(F.text.in_(LEGACY_MENU_TEXTS))
async def legacy_menu_button(message: Message, state: FSMContext, bot: Bot):
    language = await require_access(message, message.from_user.id, bot, state)
    if not language:
        return
    await state.clear()
    _keyboard_cleared.discard(message.from_user.id)  # клавиатура жива, снимаем ещё раз
    await send_main_menu(message, message.from_user.id, language)
