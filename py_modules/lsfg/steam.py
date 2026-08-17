"""Steam library scanning: find installed games and their executables.

Only reads Steam files (libraryfolders.vdf, appmanifest_*.acf) and game
directories. Never writes anything to Steam.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

LOSSLESS_APPID = "993090"
LOSSLESS_INSTALLDIR = "Lossless Scaling"
LOSSLESS_DLL_NAME = "Lossless.dll"

STEAM_ROOT_CANDIDATES = (
    ".steam/steam",
    ".steam/root",
    ".local/share/Steam",
)

# directory/file name fragments that never hold the real game executable
IGNORE_TOKENS = (
    "redist", "vcredist", "dxvk", "directx", "launcher", "crash", "unity",
    "eos", "easyanti", "anti-cheat", "anticheat", "3rd", "third", "plugin",
    "tool", "benchmark", "debug", "symbols", "steam_api", "gamingservices",
    "overlay", "nvngx", "dlss",
)

EXE_EXTENSIONS = (".exe", ".sh")


class VdfError(Exception):
    pass


def parse_vdf(text: str) -> dict:
    """Minimal Valve Data Format parser (quoted keys and values only)."""
    tokens = [
        m.group(1) if m.group(1) is not None else m.group(0)
        for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|\{|\}', text)
    ]
    pos = 0

    def parse_map() -> dict:
        nonlocal pos
        result: dict = {}
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "{":
                pos += 1
                continue
            if tok == "}":
                pos += 1
                return result
            key = tok
            pos += 1
            if pos >= len(tokens):
                raise VdfError(f"unexpected EOF after key {key!r}")
            nxt = tokens[pos]
            if nxt == "{":
                pos += 1
                result[key] = parse_map()
            elif nxt == "}":
                # key with no value; tolerate
                result[key] = ""
            else:
                result[key] = nxt
                pos += 1
        return result

    doc = parse_map()
    return doc if isinstance(doc, dict) else {}


def steam_roots(user_home: Path) -> list[Path]:
    """All Steam roots that exist for this user."""
    home = Path(user_home)
    roots: list[Path] = []
    for cand in STEAM_ROOT_CANDIDATES:
        root = home / cand
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def library_folders(steam_root: Path) -> list[Path]:
    """Parse libraryfolders.vdf and return library paths that exist."""
    vdf_paths = [
        Path(steam_root) / "steamapps" / "libraryfolders.vdf",
        Path(steam_root) / "config" / "libraryfolders.vdf",
    ]
    doc: dict = {}
    for vdf_path in vdf_paths:
        if vdf_path.is_file():
            try:
                doc = parse_vdf(vdf_path.read_text(encoding="utf-8", errors="replace"))
                break
            except (VdfError, OSError):
                continue
    folders: list[Path] = []
    entries = doc.get("libraryfolders", {})
    if isinstance(entries, dict):
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not path:
                continue
            p = Path(path)
            if (p / "steamapps").is_dir() and p not in folders:
                folders.append(p)
    if not folders and (Path(steam_root) / "steamapps").is_dir():
        folders.append(Path(steam_root))
    return folders


def parse_manifest(text: str) -> dict | None:
    """Extract appid/name/installdir from an appmanifest_*.acf file."""
    try:
        doc = parse_vdf(text)
    except VdfError:
        return None
    state = doc.get("AppState")
    if not isinstance(state, dict):
        return None
    appid = str(state.get("appid", "")).strip('"')
    name = str(state.get("name", "")).strip('"')
    installdir = str(state.get("installdir", "")).strip('"')
    if not appid or not installdir:
        return None
    return {"appid": appid, "name": name, "installdir": installdir}


def _ignored(name: str) -> bool:
    lowered = name.lower()
    return any(tok in lowered for tok in IGNORE_TOKENS)


def discover_executables(game_dir: Path, limit: int = 40) -> list[dict]:
    """Walk a game directory and return candidate executables.

    Each candidate: {"path": relative path, "size": bytes}. Sorted by
    preference (name match with the game dir first, then size).
    """
    game_dir = Path(game_dir)
    if not game_dir.is_dir():
        return []
    dir_base = game_dir.name.lower().replace(" ", "")
    candidates: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(game_dir):
        dirnames[:] = [d for d in dirnames if not _ignored(d)]
        for filename in filenames:
            if not filename.lower().endswith(EXE_EXTENSIONS):
                continue
            if _ignored(filename):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), game_dir)
            try:
                size = os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                size = 0
            stem = Path(filename).stem.lower().replace(" ", "")
            name_bonus = 1 if stem == dir_base else 0
            candidates.append({"path": rel, "size": size, "name_bonus": name_bonus})
            if len(candidates) >= limit:
                break
    candidates.sort(key=lambda c: (-c["name_bonus"], -c["size"], c["path"]))
    return [{"path": c["path"], "size": c["size"]} for c in candidates]


def scan_libraries(user_home: Path) -> dict:
    """Full scan: games + Lossless.dll location.

    Returns {"games": [...], "lossless_dll": str | None}.
    """
    games: list[dict] = []
    seen_appids: set[str] = set()
    lossless_dll: str | None = None

    for root in steam_roots(user_home):
        for library in library_folders(root):
            apps_dir = library / "steamapps"
            # Lossless.dll lookup
            dll = apps_dir / "common" / LOSSLESS_INSTALLDIR / LOSSLESS_DLL_NAME
            if dll.is_file():
                lossless_dll = str(dll)

            for manifest_path in apps_dir.glob("appmanifest_*.acf"):
                try:
                    info = parse_manifest(
                        manifest_path.read_text(encoding="utf-8", errors="replace")
                    )
                except OSError:
                    continue
                if not info or info["appid"] in seen_appids:
                    continue
                seen_appids.add(info["appid"])
                if info["appid"] == LOSSLESS_APPID:
                    continue
                game_dir = apps_dir / "common" / info["installdir"]
                exes = discover_executables(game_dir)
                games.append({
                    "appid": info["appid"],
                    "name": info["name"],
                    "installdir": info["installdir"],
                    "library": str(library),
                    "executables": exes,
                    "recommended": exes[0]["path"] if exes else None,
                })
    games.sort(key=lambda g: g["name"].lower())
    return {"games": games, "lossless_dll": lossless_dll}
