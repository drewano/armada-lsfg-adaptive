"""Integration tests for the Plugin class in main.py with a stubbed decky module.

Regression guard for the kwargs bug: set_profile_* methods pass keyword
arguments through Plugin._to_thread, which used to reject them with
"TypeError: _to_thread() got an unexpected keyword argument".
"""

import asyncio
import logging
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_decky_stub(tmp_path: Path) -> types.ModuleType:
    decky = types.ModuleType("decky")
    decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path / "settings")
    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path / "data")
    decky.DECKY_PLUGIN_LOG_DIR = str(tmp_path / "logs")
    decky.DECKY_PLUGIN_DIR = str(tmp_path / "plugin")
    decky.DECKY_PLUGIN_VERSION = "test"
    decky.DECKY_PLUGIN_NAME = "Armada LSFG Adaptive"
    decky.DECKY_USER_HOME = str(tmp_path / "home")

    async def emit(event_name, *args):  # noqa: ANN001
        return None

    decky.emit = emit
    decky.logger = logging.getLogger("decky-stub")
    sys.modules["decky"] = decky
    return decky


@pytest.fixture()
def plugin(tmp_path):
    decky = _install_decky_stub(tmp_path)
    for mod in [m for m in sys.modules if m == "main"]:
        del sys.modules[mod]
    import main as main_mod

    p = main_mod.Plugin()
    asyncio.run(p._main())
    p.decky = decky
    return p


def _conf_path(plugin) -> Path:
    return Path(plugin.user_home) / ".config" / "lsfg-vk" / "conf.toml"


def test_add_game_and_mutate_profile_kwargs_roundtrip(plugin):
    res = asyncio.run(plugin.add_steam_game("1234", "Game.exe", "Test Game"))
    assert res["ok"], res
    profile = res["profile"]
    assert profile["target_fps"] == 60  # default when no panel info

    # every one of these used to raise TypeError before the _to_thread fix
    assert asyncio.run(plugin.set_profile_target_fps("game.exe", 90))["ok"]
    assert asyncio.run(plugin.set_profile_adaptive("game.exe", False))["ok"]
    assert asyncio.run(plugin.set_profile_multiplier("game.exe", 3))["ok"]
    assert asyncio.run(plugin.set_profile_max_multiplier("game.exe", 4))["ok"]
    assert asyncio.run(plugin.set_profile_flow_scale("game.exe", 0.75))["ok"]
    assert asyncio.run(plugin.set_profile_performance_mode("game.exe", False))["ok"]
    assert asyncio.run(plugin.set_profile_stable_cadence("game.exe", False))["ok"]
    assert asyncio.run(plugin.set_profile_enabled("game.exe", False))["ok"]

    conf = _conf_path(plugin).read_text(encoding="utf-8")
    # disabled profile is removed from conf.toml, state kept in settings
    assert "Game.exe" not in conf

    assert asyncio.run(plugin.set_profile_enabled("game.exe", True))["ok"]
    conf = _conf_path(plugin).read_text(encoding="utf-8")
    assert "multiplier = 3" in conf
    assert "adaptive = false" in conf
    assert "flow_scale = 0.75" in conf

    profiles = asyncio.run(plugin.get_profiles())
    stored = {p["key"]: p for p in profiles["profiles"]}["game.exe"]
    assert stored["performance_mode"] is False


def test_set_profile_unknown_key_fails_cleanly(plugin):
    res = asyncio.run(plugin.set_profile_target_fps("nope.exe", 90))
    assert res["ok"] is False
    assert "unknown profile" in res["error"]


def test_remove_managed_profile(plugin):
    assert asyncio.run(plugin.add_steam_game("42", "Other.exe", "Other"))["ok"]
    assert asyncio.run(plugin.remove_managed_profile("other.exe"))["ok"]
    profiles = asyncio.run(plugin.get_profiles())
    assert all(p["key"] != "other.exe" for p in profiles["profiles"])
