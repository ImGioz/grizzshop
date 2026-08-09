"""Sending one message to many users.

The admin's own message is copied verbatim with copy_message, so text, formatting, photos
and media all survive without re-encoding anything.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from shop import db

logger = logging.getLogger(__name__)

# Telegram tolerates ~30 messages/second to different chats; stay under it.
SEND_INTERVAL = 0.05
PROGRESS_EVERY = 25


@dataclass
class Progress:
    total: int
    sent: int = 0
    blocked: int = 0
    failed: int = 0
    cancelled: bool = False
    _cancel: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def done(self) -> int:
        return self.sent + self.blocked + self.failed

    def cancel(self):
        self._cancel.set()

    @property
    def cancelling(self) -> bool:
        return self._cancel.is_set()

    def summary(self) -> str:
        lines = [f"Отправлено: <b>{self.sent}</b> из {self.total}"]
        if self.blocked:
            lines.append(f"Заблокировали бота: {self.blocked}")
        if self.failed:
            lines.append(f"Ошибок: {self.failed}")
        if self.cancelled:
            lines.append("<i>Остановлено вручную.</i>")
        return "\n".join(lines)


def copier(bot: Bot, from_chat_id: int, message_id: int):
    """The plain case: reproduce a message verbatim."""
    async def deliver(user_id: int):
        await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
    return deliver


async def run(bot: Bot, recipients: list[int], deliver, progress: Progress,
              on_progress=None) -> Progress:
    """Send to every recipient via `deliver(user_id)`, pacing sends and recording who is unreachable."""
    for index, user_id in enumerate(recipients, start=1):
        if progress.cancelling:
            progress.cancelled = True
            break

        try:
            await deliver(user_id)
            progress.sent += 1

        except TelegramForbiddenError:
            # user blocked the bot or deleted the account — stop bothering them next time
            progress.blocked += 1
            await db.set_blocked(user_id, True)

        except TelegramRetryAfter as error:
            logger.warning("broadcast flood limit, sleeping %s s", error.retry_after)
            await asyncio.sleep(error.retry_after)
            try:
                await deliver(user_id)
                progress.sent += 1
            except Exception:
                progress.failed += 1

        except TelegramBadRequest as error:
            logger.info("broadcast to %s failed: %s", user_id, error)
            progress.failed += 1

        except Exception:
            logger.exception("unexpected broadcast error for %s", user_id)
            progress.failed += 1

        if on_progress and index % PROGRESS_EVERY == 0:
            await on_progress(progress)

        await asyncio.sleep(SEND_INTERVAL)

    return progress
