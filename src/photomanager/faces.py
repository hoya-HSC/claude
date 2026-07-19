from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]
    embedding: np.ndarray
    """L2-normalized 512-d embedding, comparable via cosine distance."""


class FaceEmbedder:
    """GPU-backed face detector + embedder using InsightFace's buffalo_l model pack.

    Requires onnxruntime-gpu and a CUDA-capable environment (see setup/). Import
    of insightface is deferred to __init__ so this module can be imported on
    machines without a GPU (e.g. for running the non-GPU parts of the test suite).
    """

    def __init__(self, providers: list[str] | None = None) -> None:
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(
            name="buffalo_l",
            providers=providers or ["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=0, det_size=(640, 640))

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        faces = self._app.get(image)
        results = []
        for face in faces:
            embedding = face.normed_embedding.astype(np.float32)
            x1, y1, x2, y2 = face.bbox.tolist()
            results.append(DetectedFace(bbox=(x1, y1, x2, y2), embedding=embedding))
        return results


def embedding_to_blob(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
