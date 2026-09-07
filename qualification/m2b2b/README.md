# M2B.2b — Decoder numerical qualification

Status: **OPEN**. M2B.1 and M2B.2a remain CLOSED/PASS and unchanged.

## Qualification decision

Buffer indexing, dequantization, decoder math, the representative real-scene path, and exact-score tie behavior are evidenced. The remaining blocker is the detector admission threshold. The exact selected validation split contains 963 vehicle labels but only two motorcycle labels, both in one image. This cannot qualify false-negative or false-positive behavior for the declared two-class safety detector. `detector-admission-policy.json` therefore records no application threshold.

## Qualification boundary

Qualified in this checkpoint:

- graph confidence threshold is none;
- `l,t,r,b` coordinate semantics at strides 8, 16, and 32;
- sigmoid class scores with no separate objectness;
- two-stage sorted TopK with `k=300` and no IoU NMS;
- all 18,900 anchor/grid positions;
- UINT16 host-buffer indexing and NHWC/FCR host indexing behavior;
- quantization/dequantization and HailoRT UINT16/FLOAT32 equivalence;
- independent decoder numerical equivalence;
- deterministic lower-index TopK tie behavior;
- representative real-scene numerical vectors;
- SDK_QUANTIZED HAR as diagnostic evidence rather than a final-HEF golden oracle.

Not qualified: **the production detector admission threshold**. The 0.30 vehicle-only F1 peak is a diagnostic sweep result, not a recommendation or provisional production value.

## Graph confidence policy

`graph-confidence-audit.json` traces selected ONNX SHA256 `8b2c52b2ccae875b1f9a2c9a1a6d21e3a409916c3f771a400469ba2ed4eefa29`. Class logits pass through sigmoid, then two sorted, largest-first TopK operations with `k=300`. The graph contains no comparison, masking, Where, or NonMaxSuppression node.

**GRAPH CONFIDENCE THRESHOLD: NONE.** The graph ranks and caps candidates; it does not apply an absolute score cutoff.

## Exact validation threshold sweep

`threshold-sweep.json` records a dense sweep over the selected checkpoint and all 134 exact validation images. It retains image hashes and aggregate counts, not private images or predictions. Matching is per image and class, greedy by descending score, at IoU 0.50.

| Threshold | Vehicle precision | Vehicle recall | Vehicle FN | Vehicle FP | Mean candidates | P95 | Maximum |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.2104 | 0.9242 | 73 | 3340 | 31.57 | 72.50 | 110 |
| 0.05 | 0.4596 | 0.8692 | 126 | 984 | 13.59 | 35.00 | 52 |
| 0.10 | 0.6083 | 0.8255 | 168 | 512 | 9.75 | 25.70 | 33 |
| 0.15 | 0.6992 | 0.7965 | 196 | 330 | 8.19 | 22.00 | 30 |
| 0.20 | 0.7620 | 0.7778 | 214 | 234 | 7.34 | 19.35 | 29 |
| 0.25 | 0.8122 | 0.7591 | 232 | 169 | 6.72 | 18.35 | 24 |
| 0.30 | 0.8561 | 0.7352 | 255 | 119 | 6.17 | 16.00 | 24 |
| 0.50 | 0.9370 | 0.6334 | 353 | 41 | 4.86 | 13.00 | 19 |

The vehicle-only F1 peak is 0.30, but raising the cutoff from 0.10 to 0.30 loses 87 additional matched vehicles while reducing mean candidate load by only 3.58 per image. Safety policy cannot be selected from F1 alone. At 0.01 the sole matched motorcycle remains, with one motorcycle false negative; at 0.025 and above, both motorcycle labels are false negatives. With only two labels, those are observations, not stable class metrics.

Before an application cutoff, the graph returns exactly 300 candidates per image. A 0.05–0.20 cutoff yields mean 7.34–13.59 and P95 19.35–35 candidates. That does not suggest a volume threat to a small O(n) admission/association stage. At 0.01, P95 is 72.5 and maximum 110, deserving a later bounded Pi workload check after the safety threshold is supported. No runtime or tracker is introduced here.

## Exact-score tie contract

The selected ONNX imports opset 20. The retained ONNX TopK schema states that equal values use the lower index along the axis as tiebreaker. Both TopK nodes set `largest=1`, `sorted=1`, and `k=300`. The qualification decoder implements descending score, then lower flattened input index: lower location at stage one; lower location then lower class at the location-major, class-minor second stage. Scores are never altered. The zero-input tie beginning at row 62 and score `0.00005647540092468262` is explicitly qualified and no longer a blocker.

## Application buffer and numerical evidence

For all six one-frame UINT16 application buffers on little-endian Clean7:

```text
element_index = ((y * width) + x) * channels + c
byte_offset   = 2 * element_index
buffer[element_index] <-> tensor[y,x,c]
```

HailoRT 4.23.0 defines NHWC and FCR application buffers as `[N,H,W,C]`; FCR concerns device transfer order. Runtime sizes showed no host padding. Manual UINT16 dequantization equals HailoRT FLOAT32 output for every element, maximum error 0.0. Decoded outputs and TopK identities also match exactly.

The independent decoder reproduces the first 62 untied retained ONNX rows with maximum box error `0.000030517578125` pixel and score error `0.00000007075141184031963`. Later rows exercise the explicit ONNX lower-index tie rule.

## Representative real-scene fixture

`real-scene/ultralytics-bus.jpg` is the public Ultralytics package sample, SHA256 `c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63`. The retained HEF input is RGB UINT8, resized from 810x1080 to 720x960 and padded 120 pixels left/right with 114, SHA256 `6b56c889823ba04a26904fcfd1e6563b31f37b5b563d0a375b892a91561dba9a`.

Clean7 ran that exact input through the selected HEF in UINT16 and FLOAT32 modes. `real-scene/comparison-report.json` retains capture hashes and naturally occurring low/median/high vectors for both classes at strides 8/16/32, including raw UINT16, dequantized `l,t,r,b`, decoded coordinates, score, identity, rank, and a diagnostic score comparison at 0.30. Manual versus HailoRT dequantization and decoded results match with maximum error 0.0. Real HEF TopK scores span 0.00163264–0.549442 with 298 vehicle and two motorcycle-class candidates. The float ONNX comparison is retained as a whole-network quantization/compiler diagnostic, not an expected bit-exact decoder comparison.

## SDK quantized HAR interpretation

The Hailo Dataflow Compiler 3.34.0 guide describes `SDK_QUANTIZED` as an accuracy emulator and explicitly says it is not bit-exact with Hailo hardware. Compilation changes Quantized Model into Compiled Model, and the guide lists a distinct preview `SDK_BIT_EXACT` context with limited support. The selected build log confirms the quantized HAR was subsequently compiled into the HEF.

The retained HAR differences—head values up to 11.125042, boxes up to 38.526299 pixels, scores up to 0.0010176844—are diagnostics rather than final-HEF oracle failures. They remain in `comparison-report.json` and are excluded from PASS criteria. The final HEF's HailoRT UINT16-to-FLOAT32 identity is the authoritative application-path dequantization check.

## Closure requirement

Collect a representative independent motorcycle validation set with enough scenes, conditions, ranges, and negative examples to estimate class false negatives and false positives. Run the versioned sweep unchanged, select a safety-weighted operating point with explicit workload bounds, and record it in `detector-admission-policy.json`. Until then, **M2B.2b remains OPEN** and production runtime work must not begin.

## Reproduction

Qualification-only tools are `threshold_sweep.py`, `audit_graph.py`, `compare_decoder.py`, `compare_real_scene.py`, and `rave_hailo_capture.cpp`. They require the immutable selected artifacts, frozen output ABI JSON, and retained Clean7 captures.
