"""Tonnel Network marketplace — источник floor-цен для подарков.

У Tonnel нет публичного API, и всё закрыто Cloudflare, поэтому здесь тот же приём, что и с
Portals: куки живой сессии (`cf_clearance`) и user-agent из настоящего браузера лежат в
tonnel_auth.json. Файл готовится скриптом tonnel_auth.py из «Copy as cURL».

Флор ищется по коллекции и модели, без учёта фона и узора: точное сочетание трёх признаков
на продаже бывает редко, а цена модели — это и есть та сумма, за которую подарок реально
можно купить.
"""

import json
import logging
import re
import time
from decimal import Decimal
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

API = "https://gifts2.tonnel.network/api/pageGifts"
AUTH_FILE = Path(__file__).resolve().parent.parent / "tonnel_auth.json"

RATE_LIMIT_RETRIES = 3
RATE_LIMIT_PAUSE = 3

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


class TonnelAuthError(TonnelError):
    pass


def available() -> bool:
    """Есть ли доступы. Без них вызывающий код откатывается на Portals."""
    return AUTH_FILE.exists()


def _load_auth() -> dict:
    if not AUTH_FILE.exists():
        raise TonnelAuthError("tonnel_auth.json не найден — выгрузите доступы из Mini App")
    try:
        return json.loads(AUTH_FILE.read_text())
    except Exception as error:
        raise TonnelAuthError(f"tonnel_auth.json повреждён: {error}") from error


def _post(body: dict) -> list:
    auth = _load_auth()
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://tonnel.network",
        "referer": "https://tonnel.network/",
        "user-agent": auth.get("user_agent", ""),
        **auth.get("headers", {}),
    }

    for _ in range(RATE_LIMIT_RETRIES):
        response = requests.post(API, json=body, headers=headers,
                                 cookies=auth.get("cookies", {}), timeout=25)
        if response.status_code != 429:
            break
        logger.info("tonnel rate limit, waiting %s s", RATE_LIMIT_PAUSE)
        time.sleep(RATE_LIMIT_PAUSE)

    # Cloudflare отвечает на протухшие куки челленджем, а не 401, поэтому смотрим на заголовок.
    if response.status_code == 403 or response.headers.get("cf-mitigated"):
        raise TonnelAuthError("Tonnel отклонил доступы — cf_clearance живёт недолго, "
                              "выгрузите свежие в tonnel_auth.json")
    if response.status_code != 200:
        raise TonnelError(f"Tonnel ответил {response.status_code}")

    try:
        data = response.json()
    except ValueError as error:
        raise TonnelError(f"Tonnel вернул не JSON: {error}") from error

    # Формат менялся между версиями Mini App, поэтому принимаем и список, и обёртку.
    if isinstance(data, dict):
        data = data.get("results") or data.get("gifts") or []
    return data if isinstance(data, list) else []


def _price_of(item: dict) -> Decimal | None:
    raw = item.get("price")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def floor(collection: str | None, model: str | None = None) -> Decimal | None:
    """Самый дешёвый лот коллекции (и модели, если задана), в TON.

    Фон и узор намеренно не участвуют: редкий фон без своих лотов на продаже задирал оценку
    вдвое — подарок оценивался по чужому лоту с дорогим фоном вместо цены своей модели.
    """
    if not collection and not model:
        return None

    query = dict(BASE_FILTER)
    if collection:
        query["gift_name"] = collection
    if model:
        # В Tonnel модель хранится вместе с редкостью: "Banded Boa (0.5%)".
        query["model"] = {"$regex": f"^{re.escape(model)}\\b", "$options": "i"}

    body = {
        "page": 1,
        "limit": 1,
        "sort": json.dumps({"price": 1, "gift_id": -1}),
        "filter": json.dumps(query),
        "ref": 0,
        "price_range": None,
        "user_auth": _load_auth().get("user_auth", ""),
    }

    logger.info("tonnel floor: collection=%r model=%r", collection, model)
    results = _post(body)
    if not results:
        logger.info("tonnel: лотов нет")
        return None

    price = _price_of(results[0])
    logger.info("tonnel found: %s %s at %s TON", results[0].get("gift_name"),
                results[0].get("model"), price)
    return price
