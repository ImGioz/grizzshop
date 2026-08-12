import requests
from re import search
import logging
from wallet.WalletUtils import WalletUtils
from urllib.parse import urlencode
from tonsdk.utils import Address
from pytoniq_core import Cell
from tonsdk.crypto import mnemonic_to_wallet_key
import json
import base64


class FragmentApiError(Exception):
    pass


class RecipientError(FragmentApiError):
    """Fragment отказывается от получателя: нет такого аккаунта или дарить ему нечего.

    Отдельный класс, потому что это не поломка магазина, а нормальный ответ, о котором надо
    сказать клиенту человеческими словами — в отличие от протухших кук.
    """


# Fragment отвечает по-английски; ловим по подстроке, а не на равенство, потому что текст
# он поправляет время от времени. Каждой причине — свой код, чтобы бот подсказал по делу.
RECIPIENT_ERRORS = (
    ("already subscribed to telegram premium", "already_premium"),
    # username канала или бота: "Please enter a username assigned to a user."
    ("username assigned to a user", "not_a_user"),
    ("no telegram users found", "not_found"),
)


# Fragment drives stars and Premium gifts through the same three-step flow, only the method
# names and the quantity field differ (confirmed against fragment.com/js/auction.js).
PRODUCTS = {
    "stars": {
        "label": "stars",
        "amount_field": "quantity",
        "search": "searchStarsRecipient",
        "init": "initBuyStarsRequest",
        "link": "getBuyStarsLink",
    },
    "premium": {
        "label": "months of Premium",
        "amount_field": "months",
        "search": "searchPremiumGiftRecipient",
        "init": "initGiftPremiumRequest",
        "link": "getGiftPremiumLink",
    },
}


class PaymentGet:
    def __init__(self):
        self.WalletUtils = WalletUtils()
        with open('cookies.json', 'r') as file:
            loaded_cookies = json.load(file)

        self.cookies = loaded_cookies
        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://fragment.com/stars/buy",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 OPR/117.0.0.0 (Edition Yx GX)"
        }

    def _page_get(self):
        response = requests.get("https://fragment.com/stars/buy", cookies=self.cookies)
        if response.status_code != 200:
            raise FragmentApiError(f"fragment.com/stars/buy returned {response.status_code}")

        return response.text

    def _hash_get(self, page=None):
        page = self._page_get() if page is None else page

        match = search(r'api\?hash=([a-zA-Z0-9]+)', page)
        if not match:
            raise FragmentApiError("api hash not found on the page, cookies in cookies.json are probably expired")

        return match.group(1)

    def _update_url(self, page=None):
        return f"https://fragment.com/api?hash={self._hash_get(page)}"

    def _check_session_wallet(self, page, mnemonics):
        """Fragment binds the session to one TON wallet. Compare by public key, not by address: the same seed
        gives different addresses per wallet version (Telegram Wallet uses W5, tonsdk defaults to v4r2)."""
        match = search(r'Wallet\.init\((\{.*?\})\);', page)
        if not match:
            return

        session = json.loads(match.group(1))
        if not session.get("logged_in") or not session.get("address"):
            raise FragmentApiError("TON wallet is not connected on fragment.com, connect it and re-export cookies.json")

        session_address = Address(session["address"]).to_string(True, True, True)
        own_pub = mnemonic_to_wallet_key(mnemonics)[0].hex()

        chain_pub = self._onchain_public_key(session_address)
        if chain_pub and chain_pub != own_pub:
            raise FragmentApiError(
                f"wallet mismatch: fragment.com session is connected to {session_address}, which is not "
                f"controlled by the seed phrase in created_wallets/wallets_data.txt")

        return session_address

    @staticmethod
    def _onchain_public_key(address):
        try:
            from shop.config import TONCENTER_API_KEY
            headers = {"X-API-Key": TONCENTER_API_KEY} if TONCENTER_API_KEY else {}
        except ImportError:
            headers = {}

        try:
            response = requests.post("https://toncenter.com/api/v2/runGetMethod", timeout=30, headers=headers,
                                     json={"address": address, "method": "get_public_key", "stack": []}).json()
            return format(int(response["result"]["stack"][0][1], 16), "064x")
        except Exception:
            return None  # never block a purchase on a public-node hiccup or a rate limit

    def _payload_get(self, req_id, mnemonics, link_method="getBuyStarsLink"):
        payload = {
            "account": json.dumps({
                "chain": "-239",
                "publicKey": self.WalletUtils.wallet_from_mnemonics(mnemonics)[0]["public_key"]
            }),
            "device": json.dumps({
                "platform": "web",
                "appName": "telegram-wallet",
                "appVersion": "1",
                "maxProtocolVersion": 2,
                "features": ["SendTransaction", {"name": "SendTransaction", "maxMessages": 4}]
            }),
            "transaction": 1,
            "id": req_id,
            "show_sender": 1,
            "method": link_method
        }
        return urlencode(payload)

    @staticmethod
    def _payload_cell(encoded_payload):
        """Fragment hands back the message body as a BOC, which is sent on unchanged.

        Rebuilding it from text is what broke Premium: its comment spans two cells, and the old
        "take everything after the null bytes" trick returned the tail of the second one.
        """
        padded = encoded_payload + "=" * (-len(encoded_payload) % 4)
        return Cell.one_from_boc(base64.b64decode(padded))

    @staticmethod
    def _comment_of(cell):
        """The human-readable comment inside the body cell — for logs only."""
        try:
            slice_ = cell.begin_parse()
            if slice_.load_uint(32) != 0:      # not a text comment
                return ""
            return slice_.load_snake_string()
        except Exception:
            return ""

    @staticmethod
    def _check(response, step):
        data = response.json()
        if data.get("error"):
            raise FragmentApiError(f"{step}: {data['error']}. Cookies in cookies.json are probably expired, "
                                   f"re-export them from fragment.com")
        return data

    def check_recipient(self, recipient, product="premium", quantity=""):
        """Спросить Fragment, можно ли вообще дарить этому получателю.

        Тот же поиск, что и в начале покупки, но без оплаты — чтобы отказ («у него уже есть
        Premium», «нет такого аккаунта») всплыл до создания заказа, а не после оплаты.
        """
        api = PRODUCTS.get(product)
        if api is None:
            raise FragmentApiError(f"unknown product {product!r}")

        url = self._update_url()
        response = requests.post(
            url, headers=self.headers, cookies=self.cookies,
            data=f"query={recipient}&{api['amount_field']}={quantity}&method={api['search']}")

        try:
            data = response.json()
        except ValueError as error:
            raise FragmentApiError(f"{api['search']}: Fragment вернул не JSON: {error}") from error

        error = data.get("error")
        if error:
            lowered = error.lower()
            code = next((code for marker, code in RECIPIENT_ERRORS if marker in lowered), None)
            # Незнакомую формулировку не глотаем: пусть всплывёт как обычная ошибка Fragment,
            # иначе новая причина отказа будет годами показываться как "аккаунт не найден".
            if code is None:
                raise FragmentApiError(f"{api['search']}: {error}")
            raise RecipientError(code)

        if not data.get("found", {}).get("recipient"):
            raise RecipientError("not_found")

        logging.info("recipient @%s ok for %s", recipient, product)

    def get_data_for_payment(self, recipient, quantity, mnemonics, product="stars"):
        """Prepare a Fragment purchase. `quantity` is stars, or months for Premium."""
        api = PRODUCTS.get(product)
        if api is None:
            raise FragmentApiError(f"unknown product {product!r}, expected one of {sorted(PRODUCTS)}")

        logging.warning(f"Sending {quantity} {api['label']} to @{recipient}...")

        page = self._page_get()
        self._check_session_wallet(page, mnemonics)
        url = self._update_url(page)

        # the stars search takes an empty quantity, the premium one wants the month count
        search_amount = quantity if api["amount_field"] == "months" else ""
        recipient_id_dirt = requests.post(
            url, headers=self.headers, cookies=self.cookies,
            data=f"query={recipient}&{api['amount_field']}={search_amount}&method={api['search']}")
        found = self._check(recipient_id_dirt, api["search"]).get("found", {})
        recipient_id = found.get("recipient", "")
        if not recipient_id:
            raise FragmentApiError(f"recipient @{recipient} not found on Fragment")

        req_id_dirt = requests.post(
            url, headers=self.headers, cookies=self.cookies,
            data=f"recipient={recipient_id}&{api['amount_field']}={quantity}"
                 f"&payment_method=ton&method={api['init']}")
        req_id = self._check(req_id_dirt, api["init"]).get("req_id", "")

        encoded_payload = self._payload_get(req_id, mnemonics, api["link"])

        buy_payload_dirt = requests.post(url, headers=self.headers, cookies=self.cookies, data=encoded_payload)
        buy_payload = self._check(buy_payload_dirt, api["link"])["transaction"]["messages"][0]

        address, amount, encoded_message = buy_payload["address"], buy_payload["amount"], buy_payload["payload"]
        body = self._payload_cell(encoded_message)

        logging.info("Payment data received! Comment: %r", self._comment_of(body).replace("\n", " "))
        logging.warning("Waiting to send transaction...")
        return address, amount, body