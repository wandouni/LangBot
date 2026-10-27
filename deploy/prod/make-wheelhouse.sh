#!/usr/bin/env bash
# Build an offline wheelhouse plus a PEP 503 simple index for plugin deps.
#
# Usage (on a machine with internet and Docker):
#   ./deploy/prod/make-wheelhouse.sh [requirements-file] [output-dir]
#
# Defaults:
#   requirements: deploy/prod/plugin-requirements.txt
#   output:       deploy/prod/dist/wheelhouse
#
# The output directory is meant to be copied to the host and served by
# langbot-wheelhouse.service on port 8081.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REQ_FILE="${1:-${REPO_ROOT}/deploy/prod/plugin-requirements.txt}"
OUT_DIR="${2:-${REPO_ROOT}/deploy/prod/dist/wheelhouse}"

if [ ! -f "$REQ_FILE" ]; then
    echo "error: requirements file not found: ${REQ_FILE}" >&2
    exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/packages"

echo "==> downloading wheels for cp312 / manylinux2014_x86_64"
docker run --rm \
    --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "${REQ_FILE}:/req.txt:ro" \
    -v "${OUT_DIR}:/wheelhouse" \
    python:3.12-slim bash -c '
        set -euo pipefail
        python -m pip download \
            --requirement /req.txt \
            --dest /wheelhouse \
            --only-binary=:all: \
            --platform manylinux2014_x86_64 \
            --python-version 3.12 \
            --implementation cp \
            --abi cp312
    '

echo "==> generating PEP 503 simple index"
python3 - "$OUT_DIR" <<'PY'
import hashlib
import html
import pathlib
import re
import shutil
import sys

root = pathlib.Path(sys.argv[1])
packages_dir = root / "packages"
simple_dir = root / "simple"

for wheel in root.glob("*.whl"):
    shutil.move(str(wheel), packages_dir / wheel.name)

if not any(packages_dir.iterdir()):
    raise SystemExit("error: no wheels were downloaded")

def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

by_name: dict[str, list[pathlib.Path]] = {}
for wheel in sorted(packages_dir.glob("*.whl")):
    dist = wheel.name.split("-", 1)[0]
    by_name.setdefault(normalize(dist), []).append(wheel)

if simple_dir.exists():
    shutil.rmtree(simple_dir)

for name, wheels in sorted(by_name.items()):
    target = simple_dir / name
    target.mkdir(parents=True)
    links = []
    for wheel in wheels:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        href = f"../../packages/{wheel.name}#sha256={digest}"
        links.append(
            f'<a href="{html.escape(href, quote=True)}">{html.escape(wheel.name)}</a>'
        )
    (target / "index.html").write_text(
        "<!DOCTYPE html>\n<html><body>\n"
        + "\n".join(f"{link}<br/>" for link in links)
        + "\n</body></html>\n",
        encoding="utf-8",
    )

print(f"indexed {sum(len(v) for v in by_name.values())} wheels in {len(by_name)} packages")
PY

echo "==> wheelhouse ready: ${OUT_DIR}"
echo "    ship it with:"
echo "      tar -czf deploy/prod/dist/wheelhouse.tar.gz -C '${OUT_DIR}' ."
echo "      scp deploy/prod/dist/wheelhouse.tar.gz jj@192.168.31.66:/opt/langbot/"
