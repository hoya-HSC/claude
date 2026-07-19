"""Move loose photos/videos into YYYY-MM-DD date folders, safely.

This unifies and hardens the three original scripts (filename date / file
modification time / video media date) into one date resolver with a clear
priority, and adds the safety the originals lacked:

- Photo EXIF (DateTimeOriginal) and video media dates are read first, so a
  downloaded/copied file isn't mis-dated by its modification time.
- Filename collisions never overwrite: an identical file (same content
  hash) is treated as a duplicate; a different file gets a " (1)" suffix.
- Nothing moves unless apply=True; the default is a dry-run preview.

It operates within a single source directory (like the originals), so you
can keep organizing per photographer/source into separate trees.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config
from .metadata import extract_metadata

_FILENAME_DATE_PATTERNS = [
    re.compile(r"(\d{4})(\d{2})(\d{2})"),      # YYYYMMDD
    re.compile(r"(\d{4})[_-](\d{2})[_-](\d{2})"),  # YYYY_MM_DD / YYYY-MM-DD
]

_DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class PlannedMove:
    source: Path
    dest: Path
    date_source: str  # "exif" | "filename" | "mtime"


@dataclass
class OrganizePlan:
    moves: list[PlannedMove] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)  # identical file already at dest
    skipped_already_sorted: int = 0
    unresolved: list[Path] = field(default_factory=list)  # should never happen (mtime is last resort)


def _media_type(path: Path, cfg: Config) -> str | None:
    ext = path.suffix.lower()
    if ext in cfg.photo_extensions:
        return "photo"
    if ext in cfg.video_extensions:
        return "video"
    return None


def _date_from_filename(name: str) -> datetime | None:
    for pattern in _FILENAME_DATE_PATTERNS:
        m = pattern.search(name)
        if m:
            year, month, day = (int(v) for v in m.groups())
            if year >= 2000 and 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    return datetime(year, month, day)
                except ValueError:
                    continue
    return None


def resolve_date(path: Path, media_type: str) -> tuple[datetime, str]:
    """Return (date, source) using EXIF/media first, then filename, then mtime."""
    meta = extract_metadata(path, media_type)
    if meta.taken_at is not None:
        return meta.taken_at, "exif"

    from_name = _date_from_filename(path.name)
    if from_name is not None:
        return from_name, "filename"

    return datetime.fromtimestamp(path.stat().st_mtime), "mtime"


def _hash_file(path: Path) -> str:
    h = hashlib.blake2b()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dedup_dest(source: Path, dest_dir: Path) -> tuple[Path, bool]:
    """Pick a non-colliding destination path.

    Returns (dest, is_duplicate). If a file with the same name already exists
    and has identical content, is_duplicate is True (caller should not move,
    it's the same file). If it exists but differs, a numbered suffix is added
    so the existing file is never overwritten.
    """
    candidate = dest_dir / source.name
    if not candidate.exists():
        return candidate, False

    if candidate.stat().st_size == source.stat().st_size and _hash_file(candidate) == _hash_file(source):
        return candidate, True

    stem, suffix = source.stem, source.suffix
    i = 1
    while True:
        alt = dest_dir / f"{stem} ({i}){suffix}"
        if not alt.exists():
            return alt, False
        if alt.stat().st_size == source.stat().st_size and _hash_file(alt) == _hash_file(source):
            return alt, True
        i += 1


def build_plan(source_directory: Path, cfg: Config) -> OrganizePlan:
    """Compute what would move, without touching anything."""
    plan = OrganizePlan()
    source_directory = Path(source_directory)

    for path in sorted(source_directory.iterdir()):
        if not path.is_file():
            continue
        media_type = _media_type(path, cfg)
        if media_type is None:
            continue

        date, date_source = resolve_date(path, media_type)
        folder_name = date.strftime("%Y-%m-%d")

        # Already sitting in its correct date folder? (only meaningful when we
        # recurse, but iterdir() is top-level; kept for the re-run case where
        # the parent itself is a date folder.)
        if path.parent.name == folder_name:
            plan.skipped_already_sorted += 1
            continue

        dest_dir = source_directory / folder_name
        dest, is_dup = _dedup_dest(path, dest_dir)
        if is_dup:
            plan.duplicates.append(path)
        else:
            plan.moves.append(PlannedMove(source=path, dest=dest, date_source=date_source))

    return plan


def apply_plan(plan: OrganizePlan) -> int:
    moved = 0
    for mv in plan.moves:
        mv.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mv.source), str(mv.dest))
        moved += 1
    return moved
