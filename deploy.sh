#!/usr/bin/env bash
# Выкатка на Oracle: коммит -> push -> pull на сервере -> рестарт.
#
#   ./deploy.sh "поправил цены на премиум"
#   ./deploy.sh                              # если уже закоммичено вручную
#
# Требует алиас `oracle` в ~/.ssh/config.

set -euo pipefail

SERVER=oracle
REMOTE_DIR='~/xar1zmashop'
SERVICE=xar1zma-shop

cd "$(dirname "$0")"

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

# Рестарт отдельной командой после pull: если pull упадёт, бот продолжит работать на старом коде.
ssh "$SERVER" "cd $REMOTE_DIR && git pull -q && sudo systemctl restart $SERVICE"
sleep 6

if ssh "$SERVER" "systemctl is-active --quiet $SERVICE"; then
    echo "бот перезапущен ✓"
    ssh "$SERVER" "sudo journalctl -u $SERVICE --since '-1min' --no-pager -o cat | tail -5"
else
    echo "БОТ НЕ ПОДНЯЛСЯ — логи:"
    ssh "$SERVER" "sudo journalctl -u $SERVICE -n 30 --no-pager -o cat"
    exit 1
fi
