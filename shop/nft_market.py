"""Portals marketplace client.

Portals has no public API, so this replays what its Mini App does: the Telegram `initData`
goes into the Authorization header and the Cloudflare cookies come along with it — the same
trick as cookies.json for Fragment.

Grab a fresh set from Telegram Web: open the Mini App, DevTools → Network → any request to
portal-market.com → "Copy as cURL", then update portals_auth.json.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE = "https://portal-market.com/api"
AUTH_FILE = Path(__file__).resolve().parent.parent / "portals_auth.json"

RATE_LIMIT_RETRIES = 4
RATE_LIMIT_PAUSE = 4

# https://t.me/nft/LolPop-12345
GIFT_LINK_PATTERN = re.compile(r"t\.me/nft/([A-Za-z0-9]+)-(\d+)", re.IGNORECASE)


class MarketError(Exception):
    pass


class MarketAuthError(MarketError):
    pass


@dataclass
class Listing:
    name: str                 # collection, e.g. "Lol Pop"
    model: str | None
    symbol: str | None
    backdrop: str | None
    price: Decimal            # TON
    floor_price: Decimal | None
    tg_id: str | None
    photo_url: str | None

    @property
    def link(self) -> str | None:
        return f"https://t.me/nft/{self.tg_id}" if self.tg_id else None


def _load_auth() -> dict:
    if not AUTH_FILE.exists():
        raise MarketAuthError("portals_auth.json не найден — выгрузите доступы из Mini App")
    try:
        return json.loads(AUTH_FILE.read_text())
    except Exception as error:
        raise MarketAuthError(f"portals_auth.json повреждён: {error}") from error


def _request(path: str, params: dict | None = None) -> dict:
    auth = _load_auth()
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7",
        "authorization": auth["authorization"],
        "referer": "https://portal-market.com/",
        "sec-ch-ua": auth.get("sec_ch_ua", ""),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": auth.get("sec_ch_ua_platform", '"macOS"'),
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": auth.get("user_agent", ""),
    }

    for attempt in range(RATE_LIMIT_RETRIES):
        response = requests.get(f"{BASE}{path}", headers=headers, cookies=auth.get("cookies", {}),
                                params=params, timeout=25)
        if response.status_code != 429:
            break
        logger.info("portals rate limit, waiting %s s", RATE_LIMIT_PAUSE)
        time.sleep(RATE_LIMIT_PAUSE)

    if response.status_code in (401, 403):
        raise MarketAuthError("Portals отклонил доступы — initData живёт несколько часов, "
                              "выгрузите свежие из Mini App в portals_auth.json")
    if response.status_code == 429:
        raise MarketError("Portals ограничивает частоту запросов, попробуйте через минуту")
    if response.status_code != 200:
        raise MarketError(f"Portals ответил {response.status_code}")

    return response.json()


def _to_listing(nft: dict) -> Listing:
    attributes = {item["type"]: item["value"] for item in nft.get("attributes", [])}
    return Listing(
        name=nft.get("name", "—"),
        model=attributes.get("model"),
        symbol=attributes.get("symbol"),
        backdrop=attributes.get("backdrop"),
        price=Decimal(str(nft.get("price", "0"))),
        floor_price=Decimal(str(nft["floor_price"])) if nft.get("floor_price") else None,
        tg_id=nft.get("tg_id"),
        photo_url=nft.get("photo_url"),
    )


def cheapest(model: str | None = None, symbol: str | None = None,
             backdrop: str | None = None, collection: str | None = None) -> Listing | None:
    """The cheapest listing matching the given attributes — that is the floor for this combination."""
    params = {"offset": 0, "limit": 1, "status": "listed", "sort_by": "price asc"}
    if model:
        params["filter_by_models"] = model
    if symbol:
        params["filter_by_symbols"] = symbol
    if backdrop:
        params["filter_by_backdrops"] = backdrop
    if collection:
        params["filter_by_collections"] = collection

    logger.info("portals search: %s", {k: v for k, v in params.items() if k.startswith("filter")})
    results = _request("/nfts/search", params).get("results", [])
    if not results:
        return None

    listing = _to_listing(results[0])
    logger.info("portals found: %s %s/%s/%s at %s TON",
                listing.name, listing.model, listing.symbol, listing.backdrop, listing.price)
    return listing


def find_similar(model: str | None, symbol: str | None,
                 backdrop: str | None) -> tuple[Listing | None, str]:
    """Look for the requested combination, then loosen it.

    An exact model+symbol+backdrop triple is rarely on sale at any given moment, so rather than
    reporting "not found" the search steps back to broader matches and says how close it got.
    """
    attempts = [
        (("exact", model, symbol, backdrop), all((model, symbol, backdrop))),
        (("model_backdrop", model, None, backdrop), all((model, backdrop))),
        (("model_symbol", model, symbol, None), all((model, symbol))),
        (("model", model, None, None), bool(model)),
    ]

    seen = set()
    for (quality, m, s, b), usable in attempts:
        key = (m, s, b)
        if not usable or key in seen:
            continue
        seen.add(key)

        listing = cheapest(m, s, b)
        if listing:
            logger.info("match quality: %s", quality)
            return listing, quality

    return None, "none"


def parse_request(text: str) -> dict | None:
    """Understand either a gift link or the three-line model/symbol/backdrop form."""
    link = GIFT_LINK_PATTERN.search(text or "")
    if link:
        return {"kind": "link", "slug": link.group(1), "number": int(link.group(2))}

    lines = [line.strip(" .0123456789)-") for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    return {"kind": "attributes",
            "model": lines[0] if len(lines) > 0 else None,
            "symbol": lines[1] if len(lines) > 1 else None,
            "backdrop": lines[2] if len(lines) > 2 else None}


def collection_by_slug(slug: str) -> str | None:
    """Map the slug from a t.me/nft link to a collection id."""
    wanted = slug.lower()
    for collection in _request("/collections").get("collections", []):
        if (collection.get("short_name") or "").lower() == wanted:
            return collection.get("id")
    return None


# t.me publishes every gift's traits in its meta tags, no authentication involved.
META_PATTERN = re.compile(r'<meta\s+(?:property|name)="(?:og|twitter):(title|description)"\s+'
                          r'content="([^"]*)"', re.IGNORECASE)
TRAIT_LABELS = ("Model", "Backdrop", "Symbol")


def _trait(description: str, label: str) -> str | None:
    others = "|".join(other for other in TRAIT_LABELS if other != label)
    match = re.search(rf"{label}:\s*(.+?)\s*(?=(?:{others}):|$)", description)
    return match.group(1).strip() if match else None


def gift_from_link(slug: str, number: int) -> dict | None:
    """Read a specific gift's traits straight off its public t.me page.

    The link points at one particular gift; what the customer wants is another one just like
    it, so the traits are what we search by — not the collection as a whole.
    """
    url = f"https://t.me/nft/{slug}-{number}"
    try:
        response = requests.get(url, timeout=20, headers={
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"})
    except Exception as error:
        raise MarketError(f"не удалось открыть {url}: {error}") from error

    if response.status_code != 200:
        return None

    meta = {key: value for key, value in META_PATTERN.findall(response.text)}
    description = meta.get("description", "")
    if "Model:" not in description:
        return None

    gift = {
        "collection": (meta.get("title") or "").split("#")[0].strip() or slug,
        "number": number,
        "model": _trait(description, "Model"),
        "symbol": _trait(description, "Symbol"),
        "backdrop": _trait(description, "Backdrop"),
    }
    logger.info("gift %s-%s traits: %s", slug, number, gift)
    return gift
