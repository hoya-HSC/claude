from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from .config import Config
from .faces import DetectedFace, blob_to_embedding, embedding_to_blob


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def compute_person_centroids(conn: sqlite3.Connection) -> dict[int, np.ndarray]:
    """Mean embedding per person, built only from user-confirmed faces.

    Confirmed-only keeps a single wrong auto-assignment from dragging a
    person's centroid off course.
    """
    rows = conn.execute(
        "SELECT person_id, embedding FROM faces "
        "WHERE person_id IS NOT NULL AND review_status = 'confirmed'"
    ).fetchall()

    by_person: dict[int, list[np.ndarray]] = {}
    for row in rows:
        by_person.setdefault(row["person_id"], []).append(blob_to_embedding(row["embedding"]))

    return {
        person_id: np.mean(np.stack(embeddings), axis=0)
        for person_id, embeddings in by_person.items()
    }


@dataclass
class FaceAssignment:
    person_id: int | None
    distance: float | None
    needs_review: bool


def assign_face(embedding: np.ndarray, centroids: dict[int, np.ndarray], cfg: Config) -> FaceAssignment:
    if not centroids:
        return FaceAssignment(person_id=None, distance=None, needs_review=True)

    distances = {pid: cosine_distance(embedding, c) for pid, c in centroids.items()}
    best_person, best_distance = min(distances.items(), key=lambda kv: kv[1])

    if best_distance > cfg.face_match_threshold + cfg.face_review_margin:
        return FaceAssignment(person_id=None, distance=best_distance, needs_review=True)

    needs_review = best_distance > cfg.face_match_threshold - cfg.face_review_margin
    return FaceAssignment(person_id=best_person, distance=best_distance, needs_review=needs_review)


def store_detected_faces(
    conn: sqlite3.Connection, file_id: int, detections: list[DetectedFace], cfg: Config
) -> list[int]:
    centroids = compute_person_centroids(conn)
    face_ids = []
    for face in detections:
        assignment = assign_face(face.embedding, centroids, cfg)
        cur = conn.execute(
            "INSERT INTO faces (file_id, bbox, embedding, thumbnail, person_id, distance_to_person, review_status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (
                file_id,
                ",".join(f"{v:.2f}" for v in face.bbox),
                embedding_to_blob(face.embedding),
                face.thumbnail,
                assignment.person_id,
                assignment.distance,
            ),
        )
        face_ids.append(cur.lastrowid)
    conn.execute("UPDATE files SET faces_processed = 1 WHERE id = ?", (file_id,))
    return face_ids


def propose_clusters_for_unassigned(
    conn: sqlite3.Connection, min_cluster_size: int = 3
) -> dict[int, list[int]]:
    """Group faces with no person assignment into candidate clusters for review.

    Uses HDBSCAN so cluster count doesn't need to be known in advance. Returns
    {cluster_label: [face_id, ...]}, largest cluster first; noise points
    (label -1, i.e. one-off faces with no close neighbours) are omitted.
    """
    import hdbscan

    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE person_id IS NULL"
    ).fetchall()
    if len(rows) < min_cluster_size:
        return {}

    face_ids = [row["id"] for row in rows]
    embeddings = np.stack([blob_to_embedding(row["embedding"]) for row in rows])

    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
    labels = clusterer.fit_predict(embeddings)

    clusters: dict[int, list[int]] = {}
    for face_id, label in zip(face_ids, labels):
        if label == -1:
            continue
        clusters.setdefault(int(label), []).append(face_id)

    return dict(sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True))
