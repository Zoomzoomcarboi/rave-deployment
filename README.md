# RAVE Deployment

> **Architecture prototype only. Not road-ready and not intended to control a vehicle.**

RAVE (Rear Awareness Vision Engine) is a proposed Raspberry Pi 5 + Hailo edge-perception appliance for an external rear-facing camera. This repository demonstrates how RAVE could be packaged, configured, tested, released, and paired with a separate bridge running on a Comma device.

## Intended user experience

1. Buy the approved Raspberry Pi 5, AI HAT+, camera, cooling, storage, power hardware, and Ethernet adapter.
2. Flash a signed RAVE OS image using Raspberry Pi Imager.
3. Connect the camera, Pi Ethernet, Comma USB-C Ethernet adapter, and power.
4. Open the first-boot setup portal from a phone.
5. Pair RAVE with a compatible Starpilot build.
6. RAVE starts automatically on every boot.

The end user should not need to clone this repository, install Python packages, configure Linux networking, or enter crop coordinates.

## Repository map

```text
edge/                 Pi-side camera, inference, tracking, health, and transport
protocol/             Versioned Pi-to-Comma message schema
setup-ui/             First-boot and diagnostics web portal prototype
image/                RAVE OS image configuration and overlays
packaging/            Debian packaging scaffolding
hardware/             Approved hardware and installation documentation
models/               Model bundle format; trained weights are not committed
scripts/              Installer, diagnostics, and development helpers
systemd/              Long-running service definitions
tests/                Unit tests for configuration and message validation
.github/workflows/     CI and release-image workflow prototypes
```

## Safety architecture

The Raspberry Pi is a perception sensor only. It must not communicate directly with Panda or command vehicle controls. The Comma-side bridge must reject stale, unauthenticated, incompatible, or implausible data. Loss of the Pi, camera, model, Ethernet link, or heartbeat must result in RAVE being marked unavailable.

## Development quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp config/rave.toml.example config/rave.toml
rave doctor --config config/rave.toml
pytest
```

The mock inference backend emits synthetic detections. Hailo execution, camera controls, Comma networking, image creation, cryptographic pairing, and update signing are placeholders.

## Planned release artifacts

```text
rave-os-vX.Y.Z.img.xz
rave-os-vX.Y.Z.img.xz.sha256
rave-edge_X.Y.Z_arm64.deb
rave-model-X.Y.Z.tar.zst
manifest.json
release-notes.md
```

## Project status

- [x] Deployment architecture mock
- [x] Versioned configuration skeleton
- [x] Service and diagnostics skeleton
- [x] GitHub Actions placeholders
- [ ] Real camera capture
- [ ] Hailo HEF integration
- [ ] ByteTrack integration
- [ ] Authenticated Comma bridge protocol
- [ ] Hardware-in-the-loop release test
- [ ] Signed image/update pipeline
- [ ] Road validation
