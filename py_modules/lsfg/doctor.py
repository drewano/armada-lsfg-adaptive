"""On-device diagnostics for the LSFG-VK setup.

Answers the questions that matter when frame generation silently does
nothing:
- is the Vulkan manifest present and pointing at a real library?
- does the bundled library's glibc requirement fit this system's glibc?
  (the plugin's Python may run under FEX, so we parse the real aarch64
  libc instead of trusting os.confstr)
- does the engine's own CLI accept the generated conf.toml?
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import armada as armada_mod
from .layer import elf_arch as _elf_arch

_GLIBC_RE = re.compile(rb"GLIBC_([0-9]+\.[0-9]+)")


def _glibc_key(v: bytes) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(b"."))


def glibc_requirement(binary: Path) -> str | None:
    """Highest GLIBC_x.y symbol version a binary references."""
    try:
        data = Path(binary).read_bytes()
    except OSError:
        return None
    found = _GLIBC_RE.findall(data)
    if not found:
        return None
    best = max(found, key=_glibc_key)
    return best.decode()


def system_glibc() -> str | None:
    """Version of the native (aarch64) libc, from its exported symbols.

    Parsing the ELF beats os.confstr(): the plugin Python may be an x86_64
    binary under FEX and report the emulated guest glibc instead.
    """
    for loader, _ in armada_mod._ELF_LOADERS:
        ld = Path(loader)
        if not ld.is_file():
            continue
        libc = ld.parent / "libc.so.6"
        if libc.is_file():
            return glibc_requirement(libc)
    for cand in ("/lib/libc.so.6", "/usr/lib/libc.so.6"):
        if Path(cand).is_file():
            return glibc_requirement(Path(cand))
    return None


def _version_lte(a: str | None, b: str | None) -> bool | None:
    if a is None or b is None:
        return None
    ka = tuple(int(x) for x in a.split("."))
    kb = tuple(int(x) for x in b.split("."))
    return ka <= kb


def run_doctor(layer_manager, conf_path: Path, bin_dir: Path) -> dict:
    """Collect every diagnostic in one structured dict (JSON-serializable)."""
    out: dict = {"host_arch": armada_mod.host_arch()}

    # manifest + library
    manifest = layer_manager.manifest_path
    manifest_info: dict = {"exists": manifest.is_file(), "path": str(manifest)}
    if manifest.is_file():
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
            layer = doc.get("layer", {})
            lib = Path(str(layer.get("library_path", "")))
            manifest_info.update({
                "layer_name": layer.get("name"),
                "library_path": str(lib),
                "lib_exists": lib.is_file(),
                "lib_readable": lib.is_file() and lib.stat().st_size > 0,
                "has_enable_environment": bool(layer.get("enable_environment")),
            })
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            manifest_info["error"] = str(exc)
    out["manifest"] = manifest_info

    # architecture
    lib_path = layer_manager.installed_lib
    out["arch"] = {
        "lib": _elf_arch(lib_path),
        "expected": armada_mod.host_arch(),
        "lib_path": str(lib_path) if lib_path.is_file() else None,
    }
    out["arch"]["ok"] = out["arch"]["lib"] == out["arch"]["expected"]

    # glibc compatibility (library + bundled CLI)
    system = system_glibc()
    glibc: dict = {"system": system}
    for label, binary in (("layer", lib_path),):
        if binary.is_file():
            need = glibc_requirement(binary)
            glibc[f"{label}_needs"] = need
            glibc[f"{label}_ok"] = _version_lte(need, system)
    cli = Path(bin_dir) / "lsfg-vk-cli"
    if cli.is_file():
        need = glibc_requirement(cli)
        glibc["cli_needs"] = need
        glibc["cli_ok"] = _version_lte(need, system)
    out["glibc"] = glibc

    # engine CLI validation of conf.toml
    cli_info: dict = {"available": cli.is_file(), "path": str(cli)}
    if cli.is_file() and Path(conf_path).is_file():
        try:
            result = subprocess.run(
                [str(cli), "validate", "-c", str(conf_path)],
                capture_output=True, text=True, timeout=15,
            )
            cli_info.update({
                "returncode": result.returncode,
                "output": (result.stdout + result.stderr).strip()[:2000],
            })
        except (OSError, subprocess.SubprocessError) as exc:
            cli_info["error"] = str(exc)
    out["cli"] = cli_info
    return out
