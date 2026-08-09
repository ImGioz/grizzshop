"""Price tables.

The values below are defaults. Anything changed from the admin panel is stored in the
`settings` table and loaded over these at startup, so edits survive a restart.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

# Star tiers: quantity -> price in UAH. The per-star rate drops as the volume grows,
# so a custom quantity is interpolated along this curve instead of using one flat rate.
STAR_PRICES: dict[int, Decimal] = {
    50: Decimal("45"),
    100: Decimal("80"),
    150: Decimal("120"),
    200: Decimal("160"),
    250: Decimal("190"),
    300: Decimal("235"),
    350: Decimal("275"),
    400: Decimal("315"),
    450: Decimal("355"),
    500: Decimal("380"),
    600: Decimal("445"),
    700: Decimal("515"),
    800: Decimal("590"),
    900: Decimal("670"),
    1000: Decimal("740"),
}

# Only used beyond the largest tier; kept editable for that case.
PRICE_PER_STAR_CUSTOM = Decimal("0.74")

# Bulk orders get a thinner margin, but only on the stars above the threshold: charging the
# lower rate on the whole order would make 3000 stars cost less than 2999.
BULK_STARS_FROM = 3000
PRICE_PER_STAR_BULK = Decimal("0.72")

# Telegram Premium: months -> price in UAH.
PREMIUM_PRICES: dict[int, Decimal] = {
    3: Decimal("600"),
    6: Decimal("750"),
    12: Decimal("1450"),
}

PREMIUM_ENABLED = True

# Gram (TON coin): price of one TON in UAH. Any amount from MIN_TON upwards.
TON_PRICE_UAH = Decimal("75.5")
MIN_TON = Decimal("0.1")
GRAM_ENABLED = True

SETTING_PREFIX = "price_stars_"
SETTING_PER_STAR = "price_per_star"
SETTING_PREMIUM_PREFIX = "price_premium_"
SETTING_TON_PRICE = "price_ton"
SETTING_BULK_RATE = "price_per_star_bulk"
SETTING_BULK_FROM = "bulk_stars_from"


def apply_overrides(settings: dict[str, str]) -> None:
    """Load admin-panel edits over the defaults. Called at startup and after every change."""
    global PRICE_PER_STAR_CUSTOM, TON_PRICE_UAH, PRICE_PER_STAR_BULK, BULK_STARS_FROM

    for key, value in settings.items():
        if key == SETTING_BULK_RATE:
            PRICE_PER_STAR_BULK = Decimal(value)
            continue
        if key == SETTING_BULK_FROM:
            BULK_STARS_FROM = int(value)
            continue
        if key == SETTING_TON_PRICE:
            TON_PRICE_UAH = Decimal(value)
            continue
        if key.startswith(SETTING_PREMIUM_PREFIX):
            months = key[len(SETTING_PREMIUM_PREFIX):]
            if months.isdigit():
                PREMIUM_PRICES[int(months)] = Decimal(value)
        elif key.startswith(SETTING_PREFIX):
            quantity = key[len(SETTING_PREFIX):]
            if quantity.isdigit():
                STAR_PRICES[int(quantity)] = Decimal(value)
        elif key == SETTING_PER_STAR:
            PRICE_PER_STAR_CUSTOM = Decimal(value)


def _up(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_CEILING)


def star_price(quantity: int) -> Decimal:
    """Price of any star quantity, following the tier table.

    Between two tiers the price is interpolated, so a custom amount costs what the table
    implies rather than a flat rate. Above the largest tier the top rate is extended.
    """
    if quantity in STAR_PRICES:
        return STAR_PRICES[quantity]

    tiers = sorted(STAR_PRICES)
    if quantity >= tiers[-1]:
        rate = max(PRICE_PER_STAR_CUSTOM, STAR_PRICES[tiers[-1]] / Decimal(tiers[-1]))
        if quantity > BULK_STARS_FROM:
            # normal rate up to the threshold, the cheaper one only on the excess
            below = Decimal(BULK_STARS_FROM) * rate
            above = Decimal(quantity - BULK_STARS_FROM) * PRICE_PER_STAR_BULK
            return _up(below + above)
        return _up(Decimal(quantity) * rate)
    if quantity <= tiers[0]:
        return _up(Decimal(quantity) * (STAR_PRICES[tiers[0]] / Decimal(tiers[0])))

    for low, high in zip(tiers, tiers[1:]):
        if low < quantity < high:
            share = Decimal(quantity - low) / Decimal(high - low)
            return _up(STAR_PRICES[low] + share * (STAR_PRICES[high] - STAR_PRICES[low]))

    return _up(Decimal(quantity) * PRICE_PER_STAR_CUSTOM)


def star_rate(quantity: int) -> Decimal:
    """Effective price of one star at this volume, for showing in the calculator."""
    if quantity <= 0:
        return PRICE_PER_STAR_CUSTOM
    return (star_price(quantity) / Decimal(quantity)).quantize(Decimal("0.001"))


def stars_for_budget(amount: Decimal) -> int:
    """Most stars actually buyable for `amount`.

    star_price rises with quantity, so this is a binary search rather than a division:
    rounding up to whole hryvnia makes the plain amount / rate answer slightly too generous.
    """
    if amount < star_price(1):
        return 0

    low, high = 1, 1
    while star_price(high) <= amount:
        low, high = high, high * 2

    while low < high:
        middle = (low + high + 1) // 2
        if star_price(middle) <= amount:
            low = middle
        else:
            high = middle - 1

    return low


def premium_price(months: int) -> Decimal:
    return PREMIUM_PRICES[months]


def gram_price(nanotons: int) -> Decimal:
    """Cost of a TON amount, rounded up to whole hryvnia."""
    exact = (Decimal(nanotons) / Decimal(10 ** 9)) * TON_PRICE_UAH
    return exact.quantize(Decimal("1"), rounding=ROUND_CEILING)
