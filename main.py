import json
from FragmentApi.BuyStars import buy_stars

WALLETS_FILE = "created_wallets/wallets_data.txt"


def load_mnemonics(path=WALLETS_FILE):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    if not raw:
        raise ValueError(f"{path} is empty: put a seed phrase there or create a wallet first")

    # create_wallet() appends JSON blocks separated by blank lines, so take the first one
    if raw.startswith("{"):
        block = json.JSONDecoder().raw_decode(raw)[0]
        return block["mnemonics"]

    # plain seed phrase, one line of space-separated words
    return raw.split()


if __name__ == '__main__':
    mnemonics = load_mnemonics()

    recipient = input("Recipient: ")
    amount = input("Amount: ")

    buy_stars(recipient, int(amount), mnemonics, send_mode=3, testnet=False)
