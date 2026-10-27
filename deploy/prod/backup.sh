#!/usr/bin/env bash
# Back up LangBot state on the production host.
#
# Run on the server from the deployment directory:
#   cd /opt/langbot && sudo ./backup.sh
#
# The stack is stopped briefly so SQLite and plugin data are captured in a
# consistent state. If it was running before the backup, it is started again.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="${BACKUP_DIR}/langbot-${STAMP}.tar.gz"
COMPOSE=(docker compose --env-file "${APP_DIR}/.env")

mkdir -p "$BACKUP_DIR"
cd "$APP_DIR"

if [ ! -f .env ]; then
    echo "error: ${APP_DIR}/.env not found" >&2
    exit 1
fi

RUNNING="$("${COMPOSE[@]}" ps --status running -q | wc -l | tr -d ' ')"
echo "==> stopping containers for a consistent snapshot (running: ${RUNNING})"
"${COMPOSE[@]}" stop

restart_stack() {
    if [ "${RUNNING}" -gt 0 ]; then
        echo "==> starting containers again"
        "${COMPOSE[@]}" start
    fi
}
trap restart_stack EXIT

echo "==> writing ${ARCHIVE}"
tar -czf "$ARCHIVE" data docker-compose.yaml .env
tar -tzf "$ARCHIVE" >/dev/null

echo "==> archive: $(du -h "$ARCHIVE" | awk '{print $1}')"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$ARCHIVE" | tee "${ARCHIVE}.sha256"
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'langbot-*.tar.gz' -mtime +"${KEEP_DAYS}" -print -delete

echo "==> done"
