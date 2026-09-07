"""Qualification-only confidence sweep for the selected RAVE checkpoint."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from ultralytics import YOLO

CLASS_NAMES = ("vehicle", "motorcycle")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    if not len(boxes):
        return np.empty(0, dtype=np.float32)
    intersection_min = np.maximum(box[:2], boxes[:, :2])
    intersection_max = np.minimum(box[2:], boxes[:, 2:])
    intersection_wh = np.maximum(0.0, intersection_max - intersection_min)
    intersection = intersection_wh[:, 0] * intersection_wh[:, 1]
    box_area = max(0.0, float(box[2] - box[0])) * max(0.0, float(box[3] - box[1]))
    boxes_area = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
    return intersection / np.maximum(box_area + boxes_area - intersection, 1e-12)


def load_labels(label_path: Path, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    boxes, classes = [], []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        class_id, cx, cy, box_width, box_height = map(float, line.split())
        boxes.append(
            [
                (cx - box_width / 2) * width,
                (cy - box_height / 2) * height,
                (cx + box_width / 2) * width,
                (cy + box_height / 2) * height,
            ]
        )
        classes.append(int(class_id))
    return np.asarray(boxes, dtype=np.float32).reshape(-1, 4), np.asarray(classes, dtype=np.int32)


def match_image(predictions: dict, threshold: float, class_id: int) -> tuple[int, int, int]:
    pred_mask = (predictions["classes"] == class_id) & (predictions["scores"] >= threshold)
    pred_boxes = predictions["boxes"][pred_mask]
    pred_scores = predictions["scores"][pred_mask]
    gt_boxes = predictions["gt_boxes"][predictions["gt_classes"] == class_id]
    unmatched = set(range(len(gt_boxes)))
    true_positives = 0
    for index in np.argsort(-pred_scores):
        candidates = sorted(unmatched)
        if not candidates:
            break
        overlaps = box_iou(pred_boxes[index], gt_boxes[candidates])
        best = int(np.argmax(overlaps))
        if overlaps[best] >= 0.5:
            unmatched.remove(candidates[best])
            true_positives += 1
    false_positives = len(pred_boxes) - true_positives
    false_negatives = len(gt_boxes) - true_positives
    return true_positives, false_positives, false_negatives


def summarize(predictions: list[dict], threshold: float) -> dict:
    per_class = {}
    for class_id, name in enumerate(CLASS_NAMES):
        totals = np.sum([match_image(item, threshold, class_id) for item in predictions], axis=0)
        true_positives, false_positives, false_negatives = map(int, totals)
        precision = true_positives / max(true_positives + false_positives, 1)
        recall = true_positives / max(true_positives + false_negatives, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        per_class[name] = {
            "ground_truth": true_positives + false_negatives,
            "true_positives_iou50": true_positives,
            "false_positives_iou50": false_positives,
            "false_negatives_iou50": false_negatives,
            "precision_iou50": precision,
            "recall_iou50": recall,
            "f1_iou50": f1,
        }
    counts = np.asarray([np.count_nonzero(item["scores"] >= threshold) for item in predictions])
    return {
        "threshold": threshold,
        "classes": per_class,
        "candidates": {
            "total": int(counts.sum()),
            "mean_per_image": float(counts.mean()),
            "median_per_image": float(np.median(counts)),
            "p95_per_image": float(np.percentile(counts, 95)),
            "max_per_image": int(counts.max()),
            "images_with_zero": int(np.count_nonzero(counts == 0)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    image_paths = sorted(args.images.glob("*.jpg"))
    if not image_paths:
        raise SystemExit("no validation images")
    model = YOLO(args.checkpoint)
    results = model.predict(
        source=[str(path) for path in image_paths],
        imgsz=960,
        conf=0.0,
        iou=0.7,
        max_det=300,
        device="cpu",
        stream=True,
        verbose=False,
    )

    predictions = []
    inventory = []
    for path, result in zip(image_paths, results, strict=True):
        with Image.open(path) as image:
            width, height = image.size
        gt_boxes, gt_classes = load_labels(args.labels / f"{path.stem}.txt", width, height)
        predictions.append(
            {
                "boxes": result.boxes.xyxy.cpu().numpy().astype(np.float32),
                "scores": result.boxes.conf.cpu().numpy().astype(np.float32),
                "classes": result.boxes.cls.cpu().numpy().astype(np.int32),
                "gt_boxes": gt_boxes,
                "gt_classes": gt_classes,
            }
        )
        inventory.append(
            {
                "name": path.name,
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "graph_candidates": len(result.boxes),
                "ground_truth": {name: int(np.count_nonzero(gt_classes == class_id)) for class_id, name in enumerate(CLASS_NAMES)},
            }
        )

    thresholds = np.unique(
        np.concatenate(
            (
                [0.0],
                np.logspace(-5, -1, 41),
                np.linspace(0.1, 0.95, 18),
                [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
            )
        )
    )
    payload = {
        "schema_version": 1,
        "checkpoint": {"artifact": args.checkpoint.name, "sha256": sha256(args.checkpoint)},
        "dataset": {
            "images": len(predictions),
            "ground_truth": {
                name: int(sum(np.count_nonzero(item["gt_classes"] == class_id) for item in predictions))
                for class_id, name in enumerate(CLASS_NAMES)
            },
            "inventory": inventory,
        },
        "method": {
            "model_output": "end-to-end graph top-300, conf=0.0; no IoU NMS",
            "matching": "per-image, per-class greedy descending-score match at IoU >= 0.50",
            "threshold_operator": "score >= threshold",
        },
        "sweep": [summarize(predictions, float(threshold)) for threshold in thresholds],
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
