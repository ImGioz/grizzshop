#!/usr/bin/env bash
# Выкатка на Oracle: коммит -> push -> pull на сервере -> рестарт.
#
#   ./deploy.sh "поправил цены на премиум"
#   ./deploy.sh                              # если уже закоммичено вручную
#
# Требует алиас `shop` в ~/.ssh/config.

set -euo pipefail

SERVER=shop
REMOTE_DIR='~/xar1zmashop'
SERVICE=xar1zma-shop

cd "$(dirname "$0")"

# Свежая копия базы до выкатки: если новый код испортит данные, будет к чему откатиться.
./backup.sh

if [[ -n "$(git status --porcelain)" ]]; then
    if [[ $# -eq 0 ]]; then
        echo "Есть незакоммиченные изменения. Передай сообщение коммита:"
        echo "  ./deploy.sh \"что изменил\""
        git status --short
        exit 1
    fi
    git add -A
    git commit -q -m "$1"
    echo "коммит: $(git log --oneline -1)"
fi

git push -q origin main
echo "запушено"

# -A пробрасывает ключ с макбука: у сервера своего доступа к приватному репозиторию нет,
# и заводить его там не нужно — ключ живёт только здесь.
# Рестарт отдельной командой после pull: если pull упадёт, бот продолжит работать на старом коде.
ssh -A "$SERVER" "cd $REMOTE_DIR && git pull -q && systemctl restart $SERVICE"
sleep 6

if ssh "$SERVER" "systemctl is-active --quiet $SERVICE"; then
    echo "бот перезапущен ✓"
    ssh "$SERVER" "journalctl -u $SERVICE --since '-1min' --no-pager -o cat | tail -5"
else
    echo "БОТ НЕ ПОДНЯЛСЯ — логи:"
    ssh "$SERVER" "journalctl -u $SERVICE -n 30 --no-pager -o cat"
    exit 1
fi
