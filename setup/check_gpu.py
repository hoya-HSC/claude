"""Verify the GPU is actually usable by onnxruntime before running the pipeline.

Usage: python setup/check_gpu.py
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime is not installed in this environment.")
        return 1

    providers = ort.get_available_providers()
    print(f"onnxruntime {ort.__version__}, available providers: {providers}")

    if "CUDAExecutionProvider" not in providers:
        print(
            "\nCUDAExecutionProvider is NOT available -- onnxruntime will fall back "
            "to CPU, which will be far slower for hundreds of thousands of photos.\n"
            "This usually means the cudatoolkit/cudnn versions in environment.yml "
            "don't match what this onnxruntime-gpu build expects. Check the "
            "compatibility table at https://onnxruntime.ai/docs/execution-providers/"
            "CUDA-ExecutionProvider.html and adjust setup/environment.yml accordingly."
        )
        return 1

    print("CUDAExecutionProvider is available. Running a tiny GPU inference smoke test...")
    import numpy as np

    session = ort.InferenceSession(
        _tiny_identity_model(), providers=["CUDAExecutionProvider"]
    )
    result = session.run(None, {"x": np.array([[1.0, 2.0]], dtype=np.float32)})
    print(f"GPU inference OK, output: {result[0]}")
    return 0


def _tiny_identity_model() -> bytes:
    import onnx
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 2])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 2])
    node = helper.make_node("Identity", ["x"], ["y"])
    graph = helper.make_graph([node], "identity", [x], [y])
    model = helper.make_model(graph, producer_name="photomanager-check")
    return model.SerializeToString()


if __name__ == "__main__":
    sys.exit(main())
