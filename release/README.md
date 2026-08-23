# Install RAVE OS

RAVE OS will be distributed as a pre-built Raspberry Pi 5 image after validation.

> **Current release status:** Gate 2B candidate, not yet published.
>
> No downloadable Gate 2B image or GitHub Release is currently claimed here.
> Physical Raspberry Pi 5 boot validation remains pending.
> This is not a production or road-use release.

## Download status

No Gate 2B public release or downloadable asset exists yet. After a validated
image build, `scripts/package-release-candidate.sh` generates the image and its
`SHA256SUMS` and `release.json` beside it under `build/<build-name>/candidate/`.
Those build-specific files are ignored release assets, not tracked source.

Package only an artifact and provenance pair emitted by the same validated
build:

```text
scripts/package-release-candidate.sh \
  build/<build-name>/work/deploy-<version>/rave-os-gate2b.img.zst \
  build/<build-name>/provenance.json \
  build/<build-name>/candidate
```

The resulting candidate directory contains:

```text
RAVE-OS-Pi5-Gate2B-Candidate.img
RAVE-OS-Pi5-Gate2B-Candidate.img.xz
SHA256SUMS
release.json
```

## What you need

- Raspberry Pi 5
- microSD card
- SD card reader
- Raspberry Pi Imager 2.x
- downloaded RAVE OS image

## Flash the SD card

See [INSTALL.md](INSTALL.md).

The normal installation path is:

GitHub → Download RAVE OS → Raspberry Pi Imager →
Raspberry Pi 5 → Use Custom → RAVE image →
microSD card → Write → Verify → Boot

## Integrity

An eventual release will attach `SHA256SUMS` and `release.json` alongside the
image asset. Verify the downloaded image against that attached checksum before
flashing.

## Important

Do not apply Raspberry Pi Imager OS customizations to this release.

The image is intentionally treated as `init_format: none`.
RAVE first-boot provisioning will be separately validated before
customization support is enabled.
