# RAVE Deployment

> Development scaffolding plus validated integration baselines. RAVE is not
> road-ready, production-ready, or able to control a vehicle.

RAVE (Rear Awareness Vision Engine) is a Raspberry Pi 5-targeted rear-awareness
perception system. This repository defines the deployment boundary, safety rules,
hardware profile, packaging direction, and reproducible validation records.

The original edge runtime in this repository is still development scaffolding.
However, camera/inference work on the ZBook and dedicated-Ethernet/StarPilot work on
the Comma 3X have now produced hardware-validated baselines that are recorded in
[`docs/VALIDATED_BASELINES.md`](docs/VALIDATED_BASELINES.md).

## Current status

Validated outside the Pi deployment runtime:

- Arducam B0589 USB/UVC capture at 1920x1080 MJPEG 60 FPS;
- the current ZBook live-inference baseline, including the 1920x391 software crop and
  YOLO input size 960;
- real-time vehicle-tracking benchmark data on the ZBook;
- a dedicated `10.77.0.0/24` wired RAVE link to the Comma 3X;
- Comma-side safe Ethernet provisioning with bounded Params status;
- native StarPilot/Aether RAVE settings/status UI groundwork;
- ASIX AX88179/AX88179A and Realtek RTL8153 C3X Ethernet paths as hardware-validated, including reboot persistence.

Still scaffolding or not yet validated on the Pi 5 hard target:

- Pi camera/inference/tracking runtime and thermal/performance envelope;
- Hailo/accelerator execution in the production deployment stack;
- production RAVE metadata transport, pairing, authentication, replay protection,
  freshness enforcement, and receiver;
- final danger-zone/temporal-state model;
- installer, OS image, Debian packaging, production systemd services, signed updates,
  and rollback;
- automotive power/shutdown and complete vehicle-environment validation.

The repository's synthetic loop and JSON debug path remain development-only.
`protocol/rave.proto` is still a proposed schema and is not a production wire
contract.

## Enforced safety boundary

The Raspberry Pi is a stand-alone perception sensor. It must never access Panda,
vehicle CAN, or vehicle-control interfaces, and Pi software must not include Panda or
CAN dependencies. The Comma side consumes simple RAVE status/metadata and must not be
required for RAVE to determine its own perception state.

Loss, staleness, invalidity, authentication failure, session mismatch, or link loss
must make RAVE unavailable rather than preserving a last-known occupancy state.

## Hard target performance rule

Raspberry Pi 5 is the hard deployment target. Every feature must fit the required
real-time latency/performance envelope from the start. RAVE prioritizes low frame age
over nominal FPS, drops stale frames rather than queuing them, preserves compute
headroom, and only spends additional compute on temporal/model complexity after Pi 5
headroom is measured.

## Development-only mock

Install development dependencies in a virtual environment, then run checks:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
rave config-check --config config/rave.toml.example
rave doctor --config config/rave.toml.example
pytest
```

The synthetic loop requires both the example configuration's explicit development
mode and a command-line acknowledgement:

```bash
rave-edge --config config/rave.toml.example --development-mock
```

Without that flag it exits immediately. The installed systemd service deliberately
does not pass the flag, has no automatic restart policy, and has no install target.
It therefore remains inactive by default and cannot masquerade as a production
runtime.

## Repository map

```text
edge/                 Configuration, health checks, and mock-only runtime
protocol/             Proposed future wire schema (source only)
setup-ui/             First-boot UI scaffolding
image/                OS image configuration scaffolding
packaging/            Debian packaging scaffolding
hardware/             Candidate and partially validated hardware notes
models/               Model bundle format examples; no production weights
scripts/              Installer and diagnostics scaffolding
systemd/              Inactive-by-capability service definitions
tests/                Unit tests
docs/                  Architecture, deployment, roadmap, validation baselines
.github/workflows/     CI and manual release-workflow placeholder
```
