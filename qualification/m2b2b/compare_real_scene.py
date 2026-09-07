"""Compare real-scene UINT16 and FLOAT32 Hailo captures and retain vectors."""

import argparse
import json
from pathlib import Path

import numpy as np
from compare_decoder import (
    CLASSES,
    SCALES,
    decode,
    expose_onnx_heads,
    max_error,
    sha256,
    two_stage_top300,
)


def load(root: Path, abi: dict, kind: str) -> tuple[list[np.ndarray], list[np.ndarray]]:
    regression, logits = [], []
    directory = root / ("hailo-u16" if kind == "raw" else "hailo-f32")
    for _, size, reg_name, cls_name, _ in SCALES:
        pair = []
        for name, channels in ((reg_name, 4), (cls_name, 2)):
            if kind == "raw":
                raw = np.fromfile(directory / f"{name}.u16le", dtype="<u2").reshape(size, size, channels)
                entry = next(item for item in abi["outputs"] if item["name"].endswith("/" + name))
                quant = entry["quantization"]
                value = (raw.astype(np.float32) - np.float32(quant["qp_zp"])) * np.float32(quant["qp_scale"])
            else:
                value = np.fromfile(directory / f"{name}.f32le", dtype="<f4").reshape(size, size, channels)
            pair.append(value)
        regression.append(pair[0])
        logits.append(pair[1])
    return regression, logits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--abi", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    abi = json.loads(args.abi.read_text(encoding="utf-8"))
    raw_reg, raw_cls = load(args.root, abi, "raw")
    f32_reg, f32_cls = load(args.root, abi, "f32")
    boxes, scores = decode(raw_reg, raw_cls)
    decoded, identities = two_stage_top300(boxes, scores)
    decoded_f32, identities_f32 = two_stage_top300(*decode(f32_reg, f32_cls))
    image = np.fromfile(args.root / "ultralytics-bus-960.rgbu8", dtype=np.uint8).reshape(1, 960, 960, 3)
    session, head_names = expose_onnx_heads(args.onnx)
    onnx_input = image.astype(np.float32).transpose(0, 3, 1, 2) / np.float32(255.0)
    fetched = session.run(head_names, {"images": onnx_input})
    heads = [value.transpose(0, 2, 3, 1)[0] for value in fetched]
    onnx_reg = heads[0::2]
    onnx_cls = heads[1::2]
    onnx_boxes, onnx_scores = decode(onnx_reg, onnx_cls)
    _, identities_onnx = two_stage_top300(onnx_boxes, onnx_scores)

    vectors = []
    base = 0
    for scale_index, (stride, size, reg_name, cls_name, _) in enumerate(SCALES):
        for class_id, class_name in enumerate(CLASSES):
            flat = scores[base : base + size * size, class_id]
            for label, local in (
                ("minimum", int(np.argmin(flat))),
                ("median", int(np.argsort(flat, kind="stable")[len(flat) // 2])),
                ("maximum", int(np.argmax(flat))),
            ):
                y, x = divmod(local, size)
                location = base + local
                raw_reg_values = np.fromfile(
                    args.root / f"hailo-u16/{reg_name}.u16le", dtype="<u2"
                ).reshape(size, size, 4)[y, x]
                raw_cls_values = np.fromfile(
                    args.root / f"hailo-u16/{cls_name}.u16le", dtype="<u2"
                ).reshape(size, size, 2)[y, x]
                vectors.append(
                    {
                        "selection": label,
                        "stride": stride,
                        "scale": scale_index,
                        "regression_vstream": reg_name,
                        "classification_vstream": cls_name,
                        "tensor_index_yxc": [y, x, class_id],
                        "flat_location": location,
                        "class_id": class_id,
                        "class_name": class_name,
                        "raw_regression_u16": raw_reg_values.astype(int).tolist(),
                        "raw_class_u16": int(raw_cls_values[class_id]),
                        "dequantized_ltrb": raw_reg[scale_index][y, x].astype(float).tolist(),
                        "dequantized_class_logit": float(raw_cls[scale_index][y, x, class_id]),
                        "decoded_xyxy": boxes[location].astype(float).tolist(),
                        "sigmoid_score": float(scores[location, class_id]),
                        "hailo_top300_rank": next(
                            (rank for rank, item in enumerate(identities.tolist()) if item == [location, class_id]),
                            None,
                        ),
                        "diagnostic_score_ge_0_30": bool(scores[location, class_id] >= 0.30),
                    }
                )
        base += size * size

    paths = sorted(path for path in args.root.rglob("*") if path.is_file())
    report = {
        "schema_version": 1,
        "status": "PASS for manual dequantization; admission policy remains OPEN",
        "input": {
            "file": "ultralytics-bus-960.rgbu8",
            "sha256": sha256(args.root / "ultralytics-bus-960.rgbu8"),
            "source": "Ultralytics package asset bus.jpg",
            "source_sha256": sha256(args.root / "ultralytics-bus.jpg"),
            "preprocess": "BGR decode -> RGB; scale 0.8888888889 to 720x960; pad 120 left/right with 114",
        },
        "capture_files": {
            str(path.relative_to(args.root)): {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in paths
            if path.parent.name in {"hailo-u16", "hailo-f32"}
        },
        "manual_dequantization_vs_hailort_float32_max_abs_error": {
            name: max_error(raw, direct)
            for scale_index, (_, _, reg_name, cls_name, _) in enumerate(SCALES)
            for name, raw, direct in (
                (reg_name, raw_reg[scale_index], f32_reg[scale_index]),
                (cls_name, raw_cls[scale_index], f32_cls[scale_index]),
            )
        },
        "decoded_uint16_vs_hailort_float32": {
            "max_abs_error": max_error(decoded, decoded_f32),
            "top300_order_and_membership_equal": bool(np.array_equal(identities, identities_f32)),
        },
        "compiled_hef_vs_float_onnx_whole_network": {
            "head_max_abs_error": {
                name: max_error(hailo, reference)
                for scale_index, (_, _, reg_name, cls_name, _) in enumerate(SCALES)
                for name, hailo, reference in (
                    (reg_name, raw_reg[scale_index], onnx_reg[scale_index]),
                    (cls_name, raw_cls[scale_index], onnx_cls[scale_index]),
                )
            },
            "decoded_box_max_abs_error_pixels": max_error(boxes, onnx_boxes),
            "sigmoid_score_max_abs_error": max_error(scores, onnx_scores),
            "top300_membership_overlap": len(
                {tuple(value) for value in identities.tolist()}
                & {tuple(value) for value in identities_onnx.tolist()}
            ),
            "interpretation": "diagnostic whole-network compiler/quantization difference, not decoder error",
        },
        "top300_score_range": [float(decoded[:, 4].min()), float(decoded[:, 4].max())],
        "top300_class_counts": {
            class_name: int(np.count_nonzero(decoded[:, 5] == class_id))
            for class_id, class_name in enumerate(CLASSES)
        },
        "vectors": vectors,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
