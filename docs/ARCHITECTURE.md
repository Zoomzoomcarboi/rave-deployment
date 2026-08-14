# Architecture

## Current implementation boundary

The in-repository edge runtime still implements configuration validation, health
checks, and an explicit development mock. Production Pi camera capture, inference,
tracking, authenticated metadata transport, pairing, replay protection, and a RAVE
metadata receiver are not implemented here yet. JSON messages remain internal
mock/debug data only. `protocol/rave.proto` remains a proposed future wire schema.

Hardware-validated work now exists outside this scaffolding for the Arducam B0589,
ZBook inference/tracking, the dedicated C3X Ethernet path, and StarPilot network/UI
integration. See `VALIDATED_BASELINES.md`.

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

## Enforced trust and vehicle boundary

The Pi is a perception-only appliance. It must have no Panda or vehicle-CAN
interfaces, permissions, libraries, dependencies, credentials, or code paths. It
must never send vehicle-control commands. A Comma-side receiver is a distinct trust
boundary and must not translate received metadata directly into Panda/CAN commands.

Target data flow:

```text
Arducam B0589 -> latest-frame capture -> inference -> tracking/temporal state
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

## Freshness and session rules for a future receiver

Monotonic clocks are local to each device and must never be compared across the Pi
and receiver. A receiver must record its own monotonic arrival time for every frame
and heartbeat. Freshness and timeout decisions use elapsed receiver time since that
arrival. Sender processing latency may be validated independently but cannot establish
cross-device freshness.

Every sender boot must create an unpredictable boot/session identifier. Frame
sequence numbers are scoped to that identity. A receiver must reset accepted sequence
state only after an authenticated session transition and reject old-session or
out-of-window messages. Persistent device identity and ephemeral boot/session identity
are separate fields.

## Failure behavior

A future receiver must mark RAVE unavailable for heartbeat timeout, stale receiver
arrival state, protocol or session mismatch, authentication failure, replay,
unsupported model, invalid data, local health failure, reboot, or link loss. No
last-known occupancy state may persist beyond its receiver-measured validity window.

Any later advisory or policy use requires simulation, replay, fault injection,
closed-course, and controlled road validation.
