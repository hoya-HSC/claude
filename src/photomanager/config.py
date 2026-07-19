from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    db_path: str = os.environ.get("PHOTOMANAGER_DB", "photomanager.sqlite3")
    scan_roots: list[str] = field(default_factory=list)

    photo_extensions: frozenset[str] = frozenset(
        {".jpg", ".jpeg", ".png", ".heic", ".bmp", ".tiff", ".webp"}
    )
    video_extensions: frozenset[str] = frozenset(
        {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp"}
    )

    batch_size: int = 500
    """Files processed per pipeline run before checkpointing and stopping."""

    event_gap_hours: float = 48.0
    """Consecutive photos more than this far apart in time start a new event."""

    event_gap_km: float = 50.0
    """GPS jump larger than this also starts a new event, independent of time gap."""

    face_match_threshold: float = 0.45
    """Cosine distance below which a face is auto-assigned to an existing person."""

    face_review_margin: float = 0.10
    """Faces within this margin of the threshold are queued for manual review."""

    hash_algorithm: str = "blake2b"


def load_config() -> Config:
    cfg = Config()
    roots = os.environ.get("PHOTOMANAGER_SCAN_ROOTS")
    if roots:
        cfg.scan_roots = [p for p in roots.split(os.pathsep) if p]
    return cfg
