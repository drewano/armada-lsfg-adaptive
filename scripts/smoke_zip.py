#!/usr/bin/env python3
"""Smoke test: run the exact code shipped in a plugin zip.

Usage: smoke_zip.py <path-to-zip> [zip-inner-dir-name]

Unzips the plugin, injects a stub `decky` module, imports main.py from the
archive, and drives the critical server methods end to end.
"""
import asyncio
import json
import logging
import struct
import sys
import tempfile
import types
import zipfile
from pathlib import Path


def make_elf(path: Path) -> None:
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 1
    struct.pack_into("<H", header, 18, 183)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header))


def main() -> int:
    zip_path = Path(sys.argv[1])
    inner = sys.argv[2] if len(sys.argv) > 2 else "ArmadaLSFGAdaptive"
    tmp = Path(tempfile.mkdtemp(prefix="lsfg-smoke-"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    plugin_dir = tmp / inner
    assert (plugin_dir / "main.py").is_file(), "main.py missing from zip"

    # fake bundled engine + fake steam so install/scan paths run
    make_elf(plugin_dir / "bin" / "liblsfg-vk-layer.so")
    info = {
        "layer_name": "VK_LAYER_LSFGVK_experimental_frame_generation",
        "lib": "liblsfg-vk-layer.so",
        "version": "smoke",
        "source": "experimental",
        "capabilities": {"adaptive": True},
        "description": "smoke", "api_version": "1.4.328",
        "implementation_version": "2",
    }
    (plugin_dir / "bin" / "layer-info.json").write_text(json.dumps(info))

    home = tmp / "home"
    decky = types.ModuleType("decky")
    decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp / "settings")
    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp / "data")
    decky.DECKY_PLUGIN_LOG_DIR = str(tmp / "logs")
    decky.DECKY_PLUGIN_DIR = str(plugin_dir)
    decky.DECKY_PLUGIN_VERSION = "smoke"
    decky.DECKY_PLUGIN_NAME = "Armada LSFG Adaptive"
    decky.DECKY_USER_HOME = str(home)
    decky.logger = logging.getLogger("smoke")

    async def emit(*a):
        pass

    decky.emit = emit
    sys.modules["decky"] = decky
    sys.path.insert(0, str(plugin_dir / "py_modules"))
    sys.path.insert(0, str(plugin_dir))

    import main as main_mod  # noqa: E402  (the code exactly as shipped)

    plugin = main_mod.Plugin()
    asyncio.run(plugin._main())

    checks = []
    checks.append(("install_layer", asyncio.run(plugin.install_layer())))
    # fake steam library with a game + Lossless.dll
    steam = home / ".steam" / "steam" / "steamapps"
    game_dir = steam / "common" / "Demo Game" / "bin"
    game_dir.mkdir(parents=True)
    (game_dir / "DemoGame.exe").write_bytes(b"x" * 100)
    ls = steam / "common" / "Lossless Scaling"
    ls.mkdir(parents=True)
    (ls / "Lossless.dll").write_bytes(b"dll")
    (steam / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % (home / ".steam" / "steam")
    )
    (steam / "appmanifest_12345.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"12345"\n\t"name"\t\t"Demo Game"\n'
        '\t"installdir"\t\t"Demo Game"\n}\n'
    )

    checks.append(("refresh_all", asyncio.run(plugin.refresh_all())))
    checks.append(("add_steam_game",
                   asyncio.run(plugin.add_steam_game("12345", "bin/DemoGame.exe", "Demo Game"))))
    checks.append(("set_profile_target_fps",
                   asyncio.run(plugin.set_profile_target_fps("demogame.exe", 120))))
    checks.append(("set_profile_adaptive",
                   asyncio.run(plugin.set_profile_adaptive("demogame.exe", True))))
    checks.append(("get_status", asyncio.run(plugin.get_status())))
    checks.append(("run_doctor", asyncio.run(plugin.run_doctor())))
    checks.append(("get_profiles", asyncio.run(plugin.get_profiles())))
    checks.append(("get_dashboard_state", asyncio.run(plugin.get_dashboard_state())))
    checks.append(("get_active_profile_keys", asyncio.run(plugin.get_active_profile_keys())))

    failed = False
    for name, result in checks:
        json.dumps(result)  # transport-serializable
        if isinstance(result, dict) and "ok" in result and result["ok"] is not True:
            print(f"FAIL {name}: {result}")
            failed = True
        else:
            print(f"ok   {name}")

    status = dict(checks)["get_status"]
    assert status["layer"]["installed"]["manifest_ok"], "layer not installed by smoke"
    assert status["conf"]["valid"], "conf.toml invalid after smoke"
    assert status["dll"]["exists"], "Lossless.dll not discovered in smoke"
    conf = (home / ".config" / "lsfg-vk" / "conf.toml").read_text()
    assert "target_fps = 120" in conf and "DemoGame.exe" in conf

    print("SMOKE PASS" if not failed else "SMOKE FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
