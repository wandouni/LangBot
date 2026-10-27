#!/usr/bin/env bash
# Save a locally built image, copy it to the production host and load it.
#
# Usage:
#   ./deploy/prod/ship-image.sh [image-tag]
#
# Environment:
#   DEPLOY_HOST  default jj@192.168.31.66
#   DEPLOY_DIR   default /opt/langbot
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="$REPO_ROOT/deploy/prod/dist"
DEPLOY_HOST="${DEPLOY_HOST:-jj@192.168.31.66}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/langbot}"

IMAGE="${1:-}"
if [ -z "$IMAGE" ] && [ -f "$REPO_ROOT/deploy/prod/.last-image" ]; then
    IMAGE="$(cat "$REPO_ROOT/deploy/prod/.last-image")"
fi
if [ -z "$IMAGE" ]; then
    echo "usage: $0 <image-tag>" >&2
    exit 1
fi

docker image inspect "$IMAGE" >/dev/null

IMAGE_PLATFORM="$(docker image inspect "$IMAGE" --format '{{.Os}}/{{.Architecture}}')"
if [ "$IMAGE_PLATFORM" != "linux/amd64" ]; then
    echo "error: ${IMAGE} is ${IMAGE_PLATFORM}, expected linux/amd64" >&2
    exit 1
fi

SAFE_NAME="$(printf '%s' "$IMAGE" | tr '/:' '__')"
ARCHIVE="$DIST_DIR/${SAFE_NAME}.tar.zst"
mkdir -p "$DIST_DIR"

echo "==> saving ${IMAGE}"
docker save "$IMAGE" | zstd -T0 -3 -f -o "$ARCHIVE"

if command -v sha256sum >/dev/null 2>&1; then
    LOCAL_HASH="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
else
    LOCAL_HASH="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
fi

ARCHIVE_SIZE="$(du -h "$ARCHIVE" | awk '{print $1}')"
echo "==> archive ${ARCHIVE} (${ARCHIVE_SIZE}) sha256=${LOCAL_HASH}"

REMOTE_ARCHIVE="${DEPLOY_DIR}/images/$(basename "$ARCHIVE")"

echo "==> copying to ${DEPLOY_HOST}:${DEPLOY_DIR}/images"
ssh "$DEPLOY_HOST" "mkdir -p '${DEPLOY_DIR}/images'"
scp "$ARCHIVE" "${DEPLOY_HOST}:${REMOTE_ARCHIVE}"

REMOTE_HASH="$(ssh "$DEPLOY_HOST" "sha256sum '${REMOTE_ARCHIVE}' | awk '{print \$1}'")"
if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    echo "error: checksum mismatch (local ${LOCAL_HASH}, remote ${REMOTE_HASH})" >&2
    exit 1
fi
echo "==> checksum verified"

echo "==> loading image on ${DEPLOY_HOST}"
ssh "$DEPLOY_HOST" "zstd -dc '${REMOTE_ARCHIVE}' | sudo docker load"
ssh "$DEPLOY_HOST" "sudo docker image inspect '${IMAGE}' --format 'loaded: {{.Id}} created={{.Created}}'"

echo "==> shipped ${IMAGE}"
echo "    rollback tags on the host:"
ssh "$DEPLOY_HOST" "sudo docker image ls --format '{{.Repository}}:{{.Tag}} {{.CreatedSince}}' | grep '^langbot:' || true"
