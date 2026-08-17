"""conf.toml management for the lsfg-vk Vulkan layer.

The layer reads `~/.config/lsfg-vk/conf.toml`:

    [global]
    dll = "/path/to/Lossless.dll"

    [[profile]]
    name = "Some Game"
    active_in = ["Game.exe"]
    adaptive = true
    target_fps = 120
    adaptive_max_multiplier = 3
    adaptive_stable_cadence = false
    frame_generation_enabled = true
    flow_scale = 0.5
    performance_mode = true

Rules applied here:
- The `[global]` section is preserved verbatim except for the `dll` key.
- Profile blocks whose first `active_in` entry is not managed by this plugin
  are preserved verbatim (foreign blocks from other tools).
- Managed blocks are rendered from plugin state; disabled profiles are
  removed from the file entirely (their settings live in settings.json).
- Writes are atomic: backup -> temp file -> tomllib validation -> os.replace.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

BACKUP_SUFFIX = ".armada-lsfg-adaptive.bak"
TEMP_SUFFIX = ".armada-lsfg-adaptive.tmp"

# The v2 engine line (PancakeTAS develop / its forks) expects a top-level
# `version = 2` marker in conf.toml; the reference working setup on Armada
# ships it, so we always write it.
CONF_VERSION_KEY = "version = 2"

_VERSION_RE = re.compile(r"(?m)^version\s*=\s*\S+.*$")


def with_conf_version(global_section: str) -> str:
    """Re-emit the preamble canonically: `version = 2` at the true TOML top
    level, then the [global] table.

    A line-level regex cannot know which TOML table a `version =` line sits
    in: if a legacy file carried it inside [global] (parsed as
    global.version), replacing it in place left the engine without a
    root-level version and it rejected the whole file. Rewriting the
    preamble deterministically fixes any placement history.
    """
    lines = [
        line for line in global_section.splitlines()
        if not _VERSION_RE.match(line) and line.strip() != "[global]"
    ]
    body = "\n".join(lines).strip("\n")
    out = CONF_VERSION_KEY + "\n\n[global]\n"
    if body:
        out += body
        if not out.endswith("\n"):
            out += "\n"
    return out

VALID_MULTIPLIERS = (2, 3, 4)
VALID_FLOW_SCALES = (0.25, 0.5, 0.75, 1.0)
TARGET_FPS_MIN = 30
TARGET_FPS_MAX = 240

PROFILE_HEADER = "[[profile]]"
_DLL_RE = re.compile(r'(?m)^(\s*dll\s*=\s*).*$')


class ConfigError(Exception):
    """Raised when the config file cannot be parsed or written safely."""


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


@dataclass
class ProfileData:
    """A frame-generation profile managed by this plugin."""

    key: str                                   # lowercased first active_in entry
    name: str = ""
    active_in: list[str] = field(default_factory=list)
    enabled: bool = True                       # frame_generation_enabled
    adaptive: bool = True
    target_fps: int = 120
    max_multiplier: int = 3
    stable_cadence: bool = True
    multiplier: int = 2                        # fixed multiplier when adaptive is off
    flow_scale: float = 0.5
    performance_mode: bool = True
    appid: str | None = None                   # plugin metadata, not written to TOML

    def validate(self) -> None:
        if not self.active_in:
            raise ConfigError("profile needs at least one active_in entry")
        if not self.key:
            raise ConfigError("profile needs a key")
        if self.target_fps is None or not (TARGET_FPS_MIN <= int(self.target_fps) <= TARGET_FPS_MAX):
            raise ConfigError(f"target_fps out of range ({TARGET_FPS_MIN}-{TARGET_FPS_MAX})")
        self.target_fps = int(self.target_fps)
        if int(self.max_multiplier) not in VALID_MULTIPLIERS:
            raise ConfigError("max_multiplier must be 2, 3 or 4")
        self.max_multiplier = int(self.max_multiplier)
        if int(self.multiplier) not in VALID_MULTIPLIERS:
            raise ConfigError("multiplier must be 2, 3 or 4")
        self.multiplier = int(self.multiplier)
        self.flow_scale = float(self.flow_scale)
        # snap to the nearest valid value instead of rejecting
        self.flow_scale = min(VALID_FLOW_SCALES, key=lambda s: abs(s - self.flow_scale))

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "ProfileData":
        known = {f for f in cls.__dataclass_fields__}
        p = cls(**{k: v for k, v in data.items() if k in known})
        p.key = p.key.lower()
        return p

    @classmethod
    def new_game(cls, exe: str, name: str, appid: str | None = None,
                 target_fps: int = 120, adaptive: bool = True) -> "ProfileData":
        # Match on both the basename and the full relative path: under FEX the
        # engine may see either form as the process identity.
        base = os.path.basename(exe.replace("\\", "/"))
        active_in = [exe] if base.lower() == exe.lower() else [base, exe]
        p = cls(
            key=base.lower(),
            name=name or exe,
            active_in=active_in,
            appid=appid,
            adaptive=adaptive,
            target_fps=clamp(int(target_fps), TARGET_FPS_MIN, TARGET_FPS_MAX),
        )
        p.validate()
        return p


def profile_key_from(active_in: list[str]) -> str:
    """Managed profiles are keyed by the lowercased first active_in entry."""
    return (active_in[0] if active_in else "").lower()


def toml_str(value: str) -> str:
    return json.dumps(value)


def render_profile(p: ProfileData) -> str:
    p.validate()
    lines = [
        PROFILE_HEADER,
        f"name = {toml_str(p.name or p.active_in[0])}",
        f"active_in = [{', '.join(toml_str(a) for a in p.active_in)}]",
    ]
    if p.adaptive:
        lines.append("adaptive = true")
        lines.append(f"target_fps = {p.target_fps}")
        lines.append(f"adaptive_max_multiplier = {p.max_multiplier}")
        lines.append(f"adaptive_stable_cadence = {'true' if p.stable_cadence else 'false'}")
    else:
        lines.append("adaptive = false")
        lines.append(f"multiplier = {p.multiplier}")
    lines.append(f"frame_generation_enabled = {'true' if p.enabled else 'false'}")
    lines.append(f"flow_scale = {p.flow_scale:.2f}")
    lines.append(f"performance_mode = {'true' if p.performance_mode else 'false'}")
    return "\n".join(lines) + "\n"


def split_config(text: str) -> tuple[str, list[str]]:
    """Split the file into the [global] preamble and raw profile blocks.

    Only lines that strip to exactly `[[profile]]` act as separators, so
    commented-out blocks stay where they are.
    """
    lines = text.splitlines(keepends=True)
    global_lines: list[str] = []
    blocks: list[str] = []
    current: list[str] | None = None
    for line in lines:
        if line.strip() == PROFILE_HEADER:
            if current is not None:
                blocks.append("".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
        else:
            global_lines.append(line)
    if current is not None:
        blocks.append("".join(current))
    return "".join(global_lines), blocks


def parse_block(block: str) -> dict | None:
    """Parse a `[[profile]]` block; return its keys or None if unparseable."""
    try:
        doc = tomllib.loads(block)
    except tomllib.TOMLDecodeError:
        return None
    profiles = doc.get("profile")
    if isinstance(profiles, list) and profiles and isinstance(profiles[0], dict):
        return profiles[0]
    return None


def set_global_dll(global_text: str, dll_path: str | None) -> str:
    """Insert or replace the `dll` key inside the [global] section."""
    if dll_path is None:
        return global_text
    line = f"dll = {toml_str(str(dll_path))}"
    if _DLL_RE.search(global_text):
        return _DLL_RE.sub(lambda m: m.group(1) + toml_str(str(dll_path)), global_text, count=1)
    text = global_text
    if text and not text.endswith("\n"):
        text += "\n"
    if "[global]" not in text:
        text += "\n[global]\n"
    return text + line + "\n"


def load_config(path: Path) -> dict:
    """Read and validate the whole config file. Raises ConfigError on bad TOML."""
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"conf.toml is not valid TOML: {exc}") from exc


def profile_from_block(block: dict) -> ProfileData:
    """Build a ProfileData view of a parsed TOML profile block (read-only use)."""
    active_in = [str(a) for a in block.get("active_in", []) if str(a).strip()]
    adaptive = bool(block.get("adaptive", False))
    return ProfileData(
        key=profile_key_from(active_in),
        name=str(block.get("name", active_in[0] if active_in else "?")),
        active_in=active_in,
        enabled=bool(block.get("frame_generation_enabled", True)),
        adaptive=adaptive,
        target_fps=int(block.get("target_fps", 120)),
        max_multiplier=int(block.get("adaptive_max_multiplier", 3)),
        stable_cadence=bool(block.get("adaptive_stable_cadence", False)),
        multiplier=int(block.get("multiplier", 2)),
        flow_scale=float(block.get("flow_scale", 0.5)),
        performance_mode=bool(block.get("performance_mode", False)),
    )


def write_config(path: Path, managed: list[ProfileData], dll_path: str | None = None) -> list[str]:
    """Write managed profiles, preserving foreign blocks verbatim.

    Returns the list of foreign keys preserved. Raises ConfigError if the
    result would be invalid TOML; the original file is left untouched.
    """
    path = Path(path)
    text = ""
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")

    global_text, blocks = split_config(text)
    managed_keys = {p.key.lower() for p in managed}

    foreign_blocks: list[str] = []
    foreign_keys: list[str] = []
    rejected_blocks: list[str] = []
    for block in blocks:
        parsed = parse_block(block)
        if parsed is None:
            # unparseable block: quarantine instead of corrupting the output
            rejected_blocks.append(block)
            foreign_keys.append("<unparseable>")
            continue
        key = profile_key_from([str(a) for a in parsed.get("active_in", [])])
        if key in managed_keys:
            continue  # replaced by our render
        foreign_blocks.append(block)
        foreign_keys.append(key)

    def assemble(global_section: str) -> str:
        chunks = [global_section]
        for p in sorted(managed, key=lambda x: (x.name or x.key).lower()):
            if p.enabled:
                chunks.append("\n" + render_profile(p))
        for block in foreign_blocks:
            if not block.endswith("\n"):
                block += "\n"
            chunks.append("\n" + block)
        out = "\n".join(chunks).lstrip("\n")
        return out + "\n" if out else out

    new_text = assemble(with_conf_version(set_global_dll(global_text, dll_path)))
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        # the pre-existing [global] section itself is broken: quarantine the
        # whole old file and start fresh rather than leaving the user stuck
        rejected_blocks.append(text)
        new_text = assemble(with_conf_version(set_global_dll("", dll_path)))
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"refusing to write invalid TOML: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, str(path) + BACKUP_SUFFIX)
    if rejected_blocks:
        rejected_path = Path(str(path) + ".armada-lsfg-adaptive.rejected")
        with open(rejected_path, "a", encoding="utf-8") as fh:
            if rejected_path.stat().st_size == 0:
                fh.write("# Profile blocks quarantined by Armada LSFG Adaptive:\n"
                         "# they were not valid TOML and were removed from conf.toml.\n\n")
            for block in rejected_blocks:
                fh.write(block if block.endswith("\n") else block + "\n")
                fh.write("\n")
    tmp = str(path) + TEMP_SUFFIX
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new_text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return foreign_keys


def read_profiles(path: Path) -> list[ProfileData]:
    """All profiles currently present in the config file (managed or foreign)."""
    doc = load_config(path)
    result = []
    for block in doc.get("profile", []) or []:
        if isinstance(block, dict):
            result.append(profile_from_block(block))
    return result
