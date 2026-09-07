"""Record the selected ONNX graph's confidence and TopK contract."""

import argparse
import hashlib
import json
from pathlib import Path

import onnx
from onnx import numpy_helper


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = onnx.load(args.onnx)
    producers = {value: node for node in model.graph.node for value in node.output}
    initializers = {value.name: numpy_helper.to_array(value).tolist() for value in model.graph.initializer}

    def constant(value: str):
        if value in initializers:
            return initializers[value]
        node = producers.get(value)
        if node and node.op_type == "Constant":
            return onnx.helper.get_attribute_value(node.attribute[0]).int64_data[0]
        return None

    relevant = []
    forbidden = {"Greater", "GreaterOrEqual", "Less", "LessOrEqual", "Where", "NonMaxSuppression"}
    for index, node in enumerate(model.graph.node):
        if node.name.startswith("/model.23/") and node.op_type in {
            "Sigmoid", "ReduceMax", "TopK", "Gather", "GatherElements", "Flatten", "Div", "Mod"
        }:
            relevant.append(
                {
                    "index": index,
                    "name": node.name,
                    "op_type": node.op_type,
                    "inputs": list(node.input),
                    "outputs": list(node.output),
                    "attributes": {
                        attribute.name: onnx.helper.get_attribute_value(attribute)
                        for attribute in node.attribute
                    },
                    "constant_inputs": {value: constant(value) for value in node.input if constant(value) is not None},
                }
            )
    threshold_nodes = [
        {"index": index, "name": node.name, "op_type": node.op_type}
        for index, node in enumerate(model.graph.node)
        if node.op_type in forbidden
    ]
    payload = {
        "schema_version": 1,
        "onnx": {"artifact": args.onnx.name, "sha256": sha256(args.onnx)},
        "graph_output": [value.name for value in model.graph.output],
        "confidence": {
            "activation": "Sigmoid",
            "objectness_branch": "none",
            "threshold": None,
            "threshold_nodes_anywhere_in_graph": threshold_nodes,
            "conclusion": "GRAPH CONFIDENCE THRESHOLD: NONE; output0 is score-ranked TopK only.",
        },
        "topk": {
            "k": 300,
            "stages": 2,
            "largest": 1,
            "sorted": 1,
            "tie_identity_order": "not specified by the selected graph",
        },
        "selected_postprocess_nodes": relevant,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
