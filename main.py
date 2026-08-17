"""Armada LSFG Adaptive - Decky plugin backend.

Exposes to the frontend:
    status / layer install / Steam scan / per-game adaptive profiles.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import decky

from lsfg import armada as armada_mod
from lsfg import config as config_mod
from lsfg import layer as layer_mod
from lsfg import settings as settings_mod
from lsfg import steam as steam_mod

CONF_TOML_REL = ".config/lsfg-vk/conf.toml"


class Plugin:
    # ------------------------------------------------------------------ utils

    def _conf_path(self) -> Path:
        return Path(self.user_home) / CONF_TOML_REL

    def _rewrite_conf(self) -> dict:
        """Write every enabled managed profile to conf.toml."""
        profiles = list(self.settings.profiles().values())
        dll = self._resolve_dll()
        foreign = config_mod.write_config(self._conf_path(), profiles, dll_path=dll)
        return {"foreign_keys": foreign}

    def _resolve_dll(self) -> str | None:
        dll = self.settings.dll_path
        if dll and Path(dll).is_file():
            return dll
        # fall back to the last scan's discovery
        cache = self.settings.scan_cache()
        if cache and cache.get("lossless_dll") and Path(cache["lossless_dll"]).is_file():
            return cache["lossless_dll"]
        return None

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _ok(self, extra: dict | None = None) -> dict:
        self._last_error = None
        out = {"ok": True}
        if extra:
            out.update(extra)
        return out

    def _err(self, exc: Exception) -> dict:
        self._last_error = f"{type(exc).__name__}: {exc}"
        decky.logger.error("%s", self._last_error)
        return {"ok": False, "error": self._last_error}

    # -------------------------------------------------------------- lifecycle

    async def _main(self):
        self.user_home = Path(
            getattr(decky, "DECKY_USER_HOME", None) or Path.home()
        )
        self.settings = settings_mod.SettingsStore(
            Path(decky.DECKY_PLUGIN_SETTINGS_DIR)
        )
        self.settings.load()
        self.layer = layer_mod.LayerManager(
            user_home=self.user_home,
            bin_dir=Path(decky.DECKY_PLUGIN_DIR) / "bin",
            host_arch=armada_mod.host_arch(),
        )
        self._scan_lock = asyncio.Lock()
        self._panel: dict | None = None
        self._last_error: str | None = None
        decky.logger.info(
            "Armada LSFG Adaptive %s started (arch=%s, home=%s)",
            decky.DECKY_PLUGIN_VERSION,
            armada_mod.host_arch(),
            self.user_home,
        )

    async def _unload(self):
        decky.logger.info("Armada LSFG Adaptive stopped")

    async def _uninstall(self):
        # remove the layer we installed; keep conf.toml (may hold foreign data)
        try:
            await self._to_thread(self.layer.uninstall)
        except Exception as exc:  # noqa: BLE001
            decky.logger.warning("uninstall: %s", exc)

    # ------------------------------------------------------------------ status

    def _status_blocking(self) -> dict:
        conf_path = self._conf_path()
        conf_state: dict = {"path": str(conf_path)}
        try:
            profiles = config_mod.read_profiles(conf_path)
            conf_state.update({"exists": True, "valid": True, "profiles": len(profiles)})
        except config_mod.ConfigError as exc:
            conf_state.update({"exists": conf_path.exists(), "valid": False, "error": str(exc)})
        dll = self._resolve_dll()
        panel = self._panel or armada_mod.panel_info()
        self._panel = panel
        layer_status = self.layer.status()
        capabilities = layer_status["installed"].get("capabilities") or {}
        return {
            "layer": layer_status,
            "conf": conf_state,
            "dll": {"path": dll, "exists": bool(dll and Path(dll).is_file())},
            "panel": panel,
            "host_arch": armada_mod.host_arch(),
            "adaptive_supported": bool(capabilities.get("adaptive", True)),
            "last_error": self._last_error,
        }

    async def get_status(self) -> dict:
        return await self._to_thread(self._status_blocking)

    # ------------------------------------------------------------------- layer

    async def install_layer(self) -> dict:
        try:
            status = await self._to_thread(self.layer.install)
            return self._ok({"layer": status})
        except layer_mod.LayerError as exc:
            return self._err(exc)

    async def uninstall_layer(self) -> dict:
        try:
            await self._to_thread(self.layer.uninstall)
            return self._ok({"layer": self.layer.status()})
        except Exception as exc:  # noqa: BLE001
            return self._err(exc)

    # ------------------------------------------------------------------- games

    def _scan_blocking(self, progress) -> dict:
        progress(5)
        result = steam_mod.scan_libraries(self.user_home)
        progress(80)
        self.settings.set_scan_cache(result["games"])
        if result["lossless_dll"] and not self.settings.dll_path:
            self.settings.dll_path = result["lossless_dll"]
        progress(95)
        return result

    async def refresh_all(self) -> dict:
        async with self._scan_lock:
            loop = asyncio.get_running_loop()

            async def emit_progress(pct: int):
                await decky.emit("scan_progress", pct)

            def progress(pct: int):
                loop.call_soon_threadsafe(
                    lambda p=pct: loop.create_task(emit_progress(p))
                )

            try:
                result = await self._to_thread(
                    self._scan_blocking, progress
                )
                await emit_progress(100)
                return self._ok({
                    "games": result["games"],
                    "lossless_dll": result["lossless_dll"],
                })
            except Exception as exc:  # noqa: BLE001
                return self._err(exc)

    async def get_steam_games(self) -> dict:
        cache = self.settings.scan_cache()
        if cache and cache.get("games") is not None:
            return {"games": cache["games"], "cached": True}
        result = await self.refresh_all()
        if not result.get("ok"):
            return result
        return {"games": result["games"], "cached": False}

    # ---------------------------------------------------------------- profiles

    def _add_game_blocking(self, appid: str, executable: str, name: str) -> dict:
        panel = self._panel or armada_mod.panel_info()
        default_fps = armada_mod.default_target_fps(panel.get("max_refresh"))
        profile = config_mod.ProfileData.new_game(
            executable, name, appid=appid, target_fps=default_fps
        )
        self.settings.upsert_profile(profile)
        foreign = self._rewrite_conf()
        return {
            "ok": True,
            "profile": profile.to_json(),
            "foreign_keys": foreign.get("foreign_keys", []),
        }

    async def add_steam_game(self, appid: str, executable: str, name: str) -> dict:
        try:
            return await self._to_thread(self._add_game_blocking, appid, executable, name)
        except (config_mod.ConfigError, OSError) as exc:
            return self._err(exc)

    def _mutate_profile(self, key: str, **changes) -> None:
        profiles = self.settings.profiles()
        profile = profiles.get(key.lower())
        if profile is None:
            raise config_mod.ConfigError(f"unknown profile: {key}")
        for field_name, value in changes.items():
            setattr(profile, field_name, value)
        self.settings.upsert_profile(profile)
        self._rewrite_conf()

    async def _set_profile_field(self, key: str, **changes) -> dict:
        try:
            await self._to_thread(self._mutate_profile, key, **changes)
            return self._ok()
        except (config_mod.ConfigError, OSError) as exc:
            return self._err(exc)
        except Exception as exc:  # noqa: BLE001
            return self._err(exc)

    async def set_profile_enabled(self, key: str, enabled: bool) -> dict:
        return await self._set_profile_field(key, enabled=enabled)

    async def set_profile_adaptive(self, key: str, adaptive: bool) -> dict:
        return await self._set_profile_field(key, adaptive=adaptive)

    async def set_profile_target_fps(self, key: str, target_fps: int) -> dict:
        return await self._set_profile_field(key, target_fps=int(target_fps))

    async def set_profile_max_multiplier(self, key: str, max_multiplier: int) -> dict:
        return await self._set_profile_field(key, max_multiplier=int(max_multiplier))

    async def set_profile_multiplier(self, key: str, multiplier: int) -> dict:
        return await self._set_profile_field(key, multiplier=int(multiplier))

    async def set_profile_flow_scale(self, key: str, flow_scale: float) -> dict:
        return await self._set_profile_field(key, flow_scale=float(flow_scale))

    async def set_profile_performance_mode(self, key: str, performance_mode: bool) -> dict:
        return await self._set_profile_field(key, performance_mode=performance_mode)

    async def set_profile_stable_cadence(self, key: str, stable_cadence: bool) -> dict:
        return await self._set_profile_field(key, stable_cadence=stable_cadence)

    async def remove_managed_profile(self, key: str) -> dict:
        def blocking():
            self.settings.remove_profile(key)
            self._rewrite_conf()

        try:
            await self._to_thread(blocking)
            return self._ok()
        except (config_mod.ConfigError, OSError) as exc:
            return self._err(exc)

    async def get_profiles(self) -> dict:
        def blocking() -> dict:
            managed = self.settings.profiles()
            foreign: list[dict] = []
            try:
                in_file = {p.key for p in config_mod.read_profiles(self._conf_path())}
            except config_mod.ConfigError:
                in_file = None
            profiles = []
            for p in sorted(managed.values(), key=lambda x: x.name.lower()):
                profiles.append({
                    **p.to_json(),
                    "in_config": in_file is None or p.key in in_file or not p.enabled,
                })
            if in_file is not None:
                for p in config_mod.read_profiles(self._conf_path()):
                    if p.key not in managed:
                        foreign.append(p.to_json() | {"foreign": True})
            return {"profiles": profiles, "foreign": foreign}

        return await self._to_thread(blocking)

    # ------------------------------------------------------------------ global

    async def set_global_dll(self, path: str | None) -> dict:
        def blocking():
            self.settings.dll_path = path or None
            self._rewrite_conf()

        try:
            await self._to_thread(blocking)
            return self._ok()
        except (config_mod.ConfigError, OSError) as exc:
            return self._err(exc)

    # ------------------------------------------------------------ running game

    def _active_keys_blocking(self) -> list[str]:
        managed = self.settings.profiles()
        if not managed:
            return []
        # map lowercase process identifiers -> profile key
        by_proc: dict[str, str] = {}
        by_appid: dict[str, str] = {}
        for p in managed.values():
            for entry in p.active_in:
                by_proc[entry.lower().lstrip("/")] = p.key
                by_proc[Path(entry).name.lower()] = p.key
            if p.appid:
                by_appid[str(p.appid)] = p.key
        active: set[str] = set()
        try:
            pids = os.listdir("/proc")
        except OSError:
            return sorted(active)
        for pid in pids:
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as fh:
                    comm = fh.read().strip().lower()
                cmd = ""
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    argv = fh.read().split(b"\x00")
                if argv:
                    cmd = os.path.basename(argv[0].decode("utf-8", errors="replace")).lower()
                for ident in {comm, cmd}:
                    if ident in by_proc:
                        active.add(by_proc[ident])
                env_appid = None
                with open(f"/proc/{pid}/environ", "rb") as fh:
                    for item in fh.read().split(b"\x00"):
                        if item.startswith(b"SteamAppId="):
                            env_appid = item.split(b"=", 1)[1].decode(
                                "utf-8", errors="replace"
                            )
                            break
                if env_appid and env_appid in by_appid:
                    active.add(by_appid[env_appid])
            except OSError:
                continue
        return sorted(active)

    async def get_active_profile_keys(self) -> list[str]:
        return await self._to_thread(self._active_keys_blocking)

    # ----------------------------------------------------------------- one-shot

    async def get_dashboard_state(self) -> dict:
        status = await self.get_status()
        profiles = await self.get_profiles()
        return {"status": status, "profiles": profiles}
