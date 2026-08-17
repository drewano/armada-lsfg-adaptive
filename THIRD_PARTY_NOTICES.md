# Third-party notices

## lsfg-vk / lsfg-vk-experimental (bundled binary)

The `bin/liblsfg-vk-layer.so` shipped in the plugin zip is a build of
https://github.com/eugeniosegala/lsfg-vk-experimental (a fork of
https://github.com/PancakeTAS/lsfg-vk), at the pinned commit declared in
`engine/Dockerfile` (default `LSFG_REF`). The exact engine version is recorded in
`bin/layer-info.json` inside each release.

- License: **GNU GPL-3.0** — full text: https://www.gnu.org/licenses/gpl-3.0.txt
  (also present in the upstream repository as `LICENSE.md`).
- Corresponding source: the upstream repository at the pinned commit, buildable with
  the commands in `engine/entrypoint.sh`.

This plugin's own code (Python backend, TypeScript frontend, scripts) is BSD-3-Clause
(see `LICENSE`) and only aggregates the GPL binary; the combined release zip
redistributes that binary under its GPL-3.0 terms.

## Lossless.dll

NOT distributed, modified, or downloaded by this plugin. The frame-generation model is
extracted at runtime from the user's own copy of Lossless Scaling
(https://store.steampowered.com/app/993090/), which must be legitimately owned and
installed. All rights belong to its author.

## Decky / SteamDeckHomebrew

Plugin structure and loader APIs from https://github.com/SteamDeckHomebrew
(decky-plugin-template, decky-loader). The plugin does not redistribute loader code.

## Inspirational prior art

- https://github.com/BakaPute/ArmadaLSFG (conf.toml profile management approach)
- https://github.com/eugeniosegala/decky-lsfg-vk-experimental (adaptive engine packaging)
- https://github.com/Zensenshi/lsfg-vk-odin2-armada (aarch64 reference build)
