"""Generate tiny positive/negative models; these are not manga AI models."""
from pathlib import Path

import onnx
from onnx import TensorProto, helper


def main():
    assets = Path(__file__).parent / "npu-check/src/main/assets"
    assets.mkdir(parents=True, exist_ok=True)
    weights = helper.make_tensor("weights", TensorProto.FLOAT, [4, 2], list(range(1, 9)))
    cases = [
        ("matmul", [helper.make_node("MatMul", ["input", "weights"], ["output"])],
         [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 2])], [weights]),
        ("unsupported", [helper.make_node("Unique", ["input"], ["output"])],
         [helper.make_tensor_value_info("output", TensorProto.FLOAT, [None])], []),
    ]
    for name, nodes, outputs, initializers in cases:
        graph = helper.make_graph(nodes, name,
                                  [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 4])],
                                  outputs, initializers)
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)], ir_version=9)
        onnx.checker.check_model(model)
        onnx.save(model, assets / f"{name}.onnx")
    assert [sum((i + 1) * (2 * i + col + 1) for i in range(4)) for col in range(2)] == [50, 60]


if __name__ == "__main__":
    main()
