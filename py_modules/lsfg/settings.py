"""Persistent plugin state (profiles managed, scan cache).

The authoritative list of games managed by the plugin lives here; conf.toml
only receives the profiles that are currently enabled. All writes are atomic.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import ProfileData

SETTINGS_VERSION = 1


class SettingsStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / "settings.json"
        self._state: dict = {}

    # -- low level ---------------------------------------------------------

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        data.setdefault("settings_version", SETTINGS_VERSION)
        data.setdefault("profiles", {})
        data.setdefault("scan_cache", None)
        data.setdefault("dll_path", None)
        data.setdefault("default_target_fps", None)
        self._state = data
        return data

    def save(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._state, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # -- profiles ----------------------------------------------------------

    def profiles(self) -> dict[str, ProfileData]:
        raw = self._state.get("profiles") or {}
        out: dict[str, ProfileData] = {}
        for key, data in raw.items():
            try:
                p = ProfileData.from_json(data)
                out[p.key] = p
            except TypeError:
                continue
        return out

    def get_profile(self, key: str) -> ProfileData | None:
        return self.profiles().get(key.lower())

    def upsert_profile(self, profile: ProfileData) -> None:
        profile.validate()
        raw = self._state.setdefault("profiles", {})
        raw[profile.key.lower()] = profile.to_json()
        self.save()

    def remove_profile(self, key: str) -> None:
        raw = self._state.setdefault("profiles", {})
        raw.pop(key.lower(), None)
        self.save()

    # -- misc state --------------------------------------------------------

    @property
    def dll_path(self) -> str | None:
        return self._state.get("dll_path")

    @dll_path.setter
    def dll_path(self, value: str | None) -> None:
        self._state["dll_path"] = value
        self.save()

    @property
    def default_target_fps(self) -> int | None:
        return self._state.get("default_target_fps")

    @default_target_fps.setter
    def default_target_fps(self, value: int | None) -> None:
        self._state["default_target_fps"] = int(value) if value else None
        self.save()

    def scan_cache(self) -> dict | None:
        cache = self._state.get("scan_cache")
        return cache if isinstance(cache, dict) else None

    def set_scan_cache(self, games: list[dict]) -> None:
        self._state["scan_cache"] = {"games": games, "timestamp": int(time.time())}
        self.save()
