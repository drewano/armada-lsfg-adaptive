"""Vulkan implicit layer install / validation.

The plugin bundles the lsfg-vk shared library (aarch64) in its `bin/`
directory. `install()` copies it to a stable user-level location and writes
the Vulkan implicit layer manifest so the host Vulkan loader picks it up for
every Vulkan process; the layer itself decides via conf.toml `active_in`
matching whether to actually generate frames.

Layout:
    <install_root>/lib/<lib-name>.so          (copied from plugin bin/)
    <install_root>/layer-info.json            (copied from plugin bin/)
    <install_root>/installed-version          (plugin version marker)
    ~/.local/share/vulkan/implicit_layer.d/<layer_name>.json
"""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

INSTALL_ROOT_NAME = "armada-lsfg-adaptive"
VULKAN_LAYER_DIR = ".local/share/vulkan/implicit_layer.d"

ARCH_AARCH64 = "aarch64"
ARCH_X86_64 = "x86_64"
ARCH_ARM = "arm"
ARCH_X86 = "x86"
ARCH_RISCV64 = "riscv64"

_ELF_MACHINES = {
    183: ARCH_AARCH64,
    62: ARCH_X86_64,
    40: ARCH_ARM,
    3: ARCH_X86,
    243: ARCH_RISCV64,
}


class LayerError(Exception):
    pass


def elf_arch(path: Path) -> str | None:
    """Return the architecture of an ELF file by parsing its header."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(20)
    except OSError:
        return None
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return None
    endian = "<" if header[5] == 1 else ">"
    (machine,) = struct.unpack(endian + "H", header[18:20])
    return _ELF_MACHINES.get(machine, f"unknown({machine})")


def load_layer_info(bin_dir: Path) -> dict | None:
    """Read the layer-info.json shipped alongside the bundled .so."""
    info_path = Path(bin_dir) / "layer-info.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(info, dict) or not info.get("layer_name") or not info.get("lib"):
        return None
    return info


class LayerManager:
    def __init__(self, user_home: Path, bin_dir: Path, host_arch: str = ARCH_AARCH64):
        self.user_home = Path(user_home)
        self.bin_dir = Path(bin_dir)
        self.host_arch = host_arch
        self.install_root = self.user_home / ".local/share" / INSTALL_ROOT_NAME
        self.vulkan_layer_dir = self.user_home / VULKAN_LAYER_DIR

    # -- paths -------------------------------------------------------------

    @property
    def bundled_lib(self) -> Path:
        info = load_layer_info(self.bin_dir) or {}
        return self.bin_dir / info.get("lib", "liblsfg-vk-layer.so")

    @property
    def installed_lib(self) -> Path:
        info = load_layer_info(self.install_root) or load_layer_info(self.bin_dir) or {}
        return self.install_root / "lib" / info.get("lib", "liblsfg-vk-layer.so")

    @property
    def manifest_path(self) -> Path:
        info = load_layer_info(self.install_root) or load_layer_info(self.bin_dir) or {}
        return self.vulkan_layer_dir / f"{info.get('layer_name', 'VK_LAYER_LSFGVK_frame_generation')}.json"

    @property
    def version_marker(self) -> Path:
        return self.install_root / "installed-version"

    # -- status ------------------------------------------------------------

    def bundled_status(self) -> dict:
        info = load_layer_info(self.bin_dir)
        lib = self.bundled_lib
        arch = elf_arch(lib) if lib.is_file() else None
        return {
            "available": bool(info) and lib.is_file(),
            "layer_name": (info or {}).get("layer_name"),
            "version": (info or {}).get("version"),
            "source": (info or {}).get("source"),
            "capabilities": (info or {}).get("capabilities", {}),
            "arch": arch,
            "arch_ok": arch == self.host_arch,
            "path": str(lib) if lib.is_file() else None,
        }

    def status(self) -> dict:
        bundled = self.bundled_status()
        installed_info = load_layer_info(self.install_root)
        lib = self.installed_lib
        manifest = self.manifest_path
        manifest_ok = False
        if manifest.is_file():
            try:
                doc = json.loads(manifest.read_text(encoding="utf-8"))
                layer = doc.get("layer", {})
                manifest_ok = (
                    layer.get("name") == (installed_info or bundled).get("layer_name")
                    and Path(layer.get("library_path", "")) == lib.resolve()
                    and lib.is_file()
                )
            except (json.JSONDecodeError, OSError):
                manifest_ok = False
        try:
            installed_version = self.version_marker.read_text(encoding="utf-8").strip()
        except OSError:
            installed_version = None
        return {
            "bundled": bundled,
            "installed": {
                "lib_exists": lib.is_file(),
                "lib_path": str(lib) if lib.is_file() else None,
                "arch": elf_arch(lib) if lib.is_file() else None,
                "arch_ok": elf_arch(lib) == self.host_arch if lib.is_file() else False,
                "manifest_exists": manifest.is_file(),
                "manifest_path": str(manifest),
                "manifest_ok": manifest_ok,
                "version": installed_version,
                "needs_update": (
                    installed_version is not None
                    and bundled["available"]
                    and installed_version != bundled["version"]
                ),
                "capabilities": (installed_info or {}).get("capabilities", {}),
                "source": (installed_info or {}).get("source"),
            },
        }

    # -- install / uninstall -----------------------------------------------

    def install(self) -> dict:
        bundled = self.bundled_status()
        if not bundled["available"]:
            raise LayerError("no lsfg-vk library bundled in bin/")
        if not bundled["arch_ok"]:
            raise LayerError(
                f"bundled layer arch is {bundled['arch']}, expected {self.host_arch}"
            )
        info = load_layer_info(self.bin_dir) or {}

        lib_dst_dir = self.install_root / "lib"
        lib_dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.bundled_lib, lib_dst_dir / info["lib"])
        (self.install_root / "layer-info.json").write_text(
            json.dumps(info, indent=2), encoding="utf-8"
        )
        # marker tracks the engine version so plugin updates can detect a
        # stale installed layer
        self.version_marker.write_text(str(info.get("version", "")), encoding="utf-8")

        lib = self.install_root / "lib" / info["lib"]
        self.vulkan_layer_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "file_format_version": "1.2.0",
            "layer": {
                "name": info["layer_name"],
                "type": "GLOBAL",
                "library_path": str(lib.resolve()),
                "api_version": info.get("api_version", "1.3.0"),
                "implementation_version": str(info.get("implementation_version", "1")),
                "description": info.get("description", "LSFG-VK frame generation"),
                "disable_environment": {
                    "DISABLE_LSFGVK": "1",
                    "DISABLE_LSFGVK_EXPERIMENTAL": "1",
                },
            },
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)
        return self.status()

    def uninstall(self) -> None:
        """Remove the layer library + manifest. conf.toml is preserved."""
        manifest = self.manifest_path
        if self.install_root.is_dir():
            shutil.rmtree(self.install_root, ignore_errors=True)
        manifest.unlink(missing_ok=True)
        self.manifest_path.with_suffix(".json.tmp").unlink(missing_ok=True)
