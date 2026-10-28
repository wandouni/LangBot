#!/usr/bin/env bash
# Save locally built images, copy them to the production host and load them.
#
# Usage:
#   ./deploy/prod/ship-image.sh [image-tag ...]
#
# With no arguments it ships the tags recorded by build-image.sh: LangBot, the
# portal gateway and, when it was built, SqlBot.
#
# Environment:
#   DEPLOY_HOST  default jj@192.168.31.66
#   DEPLOY_DIR   default /opt/langbot
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="$REPO_ROOT/deploy/prod/dist"
DEPLOY_HOST="${DEPLOY_HOST:-jj@192.168.31.66}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/langbot}"

IMAGES=("$@")
if [ ${#IMAGES[@]} -eq 0 ]; then
    for marker in .last-image .last-gateway-image .last-sqlbot-image; do
        marker_path="$REPO_ROOT/deploy/prod/$marker"
        if [ -f "$marker_path" ]; then
            IMAGES+=("$(cat "$marker_path")")
        fi
    done
fi
if [ ${#IMAGES[@]} -eq 0 ]; then
    echo "usage: $0 <image-tag> [...]" >&2
    echo "run build-image.sh first, or pass the tags explicitly" >&2
    exit 1
fi

ship_one() {
    local image="$1"
    local safe_name archive local_hash remote_archive remote_hash

    docker image inspect "$image" >/dev/null

    local image_platform
    image_platform="$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')"
    if [ "$image_platform" != "linux/amd64" ]; then
        echo "error: ${image} is ${image_platform}, expected linux/amd64" >&2
        exit 1
    fi

    safe_name="$(printf '%s' "$image" | tr '/:' '__')"
    archive="$DIST_DIR/${safe_name}.tar.zst"
    mkdir -p "$DIST_DIR"

    echo "==> saving ${image}"
    docker save "$image" | zstd -T0 -3 -f -o "$archive"

    if command -v sha256sum >/dev/null 2>&1; then
        local_hash="$(sha256sum "$archive" | awk '{print $1}')"
    else
        local_hash="$(shasum -a 256 "$archive" | awk '{print $1}')"
    fi

    local archive_size
    archive_size="$(du -h "$archive" | awk '{print $1}')"
    echo "==> archive ${archive} (${archive_size}) sha256=${local_hash}"

    remote_archive="${DEPLOY_DIR}/images/$(basename "$archive")"

    echo "==> copying to ${DEPLOY_HOST}:${DEPLOY_DIR}/images"
    ssh "$DEPLOY_HOST" "mkdir -p '${DEPLOY_DIR}/images'"
    scp "$archive" "${DEPLOY_HOST}:${remote_archive}"

    remote_hash="$(ssh "$DEPLOY_HOST" "sha256sum '${remote_archive}' | awk '{print \$1}'")"
    if [ "$local_hash" != "$remote_hash" ]; then
        echo "error: checksum mismatch for ${image} (local ${local_hash}, remote ${remote_hash})" >&2
        exit 1
    fi
    echo "==> checksum verified"

    echo "==> loading ${image} on ${DEPLOY_HOST}"
    ssh "$DEPLOY_HOST" "zstd -dc '${remote_archive}' | sudo docker load"
    ssh "$DEPLOY_HOST" "sudo docker image inspect '${image}' --format 'loaded: {{.Id}} created={{.Created}}'"

    echo "==> shipped ${image}"
}

for image in "${IMAGES[@]}"; do
    ship_one "$image"
done

echo "    rollback tags on the host:"
ssh "$DEPLOY_HOST" "sudo docker image ls --format '{{.Repository}}:{{.Tag}} {{.CreatedSince}}' | grep -E '^(langbot|sqlbot|langbot-portal-gateway):' || true"
