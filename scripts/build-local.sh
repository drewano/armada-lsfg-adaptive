#!/usr/bin/env bash
# Build the Armada LSFG Adaptive plugin zip locally.
#
#   ./scripts/build-local.sh [--skip-backend]
#
# Steps:
#   1. frontend: pnpm install + rollup build -> dist/index.js
#   2. backend:  docker (linux/arm64) builds the lsfg-vk layer -> bin/
#   3. package:  assemble <name>-<version>.zip in the Decky plugin layout
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PLUGIN_NAME="ArmadaLSFGAdaptive"
VERSION="$(python3 -c "import json;print(json.load(open('package.json'))['version'])")"
SKIP_BACKEND="${1:-}"

echo "==> [1/3] frontend build"
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
pnpm run build
[ -f dist/index.js ] || { echo "dist/index.js missing" >&2; exit 1; }

if [ "$SKIP_BACKEND" != "--skip-backend" ]; then
  echo "==> [2/3] backend build (linux/arm64 docker)"
  docker build --platform linux/arm64 -t armada-lsfg-backend ./backend
  rm -rf bin
  mkdir -p bin backend/out
  docker run --rm -v "$ROOT/backend/out:/backend/out" armada-lsfg-backend
  cp backend/out/* bin/
fi
[ -f bin/liblsfg-vk-layer.so ] || { echo "bin/liblsfg-vk-layer.so missing (backend not built?)" >&2; exit 1; }

echo "==> [3/3] packaging ${PLUGIN_NAME}-${VERSION}.zip"
STAGING="$(mktemp -d)/${PLUGIN_NAME}"
mkdir -p "$STAGING"
rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '*.map' dist/ "$STAGING/dist/"
mkdir -p "$STAGING/bin" "$STAGING/py_modules"
rsync -a bin/ "$STAGING/bin/"
rsync -a --exclude '__pycache__' --exclude '*.pyc' py_modules/ "$STAGING/py_modules/"
cp main.py package.json plugin.json LICENSE README.md THIRD_PARTY_NOTICES.md "$STAGING/"
# pnpm-lock is not needed at runtime

OUT_DIR="${OUT_DIR:-out}"
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip"
(cd "$(dirname "$STAGING")" && zip -qr "$ROOT/$OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip" "$PLUGIN_NAME")
if command -v sha256sum >/dev/null; then sha256sum "$OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip"; else shasum -a 256 "$OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip"; fi | tee "$OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip.sha256"

echo "==> verifying zip layout"
python3 - "$OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip" <<'PY'
import json, sys, zipfile

zf = zipfile.ZipFile(sys.argv[1])
names = zf.namelist()
name = "ArmadaLSFGAdaptive"
required = [
    f"{name}/dist/index.js", f"{name}/main.py", f"{name}/plugin.json",
    f"{name}/package.json", f"{name}/LICENSE", f"{name}/bin/liblsfg-vk-layer.so",
    f"{name}/bin/layer-info.json", f"{name}/py_modules/lsfg/config.py",
]
missing = [r for r in required if r not in names]
assert not missing, f"missing from zip: {missing}"
plugin = json.loads(zf.read(f"{name}/plugin.json"))
package = json.loads(zf.read(f"{name}/package.json"))
assert plugin.get("name") and plugin.get("author"), "plugin.json incomplete"
print("zip OK:", plugin["name"], package["version"])
PY
echo "==> done: $OUT_DIR/${PLUGIN_NAME}-${VERSION}.zip"
