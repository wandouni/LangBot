#!/usr/bin/env bash
# Restart the local stack from the image recorded in deploy/local/.env.
#
#   ./deploy/local/deploy.sh        # LangBot only (normal code-change workflow)
#   ./deploy/local/deploy.sh --all  # whole stack, including gateway and SqlBot
#
# Run build-image.sh first when the working tree changed.
set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$LOCAL_DIR"

if [ ! -f .env ]; then
    echo "error: .env is missing; copy .env.example and fill it in" >&2
    exit 1
fi

# .env carries database, SSO, and API credentials; keep it owner-only.
chmod 600 .env 2>/dev/null || true

if [ "${1:-}" = "--all" ]; then
    docker compose --env-file .env up -d --remove-orphans --wait --wait-timeout 360
else
    docker compose --env-file .env up -d --no-deps --wait --wait-timeout 240 vocational-langbot-core
fi
