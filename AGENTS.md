# AGENTS.md — RAVE Deployment / RAVE OS Engineering Contract

**Repository:** `Zoomzoomcarboi/rave-deployment`  
**Applies to:** Raspberry Pi 5 RAVE appliance, RAVE OS/image, Pi-side perception runtime, management networking, local web UI, model/software update system, packaging, diagnostics, and Pi-to-Comma transport.  
**Last consolidated:** 2026-08-22

RAVE means **Rear Awareness Vision Engine**.

This repository is the deployment authority for the **Raspberry Pi 5 side of RAVE**. It is not the StarPilot/openpilot repository and it must not absorb vehicle-control responsibilities. The Pi is a stand-alone perception appliance that owns camera ingest, detection, tracking, temporal/danger-state reasoning, local health, appliance management, and the authenticated RAVE output sent to a separately reviewed Comma/StarPilot receiver.

RAVE is safety-sensitive development. A benchmark pass, a working model, a working web page, a successful boot, or a successful C3X link does **not** by itself make the complete system road-ready or production-ready.

This file is a hard engineering contract for coding agents and reviewers. It exists so validated decisions remain validated, developer-machine state never leaks into shipped RAVE units, and convenience features do not quietly compromise freshness, isolation, security, or reproducibility.

**Before changing this repository, read this file.** If a requested change conflicts with a rule here, surface the conflict. Do not silently reinterpret the architecture.

---

## 0. Authority and evidence order

When two sources disagree, use this order unless the user explicitly establishes a newer decision:

1. This `AGENTS.md` hard contract.
2. The newest hardware-validated RAVE baseline in this repository.
3. `docs/PERCEPTION_V5_BASELINE.md` for the frozen V5 camera-to-Hailo stage.
4. `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/VALIDATED_BASELINES.md`, and the current security contract.
5. Current code and tests.
6. Older design notes and historical context.
7. External reviewers, AI agents, libraries, examples, and conventional industry patterns.

A reviewer recommendation is evidence, not authority. Greptile, CodeRabbit, Codex self-review, DeepSeek, static analyzers, and similar tools may identify real defects, but their proposed architecture must still obey this contract.

### Agent Skills

Generic Agent Skills are optional workflow aids, not project authority.

- Use an individual skill only when it materially improves the current task.
- Prefer the smallest applicable skill; do not chain skills by default.
- Do not invoke a skill merely because one exists.
- Skill instructions never override this `AGENTS.md`, validated RAVE baselines, architecture contracts, current code, or tests.
- If a skill conflicts with RAVE scope, safety, performance, trust-boundary, or behavior-preservation requirements, follow RAVE and surface the conflict.
- The `using-agent-skills` SessionStart hook is not required for RAVE development; individual skills may be invoked explicitly when useful.

When project evidence evolves, the **newest completed hardware validation supersedes an older intermediate result** unless the newer record explicitly says otherwise.

Do not silently promote a planned behavior into a validated fact.

Use precise status language:

- **implemented** — code exists;
- **unit-tested** — automated tests cover it;
- **host-validated** — validated on a development workstation;
- **Pi-validated** — measured on the Raspberry Pi 5 target;
- **hardware-validated** — validated with the named physical hardware;
- **integrated** — connected to the surrounding RAVE system;
- **release-qualified** — all defined release gates for that capability are complete;
- **production-ready** — do not use this term for complete RAVE until the complete system release gates are actually satisfied.

---

## 1. Priority order

RAVE decisions follow this order:

1. Safety and truthful availability state.
2. Low end-to-end latency and low frame age.
3. Deterministic, bounded behavior.
4. Reliability and fail-safe/fail-unavailable behavior.
5. Raspberry Pi 5 compute, thermal, memory, I/O, and storage headroom.
6. Security and reproducible deployment.
7. Clear appliance UI/UX.
8. Maintainability.
9. Feature richness and visual extras.

If a lower-priority feature conflicts with a higher-priority requirement, the feature loses.

Do not trade freshness, isolation, rollback, or reproducibility for nominal FPS, model complexity, a prettier dashboard, more telemetry, or development convenience.

---

## 2. Repository scope and trust boundary

This repository owns the Pi-side RAVE appliance.

### Pi-side responsibilities

The RAVE Pi may own:

- B0589 camera discovery and capture;
- V5 freshness-first scheduling;
- preprocessing;
- Hailo-8 inference;
- YOLO26 raw-head decode/postprocessing after it is correctly implemented and validated;
- object tracking;
- temporal state estimation;
- system-derived danger-zone/threat logic;
- local RAVE health/availability state;
- authenticated RAVE metadata transport;
- Pi appliance networking;
- first-boot provisioning;
- local web management UI;
- local diagnostics;
- approved model updates;
- approved RAVE OS/application updates;
- device identity and local credentials.

### Pi-side prohibited responsibilities

The RAVE Pi must not contain or acquire:

- Panda interfaces;
- vehicle CAN access;
- vehicle-control libraries or credentials;
- steering commands;
- braking commands;
- acceleration commands;
- cruise-control commands;
- lateral or longitudinal planning authority;
- a hidden control path through the Comma;
- a dependency on Comma vehicle state for core perception or threat classification.

**RAVE is advisory perception. The Pi is not a vehicle-control authority.**

The Comma/StarPilot side is a separate trust boundary. It consumes already-determined RAVE status/threat metadata and applies its own receiver freshness/security/UI rules. The Pi must be able to reboot, disappear, lose power, lose Ethernet, or fail authentication without causing a generic StarPilot/openpilot vehicle-stack fault.

### Preserve the validated RX-only direction

The original continuous Comma -> Pi vehicle-state runtime path was removed after it caused the RAVE-related `commIssue`. That removal is an architectural invariant, not a temporary optimization.

Do not reintroduce without explicit architecture review and end-to-end hardware revalidation:

- continuous Comma -> Pi `carState` telemetry;
- 50 Hz `VEHICLE_STATE` transmission;
- a Pi dependency on Comma speed, turn signal, factory blind-spot state, or other vehicle state for core threat determination;
- any new high-rate Comma -> Pi telemetry merely because it is convenient.

The validated Comma-side runtime invariant is `vehicleStateTxHz = 0.0`. Preserve the system-level meaning of that invariant.

Current RAVE threat semantics are intentionally small: per-side `NONE`, `WATCH`, and `WARNING`, with left and right independently representable. Do not renumber, reuse, or silently reinterpret protocol message IDs, threat enums, or existing field meanings.

The currently established RAVE transport uses UDP port `47771` for runtime traffic and `47772` for pairing in the existing integration. Before implementing the production Pi transport, verify these against the current StarPilot receiver and make the final wire contract explicit. Do not create an incompatible alternate port/protocol by accident.

---

## 3. Raspberry Pi 5 is the hard deployment target

The Raspberry Pi 5 is the hard production target.

Current hardware-validated V5 development hardware includes:

- Raspberry Pi 5 Model B Rev 1.1, 4 GB RAM;
- Raspberry Pi AI HAT+ 26 TOPS;
- Hailo-8 accelerator;
- Raspberry Pi OS Lite 64-bit / Debian 13 (Trixie);
- validated V5 development kernel `6.18.39+rpt-rpi-2712`;
- validated Pi HailoRT `4.23.0`.

These recorded versions are evidence of the V5 benchmark environment. They are not permission to upgrade arbitrary components independently. A future RAVE OS release may use different versions only after compatibility and performance are deliberately revalidated.

Rules:

- Design for Pi 5 first; do not build a desktop-heavy implementation and plan to optimize it later.
- Preserve compute headroom for tracking, temporal logic, web management, diagnostics, thermal variance, and future safety logic.
- Frame age matters more than queued throughput.
- Capture may run faster than inference.
- Drop stale work rather than queueing it.
- Bound queues, buffers, retry loops, logging, memory growth, and disk growth.
- Benchmark model, decoder, tracking, web live-view, update activity, and diagnostics on Pi hardware when they affect the runtime envelope.
- A workstation result is not Pi evidence.

---

## 4. Frozen V5 camera-to-Hailo architecture

V5 is the frozen scheduling baseline for the next production perception runtime. Do not routinely tune or redesign it without a specific measured failure or regression.

Canonical stage:

```text
Arducam B0589 1920x1080 MJPEG @ 60 FPS
        |
        v
one-slot latest compressed frame
        |
        +-- >5 ms old at decode eligibility -> DROP
        |
        v
native JPEG 1/2 decode -> 960x540 BGR
        |
        v
crop y=150:346 -> 960x196
        |
        v
BGR -> RGB + 114-valued vertical letterbox
        |
        v
960x960 RGB UINT8 NHWC
        |
        v
YOLO26n 960 on Hailo-8
        |
        v
six raw YOLO26 output tensors
```

Hard V5 invariants:

- Camera transport is **MJPEG 1920x1080 at 60 FPS**. Do not reopen YUYV versus MJPEG without new evidence of a real defect.
- Canonical full-resolution crop is `1920x391`, `y=300:691`.
- Half-decode crop is `y=150:346` after native 1/2 JPEG decode to `960x540`.
- Model input remains `960x960` unless an explicit model/system change is benchmarked and approved.
- Capture is capture-driven, not an independent timer that periodically grabs whatever frame is waiting.
- The compressed frame store is one-slot/latest-value.
- Accepted work is approximately 30 Hz.
- A candidate older than **5 ms** at decode eligibility is rejected before expensive decode/inference.
- The prepared model input store is one-slot/latest-value.
- No inference backlog is permitted.
- A failed or dropped frame must never be replaced with a stale prior result.
- Camera startup/streaming failure must fail the benchmark/runtime unavailable; it must never look like a successful zero-sample run.

The V5 benchmark script is a **reference/benchmark utility**, not the production perception service. Production code must preserve the behavior, not blindly turn the benchmark into a daemon.

---

## 5. Freshness and time semantics

Freshness is a safety property.

- Use monotonic clocks for local age/timeout decisions.
- Wall-clock/NTP time is for logs, update metadata, and human display; it is not a safety freshness clock.
- Cross-device monotonic clocks are not comparable.
- Pi-side frame age uses Pi-local monotonic timing.
- Comma-side receiver freshness must use Comma-local arrival time.
- Sender timestamps may describe sender processing/order within one authenticated session but are not proof of receiver freshness.
- Persistent device identity and ephemeral boot/session identity are separate.

Any camera, decode, postprocess, tracker, temporal, transport, or health stall must eventually cause RAVE to become **unavailable/unknown**, not preserve stale CLEAR/WATCH/WARNING state.

---

## 6. Camera and accelerator discovery must be product-stable

Development scripts may use `/dev/video0`, but production code must not assume volatile device enumeration.

For production:

- identify the supported B0589 by stable device properties such as the validated USB identity (`04b4:0822`) and/or explicit udev rules;
- prefer a stable product symlink such as `/dev/rave-camera` if the implementation adopts one;
- fail unavailable on zero matching cameras;
- fail unavailable on multiple ambiguous matching cameras unless the hardware design intentionally supports them;
- never guess and open an unrelated `/dev/video*` device;
- do not hardcode a developer-observed USB bus path;
- do not hardcode a developer-observed PCIe address for the Hailo device;
- verify the Hailo-8 accelerator through the supported runtime/device API.

Hardware detection belongs to product configuration, not developer-machine identity.

---

## 7. RAVE OS is an appliance image, not a configured developer Pi

Treat Raspberry Pi OS Lite as the base operating-system substrate, in the same product-philosophy role that AGNOS serves for comma hardware.

The shipped artifact should be a versioned **RAVE OS** image.

A clean supported Pi should require only the supported hardware, flashed storage, and power to reach a functional provisioning state.

A RAVE OS release must contain, as applicable to that release:

- the exact supported Raspberry Pi OS Lite base;
- the exact supported kernel/firmware set;
- Hailo PCIe kernel driver and firmware;
- HailoRT runtime;
- compatible Hailo Python/runtime bindings;
- GStreamer and required plugins;
- OpenCV;
- NumPy and Python/runtime dependencies;
- camera/UVC dependencies;
- NetworkManager and networking dependencies;
- mDNS/local-discovery dependencies;
- provisioning-hotspot components;
- RAVE web UI and backend;
- perception runtime;
- local state/health services;
- model update service;
- OS/application update support when implemented;
- udev rules;
- systemd units;
- firewall rules;
- diagnostics required for supported recovery.

A production image must not require a first-boot `apt install`, `pip install`, developer SSH session, undocumented shell command, or internet connection merely to become operational.

If reproducing a working unit requires remembering a manual command that was run on a development Pi, deployment is not reproducible yet. Capture the requirement in the image build.

---

## 8. Image builds must be declarative and reproducible

Do not ship a raw clone/snapshot of a developer-configured SD card or NVMe device as the canonical production image.

Build RAVE OS from a repository-controlled image definition, preferably `rpi-image-gen` or another deliberately approved declarative image builder.

The image definition must own:

- package sources;
- package versions or a reproducible pinning strategy;
- files installed into the root filesystem;
- users/groups;
- service units;
- capabilities/permissions;
- udev rules;
- network policy;
- firewall policy;
- boot configuration;
- persistent-data partition/layout;
- version metadata;
- update layout;
- first-boot initialization.

Build output must identify the source commit and RAVE OS version used to produce it.

Do not assume a package named `latest` remains compatible forever. The Hailo software stack in particular must be treated as a compatible set: kernel driver, firmware, HailoRT, bindings, and HEF/toolchain compatibility must be validated together.

No field device should run unrestricted `apt full-upgrade` as an update strategy.

---

## 9. Absolute law: no developer-machine identity in RAVE artifacts

**RAVE OS is an appliance image, not a clone of the computer or Pi that built it.**

Production code, packages, images, configuration, manifests, services, examples used as production templates, generated root filesystems, and update artifacts must never depend on the identity, filesystem layout, credentials, or LAN configuration of a developer machine.

### Never make these runtime dependencies

Do not hardcode or ship:

- developer usernames;
- developer home directories;
- `/home/<developer>/...` paths;
- `/Users/<developer>/...` paths;
- Windows developer profile paths;
- workstation hostnames;
- development-machine IP addresses;
- development-machine MAC addresses;
- personal/home/work Wi-Fi SSIDs;
- Wi-Fi passwords;
- developer SSH public or private keys;
- GitHub personal access tokens;
- API keys/tokens;
- browser/session credentials;
- developer `.env` files;
- local virtual-environment paths;
- local Conda paths;
- Docker/container IDs;
- temporary export/training directories;
- workstation GPU/CUDA/ROCm assumptions;
- local package caches as runtime dependencies;
- build-host NetworkManager UUIDs;
- cached D-Bus identifiers;
- test-device serials unless deliberately defined fixtures;
- developer shell aliases/configuration;
- absolute paths to a model on a workstation;
- logs, caches, shell histories, editor state, or test state copied from a development installation.

Do not solve this by replacing one developer's identity with another. **The production artifact contains no developer-machine identity at all.**

### Build paths are allowed only during the build

A build may happen from an arbitrary source path. That path must not become required at runtime or leak into installed configuration.

Build-host paths in debug metadata should be removed or deliberately documented if they cannot affect runtime and cannot reveal sensitive identity. Release artifacts should minimize such leakage.

### Product constants are not developer identity

Intentional reviewed RAVE product values are allowed. Examples include the dedicated RAVE/Comma subnet once defined by the product contract.

The distinction is:

- `10.77.0.0/24` is a reviewed RAVE product network;
- an arbitrary home-router subnet observed during development is not.

### Release leakage check

Every image/release pipeline must scan both the repository and the **generated image/rootfs/update artifact** for developer identity leakage.

The release check should include:

- generic home-directory patterns;
- current build `$USER` and `$HOME` values;
- build hostname;
- explicitly supplied local identity denylist values;
- common secret/private-key patterns;
- unintended SSH keys;
- unintended NetworkManager user connections;
- hardcoded development subnets/SSIDs;
- build/source paths in runtime configuration;
- credential files and shell histories.

Do not hardcode private developer identity into the public safety scanner merely so the scanner can detect it. Allow local/CI denylist injection where appropriate.

A developer-identity finding in a runtime artifact is a release blocker until explained and explicitly reviewed.

---

## 10. Production filesystem and service identity contract

Production code must use deliberate system paths, not interactive-user home directories.

Preferred ownership boundaries:

```text
/opt/rave/        installed RAVE application/runtime assets
/etc/rave/        system configuration and policy
/var/lib/rave/    persistent device state, models, identity, update data
/var/log/rave/    bounded RAVE logs if separate files are required
/run/rave/        ephemeral runtime state / local IPC
```

Exact subdirectories may evolve, but runtime behavior must not fall back to an arbitrary user's home directory.

RAVE services should run under a dedicated least-privilege service identity such as:

```text
user:  rave
group: rave
```

Do not run the complete RAVE stack as root merely because hardware or NetworkManager access is easier. Split privileged operations into narrowly scoped services/capabilities.

Model, identity, network, and update files must have explicit ownership and restrictive permissions.

---

## 11. First boot creates device identity; the image does not clone it

Every flashed RAVE image must begin generic and personalize itself on the target device.

Values that must not be cloned from the build host or golden image include:

- `/etc/machine-id` content that should be unique per device;
- SSH host keys;
- RAVE device identity;
- device authentication/private keys;
- pairing/master keys;
- session keys;
- Wi-Fi credentials;
- user-specific NetworkManager connections;
- peer-specific C3X pairing material;
- runtime sequence/session state;
- logs and caches.

First-boot/provisioning code must create unique values using appropriate system entropy and persist them only in the device's writable persistent state.

Two devices flashed from the same release image must not come up with the same cryptographic identity or SSH host keys.

A device reset/restore flow must define which identity/configuration is preserved and which is regenerated. Do not improvise this during implementation.

---

## 12. RAVE network roles are deliberately separate

RAVE has two conceptually independent network roles.

### Management / provisioning network

The Pi wireless interface is for:

- first-boot setup;
- local RAVE web UI;
- user LAN access;
- software/model update checks;
- optional engineering administration.

### Dedicated runtime network

The dedicated wired RAVE-to-Comma link is for RAVE runtime metadata:

```text
RAVE Pi:   10.77.0.1/24
Comma:     10.77.0.2/24
```

Product contract for the dedicated link:

- no default gateway;
- no DNS;
- never-default routing;
- no dependency on internet access;
- management Wi-Fi routing must not be replaced by this link;
- runtime RAVE must not depend on Wi-Fi;
- Wi-Fi loss must not stop perception or the wired RAVE transport;
- the web management service should not be exposed on the dedicated Comma-facing interface unless an explicit reviewed requirement is added.

Do not bridge the management LAN/AP directly onto the dedicated Comma network.

---

## 13. Provisioning hotspot behavior

The RAVE appliance should be recoverable without SSH or a monitor.

Intended provisioning behavior:

1. Boot RAVE.
2. If a valid saved management Wi-Fi network can be joined, join it.
3. If no valid saved network exists or connection fails after a bounded policy window, expose a RAVE provisioning AP.
4. User joins the RAVE AP from a phone/laptop/tablet.
5. User opens the local RAVE web UI.
6. UI scans available Wi-Fi networks through the backend.
7. User selects a network and supplies credentials.
8. Backend attempts the transition to the selected network.
9. On success, persist the connection and expose RAVE through local discovery such as `rave-pi.local` or the final product hostname policy.
10. On failure, return to/recover the RAVE provisioning AP after a bounded timeout.

The exact AP subnet/hostname may be finalized by implementation and validation. If `192.168.50.1/24` or a similar subnet is adopted, treat it as a product constant and test for conflict behavior rather than assuming it is universally safe.

Provisioning requirements:

- AP failure must not crash perception.
- Wi-Fi association failure must not crash perception.
- Repeated Wi-Fi failure must not create an unbounded retry/spawn/log loop.
- Do not require concurrent AP+station mode unless hardware/driver behavior is validated.
- If AP-to-client transition temporarily disconnects the browser, show a clear transition/recovery path.
- Captive-portal behavior may be a convenience, but a stable direct local address must exist for recovery.
- Never log the Wi-Fi password.
- Never return stored Wi-Fi passwords through the web API.
- Never put Wi-Fi credentials in URLs.
- Store network secrets with restrictive permissions.
- Do not ship a universal production provisioning password. A unique or otherwise secure bootstrap credential mechanism must be solved before calling provisioning release-qualified.

---

## 14. Local web UI: Galaxy is the visual source of truth

The RAVE management UI is a **stand-alone browser UI served by the Pi over the local management network**.

It is not the StarPilot Raylib UI and it must not run inside the Comma. However, visually it should look like the same product family as StarPilot Galaxy.

**Do not create a merely “Galaxy-inspired” design. Use the exact Galaxy/Aether design language and the exact styling clues/tokens available from the StarPilot source.**

Implementation rules:

- inspect the current StarPilot Galaxy implementation before significant UI work;
- reuse/adapt exact design tokens, spacing, typography hierarchy, radii, borders, glows, semantic colors, controls, transitions, and interaction behavior where licensing permits;
- do not invent a second RAVE design system;
- if source/assets are reused, preserve required license notices and verify redistribution rights;
- if a Galaxy implementation changes upstream, do not silently drift RAVE; make visual synchronization an explicit reviewed change.

Known StarPilot/Aether tokens already identified and acceptable as design references include:

```text
PANEL_BG       rgba(8, 8, 10, 255)
PANEL_BORDER   rgba(255, 255, 255, 22)
PANEL_GLOW     rgba(92, 116, 151, 34)
HEADER         rgba(236, 242, 250, 255)
SUBTEXT        rgba(200, 210, 225, 255)
MUTED          rgba(160, 170, 185, 255)
PRIMARY        #8B5CF6
SUCCESS        rgba(94, 168, 130, 255)
WARNING        rgba(204, 158, 83, 255)
DANGER         rgba(173, 78, 90, 255)
TILE_RADIUS    18 px
```

Known spacing references:

```text
xs 4
sm 8
md 12
lg 16
xl 24
xxl 32
xxxl 48
tile gap 16
tile content 16
line gap 8
```

These values are **not a substitute for inspecting the current Galaxy web source**. They are known clues from the StarPilot/Aether source and should prevent arbitrary restyling.

The primary UI should make status understandable without terminal access. Deep counters and logs belong in Diagnostics, not the main dashboard.

---

## 15. Web UI is management-only and must not own perception

The browser UI and web service are support components, not the perception authority.

Hard isolation rules:

- Closing a browser must not affect perception.
- Web server failure must not stop perception.
- Wi-Fi loss must not stop perception.
- Browser reconnects must not reset perception state.
- The web process must not open the camera exclusively or steal frames from the perception process.
- The web process must not directly own Hailo inference.
- Network configuration changes happen through a constrained backend service, not shell commands emitted by JavaScript.
- The browser must never receive or store pairing master keys, signing keys, or other backend secrets.
- Local API inputs must be validated and bounded.
- Management endpoints must not become unauthenticated internet-facing services.
- The default product posture is local-network management, not cloud dependence.

### Live View

A future live camera/detection view must be decoupled from the primary perception path.

- Consume a latest-value mirror/publication from perception.
- Do not add a second camera capture path that competes with production capture.
- Rate-limit and/or reduce resolution if needed.
- Drop live-view frames rather than queueing them.
- Live View may lose quality or disable itself under load; perception may not.
- Benchmark Live View on Pi 5 before treating it as always-on.

---

## 16. Management services must be lower criticality than perception

Service names may evolve, but architecture should maintain clear fault containment between:

- perception/camera/inference;
- local RAVE state aggregation;
- Pi-to-Comma transport;
- web management;
- Wi-Fi provisioning;
- updater;
- diagnostics/log export.

Do not create one giant privileged process that owns camera, inference, NetworkManager, HTTP, updates, and cryptographic identity.

Management tasks should run at lower scheduling/I/O priority than the perception path when practical.

A web/update/network-management crash must not cause the perception service to restart unless there is a deliberate dependency reason.

A perception failure should make RAVE unavailable to consumers, not silently preserve old state.

---

## 17. Hailo stack is part of the RAVE OS compatibility contract

Hailo is not “just a Python dependency.” The working accelerator stack includes kernel/device driver, firmware, HailoRT, bindings, and HEF compatibility.

Rules:

- Do not install an arbitrary newest Hailo package on a field unit.
- Do not independently upgrade the kernel, `hailo-dkms`, HailoRT, bindings, or firmware without compatibility testing.
- Record exact versions in the RAVE OS release manifest.
- Record the Hailo target (`Hailo-8`, not Hailo-8L/Hailo-10H unless deliberately supported).
- Verify the accelerator during image acceptance using the supported Hailo identification/runtime path.
- Verify the actual RAVE HEF loads and executes, not only that a Hailo device exists.
- A model compiled for an incompatible toolchain/runtime must not be activated.

The current validated V5 HailoRT version is `4.23.0`. Treat a change from this stack as a compatibility change requiring revalidation, not an automatic improvement.

---

## 18. Third-party redistribution and licensing are release requirements

Before shipping a public RAVE OS image, verify redistribution rights for every third-party binary, package, model artifact, font, icon, and copied UI asset included in the image.

This specifically includes, as applicable:

- Raspberry Pi OS packages;
- Hailo driver/runtime packages;
- Hailo firmware/tooling components;
- StarPilot/Galaxy/Aether source/assets;
- fonts/icons;
- model weights/artifacts.

Do not assume that because a dependency can be installed on a developer Pi it may be repackaged into a public image.

If a runtime-critical dependency cannot legally be redistributed, that is a release architecture blocker until a compliant distribution/provisioning path exists. Do not quietly turn first boot into an undocumented developer-login/install process.

Preserve required licenses/notices in the image and source repository.

---

## 19. Model correctness precedes model automation

The current YOLO26n Hailo output contract is raw, not NMS-processed.

Validated input:

```text
UINT8 NHWC(960x960x3)
```

Current validated raw output family:

```text
120x120 box/regression head
120x120 class head
60x60 box/regression head
60x60 class head
30x30 box/regression head
30x30 class head
```

The current HEF does not contain Hailo NMS.

The deployment architecture remains bounding-box based. Segmentation is not required for the current RAVE safety objective and must not be added by default. Any segmentation path requires a measured safety benefit and a Pi 5 latency/headroom review.

Production postprocessing must implement the **exact YOLO26 one-to-one raw-head semantics**. Do not improvise a YOLOv8 decoder because tensor shapes look familiar.

Before accepting a new decoder/model pair:

- run identical frames through the reference PyTorch model and Hailo model;
- compare decoded detections, class IDs, confidence behavior, geometry, and IoU;
- verify letterbox/crop coordinate reversal;
- verify class mapping (`vehicle`, `motorcycle`) or explicitly migrate the schema;
- verify half-decode preprocessing impact against the canonical path;
- test negative frames and false-positive behavior;
- record decoder/model ABI compatibility.

The current 60-calibration-image HEF is a hardware/performance artifact, not final production quantization. Final accuracy qualification requires a larger representative calibration set and explicit model-quality validation.

---

## 20. Tracking, temporal logic, and danger state remain freshness-first

Tracking and temporal reasoning are later pipeline stages, not permission to queue history indefinitely.

Rules:

- tracking must use stable IDs/history without creating unbounded buffers;
- track history windows are bounded;
- temporal models must fit measured Pi 5 headroom;
- start with the simplest method that satisfies behavior;
- do not add a GRU/transformer merely because one exists;
- danger-zone determination cannot depend entirely on a user drawing/calibrating a region correctly;
- system-derived geometry/behavior must remain the safety basis;
- loss of current trustworthy perception must make the state unknown/unavailable rather than infer safety indefinitely from old tracks.

Model/data quality should be improved before compensating with heavier runtime logic.

---

## 21. Dataset/model lineage remains explicit

Even though this is the deployment repository, deployed model artifacts must have traceable lineage.

A release model manifest should include at least:

- model ID;
- model version;
- source training run/checkpoint identifier;
- model family;
- input width/height;
- input dtype/layout;
- class schema;
- output/decode contract version;
- accelerator target;
- HEF SHA-256;
- calibration provenance/count;
- minimum compatible RAVE runtime version;
- compatible RAVE OS/Hailo constraints where required;
- release approval state;
- signature metadata when signing is implemented.

Do not select “newest `best.hef`” from a directory as production update policy.

---

## 22. Automatic model updates use approved releases, not arbitrary Git pushes

The user wants deployed RAVE units to update models automatically when management Wi-Fi provides internet access. Implement this as a controlled release channel.

**A normal commit or push to `main` must not automatically activate an experimental model on a vehicle.**

Preferred model-release behavior:

1. Train/refine model outside the deployed Pi.
2. Validate checkpoint/dataset lineage.
3. Export/compile HEF.
4. Verify PyTorch-versus-HEF correctness.
5. Benchmark on Pi 5.
6. Approve the model for deployment.
7. Publish a versioned model release artifact and manifest, preferably as a GitHub Release asset or equivalent release channel rather than tracking HEF binaries in Git.
8. Pi updater sees the approved release while internet is available.
9. Download to staging.
10. Verify signature/hash and compatibility.
11. Keep the current known-good model intact.
12. Atomically activate the new model only through the approved activation policy.
13. Verify runtime self-check.
14. Roll back automatically if activation/self-check fails.

Update failure must not remove the current known-good model.

Network loss during download must leave the current model untouched.

A release with an unknown output ABI, incompatible Hailo target, wrong geometry, wrong class map, bad hash, invalid signature, or unsupported runtime version must remain staged/rejected and must not become active.

---

## 23. Model activation must not create a perception gap accidentally

Downloading may occur asynchronously when internet is available, but activation/restart is a separate operation.

Until a validated hot-swap mechanism exists:

- do not overwrite an in-use HEF in place;
- use versioned model directories;
- switch an explicit `current` pointer/manifest atomically;
- keep at least one known-good rollback model;
- activation should happen at a controlled service boundary/restart;
- during activation/restart, RAVE must report unavailable rather than stale state;
- do not infer vehicle onroad/offroad state from the Comma merely to schedule updates;
- if a future safe activation policy needs vehicle context, it requires explicit architecture review rather than reintroducing the removed Comma dependency.

Do not let update writes or decompression create measurable perception latency spikes. Throttle/defer low-priority update work if Pi benchmarks show interference.

---

## 24. RAVE OS/application updates must be signed, atomic, and reversible

Do not use a long-lived field installation mutated forever by ad-hoc package upgrades.

The target system-update architecture is a versioned image/update artifact with rollback, preferably A/B boot/rootfs once the image foundation reaches that gate.

Conceptually:

```text
boot / boot metadata
RAVE OS slot A
RAVE OS slot B
persistent RAVE data
```

Requirements for production system updates:

- signed release metadata/artifact;
- integrity verification before activation;
- compatible hardware check;
- persistent user/device data separate from OS slot;
- atomic boot-slot transition;
- post-boot health gate;
- automatic rollback when the new slot cannot become healthy;
- no destruction of Wi-Fi credentials, RAVE identity, pairing state, or user configuration during normal update;
- clear UI version/status/rollback reporting.

Do not claim A/B OTA exists until it is actually implemented and failure-tested.

---

## 25. No cloud dependency for perception or local control plane

RAVE perception and the dedicated Pi-to-Comma path must work with no internet connection.

Internet may be used for:

- approved update checks/downloads;
- explicitly requested remote support in the future.

Internet must not be required for:

- camera capture;
- Hailo inference;
- tracking/temporal logic;
- threat state;
- local health;
- Pi-to-Comma transport;
- local provisioning AP;
- local RAVE web UI;
- local configuration already stored on the device.

Do not upload camera frames, detections, logs, Wi-Fi details, device identity, or vehicle-related data to a cloud service by default. Any telemetry/export feature must be explicit, scoped, documented, and reviewed.

---

## 26. Security and secrets are first-class boundaries

Never commit, embed, log, display, or ship developer/private secrets.

Prohibited material includes:

- private SSH keys;
- signing private keys;
- pairing/master keys;
- API tokens;
- GitHub credentials;
- Wi-Fi passwords;
- private certificates;
- browser session tokens;
- developer `.env` files;
- C3X credentials;
- raw user video/captures unless deliberately approved and protected.

### Device/runtime keys

- Generate unique device secrets on-device or through a secure manufacturing/provisioning process.
- Store them in restrictive root/service-owned locations.
- Never expose raw pairing keys in the web UI.
- Never include them in diagnostics bundles by default.
- Never reuse one device's identity/key material on another device.

### Web management security

- Bind management services only to intended local management interfaces.
- Do not expose administrative endpoints to the public internet by default.
- Use CSRF/session protections appropriate to the chosen web stack.
- Validate every state-changing request server-side.
- Do not use shell interpolation with user input.
- Do not expose arbitrary file read/write or command execution endpoints.
- Network configuration APIs must be narrow and typed.

---

## 27. Pairing/session security must not be weakened

Where the Pi-side RAVE transport implements the established pairing/session model, preserve:

- persistent peer identity;
- persistent peer name where applicable;
- 32-byte master-key semantics where the existing protocol requires it;
- HMAC authentication;
- directional session keys;
- challenge/ACK session establishment;
- authenticated session binding;
- sequence checking;
- replay rejection;
- duplicate/out-of-order rejection;
- malformed/authentication counters;
- bounded receive processing.

Do not invent a second incompatible pairing protocol just because the Pi now has a web UI.

The existing StarPilot pairing model is deliberately offroad-gated and requires explicit user confirmation of the discovered candidate. The Pi implementation must support that contract and must not auto-confirm a peer merely because only one candidate responds. A Pi-side management page must not become a bypass around the C3X pairing safety gate unless the pairing architecture is deliberately redesigned and revalidated.

If the RAVE web UI later exposes Pair/Forget status/actions, it must call the backend's canonical pairing state machine. The browser must never own raw key material.

A new boot/session identifier must be authenticated before receiver sequence state is reset.

---

## 28. Configuration writes are atomic and schema-controlled

Configuration is product state.

- Define one canonical configuration schema.
- Validate type/range/enums before persistence.
- Use atomic write/rename semantics where practical.
- Preserve the last known-good configuration on failed writes/migrations.
- Version configuration schemas.
- Make migrations explicit and test rollback/forward behavior.
- Do not let unknown keys silently change behavior.
- Do not store secrets in world-readable configuration.
- Do not put runtime configuration in source checkout directories.

User configuration must survive normal RAVE OS updates unless a documented migration explicitly changes it.

---

## 29. Failure behavior must be explicit

The following must not be ambiguous:

- camera missing;
- camera busy;
- unsupported camera mode;
- GStreamer negotiation error;
- decode failure;
- Hailo missing;
- Hailo runtime mismatch;
- HEF incompatible;
- inference stall;
- decoder failure;
- tracker failure;
- temporal-state failure;
- transport loss;
- authentication loss;
- web server failure;
- Wi-Fi loss;
- provisioning failure;
- update check failure;
- update verification failure;
- storage full;
- thermal throttling;
- service crash;
- unexpected reboot.

Perception-path failures that make current RAVE state untrustworthy must make RAVE unavailable.

Management-only failures must be isolated and must not automatically take down healthy perception.

No component may preserve a prior CLEAR/WATCH/WARNING result indefinitely as a substitute for current trustworthy perception.

---

## 30. Logging, diagnostics, privacy, and storage endurance

Logs exist to diagnose failures, not to consume storage or leak data.

Rules:

- log meaningful transitions and bounded error summaries;
- maintain useful counters for stale frames, decode errors, camera restarts, Hailo errors, auth failures, update failures, and service restarts;
- avoid per-frame/per-packet persistent logging in normal operation;
- rate-limit repeated failures;
- bound log storage and rotate it;
- never log passwords, private keys, pairing master keys, tokens, or raw authorization headers;
- do not persist camera frames by default;
- diagnostics export must exclude secrets by default;
- update and log writes must respect SD/NVMe endurance;
- a full log partition must not crash perception.

Web diagnostics should separate user-facing health from engineering detail.

---

## 31. Thermal, power, and storage behavior are release gates

RAVE is not release-qualified merely because it runs on a bench.

Production qualification eventually requires:

- sustained Pi 5 thermal testing;
- accelerator thermal behavior;
- active-cooling validation;
- memory/headroom validation;
- USB/camera endurance;
- storage endurance;
- brownout/power-loss behavior;
- clean shutdown/recovery behavior;
- filesystem corruption/recovery testing;
- automotive supply behavior;
- thermal soak;
- vibration/environment testing;
- EMI/EMC considerations.

Until these are completed, document them as incomplete rather than implying they are solved.

If thermal throttling or resource exhaustion makes latency/freshness untrustworthy, RAVE health must degrade/unavailable rather than silently continue with stale state.

---

## 32. Repository safety rules

The repository is source/configuration/documentation, not a dumping ground for generated binaries, training data, or captures.

Do not commit unless explicitly intended and reviewed:

- HEF binaries;
- `.pt`/`.pth`/`.onnx`/TensorRT artifacts;
- camera video/captures;
- packet captures containing private data;
- OS images;
- compressed model bundles;
- `.deb`/`.rpm`/`.whl` release binaries;
- generated release archives;
- private keys;
- credentials.

Use release assets/artifact storage for approved binaries and images when appropriate.

Extend `scripts/check-repository-safety.sh` as the deployment system grows. It should eventually cover:

- binary artifact policy;
- private-key/token patterns;
- developer-machine identity leakage;
- forbidden user-home runtime paths;
- unintended Wi-Fi profiles/credentials;
- image/rootfs leakage scans;
- release-manifest sanity.

Tests for safety checks are part of the safety system and must evolve with the checker.

---

## 33. Exact dependency ownership

If production depends on a package, service, kernel module, udev rule, group membership, environment variable, sysctl, boot config, device permission, or system file, the repository/image definition must declare it.

Do not rely on:

- “it was already installed on my Pi”;
- shell history;
- user profile files;
- manually activated Python virtualenvs;
- developer Docker images at runtime;
- manually edited `/etc` state that is not represented in the image definition;
- undocumented group membership;
- manually created symlinks;
- manually held packages;
- manually run Hailo setup commands.

The production service environment must be explicit in its unit/configuration.

---

## 34. Release manifests and provenance

Every RAVE OS release should eventually produce machine-readable provenance containing at least:

- RAVE OS version;
- source commit;
- build timestamp for human provenance;
- supported hardware profile;
- Raspberry Pi OS base identity/version;
- kernel/firmware version;
- Hailo driver/runtime version;
- Python/runtime version;
- critical library versions;
- web UI version;
- perception runtime version;
- model compatibility ABI;
- image/update SHA-256;
- signature metadata when signing exists.

A model release has separate version/provenance from the OS release.

Do not hide an OS dependency change inside a model version or vice versa.

---

## 35. Image acceptance / clean-room validation

Before calling a RAVE OS image distributable, test it like a stranger received it.

Minimum clean-image gate:

1. Build from a clean environment using the repository image definition.
2. Confirm the build does not require files outside declared inputs.
3. Scan generated artifacts for developer identity/secrets.
4. Flash clean supported storage.
5. Boot a supported Pi 5 with no cloned machine identity.
6. Confirm unique machine/device/SSH identity is generated as designed.
7. Confirm first boot reaches a usable provisioning state without internet.
8. Confirm the provisioning AP appears when no saved Wi-Fi exists.
9. Confirm local web UI is reachable through the supported recovery address/path.
10. Provision a new Wi-Fi network through the UI.
11. Confirm the device joins that network and local discovery works.
12. Confirm failure to join Wi-Fi returns to a recoverable AP state.
13. Confirm Hailo-8 is detected with the exact supported runtime stack.
14. Confirm the supported B0589 is discovered through stable hardware identification.
15. Confirm production perception starts with no developer home directory or virtualenv.
16. Run the relevant V5 hardware regression.
17. Confirm web UI loss/restart does not stop healthy perception.
18. Confirm management Wi-Fi loss does not stop healthy perception.
19. Confirm the dedicated `10.77.0.0/24` link remains isolated from management routing.
20. Confirm model/update service failure does not remove the current known-good model.
21. Confirm logs are bounded and secret-free.
22. Reboot and confirm persistence of intended device state only.
23. Compare two units/images where practical to confirm unique identities are not cloned.

If this process requires an undocumented manual SSH repair, the image fails the reproducibility gate.

---

## 36. Perception integration validation gate

Before replacing mock/scaffolding with a production Pi service:

1. Static/syntax/lint checks.
2. Unit tests for pure scheduling/freshness/configuration logic.
3. Camera discovery negative tests.
4. Camera startup/streaming failure tests.
5. Hailo missing/incompatible-model tests.
6. Exact YOLO26 decoder correctness tests against reference inference.
7. Negative-frame / false-positive checks.
8. V5 Pi benchmark regression.
9. p50/p95/p99 frame-age comparison.
10. CPU/memory/thermal observation.
11. No-growing-queue verification.
12. service restart/failure behavior.
13. stale-result prevention.
14. exact changed-file review.
15. independent review for significant safety/architecture changes.

Do not use road testing to discover basic service, camera, model-ABI, or freshness defects that can be found on the bench.

---

## 37. Web/provisioning validation gate

Before calling provisioning/UI functional:

- fresh image with no saved Wi-Fi;
- AP appears;
- AP credentials/bootstrap behavior matches the documented security level;
- UI reachable from phone and laptop;
- scan results bounded and sanitized;
- successful Wi-Fi provision;
- wrong password failure;
- network disappears during transition;
- fallback AP recovery;
- device reboot persistence;
- change/forget Wi-Fi flow;
- no Wi-Fi password in logs/API responses;
- web service restart recovery;
- no effect on perception when browser/web service fails;
- live-view load benchmark if live view is enabled;
- management UI not reachable through unintended interfaces;
- responsive Galaxy visual parity check.

---

## 38. Update validation gate

Before enabling automatic updates by default:

### Model updates

- approved-release discovery;
- no update on arbitrary branch push;
- download interruption;
- bad hash;
- bad signature when signing is enabled;
- incompatible runtime/model ABI;
- wrong Hailo target;
- insufficient storage;
- atomic activation;
- perception unavailable during controlled restart rather than stale;
- rollback on load/self-test failure;
- old model retained;
- no measurable runtime degradation from background update work.

### RAVE OS/application updates

- signed artifact verification;
- A/B or equivalent atomic strategy;
- persistent data retained;
- failed boot rollback;
- failed post-boot health rollback;
- power loss during update;
- interrupted download;
- downgrade/rollback policy;
- image version correctly displayed in UI;
- no developer identity introduced by update artifact.

---

## 39. UI/UX quality is an engineering requirement

A headless appliance must not require terminal literacy for normal operation.

The web UI should make these states obvious:

- RAVE healthy/unavailable;
- camera health;
- perception health;
- model/version;
- frame/result rate;
- useful latency summary;
- Comma link status;
- management Wi-Fi status;
- update status;
- temperature/system health;
- setup required;
- actionable fault summary.

Do not dump raw engineering counters on the primary dashboard. Put deep diagnostics behind a Diagnostics page.

Errors should state what failed and what the user can safely do next.

Avoid buttons whose labels do not match the actual action.

Dangerous/destructive operations such as factory reset, forget identity, or rollback should require deliberate confirmation.

---

## 40. Do not make assumptions that can be measured

Do not assume:

- camera is `/dev/video0`;
- camera is physically attached;
- AI HAT is present because the package is installed;
- Hailo versions are compatible because imports work;
- Pi is online because Wi-Fi is associated;
- internet is available because an interface has an address;
- AP/client concurrency works because a tutorial says it should;
- the web page is reachable because the web process is running;
- `.local` resolution works on every client;
- an update is valid because GitHub returned HTTP 200;
- a model is compatible because its filename contains `960`;
- an image is reproducible because it boots on the development Pi;
- a package upgrade improves the system;
- a benchmark run is valid if it produced zero samples;
- a high FPS number means fresh frames;
- stale data is safe because it was recently valid.

Observe the relevant state and fail clearly.

---

## 41. Root-cause fixes over workaround accumulation

Before adding another script, service, retry loop, environment variable, package pin, or boot hack:

- identify the owning failure;
- reproduce/measure it;
- fix the owning layer;
- remove obsolete workaround paths;
- preserve one canonical implementation per function.

Do not create chains such as:

```text
install-v2.sh
install-fixed.sh
install-final.sh
install-final2.sh
```

Fix the canonical image layer/installer/service instead.

---

## 42. Git and review discipline

For meaningful deployment changes:

- inspect repository status first;
- review exact changed files;
- run relevant tests before commit;
- run `git diff --check`;
- keep generated host/runtime artifacts out of commits;
- do not commit or push unless the user explicitly authorizes it;
- do not force-push or rewrite shared history without explicit authorization;
- use descriptive commit subjects/bodies for safety/architecture changes;
- record why an invariant changed, not only what line changed;
- use independent review for safety, security, update, image, networking, or perception architecture changes;
- treat Greptile/other reviewer findings as evidence to evaluate, not commands to follow blindly.

A reviewer finding that identifies a real failure path should be fixed and regression-tested. A speculative style suggestion is not permission to disturb a hardware-validated architecture.

---

## 43. Operator command safety

When instructions are handed to the operator:

- label the exact terminal/environment clearly;
- do not include `exit` or `exit 1` in pasteable command blocks;
- do not use command sequences that can unexpectedly close the interactive shell;
- avoid `git reset --hard`, broad `git clean`, recursive deletion, repartitioning, or formatting unless the exact destructive scope is explicitly reviewed and approved;
- prefer narrow, observable commands;
- verify current directory/branch/device before mutations;
- do not assume a Python virtualenv is active;
- do not conflate host, Hailo container, Pi, and Comma terminals.

A command is part of the engineering output and should be reviewed like code.

---

## 44. Documentation truthfulness

Update documentation when architecture or validated evidence changes.

Do not leave conflicting claims such as:

- README says a feature is validated while deployment docs say it is mock-only;
- one file calls a model final while another says calibration is provisional;
- an old performance number is presented as the latest reproduction;
- a network path is called production while still requiring manual SSH setup;
- a web UI screenshot implies a service exists when it is still a mock.

When documenting metrics, state the measurement boundary. For V5, userspace-arrival-to-raw-Hailo-result does not include sensor exposure, USB/UVC time, YOLO decode, tracking, temporal state, authenticated transport, or Comma display latency.

---

## 45. Release-readiness boundary

Do not call complete RAVE production-ready until remaining gates have been completed, including as applicable:

- exact YOLO26 Hailo decode correctness;
- final detector/calibration accuracy qualification;
- production tracking;
- production temporal/danger logic;
- Pi 5 end-to-end frame-age validation through final threat output;
- sustained thermal/headroom validation;
- production authenticated transport;
- production receiver integration;
- reproducible RAVE OS image;
- clean first-boot provisioning;
- secure web management;
- signed model update path;
- signed atomic reversible OS/application update path;
- rollback validation;
- power/brownout/storage/environment validation;
- simulation/replay/fault injection;
- closed-course validation;
- controlled road validation.

A polished Galaxy UI does not make the underlying appliance release-qualified.

---

## 46. Definition of done for a RAVE deployment feature

A feature is not done because it works once.

It is done when:

- its owning architecture is correct;
- it respects the Pi/Comma trust boundary;
- it contains no developer-machine dependency;
- it is represented in the image/build definition if needed in production;
- failure behavior is explicit;
- state is bounded;
- secrets are protected;
- configuration is reproducible;
- Pi performance impact is measured when relevant;
- UI feedback is understandable;
- tests cover the important success and failure paths;
- exact changed files are reviewed;
- hardware validation exists when the claim depends on hardware;
- documentation accurately reflects its current maturity.

---

## 47. Laws that survive future refactors

**RAVE OS is an appliance image, not a snapshot of a developer machine. No developer username, home path, hostname, LAN identity, credential, manually accumulated package state, or hidden setup step may be required for a released RAVE unit to function.**

**The Raspberry Pi 5 is the hard target. Freshness beats queued throughput. Stale work is dropped, not accumulated.**

**V5 camera scheduling is frozen unless a measured failure/regression justifies changing it: MJPEG 1080p60, one-slot latest frame, capture-driven ~30 Hz accepted work, 5 ms decode-eligibility freshness guard, 960 input, no stale-result fallback.**

**RAVE perception and the Pi-to-Comma runtime link must work without Wi-Fi or internet. Wi-Fi is management/provisioning/update connectivity, not the runtime safety path.**

**The Pi must never become a Panda/CAN/vehicle-control endpoint. The Comma must not be required for the Pi to determine RAVE perception/threat state.**

**The web UI is management-only. Losing the browser, web service, AP, router, or internet must not take down healthy perception.**

**Model and OS updates must never destroy the current known-good runtime because a download, verification, compatibility check, activation, or boot failed.**

**A clean RAVE OS image flashed onto clean supported hardware must be reproducible without knowledge of who built it or what network/build directory they used.**
