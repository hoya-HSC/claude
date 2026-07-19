from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .volume import volume_key_for


@dataclass
class ScanResult:
    new_files: list[int]
    """Row ids of files.id whose content_hash was newly discovered this scan."""
    moved_files: int
    unchanged_files: int
    missing_files: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _media_type(path: Path, cfg: Config) -> str | None:
    ext = path.suffix.lower()
    if ext in cfg.photo_extensions:
        return "photo"
    if ext in cfg.video_extensions:
        return "video"
    return None


def _get_or_create_volume(conn: sqlite3.Connection, volume_key: str, mount_root: str) -> int:
    row = conn.execute(
        "SELECT id FROM volumes WHERE volume_key = ?", (volume_key,)
    ).fetchone()
    if row is not None:
        # mount_root is refreshed every scan since it can change (e.g. an
        # external disk's drive letter), unlike volume_key which is stable.
        conn.execute(
            "UPDATE volumes SET mount_root = ?, last_seen_at = ? WHERE id = ?",
            (mount_root, _now(), row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO volumes (volume_key, mount_root, last_seen_at) VALUES (?, ?, ?)",
        (volume_key, mount_root, _now()),
    )
    return cur.lastrowid


def scan(conn: sqlite3.Connection, cfg: Config) -> ScanResult:
    """Incrementally scan cfg.scan_roots and reconcile against the files table.

    A file is identified by content hash, not path, so moving or renaming it
    (including across a drive-letter change on an external disk) never
    triggers re-processing -- only its path is updated. Only genuinely new
    content runs through the (expensive) downstream pipeline.
    """
    new_files: list[int] = []
    moved_files = 0
    unchanged_files = 0
    seen_file_ids: set[int] = set()
    connected_volume_ids: set[int] = set()

    for root_str in cfg.scan_roots:
        root = Path(root_str)
        if not root.exists():
            continue
        volume_key, mount_root = volume_key_for(root)
        volume_id = _get_or_create_volume(conn, volume_key, mount_root)
        connected_volume_ids.add(volume_id)

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            media_type = _media_type(path, cfg)
            if media_type is None:
                continue

            try:
                relative_path = str(path.resolve().relative_to(Path(mount_root).resolve()))
            except ValueError:
                relative_path = str(path.resolve())
            stat = path.stat()

            existing = conn.execute(
                "SELECT id, content_hash, size, mtime FROM files "
                "WHERE volume_id = ? AND relative_path = ?",
                (volume_id, relative_path),
            ).fetchone()

            if existing is not None and existing["size"] == stat.st_size and abs(
                existing["mtime"] - stat.st_mtime
            ) < 1.0:
                conn.execute(
                    "UPDATE files SET last_seen_at = ?, status = 'active' WHERE id = ?",
                    (_now(), existing["id"]),
                )
                seen_file_ids.add(existing["id"])
                unchanged_files += 1
                continue

            content_hash = _hash_file(path, cfg.hash_algorithm)
            by_hash = conn.execute(
                "SELECT id FROM files WHERE content_hash = ?", (content_hash,)
            ).fetchone()

            if by_hash is not None:
                conn.execute(
                    "UPDATE files SET volume_id = ?, relative_path = ?, size = ?, "
                    "mtime = ?, last_seen_at = ?, status = 'active' WHERE id = ?",
                    (volume_id, relative_path, stat.st_size, stat.st_mtime, _now(), by_hash["id"]),
                )
                seen_file_ids.add(by_hash["id"])
                moved_files += 1
                continue

            if existing is not None:
                # Same path, but content changed (an edited photo, not a move) --
                # update the existing row in place and flag it for reprocessing,
                # rather than inserting a second row for the same path.
                conn.execute(
                    "UPDATE files SET content_hash = ?, size = ?, mtime = ?, "
                    "last_seen_at = ?, status = 'active', metadata_processed = 0, "
                    "faces_processed = 0 WHERE id = ?",
                    (content_hash, stat.st_size, stat.st_mtime, _now(), existing["id"]),
                )
                seen_file_ids.add(existing["id"])
                new_files.append(existing["id"])
                continue

            cur = conn.execute(
                "INSERT INTO files (content_hash, volume_id, relative_path, size, mtime, "
                "media_type, status, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (
                    content_hash, volume_id, relative_path, stat.st_size, stat.st_mtime,
                    media_type, _now(), _now(),
                ),
            )
            new_files.append(cur.lastrowid)
            seen_file_ids.add(cur.lastrowid)

    missing_files = 0
    if connected_volume_ids:
        placeholders = ",".join("?" * len(connected_volume_ids))
        rows = conn.execute(
            f"SELECT id FROM files WHERE volume_id IN ({placeholders}) AND status = 'active'",
            tuple(connected_volume_ids),
        ).fetchall()
        for row in rows:
            if row["id"] not in seen_file_ids:
                conn.execute(
                    "UPDATE files SET status = 'missing' WHERE id = ?", (row["id"],)
                )
                missing_files += 1

    return ScanResult(
        new_files=new_files,
        moved_files=moved_files,
        unchanged_files=unchanged_files,
        missing_files=missing_files,
    )
