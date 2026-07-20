"""Reformat folder names that start with a raw YYYYMMDD date to YYYY-MM-DD.

Only the leading 8-digit date gets hyphenated; everything after it is kept
verbatim. This handles day-range suffixes for free, since the range just
passes through untouched:

    20120114_무주리조트     -> 2012-01-14_무주리조트
    20120114-16_무주리조트  -> 2012-01-14-16_무주리조트

Folders that don't start with 8 consecutive digits (including already-
hyphenated names) are left alone, which also makes this safe to re-run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_FOLDER_DATE_PREFIX_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(.*)$")


@dataclass
class FolderRename:
    old_path: Path
    new_name: str


@dataclass
class RenamePlan:
    renames: list[FolderRename] = field(default_factory=list)
    skipped_collisions: list[Path] = field(default_factory=list)
    """Target name already taken by another folder; left untouched rather
    than merging/overwriting."""


def new_folder_name(name: str) -> str | None:
    """Return the reformatted name, or None if `name` doesn't start with a
    valid 8-digit date (nothing to change)."""
    m = _FOLDER_DATE_PREFIX_RE.match(name)
    if not m:
        return None
    year, month, day, rest = m.groups()
    try:
        datetime(int(year), int(month), int(day))
    except ValueError:
        return None
    return f"{year}-{month}-{day}{rest}"


def build_rename_plan(root: Path) -> RenamePlan:
    """Scan every folder under root (including root's subfolders at any
    depth) and plan renames for ones with a raw-date prefix."""
    plan = RenamePlan()
    root = Path(root)
    claimed_per_parent: dict[Path, set[str]] = {}

    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: str(p)):
        new_name = new_folder_name(folder.name)
        if new_name is None or new_name == folder.name:
            continue

        parent = folder.parent
        target = parent / new_name
        claimed = claimed_per_parent.setdefault(parent, set())

        if target.exists() or new_name in claimed:
            plan.skipped_collisions.append(folder)
            continue

        claimed.add(new_name)
        plan.renames.append(FolderRename(old_path=folder, new_name=new_name))

    return plan


def apply_rename_plan(plan: RenamePlan) -> int:
    """Rename deepest folders first, so renaming a parent never invalidates
    the still-pending old path of a folder nested inside it."""
    ordered = sorted(plan.renames, key=lambda r: len(r.old_path.parts), reverse=True)
    renamed = 0
    for r in ordered:
        target = r.old_path.parent / r.new_name
        r.old_path.rename(target)
        renamed += 1
    return renamed


def summarize_plan(plan: RenamePlan) -> str:
    lines = [f"이름 바꿀 폴더: {len(plan.renames)}개"]
    for r in plan.renames:
        lines.append(f"  {r.old_path.name}  ->  {r.new_name}")

    if plan.skipped_collisions:
        lines.append("")
        lines.append(f"※ 바꾸려는 이름이 이미 존재해서 건너뜀: {len(plan.skipped_collisions)}개")
        for p in plan.skipped_collisions:
            lines.append(f"  {p}")

    return "\n".join(lines)
