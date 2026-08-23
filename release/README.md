# Install RAVE OS

RAVE OS is distributed as a pre-built Raspberry Pi 5 image.

> **Current release status:** Gate 2B test image.
>
> This image has passed RAVE Gate 2A image-build, filesystem,
> clone-safety, artifact-integrity, and provenance validation.
> Physical Raspberry Pi 5 boot validation is still in progress.
> This is not a production or road-use release.

## Download RAVE OS

**Raspberry Pi 5 image**

[RAVE-OS-Pi5-Gate2B-Test.img.xz](https://github.com/Zoomzoomcarboi/rave-deployment/releases/download/rave-os-gate2b-test-2026-08-23/RAVE-OS-Pi5-Gate2B-Test.img.xz)

Also available with the release:

- SHA256SUMS
- release.json
- release notes

You do not need Git, Docker, Python, rpi-image-gen, or the RAVE
source code to install a published RAVE OS image.

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

Verify the downloaded image against [SHA256SUMS](SHA256SUMS)
before flashing when possible.

## Important

Do not apply Raspberry Pi Imager OS customizations to this release.

The image is intentionally treated as `init_format: none`.
RAVE first-boot provisioning will be separately validated before
customization support is enabled.
