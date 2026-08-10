#!/usr/bin/env bash
# Забирает базу с сервера на макбук.
#
#   ./backup.sh
#
# Снимок делается на сервере через SQLite .backup, а не копированием файла: у живой базы
# копия файла может оказаться битой. Копии на самом сервере не защищают от потери сервера —
# именно поэтому база уезжает сюда.

set -euo pipefail

SERVER=shop
KEEP=30

cd "$(dirname "$0")"
mkdir -p backups

STAMP=$(date +%Y%m%d-%H%M)
ssh "$SERVER" '/root/backup-db.sh >/dev/null && ls -1t /root/backups/shop-*.db | head -1' > /tmp/.dbpath
REMOTE=$(cat /tmp/.dbpath); rm -f /tmp/.dbpath

scp -q "$SERVER:$REMOTE" "backups/shop-$STAMP.db"

# Битую копию лучше заметить сейчас, чем в день, когда она понадобится.
if ! sqlite3 "backups/shop-$STAMP.db" "pragma integrity_check;" 2>/dev/null | grep -q "^ok$"; then
    echo "ВНИМАНИЕ: копия не проходит проверку целостности"
    exit 1
fi

ORDERS=$(sqlite3 "backups/shop-$STAMP.db" "select count(*) from orders;")
echo "backups/shop-$STAMP.db — заказов: $ORDERS"

ls -1t backups/shop-*.db | tail -n +$((KEEP + 1)) | xargs -r rm --
