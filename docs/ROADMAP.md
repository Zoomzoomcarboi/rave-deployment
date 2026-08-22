# Roadmap

The project now has validated development-host, Comma networking/UI, and Pi 5
camera-to-Hailo scheduling/performance baselines. The production Pi perception
service, postprocessing/tracking/temporal stack, and production metadata receiver
remain incomplete.

## M0 — Architecture foundation — complete
- Repository layout
- Configuration validation
- Mock message schema
- Service/image/release placeholders
- Panda/CAN trust boundary

## M1 — Camera and x86 inference baseline — validated on development hardware
- Arducam B0589 1920x1080 MJPEG 60 FPS capture
- Current 1920x391 software crop and YOLO input 960 baseline
- Live inference runner and performance logging
- Vehicle-tracking benchmark

## Gate 2A — dedicated Comma Ethernet provisioning — pass
- `10.77.0.2/24`, no gateway/DNS, never-default, IPv6 disabled
- exactly-one-adapter discovery and backend-owned NetworkManager profile
- bounded `RaveNetworkStatus` and persisted `RaveNetworkProfileUuid`
- Wi-Fi/default-route preservation
- ASIX and Realtek paths hardware-validated, including reboot persistence

## Gate 2B — native StarPilot/Aether UI groundwork — pass
- RAVE as a first-class StarPilot settings category/page
- Params/backend-state-driven network status
- no UI-owned NetworkManager/D-Bus/`nmcli` work
- managed-runtime focused tests/compile validation

## Gate 2C — RX-only runtime/UI contract — validated external integration baseline
- preserve RAVE as optional/advisory information
- no continuous Comma -> Pi vehicle-state dependency
- `vehicleStateTxHz = 0.0` runtime invariant
- fail-dark warning semantics and simple WATCH/WARNING/NONE presentation
- no generic openpilot `commIssue` dependency on RAVE availability

## M2A — Pi 5 camera-to-Hailo V5 architecture — hardware-validated baseline
- Raspberry Pi 5 + AI HAT+ 26 TOPS / Hailo-8
- actual RAVE YOLO26n detector at input size 960
- 1920x1080 MJPEG 60 FPS camera transport
- native JPEG 1/2 decode to 960x540
- capture-driven, one-slot latest-frame scheduler
- approximately 30 Hz accepted work
- hard 5 ms stale-input guard before decode
- no prepared-input queue
- V5 result rate 29.49 FPS
- userspace arrival -> raw Hailo result: 36.076 ms p50, 41.675 ms p95,
  44.582 ms p99
- benchmark/reference code and full measurement record in
  `PERCEPTION_V5_BASELINE.md`

## M2B — production Pi perception runtime — next
- integrate the frozen V5 scheduling/preprocess architecture into one canonical
  production runtime
- implement and validate YOLO26 raw-head decode/postprocessing
- vehicle tracking
- temporal state/danger-zone determination
- frame-age, tracker-age, output-age, CPU/accelerator, memory, and thermal telemetry
- fail-unavailable behavior for camera/decode/inference stalls
- prove compute headroom before adding heavier temporal features
- keep model-training/calibration refinement independent of deployment work while
  preserving the reviewed runtime contract

## M3 — authenticated metadata transport and receiver
- production wire schema
- sender/receiver implementation
- pairing and authentication
- replay protection and session identity
- receiver-local freshness and timeout enforcement
- logging-only validation before any higher-level use

## M4 — product deployment
- reproducible RAVE OS image
- signed packages and model bundles
- Raspberry Pi Imager catalogue
- update/rollback
- exact hardware self-test/compatibility gate
- automotive power/shutdown design

## M5 — validation
- simulation
- replay
- fault injection
- sustained thermal/USB/I/O/headroom testing
- closed-course testing
- controlled road testing
