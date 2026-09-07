#!/usr/bin/env python3
"""Capture qualification-only Hailo SDK outputs for one deterministic input."""

import argparse
import json
from pathlib import Path

import numpy as np
from hailo_sdk_client import ClientRunner, InferenceContext


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("har", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("fp", "quant"), required=True)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    expected = 960 * 960 * 3
    if len(raw) != expected:
        raise SystemExit(f"input must contain exactly {expected} bytes")
    image = np.frombuffer(raw, dtype=np.uint8).reshape(1, 960, 960, 3).astype(np.float32)
    context = (
        InferenceContext.SDK_FP_OPTIMIZED
        if args.mode == "fp"
        else InferenceContext.SDK_QUANTIZED
    )
    runner = ClientRunner(har=str(args.har))
    with runner.infer_context(context) as ctx:
        outputs = runner.infer(ctx, image)

    args.output.mkdir(parents=True, exist_ok=True)
    if isinstance(outputs, dict):
        named = outputs
    elif isinstance(outputs, (list, tuple)):
        named = {f"output_{index}": value for index, value in enumerate(outputs)}
    else:
        named = {"output_0": outputs}

    metadata = {"schema_version": 1, "mode": args.mode, "outputs": []}
    for name, value in named.items():
        array = np.asarray(value)
        filename = name.replace("/", "__") + ".npy"
        np.save(args.output / filename, array, allow_pickle=False)
        metadata["outputs"].append(
            {"name": name, "file": filename, "shape": list(array.shape), "dtype": str(array.dtype)}
        )
    (args.output / "capture-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
