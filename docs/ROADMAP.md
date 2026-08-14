# Roadmap

The project now has validated development-host and Comma networking/UI baselines, but
the Pi 5 perception appliance and production metadata receiver remain incomplete.

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
- **Not yet Pi 5 performance validation**

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

## Gate 2C — next
- define and validate the next Comma/RAVE integration increment without expanding the
  Pi trust boundary or making the perception pipeline depend on Comma state
- preserve the simple, low-latency interface and explicit unavailable/failure behavior

## M2 — Pi 5 perception runtime
- camera capture and latest-frame buffering
- optimized inference on the selected accelerator/runtime
- vehicle tracking
- temporal state/danger-zone determination
- frame-age, latency, CPU/accelerator, memory, and thermal telemetry
- prove compute headroom before adding heavier temporal features

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
- thermal and power testing
- closed-course testing
- controlled road testing
