from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from . import scanner
from .clustering import store_detected_faces
from .config import Config
from .events import TimelineItem, cluster_events
from .geocode import get_or_create_place
from .metadata import extract_metadata

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


@dataclass
class PipelineStats:
    scanned: scanner.ScanResult
    metadata_processed: int
    faces_processed: int
    events_rebuilt: int


def run_once(conn: sqlite3.Connection, cfg: Config, embedder=None) -> PipelineStats:
    """Run one bounded batch of work: scan, then metadata, then faces, then events.

    Each stage is capped at cfg.batch_size so a run can be safely re-invoked
    on a schedule -- unfinished work is picked up next time via the
    *_processed flags, nothing needs to restart from scratch.
    """
    scan_result = scanner.scan(conn, cfg)
    conn.commit()

    metadata_count = _process_metadata_batch(conn, cfg)
    conn.commit()

    faces_count = _process_faces_batch(conn, cfg, embedder) if embedder is not None else 0
    conn.commit()

    events_count = _rebuild_events(conn, cfg)
    conn.commit()

    return PipelineStats(
        scanned=scan_result,
        metadata_processed=metadata_count,
        faces_processed=faces_count,
        events_rebuilt=events_count,
    )


def _process_metadata_batch(conn: sqlite3.Connection, cfg: Config) -> int:
    rows = conn.execute(
        "SELECT id, volume_id, relative_path, media_type FROM files "
        "WHERE metadata_processed = 0 AND status = 'active' LIMIT ?",
        (cfg.batch_size,),
    ).fetchall()

    for row in rows:
        volume = conn.execute(
            "SELECT mount_root FROM volumes WHERE id = ?", (row["volume_id"],)
        ).fetchone()
        path = Path(volume["mount_root"]) / row["relative_path"]
        meta = extract_metadata(path, row["media_type"])
        place_id = get_or_create_place(conn, meta.gps_lat, meta.gps_lon)
        conn.execute(
            "UPDATE files SET taken_at = ?, gps_lat = ?, gps_lon = ?, place_id = ?, "
            "metadata_processed = 1 WHERE id = ?",
            (
                meta.taken_at.isoformat() if meta.taken_at else None,
                meta.gps_lat, meta.gps_lon, place_id, row["id"],
            ),
        )

    return len(rows)


def _process_faces_batch(conn: sqlite3.Connection, cfg: Config, embedder) -> int:
    from PIL import Image

    rows = conn.execute(
        "SELECT id, volume_id, relative_path, media_type FROM files "
        "WHERE faces_processed = 0 AND status = 'active' LIMIT ?",
        (cfg.batch_size,),
    ).fetchall()

    for row in rows:
        volume = conn.execute(
            "SELECT mount_root FROM volumes WHERE id = ?", (row["volume_id"],)
        ).fetchone()
        path = Path(volume["mount_root"]) / row["relative_path"]

        try:
            if row["media_type"] == "photo":
                frames = [np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1]]
            else:
                from .video import extract_keyframes
                frames = extract_keyframes(path)

            detections = []
            for frame in frames:
                detections.extend(embedder.detect(frame))
            store_detected_faces(conn, row["id"], detections, cfg)

            # Reuse the already-decoded first frame for the browse thumbnail
            # so galleries don't need to re-open (or reach) the source file.
            if frames:
                from .faces import make_file_thumbnail
                thumb = make_file_thumbnail(frames[0], cfg.file_thumbnail_px)
                conn.execute(
                    "UPDATE files SET thumbnail = ? WHERE id = ?", (thumb, row["id"])
                )
        except Exception as exc:
            # One unreadable/corrupt file out of hundreds of thousands
            # shouldn't abort the whole batch -- log it and move on. It's
            # marked processed so it doesn't get retried forever; delete
            # that flag manually (faces_processed = 0) to force a retry.
            print(f"skipping {path}: {exc}")
            conn.execute("UPDATE files SET faces_processed = 1 WHERE id = ?", (row["id"],))

    return len(rows)


def _rebuild_events(conn: sqlite3.Connection, cfg: Config) -> int:
    """Recompute trip/event groupings from scratch.

    Cheap (pure timestamp/GPS arithmetic, no model inference), so a full
    rebuild on every run is simpler and safer than incremental patching.
    """
    rows = conn.execute(
        "SELECT id, taken_at, gps_lat, gps_lon FROM files "
        "WHERE taken_at IS NOT NULL AND status = 'active'"
    ).fetchall()
    if not rows:
        return 0

    items = [
        TimelineItem(
            file_id=row["id"],
            taken_at=datetime.fromisoformat(row["taken_at"]),
            lat=row["gps_lat"],
            lon=row["gps_lon"],
        )
        for row in rows
    ]
    spans = cluster_events(items, cfg)

    conn.execute("UPDATE files SET event_id = NULL")
    conn.execute("DELETE FROM events")
    for span in spans:
        cur = conn.execute(
            "INSERT INTO events (start_at, end_at) VALUES (?, ?)",
            (span.start_at.isoformat(), span.end_at.isoformat()),
        )
        event_id = cur.lastrowid
        conn.executemany(
            "UPDATE files SET event_id = ? WHERE id = ?",
            [(event_id, fid) for fid in span.file_ids],
        )

    return len(spans)
