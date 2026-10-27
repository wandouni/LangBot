#!/usr/bin/env bash
# Build the production image locally for linux/amd64.
#
# Usage:
#   ./deploy/prod/build-image.sh [image-tag]
#
# The default tag is langbot:<version>-<12-char-git-sha>, which is immutable and
# lets the same tag be reused as a rollback target.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(grep -m1 '^version = ' pyproject.toml | sed -E 's/^version = "(.*)"/\1/')"
if [ -z "$VERSION" ]; then
    echo "error: cannot read version from pyproject.toml" >&2
    exit 1
fi

SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short=12 HEAD)"
IMAGE="${1:-langbot:${VERSION}-${SHORT_SHA}}"
PLATFORM="${PLATFORM:-linux/amd64}"

WORKING_TREE="clean"
if ! git diff --quiet || ! git diff --cached --quiet; then
    WORKING_TREE="dirty"
    echo "warning: working tree is dirty; commit first so the tag identifies the deployed source" >&2
    echo "warning: pass an explicit tag if you rebuild the same commit: $0 <image-tag>" >&2
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

printf '%s\n' "$IMAGE" > "$REPO_ROOT/deploy/prod/.last-image"
echo "==> built ${IMAGE}"
echo "    next: ./deploy/prod/ship-image.sh ${IMAGE}"
