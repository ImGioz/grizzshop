"""Tonnel Network marketplace — источник floor-цен для подарков.

Публичного API нет, поэтому здесь повторяется то, что делает Mini App. Две особенности,
на которые ушло больше всего времени:

* Cloudflare отсеивает не по кукам и не по заголовкам, а по TLS-отпечатку клиента. Обычный
  requests и системный curl получают 403 даже с полностью скопированными заголовками,
  поэтому запросы идут через curl_cffi, притворяющийся Chrome.
* Читать цены можно без авторизации: поле user_auth должно присутствовать, но пустая строка
  подходит. Ничего не протухает — в отличие от Portals, доступы обновлять не нужно.

Флор ищется по коллекции и модели, без учёта фона и узора: точное сочетание трёх признаков
на продаже бывает редко, а цена модели — это и есть сумма, за которую подарок реально можно
купить.
"""

import json
import logging
import re
import time
from decimal import Decimal

from curl_cffi import requests as cffi

logger = logging.getLogger(__name__)

API = "https://gifts2.tonnel.network/api/pageGifts"

# Mini App живёт на marketplace.tonnel.network; с origin вида tonnel.network Cloudflare отвечает 403.
HEADERS = {
    "accept": "*/*",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7",
    "content-type": "application/json",
    "origin": "https://marketplace.tonnel.network",
    "referer": "https://marketplace.tonnel.network/",
    "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"),
}

RETRIES = 3
RETRY_PAUSE = 3

# Лоты, которые действительно можно купить: выставлены, не выкуплены, не возвращены.
BASE_FILTER = {
    "price": {"$exists": True},
    "refunded": {"$ne": True},
    "buyer": {"$exists": False},
    "export_at": {"$exists": True},
    "asset": "TON",
}


class TonnelError(Exception):
    pass


def _post(body: dict) -> list:
    # Сессия создаётся на каждый запрос: вызовы приходят из asyncio.to_thread, а общая
    # сессия curl_cffi между потоками не рассчитана.
    for attempt in range(RETRIES):
        try:
            response = cffi.post(API, headers=HEADERS, json=body, timeout=25,
                                 impersonate="chrome")
        except Exception as error:
            if attempt == RETRIES - 1:
                raise TonnelError(f"Tonnel недоступен: {error}") from error
            time.sleep(RETRY_PAUSE)
            continue

        if response.status_code != 429:
            break
        logger.info("tonnel rate limit, waiting %s s", RETRY_PAUSE)
        time.sleep(RETRY_PAUSE)

    if response.status_code == 403:
        raise TonnelError("Tonnel ответил 403 — вероятно, изменилась защита Cloudflare")
    if response.status_code != 200:
        raise TonnelError(f"Tonnel ответил {response.status_code}")

    try:
        data = response.json()
    except ValueError as error:
        raise TonnelError(f"Tonnel вернул не JSON: {error}") from error

    if isinstance(data, dict):
        data = data.get("results") or data.get("gifts") or []
    return data if isinstance(data, list) else []


def floor(collection: str | None, model: str | None = None) -> Decimal | None:
    """Самый дешёвый лот коллекции (и модели, если задана), в TON.

    Фон и узор намеренно не участвуют: редкий фон без своих лотов на продаже задирал оценку
    вдвое — подарок оценивался по чужому лоту с дорогим фоном вместо цены своей модели.
    """
    if not collection:
        return None

    query = {**BASE_FILTER, "gift_name": collection}
    if model:
        # Модель хранится вместе с редкостью — "Colorless (2.5%)", — причём процент у разных
        # экземпляров разный, поэтому сравнение по началу строки, а не на равенство.
        query["model"] = {"$regex": f"^{re.escape(model)}\\b", "$options": "i"}

    body = {
        "page": 1,
        "limit": 1,
        "sort": json.dumps({"price": 1, "gift_id": -1}),
        "filter": json.dumps(query),
        "ref": 0,
        "price_range": None,
        # Поле обязано присутствовать: без него ответ приходит пустым. Значение не проверяется.
        "user_auth": "",
    }

    results = _post(body)
    if not results:
        logger.info("tonnel: лотов нет для %s/%s", collection, model)
        return None

    top = results[0]
    try:
        price = Decimal(str(top["price"]))
    except (KeyError, TypeError, ValueError):
        return None

    logger.info("tonnel floor: %s %s = %s TON", top.get("name"), top.get("model"), price)
    return price
