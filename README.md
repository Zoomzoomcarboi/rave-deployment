# RAVE Deployment

> Development scaffolding plus validated integration baselines. RAVE is not
> road-ready, production-ready, or able to control a vehicle.

RAVE (Rear Awareness Vision Engine) is a Raspberry Pi 5-targeted rear-awareness
perception system. This repository defines the deployment boundary, safety rules,
hardware profile, packaging direction, and reproducible validation records.

The original edge runtime in this repository is still development scaffolding.
However, camera/inference work, dedicated-Ethernet/StarPilot work, and the Pi 5 V5
camera-to-Hailo benchmark have now produced hardware-validated component baselines.
See [`docs/VALIDATED_BASELINES.md`](docs/VALIDATED_BASELINES.md) and
[`docs/PERCEPTION_V5_BASELINE.md`](docs/PERCEPTION_V5_BASELINE.md).

## Install RAVE OS

End-user images and flashing instructions are available in
**[release/](release/README.md)**.

The current image is a **Gate 2B test prerelease**. It has passed image-build and
artifact validation but has not yet completed physical Raspberry Pi 5 boot
qualification.

## Current status

Hardware-validated component baselines now include:

- Arducam B0589 USB/UVC capture at 1920x1080 MJPEG 60 FPS;
- the canonical 1920x391 `y=300:691` RAVE crop and YOLO input size 960;
- Raspberry Pi 5 + AI HAT+ / Hailo-8 execution of the actual RAVE YOLO26n 960 HEF;
- V5 capture-driven, latest-frame, approximately 30 Hz scheduling with a 5 ms
  stale-input guard and no growing frame queue;
- a 20-second V5 Pi benchmark at 29.49 raw results/s with userspace-arrival to raw
  Hailo result latency of 36.076 ms p50, 41.675 ms p95, and 44.582 ms p99;
- real-time vehicle-tracking benchmark data on the ZBook;
- a dedicated `10.77.0.0/24` wired RAVE link to the Comma 3X;
- Comma-side safe Ethernet provisioning with bounded Params status;
- native StarPilot/Aether RAVE settings/status UI groundwork;
- ASIX AX88179/AX88179A and Realtek RTL8153 C3X Ethernet paths as hardware-validated,
  including reboot persistence.

Still scaffolding, incomplete, or outside the validated V5 benchmark boundary:

- production Pi perception service integration and lifecycle management;
- YOLO26 raw-head decode/postprocessing on the Pi;
- production vehicle tracking, temporal/danger-state logic, and their end-to-end
  Pi frame-age/headroom validation;
- production RAVE metadata transport, pairing, authentication, replay protection,
  freshness enforcement, and receiver;
- final model calibration/accuracy qualification;
- installer, OS image, Debian packaging, production systemd services, signed updates,
  and rollback;
- automotive power/shutdown and complete vehicle-environment validation.

The repository's synthetic loop and JSON debug path remain development-only.
`protocol/rave.proto` is still a proposed schema and is not a production wire
contract.

The management foundation now includes an unprivileged `rave-webd` package, a static
Galaxy-language shell, and read-only `/api/v1` status/network/system schemas. All real
hardware/link/update providers remain unavailable/not integrated. The image directory contains the pinned Gate 2A `rpi-image-gen` image definition and build entry point. A real Raspberry Pi 5 image has passed build and artifact validation; physical Pi boot validation remains Gate 2B.

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

The V5 scheduling baseline is now frozen for production-runtime implementation:
capture-driven eligibility, one-slot latest-frame storage, approximately 30 Hz accepted
work, and rejection of frames already older than 5 ms at decode eligibility. Do not
replace this with a timer-driven backlog or queued-frame design without new measured
evidence and regression testing.

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

## Pi V5 benchmark reference

`scripts/benchmarks/rave_v5_pi_benchmark.py` records the benchmark/reference code for
the frozen V5 camera-to-Hailo stage. It requires the Pi-side GStreamer, OpenCV, NumPy,
and Hailo Python runtime already present on the validated development Pi. It is not
installed or launched by the production service scaffolding.

## Repository map

```text
edge/                 Configuration, health checks, and mock-only runtime
protocol/             Proposed future wire schema (source only)
setup-ui/             Permanent local management API and static browser shell foundation
image/                Pinned RAVE OS image definition and build tooling
packaging/            Debian packaging scaffolding
hardware/             Candidate and partially validated hardware notes
models/               Model bundle format examples; no production weights
scripts/              Installer, diagnostics, and benchmark/reference utilities
systemd/              Inactive-by-capability service definitions
tests/                Unit tests
docs/                  Architecture, deployment, roadmap, validation baselines
.github/workflows/     CI and manual release-workflow placeholder
```
