# Architecture

## Current implementation boundary

The in-repository edge runtime still implements configuration validation, health
checks, and an explicit development mock. The production Pi perception service,
tracking, authenticated metadata transport, pairing, replay protection, and a RAVE
metadata receiver are not implemented here yet. JSON messages remain internal
mock/debug data only. `protocol/rave.proto` remains a proposed future wire schema.

Hardware-validated work now exists for the Arducam B0589, the Raspberry Pi 5 + Hailo
camera-to-raw-inference stage, ZBook inference/tracking, the dedicated C3X Ethernet
path, and StarPilot network/UI integration. See `VALIDATED_BASELINES.md` and
`PERCEPTION_V5_BASELINE.md`.

Gate 1 adds an unprivileged `rave-webd` foundation with a versioned read-only API,
static local browser shell, typed availability/network states, and replaceable provider
interfaces. Its providers report camera, perception, Hailo, Comma link, updates, and
system measurements as unavailable/not integrated. It neither accesses hardware nor
actuates networking. See `MANAGEMENT_NETWORK.md`.

## Hard target and real-time architecture

Raspberry Pi 5 is the hard deployment target. Architecture decisions must satisfy the
Pi 5 real-time performance and latency envelope before they are accepted. In
particular:

- low frame age is more important than nominal FPS;
- stale frames are dropped rather than queued;
- the camera may run at 60 FPS while the model path remains intentionally bounded
  around 30 FPS;
- compute headroom is preserved for thermal, I/O, tracking, transport, and future
  temporal state work;
- heavier temporal/model features are added only after measured Pi 5 headroom exists;
- RAVE determines its own perception/danger state and does not depend on the Comma to
  complete that reasoning.

## Frozen V5 camera-to-Hailo scheduling baseline

The validated V5 stage is the canonical scheduling architecture for the next
production Pi runtime implementation:

```text
Arducam B0589 1920x1080 MJPEG @ 60 FPS
        |
        v
one-slot latest compressed frame
        |
        +-- >5 ms old at decode eligibility -> DROP
        |
        v
native JPEG 1/2 decode -> 960x540
        |
        v
crop y=150:346 -> 960x196
        |
        v
RGB + vertical letterbox -> 960x960 UINT8 NHWC
        |
        v
YOLO26n 960 on Hailo-8
        |
        v
six raw output tensors
```

The scheduler is capture-driven. It does not wake on an independent fixed 30 Hz timer
and then consume whatever frame happens to be waiting. Newly arrived frames become
eligible at approximately 30 Hz; if an eligible frame is already older than 5 ms at
decode start, it is discarded before JPEG decode. Both compressed-frame and prepared
input storage are single-slot latest-value buffers. A growing queue is prohibited.

The canonical full-resolution crop remains 1920x391, `y=300:691`. V5 performs native
1/2 JPEG decode and uses the measured half-scale mapping `y=150:346`, avoiding a
second resize while retaining the 960 model input. Production integration must verify
that preprocessing geometry remains equivalent rather than silently changing crop,
rounding, interpolation, RGB order, or letterbox behavior.

The V5 benchmark stops at raw Hailo tensors. YOLO26 raw-head decoding, tracking,
temporal/danger-zone logic, and transport are later stages and must preserve the same
freshness-first/no-backlog rule.

## Enforced trust and vehicle boundary

The Pi is a perception-only appliance. It must have no Panda or vehicle-CAN
interfaces, permissions, libraries, dependencies, credentials, or code paths. It
must never send vehicle-control commands. A Comma-side receiver is a distinct trust
boundary and must not translate received metadata directly into Panda/CAN commands.

Target data flow:

```text
Arducam B0589 -> V5 latest-frame capture/decode -> YOLO26 inference
                                                        |
                                                        v
                                             tracking/temporal state
                                                        |
                                                        v
                                      authenticated metadata transport
                                                        |
                                                        v
                                separately reviewed Comma receiver/UI
```

The Comma path is deliberately simple: receive validated RAVE status/metadata, enforce
its own freshness/session rules, and surface availability/state. It is not the source
of RAVE perception truth.

## Freshness clocks

Pi-side V5 input age is measured from local userspace MJPEG arrival to local decode
eligibility/result. This is a same-device monotonic measurement. It does not include
sensor exposure or USB/UVC transfer before userspace arrival.

Cross-device monotonic clocks are not comparable. A future C3X receiver must record
its own monotonic arrival time for every authenticated frame/heartbeat and use that
receiver-local clock for freshness and timeout decisions.

Every sender boot must create an unpredictable boot/session identifier. Frame
sequence numbers are scoped to that identity. A receiver must reset accepted sequence
state only after an authenticated session transition and reject old-session or
out-of-window messages. Persistent device identity and ephemeral boot/session identity
are separate fields.

## Failure behavior

At the Pi perception stage:

- stale compressed inputs are dropped before expensive decode/inference;
- JPEG decode failure drops the frame;
- no prepared-input backlog is permitted;
- a prior perception result must not be reused as if it were current;
- camera/decode/inference stalls must feed higher-level health logic that makes RAVE
  unavailable rather than preserving stale state.

A future receiver must mark RAVE unavailable for heartbeat timeout, stale receiver
arrival state, protocol or session mismatch, authentication failure, replay,
unsupported model, invalid data, local health failure, reboot, or link loss. No
last-known occupancy state may persist beyond its receiver-measured validity window.

Any later advisory or policy use requires simulation, replay, fault injection,
closed-course, and controlled road validation.
