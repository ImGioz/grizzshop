"""Каталог проектов для раздела «Ещё → Другие проекты».

Ссылки живут здесь, а не в texts.py: у каждой записи два языка подписи и один общий адрес,
и держать их рядом проще, чем синхронизировать два словаря при добавлении проекта.
"""

FOUNDER = "@grizzios"


def _item(username: str, uk: str, ru: str) -> dict:
    return {"username": username, "url": f"https://t.me/{username.lstrip('@')}",
            "label": {"uk": f"{username} — {uk}", "ru": f"{username} — {ru}"}}


CATEGORIES: dict[str, dict] = {
    "shops": {
        "title": {"uk": "🛍 Магазини", "ru": "🛍 Магазины"},
        "items": [
            _item("@nftgrizz", "NFT та зірки", "NFT и звёзды"),
            _item("@fiz_shop_grizz", "фіз. номери", "физ. номера"),
            _item("@grizzACCOUNT", "акаунти", "аккаунты"),
        ],
    },
    "services": {
        "title": {"uk": "🛠 Послуги", "ru": "🛠 Услуги"},
        "items": [
            _item("@grizz_designer", "аватарка та банер", "аватарка и баннер"),
            _item("@GRIZZmanager", "гарант угод", "гарант сделок"),
        ],
    },
    "chat": {
        "title": {"uk": "💬 Чат", "ru": "💬 Чат"},
        "items": [
            _item("@grizz_store_chat", "чат для продажу", "чат для продажи"),
        ],
    },
    "reviews": {
        "title": {"uk": "⭐ Відгуки", "ru": "⭐ Отзывы"},
        "items": [
            _item("@reviews_GRZ", "відгуки TG SHOP", "отзывы TG SHOP"),
            _item("@reviews_mngr", "відгуки по угодах", "отзывы по сделкам"),
            _item("@reviews_fiz", "відгуки по номерах", "отзывы по номерам"),
        ],
    },
    "safety": {
        "title": {"uk": "🛡 Безпека", "ru": "🛡 Безопасность"},
        "items": [
            _item("@scambazegrizz", "скам-база", "скам-база"),
        ],
    },
}


def title(key: str, language: str) -> str:
    return CATEGORIES[key]["title"].get(language, CATEGORIES[key]["title"]["ru"])


def items(key: str, language: str) -> list[tuple[str, str]]:
    """Пары (подпись, ссылка) для кнопок категории."""
    return [(item["label"].get(language, item["label"]["ru"]), item["url"])
            for item in CATEGORIES[key]["items"]]
