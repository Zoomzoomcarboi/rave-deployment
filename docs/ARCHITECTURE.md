# Architecture

## Current implementation boundary

This repository implements configuration validation, health checks, and an explicit
development mock. It does not implement camera capture, inference, transport,
authentication, pairing, replay protection, or a Comma receiver. JSON messages are
internal mock/debug data only. `protocol/rave.proto` is a proposed future wire
protocol; bindings are intentionally not generated.

## Enforced trust and vehicle boundary

The Pi is a perception-only appliance. It must have no Panda or vehicle-CAN
interfaces, permissions, libraries, dependencies, or code paths. It must never send
vehicle-control commands. A future Comma-side receiver is a distinct trust boundary
and must not translate received metadata directly into Panda/CAN commands.

Proposed future data flow:

```text
Candidate camera -> capture -> inference -> tracking -> authenticated transport
                                                        |
                                                        v
                                      separately reviewed Comma receiver
```

None of the data-flow components shown above are production implementations here.

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

Authentication, pairing, replay protection, and transport are requirements, not
implemented features.

## Failure behavior

A future receiver must mark RAVE unavailable for heartbeat timeout, stale receiver
arrival state, protocol or session mismatch, authentication failure, replay,
unsupported model, invalid data, local health failure, reboot, or link loss. No
last-known occupancy state may persist beyond its receiver-measured validity window.

Any later advisory or policy use requires simulation, replay, closed-course, and road
validation outside this baseline scaffolding.
