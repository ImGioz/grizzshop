"""Telegram bot for buying Telegram Stars through Fragment.

Spends real TON from the wallet whose seed phrase sits in created_wallets/wallets_data.txt,
so it only answers to the Telegram IDs listed in ADMIN_IDS.

Settings come from .env next to this file (or from real environment variables, which win over .env):

    BOT_TOKEN=123456:AA...
    ADMIN_IDS=111111111,222222222
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hcode
from dotenv import load_dotenv

from FragmentApi.PaymentGet import FragmentApiError, PaymentGet
from main import load_mnemonics
from wallet.Transactions import Transactions

load_dotenv()  # os.getenv reads the process environment, so .env has to be pulled in first

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {int(i) for i in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if i}
MIN_STARS = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

dispatcher = Dispatcher()
transactions = Transactions()


class BuyStars(StatesGroup):
    recipient = State()
    quantity = State()
    confirm = State()


def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Оплатить", callback_data="pay"),
        InlineKeyboardButton(text="✖️ Отмена", callback_data="cancel"),
    ]])


@dispatcher.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Бот для покупки Telegram Stars через Fragment.\n\n"
                         "/buy — купить звёзды\n"
                         "/balance — баланс кошелька\n"
                         "/cancel — отменить текущую операцию")


@dispatcher.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@dispatcher.message(Command("balance"))
async def balance(message: Message):
    address, nano = await transactions.get_balance(load_mnemonics())
    await message.answer(f"Кошелёк: {hcode(address)}\nБаланс: <b>{nano / 10 ** 9:.4f} TON</b>",
                         parse_mode="HTML")


@dispatcher.message(Command("buy"))
async def buy(message: Message, state: FSMContext):
    await state.set_state(BuyStars.recipient)
    await message.answer("Кому отправляем? Пришли @username получателя.")


@dispatcher.message(BuyStars.recipient)
async def set_recipient(message: Message, state: FSMContext):
    await state.update_data(recipient=message.text.strip().lstrip("@"))
    await state.set_state(BuyStars.quantity)
    await message.answer(f"Сколько звёзд? Минимум {MIN_STARS}.")


@dispatcher.message(BuyStars.quantity)
async def set_quantity(message: Message, state: FSMContext):
    if not message.text.strip().isdigit() or int(message.text) < MIN_STARS:
        return await message.answer(f"Нужно целое число не меньше {MIN_STARS}. Попробуй ещё раз.")

    quantity = int(message.text)
    data = await state.get_data()
    recipient = data["recipient"]

    status = await message.answer("Запрашиваю счёт у Fragment...")
    mnemonics = load_mnemonics()

    try:
        # PaymentGet is blocking (requests), so keep it off the bot's event loop
        address, amount, payload = await asyncio.to_thread(
            PaymentGet().get_data_for_payment, recipient, quantity, mnemonics)
    except FragmentApiError as error:
        await state.clear()
        return await status.edit_text(f"Fragment отказал: {error}")

    _, nano_balance = await transactions.get_balance(mnemonics)
    if nano_balance <= int(amount):
        await state.clear()
        return await status.edit_text(f"Недостаточно средств: нужно {int(amount) / 10 ** 9:.4f} TON, "
                                      f"на кошельке {nano_balance / 10 ** 9:.4f} TON.")

    await state.update_data(quantity=quantity, address=address, amount=int(amount), payload=payload)
    await state.set_state(BuyStars.confirm)
    await status.edit_text(f"<b>{quantity}</b> ⭐ для <b>@{recipient}</b>\n"
                           f"К оплате: <b>{int(amount) / 10 ** 9:.4f} TON</b>\n"
                           f"Баланс после: {(nano_balance - int(amount)) / 10 ** 9:.4f} TON",
                           parse_mode="HTML", reply_markup=confirm_keyboard())


@dispatcher.callback_query(BuyStars.confirm, F.data == "cancel")
async def reject(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Отменено, ничего не отправлено.")
    await callback.answer()


@dispatcher.callback_query(BuyStars.confirm, F.data == "pay")
async def pay(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Отправляю транзакцию...")

    try:
        await transactions.send_ton_async(mnemonics=load_mnemonics(), destination_address=data["address"],
                                          amount=data["amount"], payload=data["payload"])
    except Exception as error:
        logging.exception("transfer failed")
        return await callback.message.edit_text(f"Транзакция не прошла: {error}")

    await callback.message.edit_text(
        f"Отправлено: <b>{data['quantity']}</b> ⭐ → <b>@{data['recipient']}</b>\n"
        f"Списано {data['amount'] / 10 ** 9:.4f} TON.\n\n"
        f"Звёзды придут после подтверждения транзакции в блокчейне, обычно меньше минуты.",
        parse_mode="HTML")


async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set")
    if not ADMIN_IDS:
        raise SystemExit("ADMIN_IDS is not set: refusing to start a bot that spends TON for anyone")

    # single gate for the whole bot: every update must come from an admin
    dispatcher.message.filter(F.from_user.id.in_(ADMIN_IDS))
    dispatcher.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))

    bot = Bot(token=BOT_TOKEN)
    logging.info("bot started for admins: %s", sorted(ADMIN_IDS))
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
