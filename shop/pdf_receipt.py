"""Reading a bank receipt out of a PDF.

Deliberately bank-agnostic: we already know what we are looking for (the order's amount, our
card's last four digits, the payer name, the time window), so this pulls every candidate value
out of the flat text and the caller checks membership. No per-bank layout parsing.
"""

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import pdfplumber

from shop.localtime import KYIV

logger = logging.getLogger(__name__)


# "1 234,56" / "1234.56" / "45,00"
AMOUNT_PATTERN = re.compile(r"\d{1,3}(?:[   ]\d{3})+[.,]\d{2}|\d+[.,]\d{2}")
# a bare integer next to a currency word: "45 грн"
INTEGER_AMOUNT_PATTERN = re.compile(r"(\d{1,7})\s*(?:грн|uah|₴)", re.IGNORECASE)

# Dates and times look exactly like money once separators are stripped ("04.08.2026" -> 4.08),
# so they are blanked out before the amount scan instead of polluting the candidates.
DATE_LIKE_PATTERN = re.compile(
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"  # 04.08.2026, 06/08/2026
    r"|\d{4}[./-]\d{2}[./-]\d{2}"       # 2026-08-04, 2026/08/06
    r"|\d{1,2}:\d{2}(?::\d{2})?"        # 20:01:45
)

DIGIT_GROUP_PATTERN = re.compile(r"(?<!\d)(\d{4})(?!\d)")
DIGIT_RUN_PATTERN = re.compile(r"\d{4,}")
RECEIPT_NUMBER_PATTERN = re.compile(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}\b")
LETTER_PATTERN = re.compile(r"[A-Z]")

# A masked card: digits and mask characters, ending in the four digits banks always print.
CARD_MASK_PATTERN = re.compile(r"[\d][\d\s*•·×xX•·-]{6,24}(\d{4})(?!\d)")

# Banks write the separator as they please: 06.08.2026, 06/08/2026, 2026-08-06, 2026/08/06.
# The two patterns cannot collide — one starts with a two-digit day, the other with a four-digit year.
DATE_PATTERNS = (
    (re.compile(r"(\d{2})[./-](\d{2})[./-](\d{4})[,\s]+(\d{2}):(\d{2})(?::(\d{2}))?"), "dmy"),
    (re.compile(r"(\d{4})[./-](\d{2})[./-](\d{2})[T,\s]+(\d{2}):(\d{2})(?::(\d{2}))?"), "ymd"),
)


class PdfReceiptError(Exception):
    pass


@dataclass
class PdfReceipt:
    amounts: list[Decimal]
    dates: list[datetime]
    digit_groups: set[str]
    receipt_number: str | None
    text: str = field(repr=False, default="")

    def fingerprint(self, amount: Decimal, moment: datetime, last4: str) -> str:
        """Key for the used-receipts table.

        Not a hash of the file: re-exporting the same receipt changes every byte, so identity
        has to come from the payment itself.
        """
        if self.receipt_number:
            return f"pdf:{self.receipt_number}"
        raw = f"{amount}|{moment:%Y-%m-%dT%H:%M}|{last4}"
        return "pdf:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _clean(text: str) -> str:
    return re.sub(r"[ \t  ]+", " ", text or "")


def _parse_amounts(text: str) -> list[Decimal]:
    values = []
    money_only = DATE_LIKE_PATTERN.sub(" ", text)

    for raw in AMOUNT_PATTERN.findall(money_only):
        normalized = raw.replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            values.append(Decimal(normalized))
        except InvalidOperation:
            continue

    for raw in INTEGER_AMOUNT_PATTERN.findall(money_only):
        try:
            values.append(Decimal(raw))
        except InvalidOperation:
            continue

    return values


def _parse_dates(text: str) -> list[datetime]:
    found = []
    for pattern, order in DATE_PATTERNS:
        for groups in pattern.findall(text):
            parts = [int(part) if part else 0 for part in groups]
            day, month, year = (parts[0], parts[1], parts[2]) if order == "dmy" else (parts[2], parts[1], parts[0])
            try:
                found.append(datetime(year, month, day, parts[3], parts[4], parts[5], tzinfo=KYIV))
            except ValueError:
                continue
    return found


def parse(data: bytes) -> PdfReceipt:
    """Extract every candidate value from a PDF. Raises PdfReceiptError when there is no text."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as error:
        raise PdfReceiptError(f"не удалось открыть PDF: {error}") from error

    text = _clean("\n".join(pages))
    if len(text.strip()) < 20:
        # a scan or an image-only export: nothing to match against
        raise PdfReceiptError("в PDF нет текста — похоже, это скан или картинка")

    # A receipt number always carries letters (6CX3-5K5T-...); four all-digit groups are a
    # hyphen-formatted card number, and dropping its digits would hide the very card we look for.
    number = next((candidate for candidate in RECEIPT_NUMBER_PATTERN.findall(text)
                   if LETTER_PATTERN.search(candidate)), None)

    # The receipt number's own digits would otherwise pose as card endings — they can only
    # produce false matches, so drop them.
    number_parts = set(number.split("-")) if number else set()

    groups = set(DIGIT_GROUP_PATTERN.findall(text))
    # A card can be printed unspaced ("4441••••••••1145") or glued to other text, so also take
    # the last four digits of every longer digit run, plus explicit masked-card matches.
    tails = {run[-4:] for run in DIGIT_RUN_PATTERN.findall(text)}
    masked = set(CARD_MASK_PATTERN.findall(text))

    receipt = PdfReceipt(
        amounts=_parse_amounts(text),
        dates=_parse_dates(text),
        digit_groups=(groups | tails | masked) - number_parts,
        receipt_number=number,
        text=text,
    )

    logger.info("pdf parsed: amounts=%s dates=%s number=%s",
                receipt.amounts[:8], [f"{d:%d.%m.%Y %H:%M}" for d in receipt.dates[:5]],
                receipt.receipt_number)
    logger.info("  card candidates=%s (dropped from receipt number: %s)",
                sorted(receipt.digit_groups), sorted(number_parts) or "—")
    logger.info("  extracted text:\n%s", text[:1500])
    return receipt
