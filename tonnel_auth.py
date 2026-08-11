"""Готовит tonnel_auth.json из «Copy as cURL».

    Telegram Web -> Mini App Tonnel -> DevTools -> Network -> запрос к gifts2.tonnel.network
    -> правой кнопкой -> Copy -> Copy as cURL

Дальше вставить скопированное в файл и скормить сюда:

    python tonnel_auth.py curl.txt
    pbpaste | python tonnel_auth.py          # прямо из буфера обмена на маке

Cloudflare привязывает cf_clearance к user-agent, поэтому из cURL берётся и он тоже —
подменить его на свой значит получить 403.
"""

import json
import re
import shlex
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "tonnel_auth.json"

# Заголовки, которые Cloudflare сверяет с отпечатком сессии.
KEEP = ("user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "accept-language")


def parse(curl: str) -> dict:
    # Переносы строк в скопированной команде мешают shlex, склеиваем их.
    tokens = shlex.split(curl.replace("\\\n", " ").replace("^\n", " "))

    headers, cookies, body = {}, {}, None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in ("-H", "--header"):
            index += 1
            name, _, value = tokens[index].partition(":")
            headers[name.strip().lower()] = value.strip()
        elif token in ("-b", "--cookie"):
            index += 1
            for pair in tokens[index].split(";"):
                name, _, value = pair.strip().partition("=")
                if name:
                    cookies[name] = value
        elif token in ("--data", "--data-raw", "-d", "--data-binary"):
            index += 1
            body = tokens[index]
        index += 1

    # Куки могут приехать и обычным заголовком Cookie.
    for pair in headers.pop("cookie", "").split(";"):
        name, _, value = pair.strip().partition("=")
        if name:
            cookies[name] = value

    auth = {
        "user_agent": headers.get("user-agent", ""),
        "cookies": cookies,
        "headers": {name: headers[name] for name in KEEP if name in headers and name != "user-agent"},
    }

    # user_auth — это initData Telegram; он лежит в теле запроса и нужен части методов.
    if body:
        try:
            auth["user_auth"] = json.loads(body).get("user_auth", "")
        except ValueError:
            match = re.search(r'"user_auth"\s*:\s*"([^"]*)"', body)
            auth["user_auth"] = match.group(1) if match else ""

    return auth


def main() -> int:
    raw = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()
    if "tonnel" not in raw:
        print("Это не похоже на запрос к Tonnel — в команде нет tonnel.network")
        return 1

    auth = parse(raw)
    if "cf_clearance" not in auth["cookies"]:
        print("ВНИМАНИЕ: в cURL нет куки cf_clearance — Cloudflare будет отвечать 403.")
        print("Скопируйте запрос, который в DevTools вернул 200, а не сам челлендж.")
        return 1

    OUT.write_text(json.dumps(auth, indent=2, ensure_ascii=False))
    OUT.chmod(0o600)
    print(f"{OUT.name} записан: куки {', '.join(auth['cookies'])}")
    print(f"user_auth: {'есть' if auth.get('user_auth') else 'нет (для флора не обязателен)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
