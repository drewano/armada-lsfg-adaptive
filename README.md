# Armada LSFG Adaptive

**Decky plugin that brings adaptive LSFG-VK frame generation to Armada OS handhelds (aarch64).**

One zip, no manual Vulkan layer setup, no Steam launch options: the plugin bundles an
aarch64 build of the [lsfg-vk experimental](https://github.com/eugeniosegala/lsfg-vk-experimental)
engine (Lossless Scaling-style frame generation), installs it at the user level, and
manages per-game adaptive profiles.

---

## How it works

1. **Installs the lsfg-vk Vulkan layer** (aarch64 build bundled in the zip) at the user
   level (`~/.local`) — the immutable OS is never touched, and the plugin runs without
   the Decky `root` flag.
2. **Discovers `Lossless.dll`** in your Steam library. You must own and install
   [Lossless Scaling](https://store.steampowered.com/app/993090/) — the plugin never
   distributes or modifies the DLL; the frame-generation model is read from your copy
   at runtime.
3. **Writes `~/.config/lsfg-vk/conf.toml`** with one `[[profile]]` block per enabled
   game. Activation is by executable-name matching (`active_in`): toggle a game in the
   plugin and you are done — nothing to add to Steam launch options.

### Adaptive mode

The adaptive logic lives **inside the Vulkan layer**: it measures the game's real frame
rate and schedules 0–3 generated frames per real frame to reach the **target FPS**
(30–240), under a configurable 2x/3x/4x **max multiplier** ceiling. It ramps up
gradually, keeps the lowest proven level that already meets the target, and rolls back
when generation hurts real-frame throughput. The default target FPS is derived from the
panel's refresh rate (read from Armada's `device-env`).

Per-game settings: adaptive on/off · target FPS · max multiplier · smooth cadence ·
fixed multiplier (when adaptive is off) · flow scale · performance mode.

---

## Installation

Prerequisites: an Armada OS handheld with Decky (preinstalled), **Lossless Scaling**
installed in Steam, and the target game installed.

**Option 1 — installer script (recommended):**

```bash
curl -fsSL https://raw.githubusercontent.com/drewano/armada-lsfg-adaptive/main/install.sh | bash
```

**Option 2 — manual zip:** download the `.zip` from the latest release, then in Steam:
Quick Access Menu → Decky → plugin browser → install from file.

After installing: open the plugin in the Quick Access Menu, press **Install LSFG
layer**, **Rescan Steam library**, then add your game.

---

## Kill switches

Frame generation can be disabled for a launch by setting an environment variable
(e.g. temporarily in the game's Steam launch options):

| Variable | Effect |
|---|---|
| `DISABLE_LSFGVK=1` | disables the layer (manifest level) |
| `DISABLE_LSFGVK_EXPERIMENTAL=1` | same, experimental-engine variant |

The plugin preserves any `conf.toml` content it does not manage (profiles from other
tools). Every write is atomic with a `.bak` backup; unparseable foreign blocks are
quarantined into a `.rejected` file instead of being destroyed. **Uninstall** removes
the Vulkan layer but never touches `conf.toml`.

## Troubleshooting

- **"Lossless.dll not found"**: install and run Lossless Scaling once on Steam, then
  rescan the library.
- **No effect in game**: make sure the profile is **enabled** and the detected
  executable is the right one; under FEX, the Windows executable name is what gets
  matched.
- **Artifacts / instability**: lower Flow Scale to 0.25, enable performance mode, or
  use a fixed multiplier (adaptive off). The experimental engine moves fast — keep a
  known-good version around.
- **Logs**: `~/homebrew/logs/Armada LSFG Adaptive/`.

## Development

```bash
pnpm install && pnpm run build      # frontend -> dist/index.js
python3 -m pytest tests -q          # backend unit tests
./scripts/build-local.sh            # full zip (docker with arm64 support required)
./scripts/build-local.sh --skip-backend   # zip without rebuilding the layer
```

The Vulkan layer is compiled in `backend/` (fedora:41, linux/arm64) from
[`eugeniosegala/lsfg-vk-experimental`](https://github.com/eugeniosegala/lsfg-vk-experimental)
at the commit pinned in the Dockerfile. Alternative engine without adaptive but
proven on aarch64: `--build-arg LSFG_SOURCE=zensenshi`
([`Zensenshi/lsfg-vk-odin2-armada`](https://github.com/Zensenshi/lsfg-vk-odin2-armada)).

Releases are built by GitHub Actions on a native arm64 runner (`.github/workflows/build.yml`):
push a `v*` tag and the zip + sha256 land on the release page.

## Credits

- [PancakeTAS/lsfg-vk](https://github.com/PancakeTAS/lsfg-vk) and
  [eugeniosegala/lsfg-vk-experimental](https://github.com/eugeniosegala/lsfg-vk-experimental) —
  the engine (GPL-3.0), including all the adaptive logic.
- [BakaPute/ArmadaLSFG](https://github.com/BakaPute/ArmadaLSFG) and
  [eugeniosegala/decky-lsfg-vk-experimental](https://github.com/eugeniosegala/decky-lsfg-vk-experimental) —
  the approaches this plugin builds upon.
- [armada-os/armada](https://github.com/armada-os/armada) and
  [SteamDeckHomebrew](https://github.com/SteamDeckHomebrew).

Licenses: see `LICENSE` (plugin code, BSD-3) and `THIRD_PARTY_NOTICES.md` (engine
GPL-3.0 — the distributed layer is exactly the source pinned in `backend/Dockerfile`).
