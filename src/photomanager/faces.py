from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

THUMBNAIL_MARGIN = 0.3
"""Extra padding around the detected bbox so hair/chin aren't cut off."""


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]
    embedding: np.ndarray
    """L2-normalized 512-d embedding, comparable via cosine distance."""
    thumbnail: bytes
    """JPEG-encoded crop, cached at detection time so the review UI never
    needs to re-open the source file (works for video frames too, which
    have no standalone image file to re-open later)."""


def crop_thumbnail(
    frame_bgr: np.ndarray, bbox: tuple[float, float, float, float], margin: float = THUMBNAIL_MARGIN
) -> bytes:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    x1 -= w * margin
    x2 += w * margin
    y1 -= h * margin
    y2 += h * margin
    height, width = frame_bgr.shape[:2]
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(width, int(x2)), min(height, int(y2))

    crop_rgb = frame_bgr[y1:y2, x1:x2, ::-1]
    buf = io.BytesIO()
    Image.fromarray(crop_rgb).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


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
        """image is a BGR array (OpenCV/InsightFace convention)."""
        faces = self._app.get(image)
        results = []
        for face in faces:
            embedding = face.normed_embedding.astype(np.float32)
            bbox = tuple(face.bbox.tolist())
            results.append(DetectedFace(
                bbox=bbox,
                embedding=embedding,
                thumbnail=crop_thumbnail(image, bbox),
            ))
        return results


def embedding_to_blob(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
