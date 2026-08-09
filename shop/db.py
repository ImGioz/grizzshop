"""SQLite storage: users, orders and the receipts already spent."""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import aiosqlite

from shop.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    language    TEXT,
    subscribed  INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,   -- set when the user blocks the bot during a broadcast
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    product       TEXT NOT NULL,              -- 'stars' | 'premium'
    recipient     TEXT NOT NULL,              -- @username of the receiver
    quantity      INTEGER NOT NULL,
    price         TEXT NOT NULL,              -- Decimal as text, UAH
    status        TEXT NOT NULL,              -- pending|awaiting_check|paid|delivered|failed|expired
    payment_method TEXT,
    sender_name   TEXT,
    receipt_id    TEXT,
    card_number   TEXT,                       -- snapshot: the card shown to this buyer
    receipt_file_id TEXT,                     -- telegram file_id of the PDF, for admin review
    wallet_address TEXT,                      -- TON address for 'gram' orders
    details       TEXT,                       -- free-form item description, used by 'nft' orders
    cost_uah      TEXT,                       -- what the delivery actually cost us, UAH
    created_at    TEXT NOT NULL,
    paid_at       TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- One receipt can pay for exactly one order.
CREATE TABLE IF NOT EXISTS used_receipts (
    receipt_id  TEXT PRIMARY KEY,
    order_id    INTEGER NOT NULL,
    used_at     TEXT NOT NULL,
    payload     TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL UNIQUE,     -- one review per order
    user_id       INTEGER NOT NULL,
    client_name   TEXT NOT NULL,
    rating        INTEGER NOT NULL,
    comment       TEXT,
    photo_file_id TEXT,
    stars         INTEGER NOT NULL,            -- delivered in this order
    total_stars   INTEGER NOT NULL,            -- delivered to this user in total
    created_at    TEXT NOT NULL
);

-- Marketplace floor prices, so a showcase does not wait on four rate-limited lookups per gift.
CREATE TABLE IF NOT EXISTS price_cache (
    key        TEXT PRIMARY KEY,      -- model|symbol|backdrop
    payload    TEXT NOT NULL,         -- serialised listing
    updated_at TEXT NOT NULL
);

-- Admins added from the panel. Those listed in .env are permanent and live outside this table.
CREATE TABLE IF NOT EXISTS admins (
    user_id   INTEGER PRIMARY KEY,
    note      TEXT,
    added_by  INTEGER,
    added_at  TEXT NOT NULL
);

-- Runtime settings edited from the admin panel (prices, flags), so they survive a restart.
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status, id);
"""

PENDING_STATUSES = ("pending", "awaiting_check")


@dataclass
class Order:
    id: int
    user_id: int
    product: str
    recipient: str
    quantity: int
    price: Decimal
    status: str
    payment_method: str | None
    sender_name: str | None
    receipt_id: str | None
    card_number: str | None
    receipt_file_id: str | None
    wallet_address: str | None
    details: str | None
    cost_uah: Decimal | None
    created_at: datetime
    paid_at: datetime | None

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            product=row["product"],
            recipient=row["recipient"],
            quantity=row["quantity"],
            price=Decimal(row["price"]),
            status=row["status"],
            payment_method=row["payment_method"],
            sender_name=row["sender_name"],
            receipt_id=row["receipt_id"],
            card_number=row["card_number"],
            receipt_file_id=row["receipt_file_id"],
            wallet_address=row["wallet_address"],
            details=row["details"],
            cost_uah=Decimal(row["cost_uah"]) if row["cost_uah"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            paid_at=datetime.fromisoformat(row["paid_at"]) if row["paid_at"] else None,
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def connect():
    """One short-lived connection per operation; awaiting aiosqlite.connect already starts
    its worker thread, so this must not be awaited again by the caller."""
    connection = await aiosqlite.connect(DB_PATH)
    try:
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        await connection.close()


async def init():
    async with connect() as connection:
        await connection.executescript(SCHEMA)

        # migrate databases created by earlier versions
        cursor = await connection.execute("PRAGMA table_info(orders)")
        if "card_number" not in {row["name"] for row in await cursor.fetchall()}:
            await connection.execute("ALTER TABLE orders ADD COLUMN card_number TEXT")

        cursor = await connection.execute("PRAGMA table_info(orders)")
        if "receipt_file_id" not in {row["name"] for row in await cursor.fetchall()}:
            await connection.execute("ALTER TABLE orders ADD COLUMN receipt_file_id TEXT")

        cursor = await connection.execute("PRAGMA table_info(orders)")
        if "wallet_address" not in {row["name"] for row in await cursor.fetchall()}:
            await connection.execute("ALTER TABLE orders ADD COLUMN wallet_address TEXT")

        cursor = await connection.execute("PRAGMA table_info(orders)")
        if "details" not in {row["name"] for row in await cursor.fetchall()}:
            await connection.execute("ALTER TABLE orders ADD COLUMN details TEXT")

        cursor = await connection.execute("PRAGMA table_info(orders)")
        if "cost_uah" not in {row["name"] for row in await cursor.fetchall()}:
            await connection.execute("ALTER TABLE orders ADD COLUMN cost_uah TEXT")

        cursor = await connection.execute("PRAGMA table_info(users)")
        if "blocked" not in {row["name"] for row in await cursor.fetchall()}:
            await connection.execute("ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")

        await connection.commit()


async def upsert_user(user_id: int, username: str | None):
    async with connect() as connection:
        await connection.execute(
            "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id) DO UPDATE SET username = excluded.username",
            (user_id, username, _now()))
        await connection.commit()


async def get_user(user_id: int):
    async with connect() as connection:
        cursor = await connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()


async def set_language(user_id: int, language: str):
    async with connect() as connection:
        await connection.execute("UPDATE users SET language = ? WHERE user_id = ?", (language, user_id))
        await connection.commit()


async def get_language(user_id: int) -> str | None:
    user = await get_user(user_id)
    return user["language"] if user else None


async def set_subscribed(user_id: int, subscribed: bool):
    async with connect() as connection:
        await connection.execute("UPDATE users SET subscribed = ? WHERE user_id = ?",
                                 (1 if subscribed else 0, user_id))
        await connection.commit()


async def create_order(user_id: int, product: str, recipient: str, quantity: int, price: Decimal,
                       card_number: str | None = None, wallet_address: str | None = None,
                       details: str | None = None) -> int:
    """`quantity` is stars, months of Premium, or nanotons for a 'gram' order."""
    async with connect() as connection:
        cursor = await connection.execute(
            "INSERT INTO orders (user_id, product, recipient, quantity, price, status, card_number, "
            "wallet_address, details, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (user_id, product, recipient, quantity, str(price), card_number, wallet_address,
             details, _now()))
        await connection.commit()
        return cursor.lastrowid


async def get_order(order_id: int) -> Order | None:
    async with connect() as connection:
        cursor = await connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = await cursor.fetchone()
        return Order.from_row(row) if row else None


async def update_order(order_id: int, **fields):
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    async with connect() as connection:
        await connection.execute(f"UPDATE orders SET {assignments} WHERE id = ?",
                                 (*fields.values(), order_id))
        await connection.commit()


async def delete_order(order_id: int) -> bool:
    """Remove an order outright. Only used for cancellation, before any payment is claimed."""
    async with connect() as connection:
        cursor = await connection.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        await connection.commit()
        return cursor.rowcount > 0


async def mark_paid(order_id: int, receipt_id: str, payload: dict) -> bool:
    """Claim the receipt and flip the order to paid. False when the receipt was already spent."""
    async with connect() as connection:
        try:
            await connection.execute(
                "INSERT INTO used_receipts (receipt_id, order_id, used_at, payload) VALUES (?, ?, ?, ?)",
                (receipt_id, order_id, _now(), json.dumps(payload, ensure_ascii=False, default=str)))
        except aiosqlite.IntegrityError:
            return False

        await connection.execute("UPDATE orders SET status = 'paid', receipt_id = ?, paid_at = ? WHERE id = ?",
                                 (receipt_id, _now(), order_id))
        await connection.commit()
        return True


async def expire_stale_orders(timeout_minutes: int) -> list[int]:
    """Move unpaid orders past their deadline to 'expired'. Returns the affected ids."""
    cutoff = datetime.now(timezone.utc).timestamp() - timeout_minutes * 60
    async with connect() as connection:
        pending = ", ".join("?" * len(PENDING_STATUSES))
        cursor = await connection.execute(
            f"SELECT id, created_at FROM orders WHERE status IN ({pending})", PENDING_STATUSES)
        stale = [row["id"] for row in await cursor.fetchall()
                 if datetime.fromisoformat(row["created_at"]).timestamp() < cutoff]

        if stale:
            placeholders = ", ".join("?" * len(stale))
            await connection.execute(f"UPDATE orders SET status = 'expired' WHERE id IN ({placeholders})", stale)
            await connection.commit()
        return stale


BROADCAST_AUDIENCES = {
    # name -> (human title, extra WHERE clause)
    "all": ("всем пользователям", ""),
    "subscribed": ("подписанным на канал", "AND subscribed = 1"),
    "buyers": ("покупателям", "AND user_id IN (SELECT user_id FROM orders "
                              "WHERE status IN ('paid', 'delivered'))"),
}


async def broadcast_recipients(audience: str) -> list[int]:
    """User ids for a broadcast. Users who blocked the bot are skipped."""
    _, condition = BROADCAST_AUDIENCES[audience]
    async with connect() as connection:
        cursor = await connection.execute(
            f"SELECT user_id FROM users WHERE blocked = 0 {condition} ORDER BY user_id")
        return [row["user_id"] for row in await cursor.fetchall()]


async def set_blocked(user_id: int, blocked: bool = True):
    async with connect() as connection:
        await connection.execute("UPDATE users SET blocked = ? WHERE user_id = ?",
                                 (1 if blocked else 0, user_id))
        await connection.commit()


async def cached_price(key: str) -> tuple[dict, datetime] | None:
    async with connect() as connection:
        cursor = await connection.execute(
            "SELECT payload, updated_at FROM price_cache WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if not row:
            return None
        return json.loads(row["payload"]), datetime.fromisoformat(row["updated_at"])


async def store_price(key: str, payload: dict) -> None:
    async with connect() as connection:
        await connection.execute(
            "INSERT INTO price_cache (key, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET payload = excluded.payload, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(payload, ensure_ascii=False), _now()))
        await connection.commit()


async def add_admin(user_id: int, note: str | None, added_by: int) -> bool:
    """False when this id is already an admin."""
    async with connect() as connection:
        try:
            await connection.execute(
                "INSERT INTO admins (user_id, note, added_by, added_at) VALUES (?, ?, ?, ?)",
                (user_id, note, added_by, _now()))
        except aiosqlite.IntegrityError:
            return False
        await connection.commit()
        return True


async def remove_admin(user_id: int) -> bool:
    async with connect() as connection:
        cursor = await connection.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await connection.commit()
        return cursor.rowcount > 0


async def list_admins() -> list:
    async with connect() as connection:
        cursor = await connection.execute("SELECT * FROM admins ORDER BY added_at")
        return list(await cursor.fetchall())


async def admin_ids() -> set[int]:
    async with connect() as connection:
        cursor = await connection.execute("SELECT user_id FROM admins")
        return {row["user_id"] for row in await cursor.fetchall()}


async def create_review(order_id: int, user_id: int, client_name: str, rating: int,
                        comment: str | None, photo_file_id: str | None,
                        stars: int, total_stars: int) -> int | None:
    """Store a review. Returns None when this order already has one."""
    async with connect() as connection:
        try:
            cursor = await connection.execute(
                "INSERT INTO reviews (order_id, user_id, client_name, rating, comment, photo_file_id, "
                "stars, total_stars, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, user_id, client_name, rating, comment, photo_file_id,
                 stars, total_stars, _now()))
        except aiosqlite.IntegrityError:
            return None
        await connection.commit()
        return cursor.lastrowid


async def has_review(order_id: int) -> bool:
    async with connect() as connection:
        cursor = await connection.execute("SELECT 1 FROM reviews WHERE order_id = ?", (order_id,))
        return await cursor.fetchone() is not None


async def review_stats(since: datetime | None = None) -> tuple[int, float]:
    query = "SELECT COUNT(*) AS n, COALESCE(AVG(rating), 0) AS avg_rating FROM reviews"
    values = ()
    if since:
        query += " WHERE created_at >= ?"
        values = (since.isoformat(),)

    async with connect() as connection:
        cursor = await connection.execute(query, values)
        row = await cursor.fetchone()
        return row["n"], row["avg_rating"]


async def get_settings() -> dict[str, str]:
    async with connect() as connection:
        cursor = await connection.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in await cursor.fetchall()}


async def set_setting(key: str, value: str):
    async with connect() as connection:
        await connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, str(value)))
        await connection.commit()


async def count_orders(statuses: tuple[str, ...] | None = None) -> int:
    async with connect() as connection:
        if statuses:
            placeholders = ", ".join("?" * len(statuses))
            cursor = await connection.execute(
                f"SELECT COUNT(*) AS n FROM orders WHERE status IN ({placeholders})", statuses)
        else:
            cursor = await connection.execute("SELECT COUNT(*) AS n FROM orders")
        return (await cursor.fetchone())["n"]


async def orders_page(statuses: tuple[str, ...] | None, offset: int, limit: int) -> list[Order]:
    async with connect() as connection:
        if statuses:
            placeholders = ", ".join("?" * len(statuses))
            cursor = await connection.execute(
                f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT ? OFFSET ?",
                (*statuses, limit, offset))
        else:
            cursor = await connection.execute(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return [Order.from_row(row) for row in await cursor.fetchall()]


SUCCESSFUL_STATUSES = ("paid", "delivered")
UNSUCCESSFUL_STATUSES = ("failed", "expired", "cancelled")


async def shop_stats(statuses: tuple[str, ...] | None = None, since: datetime | None = None) -> dict:
    """Totals for the given order statuses; `None` covers every operation.

    `since` limits everything to orders, users and reviews created from that moment on.
    Timestamps are stored as UTC ISO strings, so a plain string comparison is chronological.
    """
    cutoff = since.isoformat() if since else None

    def window(prefix: str, column: str = "created_at"):
        return f" {prefix} {column} >= ?" if cutoff else ""

    async with connect() as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) AS n FROM users" + window("WHERE"),
            (cutoff,) if cutoff else ())
        users = (await cursor.fetchone())["n"]

        cursor = await connection.execute(
            "SELECT status, COUNT(*) AS n FROM orders" + window("WHERE") + " GROUP BY status",
            (cutoff,) if cutoff else ())
        by_status = {row["status"]: row["n"] for row in await cursor.fetchall()}

        totals = ("SELECT COUNT(*) AS orders, COALESCE(SUM(CAST(price AS REAL)), 0) AS revenue, "
                  "COALESCE(SUM(CASE WHEN product = 'stars' THEN quantity END), 0) AS stars, "
                  # margin is only meaningful where the real cost was recorded
                  "COUNT(cost_uah) AS priced, "
                  "COALESCE(SUM(CAST(cost_uah AS REAL)), 0) AS cost, "
                  "COALESCE(SUM(CASE WHEN cost_uah IS NOT NULL THEN CAST(price AS REAL) END), 0) "
                  "AS priced_revenue FROM orders")
        conditions, values = [], []
        if statuses:
            conditions.append(f"status IN ({', '.join('?' * len(statuses))})")
            values.extend(statuses)
        if cutoff:
            conditions.append("created_at >= ?")
            values.append(cutoff)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        cursor = await connection.execute(totals + where, values)
        row = await cursor.fetchone()

        return {"users": users, "by_status": by_status, "orders": row["orders"],
                "revenue": row["revenue"], "stars": row["stars"],
                "priced": row["priced"], "cost": row["cost"],
                "priced_revenue": row["priced_revenue"]}


async def orders_by_status(statuses: tuple[str, ...]) -> list[Order]:
    placeholders = ", ".join("?" * len(statuses))
    async with connect() as connection:
        cursor = await connection.execute(
            f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY id", statuses)
        return [Order.from_row(row) for row in await cursor.fetchall()]


async def profile_stats(user_id: int) -> tuple[int, int]:
    async with connect() as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(quantity), 0) AS stars FROM orders "
            "WHERE user_id = ? AND status IN ('paid', 'delivered') AND product = 'stars'", (user_id,))
        row = await cursor.fetchone()
        return row["orders"], row["stars"]
