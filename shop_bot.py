"""Entry point for the shop bot.

    python shop_bot.py

Settings live in .env — see shop/config.py for the full list.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from shop import config, db, runtime
from shop.admin import router as admin_router
from shop.handlers import router
from shop.prices import apply_overrides
from shop.repost import router as repost_router
from wallet.Transactions import sync_clock, validate_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("shop_bot")


async def expire_orders_periodically(interval_seconds: int = 60):
    while True:
        try:
            expired = await db.expire_stale_orders(runtime.order_timeout_minutes())
            if expired:
                logger.info("expired orders: %s", expired)
        except Exception:
            logger.exception("order janitor failed")
        await asyncio.sleep(interval_seconds)


async def main():
    problems = config.validate()
    if problems:
        raise SystemExit("Не запускаюсь, проверьте .env:\n- " + "\n- ".join(problems))

    await db.init()

    # everything edited from the admin panel lives in the database, not in .env/prices.py
    settings = await db.get_settings()
    apply_overrides(settings)
    runtime.apply(settings)
    runtime.apply_admins(await db.admin_ids())

    ok, message = validate_api_key()
    (logger.info if ok else logger.warning)("toncenter: %s", message)

    # a host clock behind the network makes every transfer expire on arrival (exit code 136)
    skew, clock_message = sync_clock()
    (logger.info if abs(skew) < 5 else logger.warning)("часы: %s", clock_message)

    bot = Bot(token=config.BOT_TOKEN)
    dispatcher = Dispatcher()
    dispatcher.include_router(admin_router)  # admin routes first: they are the narrower filter
    dispatcher.include_router(repost_router)
    dispatcher.include_router(router)

    janitor = asyncio.create_task(expire_orders_periodically())
    logger.info("shop bot started, база %s, админы: .env %s + панель %s",
                config.DB_PATH, sorted(config.ADMIN_IDS), sorted(await db.admin_ids()))
    try:
        await dispatcher.start_polling(bot)
    finally:
        janitor.cancel()


if __name__ == "__main__":
    asyncio.run(main())
