# Validated RAVE baselines

Last updated: 2026-08-22.

This document records facts measured or hardware-validated during RAVE development.
It does **not** make the repository road-ready or production-ready. Production
postprocessing/tracking/temporal logic, the production metadata protocol/receiver,
authenticated transport, end-to-end fault handling, and vehicle qualification remain
open work.

## Safety and platform requirements

- Raspberry Pi 5 is the hard deployment target. Features must fit its required
  real-time latency/performance envelope from the start; do not build a heavier path
  first and plan to optimize it later.
- Low frame age is more important than nominal FPS. Stale frames must be dropped
  rather than queued.
- Preserve Pi 5 compute headroom. More expensive temporal/model features may be added
  only when measured Pi 5 headroom remains available.
- The camera may run at 60 FPS while the model pipeline is intentionally bounded near
  30 FPS.
- RAVE must determine its own perception/danger state. The Comma side is a consumer
  of simple RAVE status/metadata and must not be required to make the perception
  pipeline function.
- The Pi remains perception-only: no Panda/CAN access, vehicle-control dependencies,
  credentials, permissions, or direct control commands.

## Camera and x86 inference baseline

Hardware-validated development camera: Arducam B0589 USB/UVC (`04b4:0822`).

Known-good capture path on the HP ZBook Studio G7:

- 1920x1080 MJPEG at 60 FPS via V4L2/FFmpeg;
- native stream-copy recording to 10-minute MKV segments;
- no software flip in the validated capture path;
- canonical live-inference software crop: 1920x391, `y=300:691`;
- YOLO input size: 960;
- confidence threshold used for the validated development baseline: 0.05;
- model loop intentionally bounded around 30 FPS while camera capture remains 60 FPS.

RAVE Live Inference v3.2.0 (`2026.08.08-prod3`) was hardware-validated on an HP
ZBook Studio G7 with Quadro T2000 Max-Q (4 GB) and returned high-30-FPS end-to-end
operation after the capture/inference pipeline fixes. This remains an x86/NVIDIA
development baseline.

A separate vehicle-tracking benchmark used a 1920x530 crop at `(x=0,y=212)`, YOLO
`imgsz=960`, confidence `0.05`, IoU `0.50`, and a matched 30 FPS replay rate. Measured
YOLO+tracking latency was 13.13 ms median and 15.94 ms p95, with 29.83 FPS replay
throughput and 8.37 ms mean frame age. Do not silently treat that benchmark crop as
the canonical live-inference crop; it was a specific benchmark configuration.

## Raspberry Pi 5 + Hailo-8 perception baseline

Hardware used for the 2026-08-22 Pi validation:

- Raspberry Pi 5 Model B Rev 1.1, 4 GB RAM;
- Raspberry Pi AI HAT+ 26 TOPS;
- Hailo-8 accelerator;
- Raspberry Pi OS Lite 64-bit / Debian 13 Trixie;
- kernel `6.18.39+rpt-rpi-2712`;
- HailoRT `4.23.0`.

The actual RAVE `real_world_v1/best.pt` YOLO26n detector was exported at `imgsz=960`
for Hailo-8. The 60-image calibration HEF used for performance validation has SHA-256:

```text
ebcda77f0694db7023dfd3926a357a8097e714cbc5985fe094a46805d3f48c19
```

The Pi runtime successfully parsed and executed this HEF despite it being produced by
the newer Hailo 2026-07 compiler suite. The HEF input is 960x960x3 UINT8 NHWC and the
model returns six raw UINT16 YOLO26 head tensors. Hailo NMS is not baked into this
artifact.

Standalone actual-model Hailo measurements:

- streaming throughput: **52.30 FPS**;
- 793 frames in 15 seconds;
- Hailo temperature: 52.39 C min, 54.73 C average, 55.78 C max;
- blocking hardware inference: 18.689 ms p50, 18.710 ms p95, 18.720 ms p99;
- complete blocking call: approximately 18.90 ms p50.

The 60-image quantization artifact is not final model qualification. The export path
warned that more than 300 representative images are recommended for INT8 calibration,
with a substantially larger representative set preferred for final accuracy work.

## Pi V5 latest-frame architecture — frozen scheduling baseline

The validated V5 stage uses:

- B0589 1920x1080 MJPEG at 60 FPS;
- one-slot newest compressed frame only;
- capture-driven eligibility near 30 Hz;
- a hard 5 ms maximum input age at decode eligibility;
- native 1/2 JPEG decode to 960x540;
- half-scale crop `y=150:346`, producing 960x196 content;
- RGB conversion and 114-valued vertical letterbox to 960x960;
- one-slot newest prepared input only;
- blocking Hailo YOLO26n inference;
- no growing queues and no stale-result fallback.

A 20-second V5 run measured:

```text
Captured frames:              1176
Capture rate:                 58.79 FPS
Compressed overwrites:          84
Rate-limited arrivals:          380
Stale-frame drops (>5 ms):      120
Decode attempts:                591
Decode rate:                  29.54 FPS
Decode failures:                  0
Prepared frames:                591
Prepared overwrites:              0
Inferences completed:           590
Raw-result rate:              29.49 FPS
```

Latency from compressed-MJPEG userspace arrival:

| Metric | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| Arrival -> decode start | 0.049 ms | 2.201 ms | 3.225 ms |
| Half JPEG decode | 16.501 ms | 19.895 ms | 21.966 ms |
| RAVE preprocess | 0.573 ms | 0.663 ms | 0.921 ms |
| Arrival -> inference start | 17.337 ms | 22.846 ms | 25.625 ms |
| Hailo blocking inference | 18.747 ms | 18.952 ms | 19.680 ms |
| Arrival -> raw inference result | **36.076 ms** | **41.675 ms** | **44.582 ms** |

These arrival-based measurements do not include sensor exposure or USB/UVC transport
before the compressed frame reaches Pi userspace. They also stop at raw Hailo tensors;
YOLO26 postprocessing, tracking, temporal reasoning, danger-zone logic, metadata
transport, and C3X receiver latency are not included.

V5 is frozen as the scheduling baseline for production-runtime implementation because
it maintained approximately 30 Hz while aggressively reducing stale-input tail latency.
Further scheduler changes require new measured evidence and regression testing. Full
measurement history and architecture details are in `PERCEPTION_V5_BASELINE.md`.

## Dedicated RAVE Ethernet link

The runtime transport baseline is a dedicated wired Ethernet link. Wi-Fi is not the
intended RAVE runtime transport.

Validated addressing:

```text
RAVE computer / Pi 5:         10.77.0.1/24
Comma 3X:                     10.77.0.2/24
```

Comma-side NetworkManager requirements validated during Gate 2A/2B work:

- manual IPv4 `10.77.0.2/24`;
- no gateway;
- no DNS and ignore automatic DNS;
- `ipv4.never-default=yes`;
- IPv6 disabled;
- autoconnect enabled;
- Wi-Fi/default route remains unchanged.

StarPilot-side provisioning must discover exactly one eligible USB Ethernet adapter
and must not hardcode `eth0`, a MAC address, or a profile UUID. Missing or ambiguous
eligible adapters fail unavailable rather than modifying an unrelated interface.

Physically validated C3X adapter paths:

- ASIX AX88179/AX88179A: driver `ax88179_178a`, USB ID `0b95:1790`. This path passed
  pairing, profile reuse, hotplug, and reboot-persistence validation.
- Realtek RTL8152/RTL8153: driver `r8152`, tested USB ID `0bda:8153`. This path passed
  UI pairing, profile reuse, hotplug recovery, and untouched-reboot persistence.
  After reboot it returned `connected` at `10.77.0.2/24` using the same backend-owned
  profile without re-pairing, replugging, SSH, or manual NetworkManager intervention.
  An earlier reboot enumeration/reset event was superseded by the repeat passing
  untouched-reboot validation and is retained only as a transient test observation.

During the latest C3X validation, the generated RAVE NetworkManager profile UUID was
`3c3fa201-afe0-4bab-bfba-4dd83270f4fe`. This is a recorded test artifact, not a value
to hardcode.

## Comma / StarPilot integration baseline

Gate 2A/2B established Comma-side network-management and native StarPilot/Aether UI
integration groundwork. Later RX-only/Gate 2C work preserved RAVE as optional advisory
information and removed the continuous Comma -> Pi vehicle-state runtime dependency.
This is still distinct from the Pi perception-metadata receiver.

The managed `rave_networkd` process is controlled by the live `RaveEnabled` Param,
uses the dedicated adapter provisioning rules above, and exposes bounded status via
`RaveNetworkStatus`. Status states are:

- `disabled`
- `adapterMissing`
- `adapterAmbiguous`
- `configuring`
- `connected`
- `profileConflict`
- `networkError`

The generated profile identity is stored in `RaveNetworkProfileUuid` so the backend
owns and can safely reuse its profile without touching unrelated networking.

The UI contract is intentionally thin:

- native StarPilot/Aether Raylib UI;
- Params/state driven;
- no UI-owned networking;
- no D-Bus or `nmcli` calls from the UI;
- no new UI networking threads;
- no sleeps/blocking work in render/update loops;
- no stale `Connected` presentation after backend state changes;
- unsafe on-road configuration changes must not be introduced.

The Gate 2B managed-runtime validation was performed against StarPilot integration
snapshot `700b585`; the focused runtime validation passed 45 tests plus 15 subtests
and Python compile checks. Keep that identifier as traceability for the external
integration baseline, not as a dependency of this repository.

## Still open before product deployment

- production Pi perception service and reproducible lifecycle management;
- correct YOLO26 raw-head decode/postprocessing and detection-equivalence validation;
- production tracking and temporal/danger-zone determination;
- sustained Pi thermal, power, USB/I/O, memory, and compute-headroom validation with
  the full perception stack;
- production RAVE metadata wire protocol and sender/receiver implementation;
- pairing, authentication, replay protection, freshness timeouts, and fault injection;
- Pi-side reproducible network provisioning and service packaging;
- automotive power/shutdown behavior;
- signed/atomic model and software update path;
- simulation, replay, closed-course, and controlled road validation.
