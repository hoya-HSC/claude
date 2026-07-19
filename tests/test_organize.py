import os
from datetime import datetime

from photomanager import organize
from photomanager.config import Config


def _touch(path, content=b"x", mtime=None):
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_date_from_filename_variants():
    assert organize._date_from_filename("KakaoTalk_20250115_photo.jpg") == datetime(2025, 1, 15)
    assert organize._date_from_filename("2025_01_15 trip.jpg") == datetime(2025, 1, 15)
    assert organize._date_from_filename("2025-01-15.jpg") == datetime(2025, 1, 15)
    assert organize._date_from_filename("no date here.jpg") is None
    assert organize._date_from_filename("19990101.jpg") is None  # pre-2000 rejected
    assert organize._date_from_filename("20259999.jpg") is None  # impossible month/day


def test_plan_uses_filename_date_over_mtime(tmp_path):
    # mtime says 2020, filename says 2025 -> filename wins (more reliable than mtime)
    f = tmp_path / "IMG_20250115.jpg"
    _touch(f, mtime=datetime(2020, 6, 1).timestamp())
    plan = organize.build_plan(tmp_path, Config())
    assert len(plan.moves) == 1
    assert plan.moves[0].dest.parent.name == "2025-01-15"
    assert plan.moves[0].date_source == "filename"


def test_plan_falls_back_to_mtime(tmp_path):
    f = tmp_path / "randomname.jpg"
    _touch(f, mtime=datetime(2021, 3, 9).timestamp())
    plan = organize.build_plan(tmp_path, Config())
    assert plan.moves[0].dest.parent.name == "2021-03-09"
    assert plan.moves[0].date_source == "mtime"


def test_identical_file_is_detected_as_duplicate(tmp_path):
    (tmp_path / "2025-01-15").mkdir()
    _touch(tmp_path / "2025-01-15" / "IMG_20250115.jpg", content=b"same")
    _touch(tmp_path / "IMG_20250115.jpg", content=b"same")
    plan = organize.build_plan(tmp_path, Config())
    assert len(plan.moves) == 0
    assert len(plan.duplicates) == 1


def test_name_collision_with_different_content_is_suffixed_not_overwritten(tmp_path):
    (tmp_path / "2025-01-15").mkdir()
    _touch(tmp_path / "2025-01-15" / "IMG_20250115.jpg", content=b"ORIGINAL")
    _touch(tmp_path / "IMG_20250115.jpg", content=b"DIFFERENT")
    plan = organize.build_plan(tmp_path, Config())
    assert len(plan.moves) == 1
    assert plan.moves[0].dest.name == "IMG_20250115 (1).jpg"


def test_apply_moves_files_and_preserves_original_on_collision(tmp_path):
    existing = tmp_path / "2025-01-15" / "IMG_20250115.jpg"
    existing.parent.mkdir()
    _touch(existing, content=b"ORIGINAL")
    _touch(tmp_path / "IMG_20250115.jpg", content=b"DIFFERENT")

    plan = organize.build_plan(tmp_path, Config())
    organize.apply_plan(plan)

    assert existing.read_bytes() == b"ORIGINAL"  # never overwritten
    assert (tmp_path / "2025-01-15" / "IMG_20250115 (1).jpg").read_bytes() == b"DIFFERENT"
    assert not (tmp_path / "IMG_20250115.jpg").exists()  # source moved


def test_non_media_files_are_ignored(tmp_path):
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "IMG_20250115.jpg")
    plan = organize.build_plan(tmp_path, Config())
    assert len(plan.moves) == 1
    assert plan.moves[0].source.name == "IMG_20250115.jpg"


def test_dry_run_does_not_move(tmp_path):
    f = tmp_path / "IMG_20250115.jpg"
    _touch(f)
    organize.build_plan(tmp_path, Config())  # planning only
    assert f.exists()  # still there, nothing moved


def test_summarize_plan_reports_counts_and_folders(tmp_path):
    for i in range(3):
        _touch(tmp_path / f"IMG_20250115_{i}.jpg")
    _touch(tmp_path / "randomname.jpg", mtime=datetime(2021, 3, 9).timestamp())

    plan = organize.build_plan(tmp_path, Config())
    summary = organize.summarize_plan(plan)

    assert "이동 대상: 4개" in summary
    assert "2025-01-15/   3개" in summary
    assert "2021-03-09/   1개" in summary
    assert "수정시간으로 추정된 파일 1개" in summary
    assert "randomname.jpg" in summary


def test_summarize_plan_truncates_long_mtime_list(tmp_path):
    for i in range(5):
        _touch(tmp_path / f"random{i}.jpg", mtime=datetime(2021, 3, 9).timestamp())

    plan = organize.build_plan(tmp_path, Config())
    summary = organize.summarize_plan(plan, mtime_preview_limit=2)

    assert "외 3개" in summary
