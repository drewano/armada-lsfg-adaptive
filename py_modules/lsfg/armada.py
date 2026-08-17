"""Armada OS integration helpers.

Armada exposes per-device environment through /usr/libexec/armada/device-env
(sourced by the session scripts). We use it to read the panel's supported
refresh rates so the plugin can propose a sensible default target FPS, and to
detect that we are running on Armada (vs. generic Linux / SteamOS).
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

DEVICE_ENV = Path("/usr/libexec/armada/device-env")
GAME_LAUNCH = Path("/usr/libexec/armada/armada-game-launch")

_REFRESH_SPLIT = re.compile(r"[,\s]+")


def is_armada() -> bool:
    return DEVICE_ENV.exists()


# The decky PluginLoader binary may run under FEX emulation on Armada, in
# which case platform.machine() reports the emulated arch (x86_64) instead of
# the real host. Probe the userspace ELF loaders instead: they reflect the
# actual system, emulation or not.
_ELF_LOADERS = (
    ("/lib/ld-linux-aarch64.so.1", "aarch64"),
    ("/lib/ld-linux-x86-64.so.2", "x86_64"),
    ("/lib/ld-linux-armhf.so.3", "arm"),
    ("/lib/ld-linux.so.2", "x86"),
)


def host_arch() -> str:
    for loader, arch in _ELF_LOADERS:
        if os.path.exists(loader):
            return arch
    machine = platform.machine().lower()
    return {
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(machine, machine)


def _parse_env_output(text: str, prefix: str = "ARMADA_") -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith(prefix) and key not in env:
            env[key] = value.strip().strip('"').strip("'")
    return env


def read_device_env() -> dict[str, str]:
    """Run device-env and capture the ARMADA_* variables it exports."""
    if not DEVICE_ENV.exists():
        return {}
    try:
        result = subprocess.run(
            ["bash", "-c", f"set -a; source {DEVICE_ENV} >/dev/null 2>&1; env"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    return _parse_env_output(result.stdout)


def _gamescope_env() -> dict[str, str]:
    """Fallback: scrape ARMADA_* vars from the running gamescope process."""
    try:
        pids = os.listdir("/proc")
    except OSError:  # not Linux / no procfs
        return {}
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as fh:
                comm = fh.read().strip()
            if "gamescope" not in comm:
                continue
            with open(f"/proc/{pid}/environ", "rb") as fh:
                raw = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        env = _parse_env_output(raw.replace("\x00", "\n"))
        if env:
            return env
    return {}


def parse_refresh_rates(value: str | None) -> list[int]:
    """Parse e.g. '60,90,120' or '60.00 120.00' into sorted ints."""
    if not value:
        return []
    rates: list[int] = []
    for token in _REFRESH_SPLIT.split(value.strip()):
        try:
            rate = int(float(token))
        except ValueError:
            continue
        if 10 <= rate <= 1000 and rate not in rates:
            rates.append(rate)
    return sorted(rates)


def panel_info() -> dict:
    """Panel/device info for the UI and default target FPS."""
    env = read_device_env() or _gamescope_env()
    refresh_rates = parse_refresh_rates(env.get("ARMADA_PANEL_REFRESH_RATES"))
    return {
        "is_armada": is_armada(),
        "device": env.get("ARMADA_DEVICE_NAME") or env.get("ARMADA_DEVICE"),
        "refresh_rates": refresh_rates,
        "max_refresh": refresh_rates[-1] if refresh_rates else None,
        "native_width": env.get("ARMADA_PANEL_NATIVE_WIDTH"),
        "native_height": env.get("ARMADA_PANEL_NATIVE_HEIGHT"),
    }


def default_target_fps(max_refresh: int | None) -> int:
    """Sensible default target: 120 when the panel can do it, else its max."""
    if not max_refresh:
        return 60
    if max_refresh >= 120:
        return 120
    return max(30, max_refresh)
