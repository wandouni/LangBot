#!/usr/bin/env bash
# Build the local LangBot image from the current working tree (including
# uncommitted changes) and point deploy/local/.env at it.
#
# Usage:
#   ./deploy/local/build-image.sh [image-tag]
#
# The default tag embeds the 12-char git SHA plus a timestamp when the working
# tree is dirty, so every build is identifiable and a previous image can still
# be used as a rollback target.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_DIR="$REPO_ROOT/deploy/local"
cd "$REPO_ROOT"

VERSION="$(grep -m1 '^version = ' pyproject.toml | sed -E 's/^version = "(.*)"/\1/')"
if [ -z "$VERSION" ]; then
    echo "error: cannot read version from pyproject.toml" >&2
    exit 1
fi

SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short=12 HEAD)"
DIRTY_SUFFIX=""
WORKING_TREE="clean"
if [ -n "$(git status --porcelain)" ]; then
    WORKING_TREE="dirty"
    DIRTY_SUFFIX="-dirty-$(date +%Y%m%d%H%M%S)"
    echo "warning: working tree is dirty; building uncommitted changes into the image" >&2
fi

IMAGE="${1:-langbot:local-${VERSION}-${SHORT_SHA}${DIRTY_SUFFIX}}"
PLATFORM="${PLATFORM:-linux/amd64}"

if [ ! -f "$LOCAL_DIR/.env" ]; then
    echo "error: $LOCAL_DIR/.env is missing; copy .env.example and fill it in" >&2
    exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
    echo "error: docker buildx is not available" >&2
    exit 1
fi

echo "==> building ${IMAGE} (${PLATFORM}) from ${SHA} [${WORKING_TREE}]"
docker buildx build \
    --platform "$PLATFORM" \
    --build-arg "LANGBOT_BUILD_REVISION=${SHA}" \
    --label "org.opencontainers.image.revision=${SHA}" \
    --label "org.opencontainers.image.version=${VERSION}" \
    --label "org.langbot.working-tree=${WORKING_TREE}" \
    --tag "$IMAGE" \
    --load \
    --file Dockerfile \
    .

echo "==> verifying embedded revision"
docker run --rm --platform "$PLATFORM" --entrypoint /app/.venv/bin/python "$IMAGE" \
    -c 'import langbot._build_info as info; print("image revision:", info.CORE_REVISION)'

printf '%s\n' "$IMAGE" > "$LOCAL_DIR/.last-image"

GATEWAY_IMAGE="${PORTAL_GATEWAY_IMAGE:-langbot-portal-gateway:local-${SHORT_SHA}${DIRTY_SUFFIX}}"
echo "==> building ${GATEWAY_IMAGE} (${PLATFORM})"
docker buildx build \
    --platform "$PLATFORM" \
    --label "org.opencontainers.image.revision=${SHA}" \
    --tag "$GATEWAY_IMAGE" \
    --load \
    --file deploy/portal/Dockerfile \
    deploy/portal
printf '%s\n' "$GATEWAY_IMAGE" > "$LOCAL_DIR/.last-gateway-image"

# Rewrite only the image keys; keep every other local setting untouched.
update_env() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    grep -v "^${key}=" "$LOCAL_DIR/.env" > "$tmp" || true
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    mv "$tmp" "$LOCAL_DIR/.env"
}

update_env LANGBOT_IMAGE "$IMAGE"
update_env PORTAL_GATEWAY_IMAGE "$GATEWAY_IMAGE"

echo "==> built ${IMAGE}"
echo "==> built ${GATEWAY_IMAGE}"
echo "    next: ./deploy/local/deploy.sh        # restart LangBot only"
echo "          ./deploy/local/deploy.sh --all  # restart the whole stack"
