"""Matching a Monobank receipt against an order."""

import logging
import re
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal

from monobank_receipt import OK_STATUS, UAH_CURRENCY_CODE, Receipt
from shop import runtime
from shop.db import Order

logger = logging.getLogger(__name__)

# Apostrophes are dropped rather than kept: banks print the straight ' while people type the
# typographic ’, and treating them as part of the word made Мар'ян and Мар’ян different names.
_APOSTROPHES = re.compile(r"['’ʼ`´ʹ‘]")
# Everything that is not a letter or digit separates words, hyphens included: a double surname
# written as Іваненко-Петренко must match Іваненко Петренко.
_SEPARATORS = re.compile(r"[^\w]+", re.UNICODE)


@dataclass
class VerificationResult:
    ok: bool
    reason_key: str | None = None
    details: dict | None = None


def normalize_name(name: str) -> set[str]:
    """A name as an unordered set of words, so 'Іванов Петро' == 'Петро Іванов'."""
    without_apostrophes = _APOSTROPHES.sub("", (name or "").strip().lower())
    cleaned = _SEPARATORS.sub(" ", without_apostrophes)
    return {word for word in cleaned.split() if word}


def names_match(receipt_name: str, user_input_name: str) -> bool:
    receipt_words = normalize_name(receipt_name)
    input_words = normalize_name(user_input_name)
    if not receipt_words or not input_words:
        return False
    if receipt_words == input_words:
        return True

    # Monobank often masks the patronymic or prints only two of three words, so accept
    # the case where one side is fully contained in the other and shares at least two words.
    common = receipt_words & input_words
    return len(common) >= 2 and (receipt_words <= input_words or input_words <= receipt_words)


def cards_match(receipt_card: str | None, our_card: str | None = None) -> bool:
    receipt_digits = re.sub(r"\D", "", receipt_card or "")
    our_digits = re.sub(r"\D", "", our_card if our_card is not None else runtime.card_number())
    if len(receipt_digits) < 4 or len(our_digits) < 4:
        return False
    return receipt_digits[-4:] == our_digits[-4:]


# TEMPORARY (test mode): every PDF is accepted as valid payment, no matching against the
# order is performed. Set back to False to restore the real checks below.
DISABLE_PDF_VERIFICATION = True


def verify_pdf(receipt, order: Order, tolerance_minutes: int | None = None) -> VerificationResult:
    """Match a PDF against an order by looking for the values we already expect to see."""
    if tolerance_minutes is None:
        tolerance_minutes = runtime.payment_tolerance_minutes()

    our_card = order.card_number or runtime.card_number()
    last4 = re.sub(r"\D", "", our_card)[-4:]
    expected = Decimal(order.price)

    created_at = order.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    logger.info("verifying order %s against a PDF", order.id)
    logger.info("  expect amount=%s last4=%s payer=%r window=±%s min",
                expected, last4, order.sender_name, tolerance_minutes)

    if DISABLE_PDF_VERIFICATION:
        moment = receipt.dates[0] if receipt.dates else created_at
        logger.warning("  -> ACCEPTED without verification (test mode), order %s", order.id)
        return VerificationResult(True, details={"amount": expected, "moment": moment, "last4": last4})

    def fail(reason, **details):
        logger.warning("  -> REJECTED: %s %s", reason, details or "")
        return VerificationResult(False, reason, details or None)

    if not any(abs(value - expected) <= Decimal("0.01") for value in receipt.amounts):
        return fail("verify_failed_amount",
                    actual=", ".join(str(v) for v in sorted(set(receipt.amounts))[:5]) or "—",
                    expected=expected)

    if last4 not in receipt.digit_groups:
        return fail("verify_failed_card")

    if not names_match(receipt.text, order.sender_name or ""):
        return fail("verify_failed_name")

    matching = [moment for moment in receipt.dates
                if abs((moment - created_at).total_seconds()) <= tolerance_minutes * 60]
    if not matching:
        return fail("verify_failed_time", tolerance=tolerance_minutes)

    logger.info("  -> ACCEPTED, payment time %s", matching[0])
    return VerificationResult(True, details={"amount": expected, "moment": matching[0], "last4": last4})


def verify_payment(receipt: Receipt, order: Order,
                   tolerance_minutes: int | None = None) -> VerificationResult:
    if tolerance_minutes is None:
        tolerance_minutes = runtime.payment_tolerance_minutes()

    # the card the buyer was actually shown, so changing it in the panel cannot break open orders
    our_card = order.card_number or runtime.card_number()

    logger.info("verifying order %s against receipt %s", order.id, receipt.receipt_id)
    logger.info("  payer    receipt=%r  order=%r", receipt.payer, order.sender_name)
    logger.info("  card     receipt=%r  ours=%r", receipt.receiver, our_card)
    logger.info("  amount   receipt=%r  order=%r", receipt.amount, order.price)
    logger.info("  date     receipt=%s  order=%s  tolerance=%smin",
                receipt.payment_date, order.created_at, tolerance_minutes)

    def fail(reason, **details):
        logger.warning("  -> REJECTED: %s %s", reason, details or "")
        return VerificationResult(False, reason, details or None)

    if not receipt.payer or not receipt.amount or not receipt.payment_date:
        return fail("verify_failed_incomplete")

    # A receipt exists for pending and failed transfers too, so the status is not decoration.
    if receipt.status is not None and receipt.status != OK_STATUS:
        return fail("verify_failed_status", status=receipt.status)

    if receipt.currency is not None and receipt.currency != UAH_CURRENCY_CODE:
        return fail("verify_failed_currency", currency=receipt.currency)

    if not names_match(receipt.payer, order.sender_name or ""):
        return fail("verify_failed_name")

    if not cards_match(receipt.receiver, our_card):
        return fail("verify_failed_card")

    expected = Decimal(order.price)
    actual = Decimal(str(receipt.amount))
    if abs(actual - expected) > Decimal("0.01"):
        return fail("verify_failed_amount", actual=actual, expected=expected)

    created_at = order.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    delta = abs((receipt.payment_date - created_at).total_seconds())
    logger.info("  delta    %.0f s", delta)
    if delta > tolerance_minutes * 60:
        return fail("verify_failed_time", tolerance=tolerance_minutes)

    logger.info("  -> ACCEPTED")
    return VerificationResult(True)
