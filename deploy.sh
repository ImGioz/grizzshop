#!/usr/bin/env bash
# Выкатка GrizzShop: коммит -> push -> pull на сервере -> рестарт.
#
#   ./deploy.sh "поправил цены"
#   ./deploy.sh                    # если уже закоммичено вручную
#
# Требует алиас `grizz` в ~/.ssh/config и первичную настройку сервера — см. DEPLOY.md.

set -euo pipefail

SERVER=grizz
REMOTE=grizzshop
REMOTE_DIR='~/grizzshop'
SERVICE=grizzshop

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

# origin остаётся у Xar1zma, GrizzShop живёт в отдельном репозитории
git push -q "$REMOTE" main
echo "запушено в $REMOTE"

# -A пробрасывает ключ с макбука: у сервера своего доступа к приватному репозиторию нет.
# Рестарт отдельной командой после pull: если pull упадёт, бот продолжит работать на старом коде.
# pip перед рестартом: иначе коммит с новой зависимостью роняет бота при старте.
ssh -A "$SERVER" "cd $REMOTE_DIR && git pull -q && venv/bin/pip install -q -r requirements.txt && systemctl restart $SERVICE"
sleep 6

if ssh "$SERVER" "systemctl is-active --quiet $SERVICE"; then
    echo "бот перезапущен ✓"
    ssh "$SERVER" "journalctl -u $SERVICE --since '-1min' --no-pager -o cat | tail -5"
else
    echo "БОТ НЕ ПОДНЯЛСЯ — логи:"
    ssh "$SERVER" "journalctl -u $SERVICE -n 30 --no-pager -o cat"
    exit 1
fi
