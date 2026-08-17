#!/usr/bin/env bash
# Build the lsfg-vk Vulkan layer and emit artifacts to /engine/out:
#   - liblsfg-vk-layer.so   (the layer library)
#   - layer-info.json       (metadata consumed by the plugin's layer manager)
set -euo pipefail

: "${LSFG_SOURCE:=experimental}"
EXPERIMENTAL_REPO="${EXPERIMENTAL_REPO:-https://github.com/eugeniosegala/lsfg-vk-experimental}"
ZENSENSHI_REPO="${ZENSENSHI_REPO:-https://github.com/Zensenshi/lsfg-vk-odin2-armada}"
: "${LSFG_REF:=276030d4925c40038a61ecd66bd49ce777faec8c}"
: "${LSFG_ZENSENSHI_REF:=main}"

case "$LSFG_SOURCE" in
  experimental)
    REPO="$EXPERIMENTAL_REPO"; REF="$LSFG_REF"
    ADAPTIVE=true; DEFAULT_LAYER_NAME="VK_LAYER_LSFGVK_experimental_frame_generation" ;;
  zensenshi)
    REPO="$ZENSENSHI_REPO"; REF="$LSFG_ZENSENSHI_REF"
    ADAPTIVE=false; DEFAULT_LAYER_NAME="VK_LAYER_LSFGVK_frame_generation" ;;
  *)
    echo "unknown LSFG_SOURCE: $LSFG_SOURCE (expected experimental|zensenshi)" >&2; exit 1 ;;
esac

SRC=/work/src
OUT=/engine/out
mkdir -p "$SRC" "$OUT"

SLUG="${REPO#https://github.com/}"
echo "==> fetching $SLUG @ $REF"
curl -fsSL "https://codeload.github.com/${SLUG}/tar.gz/${REF}" -o /work/src.tar.gz
tar -xzf /work/src.tar.gz -C "$SRC" --strip-components=1

VERSION="$(cat "$SRC/VERSION" 2>/dev/null | tr -d '[:space:]' || true)"
[ -n "$VERSION" ] || VERSION="git-${REF:0:12}"

echo "==> building (version $VERSION)"
cmake -S "$SRC" -B /work/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF \
  -DLSFGVK_BUILD_UI=OFF \
  -DLSFGVK_BUILD_CLI=OFF
cmake --build /work/build --parallel "$(nproc)"

LAYER_LIB="$(find /work/build \( -name 'liblsfg-vk-layer.so' -o -name 'liblsfgVkLayer.so' \) -type f | head -n1 || true)"
if [ -z "$LAYER_LIB" ]; then
  echo "FATAL: layer library not found in build output" >&2
  find /work/build -name '*.so' >&2 || true
  exit 1
fi
echo "==> built $LAYER_LIB"

cp "$LAYER_LIB" "$OUT/$(basename "$LAYER_LIB")"

echo "==> writing layer-info.json"
LSFG_SOURCE="$LSFG_SOURCE" VERSION="$VERSION" \
LIB_NAME="$(basename "$LAYER_LIB")" BUILD_DIR="/work/build" \
DEFAULT_LAYER_NAME="$DEFAULT_LAYER_NAME" ADAPTIVE="$ADAPTIVE" \
python3 - <<'PY'
import json, os, pathlib, struct

build_dir = pathlib.Path(os.environ["BUILD_DIR"])
layer_name = os.environ["DEFAULT_LAYER_NAME"]
api_version = "1.3.0"

# prefer values straight from the engine's generated manifest when present
manifests = sorted(build_dir.rglob("VkLayer_*.json"))
for manifest in manifests:
    try:
        doc = json.loads(manifest.read_text())
        layer = doc.get("layer", {})
        if layer.get("name"):
            layer_name = layer["name"]
            api_version = layer.get("api_version", api_version)
            break
    except (json.JSONDecodeError, OSError):
        continue

lib = pathlib.Path("/engine/out") / os.environ["LIB_NAME"]
with open(lib, "rb") as fh:
    header = fh.read(20)
if header[:4] != b"\x7fELF":
    raise SystemExit("output is not an ELF file")
(machine,) = struct.unpack("<H", header[18:20])
if machine != 183:  # EM_AARCH64
    raise SystemExit(f"output is not aarch64 (e_machine={machine})")

info = {
    "layer_name": layer_name,
    "lib": os.environ["LIB_NAME"],
    "version": os.environ["VERSION"],
    "source": os.environ["LSFG_SOURCE"],
    "capabilities": {"adaptive": os.environ["ADAPTIVE"] == "true"},
    "description": "LSFG-VK frame generation layer (Armada LSFG Adaptive build)",
    "api_version": api_version,
    "implementation_version": "2",
}
(pathlib.Path("/engine/out") / "layer-info.json").write_text(json.dumps(info, indent=2))
print(json.dumps(info, indent=2))
PY

echo "==> done"
ls -la "$OUT"
