# Первичная настройка сервера

Разово, на чистом Ubuntu/Debian. Дальше выкатка идёт через `./deploy.sh "что изменил"`.

## 1. Доступ с макбука

В `~/.ssh/config`:

```
Host grizz
    HostName <IP сервера>
    User root
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

## 2. Пакеты

```bash
apt update
apt install -y python3 python3-venv python3-pip git
```

Нужен Python 3.11 или новее — в коде используется синтаксис `str | None`.

## 3. Код и окружение

Репозиторий приватный, у сервера своего доступа к нему нет — поэтому клонируем
с проброшенным ключом (`ssh -A grizz`), как это делает и `deploy.sh`.

```bash
git clone git@github.com:<аккаунт>/<репозиторий>.git ~/grizzshop
cd ~/grizzshop
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium      # квитанции Monobank открываются реальным браузером
venv/bin/playwright install-deps chromium # системные библиотеки для него
```

## 4. Файлы, которых нет в репозитории

Их переносим с макбука руками — это секреты, в git они не попадают:

```bash
scp .env grizz:~/grizzshop/.env
scp cookies.json grizz:~/grizzshop/cookies.json
scp created_wallets/wallets_data.txt grizz:~/grizzshop/created_wallets/wallets_data.txt
```

| файл | что внутри | без него |
|---|---|---|
| `.env` | токен бота, ID админов, реквизиты карты, ключ toncenter | бот не стартует |
| `cookies.json` | сессия fragment.com | не выдаются звёзды и Premium |
| `created_wallets/wallets_data.txt` | сид-фраза TON-кошелька магазина | нечем платить за выдачу |

Базу `shop.db` не копируем: она создастся пустой при первом запуске. Если нужно
перенести клиентов и заказы — скопировать файл тем же `scp` до старта сервиса.

## 5. Сервис

`/etc/systemd/system/grizzshop.service`:

```ini
[Unit]
Description=GrizzShop Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/grizzshop
ExecStart=/root/grizzshop/venv/bin/python shop_bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now grizzshop
systemctl status grizzshop
journalctl -u grizzshop -f
```

В логе при старте видно, какую базу бот открыл и кто у него админы:

```
shop bot started, база shop.db, админы: .env [...] + панель [...]
```

## 6. Проверка

- `/start` в боте — приходит меню картинкой с инлайн-кнопками;
- часы сервера синхронны (в логе `часы: часы синхронны з мережею`), иначе транзакции
  протухают на лету;
- toncenter принял ключ — иначе выдача упрётся в лимит анонимных запросов.
