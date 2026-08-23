# RAVE OS image foundation

Gate 1 follows the current upstream `rpi-image-gen` v2 model: YAML configuration,
metadata-bearing composable layers, and an external source directory supplied with
`-S image`. It replaces the previous descriptive mock, but it is still an **unbuilt
definition**, not a distributable or validated RAVE OS image.

The composition starts from upstream `trixie-minbase.yaml`, targets the upstream Pi 5
and Raspberry Pi OS image layers, and adds `rave-base`, `rave-identity`, `rave-network`,
`rave-hailo`, `rave-runtime`, `rave-web`, and `rave-update`. Product layers that write
RAVE-owned paths depend directly on `rave-base`; no artificial chain encodes ordering. Only
the filesystem/service identity and clone-safety boundary are substantive in Gate 1;
the other layers carry explicit incomplete markers.

The validated development evidence remains kernel `6.18.39+rpt-rpi-2712`, HailoRT
`4.23.0`, Hailo-8, Raspberry Pi 5, and Debian 13 Trixie. This definition deliberately
does not fetch Hailo packages or encode a kernel upgrade/downgrade. A compatible pinned
package source and redistribution review are prerequisites for that layer.

After selecting and recording an upstream `rpi-image-gen` release, the intended command
shape is `rpi-image-gen build -S image -c config/rave-os-gate1.yaml`. This is not a
successful build record. Before any image claim, lint the custom layers with the chosen
release, build from clean inputs, scan the rootfs/artifact, flash supported hardware,
and complete the applicable acceptance gate.

## First-boot identity boundary

The generic image must ship with an empty `/etc/machine-id`, no SSH host keys, no RAVE
device/private identity, no NetworkManager user profiles, no pairing/session material,
and no logs/cache. System boot may generate machine identity and SSH host keys through
the selected base image's reviewed mechanisms. RAVE cryptographic identity formats and
reset-preservation policy are intentionally not invented in Gate 1.

The `rave-identity` scrub uses the current upstream `mmdebstrap` `cleanup-hooks` phase,
which runs after package installation and every normal customization hook. This makes
the final root filesystem clone-safe even when an earlier package or layer created
machine-specific state.
