"""Delivering stars through Fragment, reusing the wallet flow from FragmentApi + wallet/."""

import asyncio
import logging

from FragmentApi.PaymentGet import FragmentApiError, PaymentGet
from main import load_mnemonics
from wallet.Transactions import Transactions

logger = logging.getLogger(__name__)


class DeliveryError(Exception):
    pass


def parse_ton_address(text: str):
    """Validate a TON address the customer typed. Returns the normalised form or None."""
    from pytoniq_core import Address

    candidate = (text or "").strip()
    try:
        address = Address(candidate)
    except Exception:
        return None

    if address.wc != 0:            # basechain only; masterchain is not for user wallets
        return None
    return address.to_str(is_user_friendly=True, is_bounceable=False)


async def deliver_gram(wallet_address: str, nanotons: int) -> int:
    """Send TON straight from the shop wallet to the customer's address. No Fragment involved.

    Returns what it cost us in nanotons, so the order can record its margin.
    """
    from shop import runtime

    if runtime.test_mode():
        logger.warning("TEST MODE: pretending to send %.4f TON to %s, nothing spent",
                       nanotons / 10 ** 9, wallet_address)
        return nanotons

    logger.info("sending %.4f TON to %s", nanotons / 10 ** 9, wallet_address)
    try:
        await Transactions.send_checked(mnemonics=load_mnemonics(), destination_address=wallet_address,
                                        amount=nanotons, payload=None)
    except ValueError as error:
        raise DeliveryError(str(error)) from error
    except Exception as error:
        raise DeliveryError(f"транзакция не прошла: {error}") from error

    return nanotons


async def deliver_stars(recipient: str, quantity: int, product: str = "stars") -> int:
    """Buy `quantity` stars (or months of Premium) for `recipient` and pay for it in TON.

    Raises DeliveryError with a human-readable reason; the caller decides what to tell the customer.
    """
    from shop import runtime

    if runtime.test_mode():
        # Test mode: the order runs its full course — verification, payment, status, review —
        # and only this last step, the one that spends real TON, is skipped.
        logger.warning("TEST MODE: pretending to deliver %s %s to @%s, no TON spent",
                       quantity, product, recipient)
        return 0

    mnemonics = load_mnemonics()

    try:
        # PaymentGet is built on blocking requests, keep it off the event loop
        address, amount, payload = await asyncio.to_thread(
            PaymentGet().get_data_for_payment, recipient, quantity, mnemonics, product)
    except FragmentApiError as error:
        raise DeliveryError(f"Fragment: {error}") from error

    logger.info("delivering %s %s to @%s for %.4f TON",
                quantity, product, recipient, int(amount) / 10 ** 9)
    try:
        # one client session covers the balance check and the transfer
        await Transactions.send_checked(mnemonics=mnemonics, destination_address=address,
                                        amount=int(amount), payload=payload)
    except ValueError as error:
        raise DeliveryError(str(error)) from error
    except Exception as error:
        raise DeliveryError(f"транзакция не прошла: {error}") from error

    return int(amount)
