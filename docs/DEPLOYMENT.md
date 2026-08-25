# Deployment workflow

There is no customer deployment today. No signed release image, production RAVE
metadata receiver, pairing/authentication flow, automotive power design, or complete
vehicle-environment qualification exists yet.

There are hardware-validated development baselines that must be preserved as
deployment work moves forward. See `VALIDATED_BASELINES.md` and
`PERCEPTION_V5_BASELINE.md`.

## Hard target

Raspberry Pi 5 is the deployment target and must be treated as the performance budget
from the beginning. Deployment candidates that only work after assuming desktop-class
compute are not acceptable. Low frame age, stale-frame dropping, bounded processing,
and compute headroom are release requirements rather than later optimizations.

## Frozen V5 perception-stage baseline

The next Pi production runtime must begin from the hardware-validated V5 scheduling
architecture rather than recreating a queued or independent timer-driven pipeline:

- B0589 1920x1080 MJPEG at 60 FPS;
- one-slot newest compressed frame;
- capture-driven eligibility near 30 Hz;
- reject a frame already older than 5 ms at decode eligibility;
- native 1/2 JPEG decode to 960x540;
- measured half-scale crop `y=150:346`, corresponding to the canonical full-resolution
  `y=300:691` crop;
- 960x960 RGB UINT8 model input;
- one-slot newest prepared input;
- Hailo-8 YOLO26n inference;
- no stale-result fallback.

The reference benchmark lives at `scripts/benchmarks/rave_v5_pi_benchmark.py`. It is
not a production service and must not be enabled as one without the production-runtime
review gate described in `PERCEPTION_V5_BASELINE.md`.

The current 60-calibration-image HEF is a performance artifact, not the final qualified
model bundle. Training, calibration, and detection refinement may continue in parallel
with deployment engineering.

## Dedicated runtime network baseline

The intended runtime transport is a dedicated wired Ethernet link:

```text
RAVE computer / Pi 5          10.77.0.1/24
Comma 3X                      10.77.0.2/24
```

The Comma-side RAVE profile uses no gateway or DNS, is `never-default`, disables IPv6,
and must preserve the device's normal Wi-Fi/default-route behavior. Provisioning is
owned by the StarPilot backend and must work without requiring SSH, terminal commands,
or manual NetworkManager setup on a fresh supported adapter.

Both supported C3X adapter paths have passed hardware validation including reboot
persistence: ASIX AX88179/AX88179A (`ax88179_178a`, `0b95:1790`) and Realtek RTL8153
(`r8152`, tested `0bda:8153`). An earlier Realtek reboot-enumeration/reset event was
not reproduced during the final untouched-reboot validation and is treated as a
transient test event rather than a qualification failure.

## Development path

Developers can validate configuration and run the explicitly gated mock as described
in the repository README. `scripts/install.sh`, Debian packaging, systemd services,
and image files are still scaffolding and do not install the V5 benchmark as a
production Pi perception service.

Production integration of V5 must receive exact changed-file review, syntax/static
checks, relevant unit tests, Pi benchmark regression, and failure-path review before it
can replace the mock-only runtime boundary.

The Gate 2B candidate adds the boot-enabled `RAVE-Setup` AP, bounded DHCP, a web
listener restricted to `192.168.77.1:8080`, and a read-only Pi management provider.
The historical Gate 2A build record remains in `RAVE_OS_GATE2A_BUILD.md`. A flashed
Gate 2B engineering image has supplied diagnostic boot evidence and live validation of
three management-network corrections, but that image required manual runtime repair
and reproduced an SSH-listener lifecycle failure after reboot. The corrected current
source is therefore not yet clean-image Pi-validated. Qualification requires a fresh
source-built image and the five consecutive untouched boots in
`GATE2B_NETWORK_ACCEPTANCE.md`.

## Release/update requirements

Application and model updates must eventually be signed, atomic, reversible, and
subject to safety-state controls. Release readiness also requires a reproducible Pi
image, exact hardware compatibility checks, thermal/power validation, fault injection,
and a rollback path. No production update pipeline is implemented yet.
