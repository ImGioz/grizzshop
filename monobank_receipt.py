"""Parser for Monobank receipt pages (check.monobank.ua / check.monobank.com.ua).

The page sits behind an invisible reCAPTCHA v3. Since v3 only scores a request and has nothing
to solve, the two calls its JavaScript makes are reproduced over plain HTTP and the receipt API
is queried directly — no browser involved. Chromium remains as a fallback for the day Monobank
tightens this, which is why playwright is imported lazily.

Used both as a CLI and as a library by the shop bot:

    python monobank_receipt.py https://check.monobank.ua/p/<id> --save raw.json
    from monobank_receipt import fetch_receipt          # -> Receipt
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)

RECEIPT_ORIGIN = "https://check.monobank.ua"
RECEIPT_URL = RECEIPT_ORIGIN + "/p/{receipt_id}"
RECEIPT_API = RECEIPT_ORIGIN + "/ext/api/web/payments/receipts"
# Site key taken from the receipt page; reCAPTCHA v3, invisible.
RECAPTCHA_SITE_KEY = "6LchFy8rAAAAAB-oJBZkOGi-1twHv1SWW8ahvr-S"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
API_MARKER = "ext/api/web/payments/receipts"
DEFAULT_TIMEOUT_MS = 30000

# Each check costs a whole Chromium: ~150 MB on a light page, 250-350 MB on the receipt page
# with its reCAPTCHA. On a 2 GB VPS a handful of simultaneous checks is an OOM, so they queue.
# A check takes a few seconds, so waiting in line is invisible to the customer.
MAX_CONCURRENT_BROWSERS = int(os.getenv("MAX_CONCURRENT_BROWSERS", "2"))
_browser_slots = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)

LAUNCH_ARGS = [
    "--disable-dev-shm-usage",   # without this Chromium exhausts /dev/shm on small servers
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-features=TranslateUI,BackForwardCache",
    "--mute-audio",
]

# Both domains are in the wild and redirect to the same receipt.
ID_PATTERN = re.compile(r"check\.monobank(?:\.com)?\.ua/p/([^/?#]+)")

# The API is undocumented and its field names have changed over time, so every value is looked up
# through a list of candidates instead of a single hard-coded key.
PAYER_KEYS = ("payerName", "senderName", "sender", "payer", "clientName", "cardHolder", "from")
RECEIVER_KEYS = ("receiverCard", "receiver", "cardMask", "maskedPan", "pan", "destination", "to", "cardNumber")
AMOUNT_KEYS = ("amount", "total", "totalAmount", "sum", "operationAmount")
DATE_KEYS = ("paymentDate", "date", "createdDate", "receiptDate", "operationDate", "time", "timestamp")


class ReceiptError(Exception):
    pass


UAH_CURRENCY_CODE = 980
OK_STATUS = "OK"


@dataclass
class Receipt:
    receipt_id: str
    payer: str | None
    receiver: str | None
    amount: float | None           # in hryvnia, as the API reports it
    payment_date: datetime | None  # timezone-aware
    currency: int | None = None    # ISO 4217 numeric, 980 = UAH
    status: str | None = None      # paymentStatus, "OK" for a completed transfer
    receipt_number: str | None = None
    purpose: str | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def to_dict(self):
        return {
            "receipt_id": self.receipt_id,
            "receiptNumber": self.receipt_number,
            "payer": self.payer,
            "receiver": self.receiver,
            "amount": self.amount,
            "currency": self.currency,
            "paymentStatus": self.status,
            "paymentPurpose": self.purpose,
            "paymentDate": self.payment_date.isoformat() if self.payment_date else None,
        }


def extract_receipt_id(url_or_id: str) -> str:
    match = ID_PATTERN.search(url_or_id)
    return match.group(1) if match else url_or_id.strip()


def _walk(data: Any):
    """Yield every dict in a nested structure: the fields we need are not always top level."""
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _walk(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk(item)


def _find(data: Any, keys: tuple[str, ...]):
    return _find_with_key(data, keys)[0]


def _find_with_key(data: Any, keys: tuple[str, ...]) -> tuple[Any, str | None]:
    """Also report which candidate key matched — the API schema is undocumented, and knowing
    the source key is what makes a wrong guess debuggable."""
    for node in _walk(data):
        for key in keys:
            value = node.get(key)
            if value not in (None, "", [], {}):
                return value, key
    return None, None


def _parse_amount(value) -> float | None:
    """The receipts endpoint reports hryvnia, not kopecks: a 1 UAH transfer comes back as `1`.
    The number is taken as-is, only the sign is dropped."""
    if value is None:
        return None
    if isinstance(value, str):
        value = re.sub(r"[^\d.\-]", "", value.replace(",", "."))
        if not value:
            return None
    try:
        return round(abs(float(value)), 2)
    except (TypeError, ValueError):
        return None


def _parse_date(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # epoch, in seconds or milliseconds
        seconds = value / 1000 if value > 10 ** 11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)

    text = str(value).strip().replace("Z", "+00:00")
    for parse in (
        lambda t: datetime.fromisoformat(t),
        lambda t: datetime.strptime(t, "%d.%m.%Y %H:%M:%S"),
        lambda t: datetime.strptime(t, "%d.%m.%Y %H:%M"),
        lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            parsed = parse(text)
        except (ValueError, TypeError):
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _first_receipt(data: dict) -> dict | None:
    """The endpoint answers {"result": {"receipts": [ {...} ]}}."""
    receipts = (data or {}).get("result", {}).get("receipts")
    if isinstance(receipts, list) and receipts and isinstance(receipts[0], dict):
        return receipts[0]
    return None


def normalize(receipt_id: str, data: dict) -> Receipt:
    # Parse the documented shape when it is there; the key search stays as a fallback
    # in case Monobank reshapes the response again.
    node = _first_receipt(data)
    source = node if node is not None else data

    payer, payer_key = _find_with_key(source, PAYER_KEYS)
    receiver, receiver_key = _find_with_key(source, RECEIVER_KEYS)
    amount, amount_key = _find_with_key(source, AMOUNT_KEYS)
    date, date_key = _find_with_key(source, DATE_KEYS)

    receipt = Receipt(
        receipt_id=receipt_id,
        payer=payer or None,
        receiver=str(receiver) if receiver else None,
        amount=_parse_amount(amount),
        payment_date=_parse_date(date),
        currency=(node or {}).get("currency"),
        status=(node or {}).get("paymentStatus"),
        receipt_number=(node or {}).get("receiptNumber"),
        purpose=(node or {}).get("paymentPurpose"),
        raw=data,
    )

    logger.info("receipt %s parsed:", receipt_id)
    for label, key, raw_value, parsed in (
        ("payer   ", payer_key, payer, receipt.payer),
        ("receiver", receiver_key, receiver, receipt.receiver),
        ("amount  ", amount_key, amount, receipt.amount),
        ("date    ", date_key, date, receipt.payment_date),
    ):
        logger.info("  %s from key %-14r raw=%-28r -> %r", label, key, raw_value, parsed)
    logger.info("  status=%r currency=%r number=%r", receipt.status, receipt.currency, receipt.receipt_number)

    return receipt


def _recaptcha_padding(origin: str) -> str:
    raw = base64.b64encode(f"{origin}:443".encode()).decode().rstrip("=")
    return raw + "." * ((4 - len(raw) % 4) % 4)


def _captcha_token(session) -> str:
    """Obtain a reCAPTCHA v3 token over plain HTTP.

    v3 has nothing to solve — it only scores the request — so the two calls its JS makes can be
    reproduced directly: fetch the anchor frame for a one-time token, then exchange it on reload.
    """
    loader = session.get("https://www.google.com/recaptcha/api.js",
                         params={"render": RECAPTCHA_SITE_KEY}, timeout=20)
    version = re.search(r"releases/([\w-]+)/", loader.text)
    if not version:
        raise ReceiptError("не удалось определить версию reCAPTCHA")
    version = version.group(1)

    padding = _recaptcha_padding(RECEIPT_ORIGIN)
    anchor = session.get("https://www.google.com/recaptcha/api2/anchor", timeout=20,
                         params={"ar": "1", "k": RECAPTCHA_SITE_KEY, "co": padding,
                                 "hl": "en", "v": version, "size": "invisible", "cb": "monobank"})
    first = re.search(r'id="recaptcha-token"\s+value="([^"]+)"', anchor.text)
    if not first:
        raise ReceiptError("reCAPTCHA не выдала стартовый токен")

    reload_response = session.post(
        "https://www.google.com/recaptcha/api2/reload", timeout=20,
        params={"k": RECAPTCHA_SITE_KEY},
        headers={"content-type": "application/x-www-form-urlencoded", "referer": anchor.url},
        data={"v": version, "reason": "q", "c": first.group(1), "k": RECAPTCHA_SITE_KEY,
              "co": padding, "hl": "en", "size": "invisible"})

    token = re.search(r'"rresp","([^"]+)"', reload_response.text)
    if not token:
        raise ReceiptError("reCAPTCHA отклонила запрос")
    return token.group(1)


def _fetch_receipt_sync(receipt_id: str) -> dict:
    import requests

    session = requests.Session()
    session.headers["user-agent"] = USER_AGENT

    response = session.post(
        RECEIPT_API, timeout=25,
        json={"paymentToken": receipt_id, "captchaV3": _captcha_token(session)},
        headers={"content-type": "application/json", "origin": RECEIPT_ORIGIN,
                 "referer": f"{RECEIPT_ORIGIN}/p/{receipt_id}"})

    if response.status_code != 200:
        raise ReceiptError(f"Monobank ответил {response.status_code}: {response.text[:120]}")

    data = response.json()
    logger.info("raw receipt JSON for %s:\n%s", receipt_id,
                json.dumps(data, ensure_ascii=False, indent=2))
    return data


async def fetch_receipt_raw(receipt_id: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """Read a receipt without a browser; falls back to Chromium only if the API refuses."""
    try:
        return await asyncio.to_thread(_fetch_receipt_sync, receipt_id)
    except ReceiptError:
        raise
    except Exception as error:
        logger.warning("direct receipt fetch failed (%s), falling back to a browser", error)

    try:
        return await _fetch_receipt_browser(receipt_id, timeout_ms)
    except ReceiptError:
        raise
    except Exception as error:
        # the browser is optional now — a server without Chromium must fail cleanly, not crash
        logger.error("browser fallback unavailable: %s", error)
        raise ReceiptError("не удалось прочитать квитанцию, попробуйте ещё раз") from error


async def _fetch_receipt_browser(receipt_id: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    from playwright.async_api import async_playwright

    url = RECEIPT_URL.format(receipt_id=receipt_id)
    if _browser_slots.locked():
        logger.info("receipt %s: waiting for a free browser slot", receipt_id)

    async with _browser_slots, async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            page = await browser.new_page()
            try:
                async with page.expect_response(
                    lambda response: API_MARKER in response.url and response.status == 200,
                    timeout=timeout_ms,
                ) as response_info:
                    await page.goto(url)
                response = await response_info.value
                data = await response.json()
                logger.info("raw receipt JSON for %s:\n%s", receipt_id,
                            json.dumps(data, ensure_ascii=False, indent=2))
                return data
            except Exception as error:
                raise ReceiptError("не удалось получить данные чека: страница не отдала API-ответ "
                                   "(ссылка неверна, чек удалён или сработала CAPTCHA)") from error
        finally:
            await browser.close()


async def fetch_receipt(url_or_id: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> Receipt:
    receipt_id = extract_receipt_id(url_or_id)
    if not receipt_id:
        raise ReceiptError("пустая ссылка на чек")

    raw = await fetch_receipt_raw(receipt_id, timeout_ms)
    return normalize(receipt_id, raw)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Парсер чеков check.monobank.ua")
    parser.add_argument("url_or_id", help="Ссылка check.monobank.ua/p/<ID> или сам ID")
    parser.add_argument("--save", metavar="FILE", help="Сохранить сырой JSON в файл")
    args = parser.parse_args()

    try:
        receipt = asyncio.run(fetch_receipt(args.url_or_id))
    except ReceiptError as error:
        print(f"[x] {error}", file=sys.stderr)
        raise SystemExit(1)

    print("\n=== Разобранные поля ===")
    print(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2))
    print("\n=== Полный JSON ===")
    print(json.dumps(receipt.raw, ensure_ascii=False, indent=2))

    if args.save:
        with open(args.save, "w", encoding="utf-8") as file:
            json.dump(receipt.raw, file, ensure_ascii=False, indent=2)
        print(f"\n[*] Сохранено в {args.save}")


if __name__ == "__main__":
    _main()
