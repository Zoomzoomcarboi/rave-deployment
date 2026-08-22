# Pi 5 Perception V5 Baseline

Last updated: 2026-08-22.

This document records the hardware-validated V5 camera-to-Hailo scheduling and
preprocessing architecture for RAVE (Rear Awareness Vision Engine). It is a
component/runtime-stage baseline, not a claim that the complete RAVE system is
road-ready or production-ready.

V5 is the frozen scheduling baseline for the next production-runtime implementation.
Further scheduling experiments should require new evidence of a specific failure or
performance regression rather than routine iteration.

## Scope of the validated stage

The V5 benchmark covers:

```text
Arducam B0589 1920x1080 MJPEG @ 60 FPS
        |
        v
one-slot latest compressed frame
        |
        +-- frame older than 5 ms at decode eligibility -> DROP
        |
        v
native JPEG 1/2 decode -> 960x540 BGR
        |
        v
RAVE crop y=150:346 -> 960x196
        |
        v
BGR -> RGB + 114-valued vertical letterbox
        |
        v
960x960 RGB UINT8 NHWC
        |
        v
YOLO26n Hailo-8 HEF
        |
        v
six raw YOLO26 output tensors
```

The benchmark stops at the raw Hailo output tensors. YOLO26 raw-head decode,
confidence filtering, vehicle tracking, temporal reasoning, danger-zone logic, and
metadata transport are outside this measurement and remain separate work.

## Frozen architecture decisions

### Camera and model geometry

- Camera: Arducam B0589 USB/UVC (`04b4:0822`).
- Camera transport: **1920x1080 MJPEG at 60 FPS**.
- Canonical full-resolution RAVE crop remains 1920x391, `y=300:691`.
- V5 uses libjpeg/OpenCV native 1/2-scale JPEG decode to 960x540, then crops
  `y=150:346`, producing 960x196 content without a second resize.
- YOLO input remains **960x960**. Reducing model resolution is not part of the V5
  architecture.
- The 960 input is retained to preserve spatial detail across the wide rear-camera
  field of view while model-training and detection refinement continue independently.
- The V5 half-scale crop mapping is the measured implementation. Production
  integration must preserve the same geometry and explicitly verify image/preprocess
  equivalence rather than silently changing crop or rounding behavior.

### Freshness-first scheduling

V5 uses capture-driven eligibility rather than a timer that wakes independently of
camera arrivals.

The policy is:

1. Capture may run faster than inference.
2. Store only the newest compressed MJPEG frame in a one-slot buffer.
3. Never build a frame backlog.
4. Rate-limit accepted work to approximately 30 Hz.
5. When a newly arrived frame becomes eligible, calculate its local userspace age.
6. If the frame is already older than **5 ms**, discard it before JPEG decode.
7. Decode and preprocess only accepted fresh frames.
8. Store only the newest prepared model input in a one-slot buffer.
9. Hailo consumes prepared frames immediately; no inference queue is permitted.
10. A dropped or failed frame is not replaced by a stale previous result.

The 5 ms value is the validated V5 development freshness guard. Treat any later
change as a measurable architecture change requiring regression testing.

### Failure behavior

- JPEG decode failure drops that frame.
- Stale frames are dropped before expensive processing.
- Prepared-frame backlog is not allowed.
- The pipeline must not hold or replay a previous perception result as if it were
  current.
- Camera/inference stalls must eventually make RAVE unavailable in the higher-level
  health/state layer rather than preserving stale CLEAR/WATCH/WARNING state.

## Validated hardware and model artifact

Pi-side benchmark hardware:

- Raspberry Pi 5 Model B Rev 1.1, 4 GB RAM.
- Raspberry Pi AI HAT+ 26 TOPS.
- Hailo-8 accelerator.
- Raspberry Pi OS Lite 64-bit / Debian 13 (Trixie).
- Kernel `6.18.39+rpt-rpi-2712`.
- Pi HailoRT `4.23.0`.

The benchmarked HEF was produced from the actual RAVE `real_world_v1/best.pt`
YOLO26n detector at `imgsz=960` with classes:

- `vehicle`
- `motorcycle`

The 60-image calibration HEF used for this performance stage has SHA-256:

```text
ebcda77f0694db7023dfd3926a357a8097e714cbc5985fe094a46805d3f48c19
```

This 60-image calibration artifact is sufficient for the recorded hardware/performance
baseline but is **not** frozen as the final production quantization artifact. Hailo's
export path warned that more than 300 representative images are recommended for INT8
calibration, with a substantially larger representative set preferred for final
accuracy work. Model training, calibration, and detection refinement continue in
parallel with deployment engineering.

## Hailo input/output contract

Input:

```text
best/input_layer1 UINT8 NHWC(960x960x3)
```

Raw outputs:

```text
best/conv61 UINT16 NHWC(120x120x4)
best/conv64 UINT16 NHWC(120x120x2)
best/conv77 UINT16 FCR (60x60x4)
best/conv80 UINT16 FCR (60x60x2)
best/conv91 UINT16 FCR (30x30x4)
best/conv94 UINT16 FCR (30x30x2)
```

The HEF does not contain Hailo NMS (`nms: false`). Production postprocessing must
implement the correct YOLO26 one-to-one raw-head decode semantics and must not assume
a stock YOLOv8 Hailo NMS output contract.

## V1 through V5 measurements

All arrival-based latency measurements begin when a compressed MJPEG frame reaches
Pi userspace. They do **not** include sensor exposure or USB/UVC transport before
userspace arrival.

### V1 — full JPEG decode, fixed 30 Hz scheduler

- Result rate: 29.77 FPS.
- Arrival -> decode start: p50 20.793 ms, p95 32.693 ms, p99 35.586 ms.
- JPEG decode: p50 20.549 ms.
- RAVE preprocessing: p50 1.322 ms.
- Hailo blocking inference: p50 18.839 ms.
- Arrival -> raw inference result: p50 61.425 ms, p95 73.898 ms, p99 76.376 ms.

This established that the fixed timer introduced substantial frame-age delay.

### V2 — native 1/2 JPEG decode, fixed 30 Hz scheduler

- Result rate: 29.78 FPS.
- Arrival -> decode start: p50 22.938 ms.
- Half JPEG decode: p50 16.473 ms.
- RAVE preprocessing: p50 0.574 ms.
- Hailo blocking inference: p50 18.764 ms.
- Arrival -> raw inference result: p50 59.073 ms, p95 70.704 ms, p99 72.063 ms.

Native 1/2 JPEG decode materially reduced compute, but timer-phase waiting still
controlled frame age.

### V3 — capture-driven diagnostic, uncapped

- Result rate: 48.57 FPS (diagnostic only; not the intended operating rate).
- Arrival -> decode start: p50 0.640 ms, p95 1.063 ms, p99 3.056 ms.
- Half JPEG decode: p50 19.644 ms.
- Hailo inference: p50 18.753 ms.
- Arrival -> raw inference result: p50 39.947 ms, p95 41.700 ms, p99 44.225 ms.

This proved that most of the V2 latency penalty came from scheduling/phase delay and
that a capture-driven latest-frame policy was the correct direction.

### V4 — capture-driven, freshness-first 30 Hz

- Result rate: 29.88 FPS.
- Arrival -> decode start: p50 0.049 ms, p95 11.214 ms, p99 16.386 ms.
- Half JPEG decode: p50 16.145 ms.
- RAVE preprocessing: p50 0.583 ms.
- Hailo inference: p50 18.742 ms.
- Arrival -> raw inference result: p50 35.792 ms, p95 50.471 ms, p99 56.170 ms.

Median scheduling was effectively solved, but the tail still admitted older camera
frames.

### V5 — hard freshness guard, frozen scheduler baseline

20-second run:

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
RAVE raw-result rate:         29.49 FPS
```

Latency:

| Metric | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| Arrival -> decode start | 0.049 ms | 2.201 ms | 3.225 ms |
| Half JPEG decode | 16.501 ms | 19.895 ms | 21.966 ms |
| RAVE preprocess | 0.573 ms | 0.663 ms | 0.921 ms |
| Arrival -> inference start | 17.337 ms | 22.846 ms | 25.625 ms |
| Hailo blocking inference | 18.747 ms | 18.952 ms | 19.680 ms |
| Arrival -> raw inference result | **36.076 ms** | **41.675 ms** | **44.582 ms** |

Compared with V4, V5 preserved approximately 30 Hz output while reducing the
raw-result frame-age tail by about 8.8 ms at p95 and 11.6 ms at p99. The explicit
stale-frame drops are intentional safety behavior, not lost-work defects.

## Interpretation and limits

V5 satisfies the current scheduling-stage objective:

- capture remains approximately 60 FPS;
- accepted decode/inference work remains approximately 30 FPS;
- no growing frame queue exists;
- stale inputs are explicitly rejected;
- decode and prepared-frame failures do not create a stale-result fallback;
- the Pi 5 + Hailo-8 path has demonstrated stable raw-inference throughput at the
  target rate.

The approximately 36 ms median is close to the measured dependent compute floor:
roughly 16.5 ms half-JPEG decode, 0.6 ms preprocessing, and 18.7 ms blocking Hailo
inference. Scheduling is no longer the primary median-latency problem.

This is **not** full camera-to-final-detection latency. The following remain outside
the measured V5 stage:

- sensor exposure and pre-userspace USB/UVC latency;
- YOLO26 raw-head decode/postprocessing;
- tracker latency;
- temporal/danger-state latency;
- authenticated metadata serialization/transport;
- C3X receiver/UI freshness latency.

## Production-integration gate

Do not convert the benchmark directly into an enabled production service without
review. The production implementation must:

- preserve one-slot latest-frame semantics;
- preserve capture-driven eligibility and the 5 ms stale-input guard unless a later
  hardware benchmark justifies a change;
- preserve the canonical crop/model geometry and 960 input;
- fail unavailable on camera, decode, inference, or freshness failure;
- expose bounded counters/latency diagnostics without per-frame log spam;
- avoid Panda/CAN/vehicle-control dependencies;
- remain independent of Comma vehicle state;
- include unit tests for pure scheduling/freshness logic;
- pass syntax/static checks, relevant tests, and exact changed-file review;
- rerun the Pi 5 benchmark and compare p50/p95/p99 frame age before acceptance.

The model artifact remains replaceable. Improved training/calibration may proceed in
parallel as long as the runtime input/output contract is deliberately reviewed when it
changes.

## Post-review hardware reproduction

The frozen V5 benchmark was reproduced on the Raspberry Pi 5 after static review
using the exact reviewed benchmark script and the exact validated HEF.

Benchmark script SHA-256:

```text
a54c3ab38279264c8d6815458be23eb75e2123f5b4a538ec37643488c913b7f1
```

HEF SHA-256:

```text
ebcda77f0694db7023dfd3926a357a8097e714cbc5985fe094a46805d3f48c19
```

20-second reproduction result:

```text
Captured:                         1201
Capture rate:                    60.03 FPS
Compressed overwrites:             117
Rate-limited arrivals:              478
Stale-frame drops:                    5
Decode attempts:                    600
Decode rate:                      29.99 FPS
Decode failures:                      0
Prepared frames:                    600
Prepared overwrites:                  0
Inferences completed:               600
Raw-result rate:                  29.99 FPS
```

Latency:

| Metric | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| Arrival -> decode start | 0.045 ms | 1.494 ms | 3.010 ms |
| Half JPEG decode | 16.631 ms | 19.911 ms | 22.950 ms |
| RAVE preprocess | 0.587 ms | 0.754 ms | 1.021 ms |
| Arrival -> inference start | 17.532 ms | 22.959 ms | 25.138 ms |
| Hailo blocking inference | 18.760 ms | 18.970 ms | 19.101 ms |
| Arrival -> raw inference result | 36.305 ms | 41.750 ms | 43.853 ms |

The reproduction remained within the V5 performance envelope. The difference in
stale-frame-drop count is not itself a regression criterion; camera-arrival phase and
runtime timing affect how many candidate frames exceed the guard. The architectural
requirement is that any candidate older than 5 ms at decode eligibility is rejected
rather than queued or inferred. In this reproduction, accepted decode-start age
remained bounded below that guard through p99.

This reproduction confirms the frozen V5 scheduling architecture without changing
its capture, preprocessing, rate-control, freshness, or Hailo execution behavior.

### Camera-failure validation

Following independent Greptile review, the benchmark was hardened so camera startup
and streaming failures cannot complete as successful zero-sample reproduction runs.

A negative hardware test used an otherwise identical temporary benchmark copy with
the camera path changed from `/dev/video0` to nonexistent `/dev/video999`. GStreamer
failed to enter `PLAYING`, the benchmark raised a `RuntimeError`, and the process
returned exit status `1`.

The benchmark therefore distinguishes a functioning B0589 reproduction run from a
camera-start failure and fails closed rather than reporting an invalid successful
measurement.
