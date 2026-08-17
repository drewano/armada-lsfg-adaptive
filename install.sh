#!/usr/bin/env bash
# Armada LSFG Adaptive - one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/andrewwassef/armada-lsfg-adaptive/main/install.sh | bash
#
# Downloads a release zip from GitHub, verifies its checksum, validates its
# layout, backs up any previous install, and atomically installs it into the
# Decky plugin folder. Only the final placement needs sudo (if the plugins
# dir is root-owned).
set -euo pipefail

REPO_SLUG="${ARMADA_LSFG_REPO:-drewano/armada-lsfg-adaptive}"
VERSION="${ARMADA_LSFG_VERSION:-latest}"
PLUGIN_NAME="ArmadaLSFGAdaptive"
PLUGINS_DIR="${ARMADA_LSFG_PLUGINS_DIR:-$HOME/homebrew/plugins}"
BACKUP_DIR="$HOME/${PLUGIN_NAME}-backups"

err() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "==> $*"; }

command -v curl >/dev/null || err "curl is required"
command -v python3 >/dev/null || err "python3 is required"
command -v unzip >/dev/null || err "unzip is required"

# ---------------------------------------------------------------- download

API="https://api.github.com/repos/${REPO_SLUG}/releases"
if [ "$VERSION" = "latest" ]; then
  log "resolving latest release"
  VERSION="$(curl -fsSL "$API/latest" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tag_name"])')"
fi
BASE_URL="https://github.com/${REPO_SLUG}/releases/download/${VERSION}"
ZIP="${PLUGIN_NAME}-${VERSION#v}.zip"
log "installing ${REPO_SLUG} ${VERSION}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$BASE_URL/$ZIP" -o "$TMP/$ZIP"
if curl -fsSL "$BASE_URL/$ZIP.sha256" -o "$TMP/$ZIP.sha256" 2>/dev/null; then
  log "verifying sha256"
  (cd "$TMP" && sha256sum --check --status "$ZIP.sha256" 2>/dev/null \
     || (cd "$TMP" && shasum -a 256 --check --status "$ZIP.sha256") \
     || err "checksum mismatch")
else
  log "no checksum published, skipping verification"
fi

# ---------------------------------------------------------------- validate

log "validating archive"
python3 - "$TMP/$ZIP" "$PLUGIN_NAME" <<'PY'
import json, sys, zipfile

zf = zipfile.ZipFile(sys.argv[1])
name = sys.argv[2]
top = f"{name}/"
for info in zf.infolist():
    path = info.filename
    if path.startswith("/") or ".." in path.split("/") or not path.startswith(top):
        raise SystemExit(f"unsafe entry: {path}")
    if info.is_dir():
        continue
    perm = info.external_attr >> 16
    if perm & 0o170000 == 0o120000:  # symlink
        raise SystemExit(f"symlinks not allowed: {path}")
required = [f"{name}/dist/index.js", f"{name}/main.py", f"{name}/plugin.json",
            f"{name}/package.json", f"{name}/LICENSE", f"{name}/py_modules/lsfg/config.py"]
missing = [r for r in required if r not in zf.namelist()]
if missing:
    raise SystemExit(f"missing files: {missing}")
plugin = json.loads(zf.read(f"{name}/plugin.json"))
package = json.loads(zf.read(f"{name}/package.json"))
assert plugin.get("name") and plugin.get("author") and package.get("version")
print(f"validated {plugin['name']} {package['version']}")
PY

# ---------------------------------------------------------------- install

log "installing into $PLUGINS_DIR/$PLUGIN_NAME"
mkdir -p "$PLUGINS_DIR"
if [ -d "$PLUGINS_DIR/$PLUGIN_NAME" ]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP="$BACKUP_DIR/${PLUGIN_NAME}-$(date +%Y%m%d-%H%M%S).zip"
  log "backing up current install to $BACKUP"
  (cd "$PLUGINS_DIR" && zip -qr "$BACKUP" "$PLUGIN_NAME")
fi

STAGE="$TMP/stage"
mkdir -p "$STAGE"
unzip -q "$TMP/$ZIP" -d "$STAGE"
SUDO=""
if [ "$(id -u)" != "0" ] && [ ! -w "$PLUGINS_DIR" ]; then
  SUDO="sudo"
  log "plugins dir needs elevated rights, requesting sudo"
fi
$SUDO rm -rf "$PLUGINS_DIR/$PLUGIN_NAME.new"
$SUDO cp -a "$STAGE/$PLUGIN_NAME" "$PLUGINS_DIR/$PLUGIN_NAME.new"
$SUDO rm -rf "$PLUGINS_DIR/$PLUGIN_NAME"
$SUDO mv "$PLUGINS_DIR/$PLUGIN_NAME.new" "$PLUGINS_DIR/$PLUGIN_NAME"

if command -v systemctl >/dev/null 2>&1; then
  log "restarting Decky plugin loader"
  $SUDO systemctl restart plugin_loader 2>/dev/null || log "could not restart plugin_loader (fine if Decky auto-detects)"
fi

log "done - open the Quick Access Menu > Armada LSFG Adaptive"
