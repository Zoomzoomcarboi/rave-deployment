# Architecture

## Trust boundary

`rave-edge` produces perception metadata. `rave-bridge`, running inside a compatible Starpilot fork, is responsible for authentication, compatibility checks, freshness validation, plausibility checks, logging, UI integration, and any later policy use.

```text
Camera -> Capture -> Crop/letterbox -> Hailo detection -> Tracking
       -> Temporal/risk analysis -> Authenticated metadata -> RAVE Bridge
```

## Failure behavior

The bridge must mark RAVE unavailable when any of these occur:

- heartbeat timeout;
- stale frame timestamp;
- protocol mismatch;
- failed authentication;
- unsupported model version;
- unreasonable latency;
- invalid coordinates or risk values;
- camera or accelerator health failure;
- Pi reboot or Ethernet loss.

No last-known occupancy state may persist after its validity window.

## Phased integration

1. Capture and offline logging.
2. Live metadata transport to a laptop receiver.
3. Comma bridge logging only.
4. UI visualization.
5. Advisory lane-change gating after validation.
6. Potential planner integration only after extensive simulation, replay, closed-course, and road validation.
