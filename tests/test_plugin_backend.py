"""Comprehensive integration tests for the Plugin class with a stubbed decky.

Every server method the frontend can call is exercised here, its return
value is checked for JSON serializability (the WebSocket transport chokes
on anything else), and the full conf.toml round-trip is verified.
"""

import asyncio
import json
import logging
import struct
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EMIT_LOG: list[tuple] = []


def _install_decky_stub(tmp_path: Path) -> types.ModuleType:
    decky = types.ModuleType("decky")
    decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path / "settings")
    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path / "data")
    decky.DECKY_PLUGIN_LOG_DIR = str(tmp_path / "logs")
    decky.DECKY_PLUGIN_DIR = str(tmp_path / "plugin")
    decky.DECKY_PLUGIN_VERSION = "test"
    decky.DECKY_PLUGIN_NAME = "Armada LSFG Adaptive"
    decky.DECKY_USER_HOME = str(tmp_path / "home")

    async def emit(event_name, *args):
        EMIT_LOG.append((event_name,) + args)

    decky.emit = emit
    decky.logger = logging.getLogger("decky-stub")
    sys.modules["decky"] = decky
    return decky


def make_elf(path: Path) -> Path:
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 1
    struct.pack_into("<H", header, 18, 183)  # EM_AARCH64
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header))
    return path


def make_fake_bin(plugin_dir: Path) -> None:
    bin_dir = plugin_dir / "bin"
    make_elf(bin_dir / "liblsfg-vk-layer.so")
    (bin_dir / "layer-info.json").write_text(json.dumps({
        "layer_name": "VK_LAYER_LSFGVK_experimental_frame_generation",
        "lib": "liblsfg-vk-layer.so",
        "version": "test-engine-1",
        "source": "experimental",
        "capabilities": {"adaptive": True},
        "description": "test layer",
        "api_version": "1.4.328",
        "implementation_version": "2",
    }))


def make_fake_steam(home: Path) -> None:
    """Minimal Steam layout: one game + Lossless Scaling installed."""
    steam = home / ".steam" / "steam"
    apps = steam / "steamapps"
    apps.mkdir(parents=True)
    (apps / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % steam
    )
    (apps / "appmanifest_1091500.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"1091500"\n\t"name"\t\t"Cyberpunk 2077"\n'
        '\t"installdir"\t\t"Cyberpunk 2077"\n}\n'
    )
    game = apps / "common" / "Cyberpunk 2077" / "bin" / "x64"
    game.mkdir(parents=True)
    (game / "Cyberpunk2077.exe").write_bytes(b"x" * 100)
    ls = apps / "common" / "Lossless Scaling"
    ls.mkdir()
    (ls / "Lossless.dll").write_bytes(b"dll")


@pytest.fixture()
def plugin(tmp_path):
    EMIT_LOG.clear()
    decky = _install_decky_stub(tmp_path)
    sys.modules.pop("main", None)
    import main as main_mod

    p = main_mod.Plugin()
    asyncio.run(p._main())
    p.decky = decky
    yield p
    asyncio.run(p._unload())


def run(coro):
    return asyncio.run(coro)


def assert_jsonable(value, label=""):
    json.dumps(value, default=lambda o: pytest.fail(
        f"{label or 'value'} is not JSON serializable: {type(o)}"
    ))


# ------------------------------------------------------------ every method

def test_every_method_returns_jsonable_shapes(plugin, tmp_path):
    make_fake_bin(Path(plugin.decky.DECKY_PLUGIN_DIR))
    make_fake_steam(Path(plugin.decky.DECKY_USER_HOME))

    results = {
        "get_status": run(plugin.get_status()),
        "install_layer": run(plugin.install_layer()),
        "refresh_all": run(plugin.refresh_all()),
        "get_steam_games": run(plugin.get_steam_games()),
        "add_steam_game": run(plugin.add_steam_game("1091500", "bin/x64/Cyberpunk2077.exe", "Cyberpunk 2077")),
        "get_profiles": run(plugin.get_profiles()),
        "set_profile_enabled": run(plugin.set_profile_enabled("cyberpunk2077.exe", True)),
        "set_profile_adaptive": run(plugin.set_profile_adaptive("cyberpunk2077.exe", False)),
        "set_profile_target_fps": run(plugin.set_profile_target_fps("cyberpunk2077.exe", 120)),
        "set_profile_max_multiplier": run(plugin.set_profile_max_multiplier("cyberpunk2077.exe", 3)),
        "set_profile_multiplier": run(plugin.set_profile_multiplier("cyberpunk2077.exe", 2)),
        "set_profile_flow_scale": run(plugin.set_profile_flow_scale("cyberpunk2077.exe", 0.5)),
        "set_profile_performance_mode": run(plugin.set_profile_performance_mode("cyberpunk2077.exe", True)),
        "set_profile_stable_cadence": run(plugin.set_profile_stable_cadence("cyberpunk2077.exe", True)),
        "run_doctor": run(plugin.run_doctor()),
        "get_active_profile_keys": run(plugin.get_active_profile_keys()),
        "get_dashboard_state": run(plugin.get_dashboard_state()),
        "set_global_dll": run(plugin.set_global_dll("/tmp/does-not-matter.dll")),
        "uninstall_layer": run(plugin.uninstall_layer()),
    }
    for name, result in results.items():
        assert_jsonable(result, name)
    for name in ("install_layer", "refresh_all", "add_steam_game", "set_profile_enabled",
                 "set_profile_adaptive", "set_profile_target_fps", "set_profile_max_multiplier",
                 "set_profile_multiplier", "set_profile_flow_scale",
                 "set_profile_performance_mode", "set_profile_stable_cadence",
                 "set_global_dll", "uninstall_layer"):
        assert results[name].get("ok") is True, (name, results[name])


# ------------------------------------------------------------ layer flows

def test_install_and_uninstall_layer(plugin, tmp_path):
    home = Path(plugin.decky.DECKY_USER_HOME)
    make_fake_bin(Path(plugin.decky.DECKY_PLUGIN_DIR))

    res = run(plugin.install_layer())
    assert res["ok"]
    manifest = (home / ".local/share/vulkan/implicit_layer.d"
                / "VK_LAYER_LSFGVK_experimental_frame_generation.json")
    assert manifest.is_file()
    doc = json.loads(manifest.read_text())
    assert doc["layer"]["disable_environment"]["DISABLE_LSFGVK"] == "1"
    assert "enable_environment" not in doc["layer"]
    status = run(plugin.get_status())
    assert status["layer"]["installed"]["manifest_ok"] is True
    assert status["layer"]["installed"]["arch_ok"] is True

    # idempotent
    assert run(plugin.install_layer())["ok"]

    assert run(plugin.uninstall_layer())["ok"]
    status = run(plugin.get_status())
    assert status["layer"]["installed"]["lib_exists"] is False
    assert status["layer"]["installed"]["manifest_exists"] is False


def test_install_layer_without_bundle_fails_cleanly(plugin):
    res = run(plugin.install_layer())
    assert res["ok"] is False
    assert "bundled" in res["error"]


def test_uninstall_keeps_conf_toml(plugin, tmp_path):
    make_fake_bin(Path(plugin.decky.DECKY_PLUGIN_DIR))
    run(plugin.add_steam_game("1", "A.exe", "A"))
    conf = Path(plugin.user_home) / ".config/lsfg-vk/conf.toml"
    assert conf.exists()
    run(plugin.uninstall_layer())
    assert conf.exists()


# ------------------------------------------------------------ steam scan

def test_refresh_all_discovers_games_and_dll(plugin):
    make_fake_steam(Path(plugin.decky.DECKY_USER_HOME))
    res = run(plugin.refresh_all())
    assert res["ok"]
    assert len(res["games"]) == 1
    assert res["games"][0]["name"] == "Cyberpunk 2077"
    assert res["lossless_dll"].endswith("Lossless Scaling/Lossless.dll")
    # progress events were emitted through decky
    events = [e for e in EMIT_LOG if e[0] == "scan_progress"]
    assert events and events[-1][1] == 100
    # dll persisted into settings
    status = run(plugin.get_status())
    assert status["dll"]["exists"] is True
    assert "Lossless.dll" in status["dll"]["path"]


def test_get_steam_games_uses_cache(plugin):
    make_fake_steam(Path(plugin.decky.DECKY_USER_HOME))
    first = run(plugin.get_steam_games())
    assert first["cached"] is False
    second = run(plugin.get_steam_games())
    assert second["cached"] is True
    assert len(second["games"]) == 1


# ------------------------------------------------------------ conf handling

def test_corrupt_conf_recovered_by_add(plugin):
    conf = Path(plugin.user_home) / ".config/lsfg-vk/conf.toml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("this is [[[ not toml", encoding="utf-8")
    status = run(plugin.get_status())
    assert status["conf"]["valid"] is False

    res = run(plugin.add_steam_game("7", "B.exe", "B"))
    assert res["ok"]
    status = run(plugin.get_status())
    assert status["conf"]["valid"] is True
    assert "B.exe" in conf.read_text()


def test_foreign_profile_survives_mutations(plugin):
    conf = Path(plugin.user_home) / ".config/lsfg-vk/conf.toml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(
        '[[profile]]\nname = "Foreign"\nactive_in = ["foreign.exe"]\n'
        "multiplier = 3\nweird_key = [1, 2]\n",
        encoding="utf-8",
    )
    run(plugin.add_steam_game("5", "C.exe", "C"))
    run(plugin.set_profile_target_fps("c.exe", 90))
    text = conf.read_text(encoding="utf-8")
    assert "foreign.exe" in text and "weird_key" in text
    profiles = run(plugin.get_profiles())
    assert any(p.get("foreign") for p in profiles["foreign"])


def test_disabled_profile_removed_others_kept(plugin):
    run(plugin.add_steam_game("1", "A.exe", "A"))
    run(plugin.add_steam_game("2", "B.exe", "B"))
    run(plugin.set_profile_enabled("a.exe", False))
    text = (Path(plugin.user_home) / ".config/lsfg-vk/conf.toml").read_text()
    assert "A.exe" not in text
    assert "B.exe" in text
    # state survives: re-enable writes it back
    run(plugin.set_profile_enabled("a.exe", True))
    text = (Path(plugin.user_home) / ".config/lsfg-vk/conf.toml").read_text()
    assert "A.exe" in text


def test_case_insensitive_profile_keys(plugin):
    run(plugin.add_steam_game("9", "Game.EXE", "G"))
    assert run(plugin.set_profile_target_fps("GAME.exe", 90))["ok"]
    stored = {p["key"]: p for p in run(plugin.get_profiles())["profiles"]}
    assert stored["game.exe"]["target_fps"] == 90


def test_subpath_executable_valid(plugin):
    res = run(plugin.add_steam_game("10", "bin/x64/Game.exe", "Sub"))
    assert res["ok"]
    text = (Path(plugin.user_home) / ".config/lsfg-vk/conf.toml").read_text()
    assert '"bin/x64/Game.exe"' in text
    run(plugin.get_status())  # conf parses fine


def test_validation_boundaries(plugin):
    run(plugin.add_steam_game("1", "A.exe", "A"))
    assert run(plugin.set_profile_target_fps("a.exe", 30))["ok"]
    assert run(plugin.set_profile_target_fps("a.exe", 240))["ok"]
    for bad in (29, 241, None):
        res = run(plugin.set_profile_target_fps("a.exe", bad if bad else 0))
        if bad in (29, 241):
            assert res["ok"] is False and "range" in res["error"]
    assert run(plugin.set_profile_multiplier("a.exe", 5))["ok"] is False
    # flow scale snaps to nearest valid value instead of failing
    assert run(plugin.set_profile_flow_scale("a.exe", 0.6))["ok"]
    stored = {p["key"]: p for p in run(plugin.get_profiles())["profiles"]}
    assert stored["a.exe"]["flow_scale"] == 0.5


def test_dashboard_state_shape(plugin):
    make_fake_bin(Path(plugin.decky.DECKY_PLUGIN_DIR))
    state = run(plugin.get_dashboard_state())
    assert set(state) == {"status", "profiles"}
    assert set(state["status"]) >= {"layer", "conf", "dll", "panel", "host_arch",
                                    "adaptive_supported", "last_error"}
    assert isinstance(state["profiles"]["profiles"], list)


def test_last_error_cleared_on_success(plugin):
    res = run(plugin.set_profile_target_fps("ghost.exe", 90))
    assert res["ok"] is False
    status = run(plugin.get_status())
    assert status["last_error"] and "unknown profile" in status["last_error"]
    run(plugin.add_steam_game("1", "A.exe", "A"))
    assert run(plugin.set_profile_target_fps("a.exe", 60))["ok"]
    assert run(plugin.get_status())["last_error"] is None


def test_set_global_dll_overrides_scan(plugin, tmp_path):
    make_fake_steam(Path(plugin.decky.DECKY_USER_HOME))
    run(plugin.refresh_all())
    custom = tmp_path / "custom.dll"
    custom.write_bytes(b"x")
    assert run(plugin.set_global_dll(str(custom)))["ok"]
    status = run(plugin.get_status())
    assert status["dll"]["path"] == str(custom)
    text = (Path(plugin.user_home) / ".config/lsfg-vk/conf.toml").read_text()
    assert str(custom) in text
    # unsetting falls back to the discovered dll
    assert run(plugin.set_global_dll(None))["ok"]
    status = run(plugin.get_status())
    assert "Lossless.dll" in status["dll"]["path"]


# ------------------------------------------------------------ running game

def test_active_profile_keys_fake_proc(plugin, tmp_path):
    run(plugin.add_steam_game("1091500", "bin/x64/Cyberpunk2077.exe", "Cyberpunk 2077"))
    run(plugin.add_steam_game("77", "Solo.exe", "Solo"))

    proc = tmp_path / "proc"
    # game process: comm matches executable basename, SteamAppId in environ
    game = proc / "4242"
    game.mkdir(parents=True)
    (game / "comm").write_text("Cyberpunk2077.exe")
    (game / "cmdline").write_bytes(b"Z:\0games\0\0")
    (game / "environ").write_bytes(b"HOME=/home\0SteamAppId=1091500\0\0")
    # unrelated process
    other = proc / "1"
    other.mkdir(parents=True)
    (other / "comm").write_text("systemd")
    (other / "cmdline").write_bytes(b"/sbin/init\0\0")
    (other / "environ").write_bytes(b"HOME=/\0\0")

    active = plugin._active_keys_blocking(str(proc))
    assert active == ["cyberpunk2077.exe"]


def test_active_keys_no_proc(plugin, tmp_path):
    run(plugin.add_steam_game("1", "A.exe", "A"))
    assert plugin._active_keys_blocking(str(tmp_path / "nope")) == []


# ------------------------------------------------------- v0.2 engine changes

def test_conf_writes_version_key_and_dual_active_in(plugin):
    res = run(plugin.add_steam_game("55", "bin/Win64/Deep.exe", "Deep"))
    assert res["ok"]
    assert res["profile"]["key"] == "deep.exe"
    assert res["profile"]["active_in"] == ["Deep.exe", "bin/Win64/Deep.exe"]
    import tomllib

    conf = Path(plugin.user_home) / ".config" / "lsfg-vk" / "conf.toml"
    doc = tomllib.loads(conf.read_text(encoding="utf-8"))
    assert doc["version"] == 2
    assert doc["profile"][0]["active_in"] == ["Deep.exe", "bin/Win64/Deep.exe"]


def test_readd_same_game_merges_instead_of_duplicating(plugin):
    run(plugin.add_steam_game("66", "bin/Game.exe", "Game"))
    run(plugin.set_profile_multiplier("game.exe", 3))
    res = run(plugin.add_steam_game("66", "bin/Game.exe", "Game"))
    assert res["ok"]
    profiles = run(plugin.get_profiles())["profiles"]
    matching = [p for p in profiles if p["key"] == "game.exe"]
    assert len(matching) == 1
    assert matching[0]["multiplier"] == 3  # settings preserved through merge


def test_heal_profiles_adds_basename_to_legacy_profiles(plugin):
    import lsfg.config as config_mod

    legacy = config_mod.ProfileData(
        key="bin/x64/legacy.exe", name="Legacy", active_in=["bin/x64/Legacy.exe"],
    )
    plugin.settings.upsert_profile(legacy)
    run(plugin._main())  # simulate plugin restart
    healed = plugin.settings.get_profile("bin/x64/legacy.exe")
    assert healed is not None
    assert "Legacy.exe" in healed.active_in
    conf = (Path(plugin.user_home) / ".config" / "lsfg-vk" / "conf.toml").read_text()
    assert "Legacy.exe" in conf


def test_adaptive_defaults_to_engine_capability(plugin):
    make_fake_bin(Path(plugin.decky.DECKY_PLUGIN_DIR))
    info_path = Path(plugin.decky.DECKY_PLUGIN_DIR) / "bin" / "layer-info.json"
    info = json.loads(info_path.read_text())
    info["capabilities"]["adaptive"] = False
    info_path.write_text(json.dumps(info))
    res = run(plugin.add_steam_game("77", "Cap.exe", "Cap"))
    assert res["profile"]["adaptive"] is False
    info["capabilities"]["adaptive"] = True
    info_path.write_text(json.dumps(info))
    res = run(plugin.add_steam_game("88", "Cap2.exe", "Cap2"))
    assert res["profile"]["adaptive"] is True


def test_doctor_reports_structure(plugin):
    make_fake_bin(Path(plugin.decky.DECKY_PLUGIN_DIR))
    run(plugin.install_layer())
    result = run(plugin.run_doctor())
    assert_jsonable(result, "doctor")
    assert result["manifest"]["exists"] is True
    assert result["manifest"]["lib_exists"] is True
    assert result["manifest"]["has_enable_environment"] is False
    assert result["arch"]["ok"] is True
    assert "glibc" in result and "cli" in result
