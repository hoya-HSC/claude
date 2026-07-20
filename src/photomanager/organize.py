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

import bisect
import hashlib
import re
import shutil
from collections import Counter
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

_RELIABLE_SOURCES = ("exif", "filename")


@dataclass
class PlannedMove:
    source: Path
    dest: Path
    date_source: str  # "exif" | "filename" | "estimated" | "mtime"


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


@dataclass
class _Candidate:
    path: Path
    date: datetime
    date_source: str


def _estimate_from_neighbors(candidates: list[_Candidate]) -> None:
    """Fill in a date for mtime-only files (typically videos with no EXIF/
    media date) using the nearest reliable (exif/filename) neighbours in
    filename order within the same folder.

    A file's own mtime is trusted whenever it's *plausible* given its
    position: if it sits (by filename order) between two reliably-dated
    neighbours, its true date should logically fall within their date range
    too (file-transfer tools routinely preserve mtime even with no EXIF).
    When mtime already falls inside that range, it's left alone -- there's
    nothing to fix. Only when mtime falls *outside* the range it should
    logically be in (e.g. a later re-copy or backup restore reset it) does
    this replace it with an interpolated estimate between the neighbours.

    This caught a real case: five videos all actually shot 8/12 (their own
    mtime already said so) sat between a photo from 8/3 and one from 8/12 in
    filename order. A naive "always interpolate" approach smeared them across
    8/5-8/11; range-checking mtime first leaves all five at their own,
    already-correct 8/12.
    """
    reliable_indices = [i for i, c in enumerate(candidates) if c.date_source in _RELIABLE_SOURCES]
    if not reliable_indices:
        return

    for i, c in enumerate(candidates):
        if c.date_source != "mtime":
            continue

        pos = bisect.bisect_left(reliable_indices, i)
        before_idx = reliable_indices[pos - 1] if pos > 0 else None
        after_idx = reliable_indices[pos] if pos < len(reliable_indices) else None
        if before_idx is None and after_idx is None:
            continue  # no reliable neighbour on either side, mtime stands as-is

        own = c.date

        if before_idx is not None and after_idx is not None:
            before, after = candidates[before_idx], candidates[after_idx]
            lo, hi = min(before.date, after.date), max(before.date, after.date)
            if lo <= own <= hi:
                continue  # mtime is already plausible, leave it alone
            span = after_idx - before_idx
            weight = (i - before_idx) / span
            c.date = before.date + (after.date - before.date) * weight
            c.date_source = "estimated"
        elif before_idx is not None:
            before = candidates[before_idx]
            if own >= before.date:
                continue  # can't logically predate a confirmed earlier file
            c.date = before.date
            c.date_source = "estimated"
        else:
            after = candidates[after_idx]
            if own <= after.date:
                continue  # can't logically postdate a confirmed later file
            c.date = after.date
            c.date_source = "estimated"


def build_plan(source_directory: Path, cfg: Config) -> OrganizePlan:
    """Compute what would move, without touching anything."""
    plan = OrganizePlan()
    source_directory = Path(source_directory)

    candidates: list[_Candidate] = []
    for path in sorted(source_directory.iterdir()):
        if not path.is_file():
            continue
        media_type = _media_type(path, cfg)
        if media_type is None:
            continue
        date, date_source = resolve_date(path, media_type)
        candidates.append(_Candidate(path=path, date=date, date_source=date_source))

    if cfg.estimate_missing_dates_from_neighbors:
        _estimate_from_neighbors(candidates)

    for c in candidates:
        folder_name = c.date.strftime("%Y-%m-%d")

        # Already sitting in its correct date folder? (only meaningful when we
        # recurse, but iterdir() is top-level; kept for the re-run case where
        # the parent itself is a date folder.)
        if c.path.parent.name == folder_name:
            plan.skipped_already_sorted += 1
            continue

        dest_dir = source_directory / folder_name
        dest, is_dup = _dedup_dest(c.path, dest_dir)
        if is_dup:
            plan.duplicates.append(c.path)
        else:
            plan.moves.append(PlannedMove(source=c.path, dest=dest, date_source=c.date_source))

    return plan


def apply_plan(plan: OrganizePlan) -> int:
    moved = 0
    for mv in plan.moves:
        mv.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mv.source), str(mv.dest))
        moved += 1
    return moved


def summarize_plan(
    plan: OrganizePlan, *, mtime_preview_limit: int = 30, full_list: bool = False
) -> str:
    """Human-readable plan summary shared by the CLI and the GUI.

    Per-date-folder counts instead of a flat file list, since a messy library
    can produce hundreds of moves that a line-by-line dump makes unreadable.
    Pass full_list=True to append every planned move after a divider (the
    GUI does this instead of requiring a CSV export).
    """
    by_source = Counter(mv.date_source for mv in plan.moves)
    folder_counts = Counter(mv.dest.parent.name for mv in plan.moves)

    lines = [
        f"이동 대상: {len(plan.moves)}개  "
        f"(EXIF/메타 {by_source['exif']}, 파일명 {by_source['filename']}, "
        f"전후 파일로 추정 {by_source['estimated']}, 수정시간 {by_source['mtime']})",
        f"이미 같은 파일 존재(중복, 건너뜀): {len(plan.duplicates)}개",
        f"이미 날짜 폴더에 있음: {plan.skipped_already_sorted}개",
        "",
        f"생성될 날짜 폴더: {len(folder_counts)}개",
    ]
    for folder, count in sorted(folder_counts.items()):
        lines.append(f"  {folder}/   {count}개")

    estimated_moves = [mv for mv in plan.moves if mv.date_source == "estimated"]
    if estimated_moves:
        lines.append("")
        lines.append(
            f"※ 전후 파일 날짜로 추정된 파일 {len(estimated_moves)}개 "
            f"(주로 EXIF 없는 동영상; 앞뒤 사진 촬영일 사이로 추정, 확인 권장):"
        )
        for mv in estimated_moves[:mtime_preview_limit]:
            lines.append(f"  {mv.source.name}  ->  {mv.dest.parent.name}/")
        if len(estimated_moves) > mtime_preview_limit:
            lines.append(f"  ... 외 {len(estimated_moves) - mtime_preview_limit}개")

    mtime_moves = [mv for mv in plan.moves if mv.date_source == "mtime"]
    if mtime_moves:
        lines.append("")
        lines.append(
            f"※ 수정시간으로 추정된 파일 {len(mtime_moves)}개 "
            f"(전후에 참고할 파일도 없어 추정 불가, 촬영일과 다를 수 있음, 확인 권장):"
        )
        for mv in mtime_moves[:mtime_preview_limit]:
            lines.append(f"  {mv.source.name}  ->  {mv.dest.parent.name}/")
        if len(mtime_moves) > mtime_preview_limit:
            lines.append(f"  ... 외 {len(mtime_moves) - mtime_preview_limit}개")

    if full_list and plan.moves:
        by_folder: dict[str, list[PlannedMove]] = {}
        for mv in plan.moves:
            by_folder.setdefault(mv.dest.parent.name, []).append(mv)

        lines.append("")
        lines.append("=" * 50)
        lines.append(f"전체 이동 목록 ({len(plan.moves)}개, 날짜 폴더별)")
        lines.append("=" * 50)
        for folder in sorted(by_folder):
            moves = by_folder[folder]
            lines.append(f"\n{folder}/  ({len(moves)}개)")
            for mv in sorted(moves, key=lambda m: m.source.name):
                lines.append(f"  {mv.source.name}  [{mv.date_source}]")

    return "\n".join(lines)
