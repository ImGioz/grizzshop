import asyncio
import logging
import time
from contextlib import asynccontextmanager

from ton_core import (NetworkGlobalID, WalletV3Params, WalletV4Params, WalletV5Params)
from tonutils.clients import ToncenterClient
from tonutils.contracts import WalletV3R1, WalletV3R2, WalletV4R1, WalletV4R2, WalletV5R1
from tonutils.types import RetryPolicy, RetryRule

# Telegram Wallet (TON Space) creates W5 wallets, so v5r1 is the default here.
# tonsdk/TonTools cannot derive W5 at all, which is why this module uses tonutils.
WALLET_VERSIONS = {
    "v3r1": WalletV3R1,
    "v3r2": WalletV3R2,
    "v4r1": WalletV4R1,
    "v4r2": WalletV4R2,
    "v5r1": WalletV5R1,
}

# A signed external message carries an expiry. Retrying the *same* message past that point can
# never succeed — the wallet rejects it with exit code 136 — so the retry budget below must stay
# well under TRANSFER_TTL, and a genuine failure is recovered by rebuilding the message instead.
TRANSFER_TTL = 180        # seconds a signed transfer stays valid
SEND_ATTEMPTS = 3         # full rebuild-and-sign attempts
RETRY_AFTER_SECONDS = 4

# A single delivery makes several calls in a row (seqno, state, send), so anonymous toncenter
# runs into 429 almost immediately. Retry 429 patiently, but never longer than the message lives.
RETRY_POLICY = RetryPolicy(
    rules=(
        RetryRule(max_retries=5, base_delay=1.0, max_delay=8.0, backoff_factor=2.0, codes=frozenset({429})),
        RetryRule(max_retries=2, base_delay=1.0, max_delay=4.0, backoff_factor=2.0,
                  codes=frozenset({500, 502, 503, 504})),
    ),
    total_timeout=45.0,
)

WALLET_PARAMS = {
    "v3r1": WalletV3Params, "v3r2": WalletV3Params,
    "v4r1": WalletV4Params, "v4r2": WalletV4Params,
    "v5r1": WalletV5Params,
}

# exitcode 136 is the wallet saying "valid_until has passed"
EXPIRED_MARKERS = ("exitcode=136", "exit_code=136")

logger = logging.getLogger(__name__)


_UNSET = object()
_api_key_override = _UNSET

# Difference between network time and this machine's clock, in seconds. A wallet compares
# valid_until against the blockchain's clock, so a host running behind signs messages that are
# already expired on arrival and every transfer fails with exit code 136.
_clock_skew = 0.0


def clock_skew() -> float:
    return _clock_skew


def network_now() -> int:
    return int(time.time() + _clock_skew)


def sync_clock() -> tuple[float, str]:
    """Measure how far this host's clock is from the network's, using the server Date header."""
    global _clock_skew

    import email.utils
    import requests
    try:
        response = requests.get("https://toncenter.com/api/v2/getMasterchainInfo", timeout=15)
        header = response.headers.get("Date")
        if not header:
            return _clock_skew, "сервер не вернул время, оставляю прежнюю поправку"
        server = email.utils.parsedate_to_datetime(header).timestamp()
    except Exception as error:
        return _clock_skew, f"не удалось сверить часы ({error})"

    _clock_skew = server - time.time()
    if abs(_clock_skew) < 5:
        return _clock_skew, "часы синхронны с сетью"
    return _clock_skew, (f"часы машины расходятся с сетью на {_clock_skew:+.0f} с — поправка применена, "
                         f"но лучше починить NTP на сервере")


def _toncenter_settings():
    # imported lazily so wallet/ stays usable without the shop package
    try:
        from shop.config import TONCENTER_API_KEY, TONCENTER_RPS
        return TONCENTER_API_KEY, TONCENTER_RPS
    except ImportError:
        return None, 1


def effective_api_key():
    key, _ = _toncenter_settings()
    return key if _api_key_override is _UNSET else _api_key_override


def validate_api_key() -> tuple[bool, str]:
    """Check the key against toncenter v2 once at startup.

    tonutils talks to /api/v2 only, and a key issued for the v3 API is rejected there with 401.
    Rather than failing every delivery, disable the bad key and fall back to anonymous access.
    """
    global _api_key_override

    key = effective_api_key()
    if not key:
        return False, "ключ не задан, работаем анонимно (~1 запрос/сек, возможны 429)"

    import requests
    try:
        response = requests.get("https://toncenter.com/api/v2/getMasterchainInfo",
                                headers={"X-API-Key": key}, timeout=15)
    except Exception as error:
        return False, f"не удалось проверить ключ ({error}), оставляю как есть"

    if response.status_code == 200:
        return True, "ключ toncenter принят"

    _api_key_override = None
    return False, (f"ключ toncenter отклонён ({response.status_code} "
                   f"{response.json().get('error', '')!r}), работаю анонимно. "
                   f"Нужен ключ для API v2 — возьмите в боте @toncenter")


def make_client(testnet: bool = False) -> ToncenterClient:
    _, rps = _toncenter_settings()
    key = effective_api_key()

    return ToncenterClient(
        NetworkGlobalID.TESTNET if testnet else NetworkGlobalID.MAINNET,
        api_key=key,
        # without a key toncenter allows about one request per second
        rps_limit=max(1, int(rps if key else 1)),
        retry_policy=RETRY_POLICY,
    )


class Transactions:
    @staticmethod
    @asynccontextmanager
    async def session(mnemonics, version='v5r1', testnet=False):
        """One connected client + wallet, so a whole delivery costs a single session."""
        wallet_class = WALLET_VERSIONS.get(version)
        if wallet_class is None:
            raise ValueError(f"unsupported wallet version {version!r}, expected one of {sorted(WALLET_VERSIONS)}")

        client = make_client(testnet)
        try:
            await client.connect()
            wallet, _, _, _ = wallet_class.from_mnemonic(client, list(mnemonics))
            yield client, wallet
        finally:
            await client.close()

    @classmethod
    async def send_ton_async(cls, mnemonics, destination_address, amount, payload, nano_amount=True,
                             version='v5r1', testnet=False, send_mode=3):
        amount = int(amount) if nano_amount else int(float(amount) * 10 ** 9)

        async with cls.session(mnemonics, version, testnet) as (_, wallet):
            await cls._transfer(wallet, destination_address, amount, payload, send_mode, version)
        return 1

    @staticmethod
    async def _transfer(wallet, destination_address, amount, payload, send_mode, version='v5r1'):
        if payload is None:
            clean_payload = "<нет>"
        else:
            clean_payload = payload.replace("\n", " ") if isinstance(payload, str) else "<cell>"
        logger.warning(f'Sending {amount / 10 ** 9} TON from {wallet.address.to_str()} '
                       f'to {destination_address} with payload: {clean_payload}')

        params_class = WALLET_PARAMS.get(version)

        for attempt in range(1, SEND_ATTEMPTS + 1):
            # expiry is measured against the network's clock, not this host's: a machine running
            # behind would otherwise sign messages that are already expired on arrival.
            # The seqno stays the same across attempts, so at most one of these can ever
            # execute — rebuilding cannot double-spend.
            params = (params_class(valid_until=network_now() + TRANSFER_TTL)
                      if params_class else None)
            try:
                await wallet.transfer(destination=destination_address, amount=amount,
                                      body=payload, send_mode=send_mode, params=params)
                logger.info("Sending successful!")
                return
            except Exception as error:
                expired = any(marker in str(error) for marker in EXPIRED_MARKERS)
                if attempt == SEND_ATTEMPTS:
                    raise

                if expired:
                    # the clock may have drifted since startup — re-measure before retrying
                    skew, message = await asyncio.to_thread(sync_clock)
                    logger.warning("expired message, clock re-synced: %s", message)

                logger.warning("send attempt %s/%s failed (%s), rebuilding the message: %s",
                               attempt, SEND_ATTEMPTS,
                               "message expired" if expired else "network error", error)
                await asyncio.sleep(RETRY_AFTER_SECONDS)

    def send_ton(self, mnemonics, destination_address, amount, payload, nano_amount=True, version='v5r1',
                 testnet=False, send_mode=3):
        """Blocking wrapper kept for main.py. Inside an event loop await send_ton_async instead."""
        try:
            return asyncio.run(self.send_ton_async(mnemonics, destination_address, amount, payload, nano_amount,
                                                   version, testnet, send_mode))
        except Exception as error:
            logger.error(f"Transaction failed: {error}")
            return 0

    @classmethod
    async def get_balance(cls, mnemonics, version='v5r1', testnet=False):
        async with cls.session(mnemonics, version, testnet) as (client, wallet):
            info = await client.get_info(wallet.address)
            return wallet.address.to_str(), info.balance

    @classmethod
    async def send_checked(cls, mnemonics, destination_address, amount, payload, version='v5r1',
                           testnet=False, send_mode=3):
        """Balance check and transfer over one client, which halves the toncenter calls."""
        amount = int(amount)
        async with cls.session(mnemonics, version, testnet) as (client, wallet):
            info = await client.get_info(wallet.address)
            if info.balance <= amount:
                raise ValueError(f"на кошельке {info.balance / 10 ** 9:.4f} TON, "
                                 f"нужно {amount / 10 ** 9:.4f} TON")
            await cls._transfer(wallet, destination_address, amount, payload, send_mode, version)
        return 1
