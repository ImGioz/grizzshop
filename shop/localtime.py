"""Киевское время в одном месте.

В базе всё лежит в UTC — так и должно быть, — но людям показывать надо местное. Раньше
смещение было прописано константой UTC+3 сразу в трёх файлах, и полгода, с последнего
воскресенья октября по последнее марта, оно врало на час: Киев зимой на UTC+2.

zoneinfo берёт правила перехода из системной базы часовых поясов, поэтому переход считается
сам и переживёт очередное решение об отмене перевода часов.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


def now() -> datetime:
    return datetime.now(KYIV)


def to_kyiv(moment: datetime) -> datetime:
    """Перевести момент в киевское время.

    Наивное время считаем UTC: именно так его писала база до появления этого модуля.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KYIV)


def stamp(moment: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_kyiv(moment).strftime(fmt) if moment else "—"
