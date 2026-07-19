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

    # Neighbor estimation is exercised separately below; disable it here so
    # this test stays a pure check of the summary's counts/formatting.
    cfg = Config(estimate_missing_dates_from_neighbors=False)
    plan = organize.build_plan(tmp_path, cfg)
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


def test_summarize_plan_full_list_includes_every_move(tmp_path):
    for i in range(40):
        _touch(tmp_path / f"IMG_20250115_{i}.jpg")

    plan = organize.build_plan(tmp_path, Config())
    summary_short = organize.summarize_plan(plan)
    summary_full = organize.summarize_plan(plan, full_list=True)

    assert "전체 이동 목록" not in summary_short
    assert "전체 이동 목록 (40개, 날짜 폴더별)" in summary_full
    for i in range(40):
        assert f"IMG_20250115_{i}.jpg" in summary_full


def test_summarize_plan_full_list_groups_by_destination_folder(tmp_path):
    """Files must be listed under their destination folder heading, not in
    scan order -- interleaved dates (as in the original flat list) is exactly
    what confused the user."""
    _touch(tmp_path / "IMG_20250115_a.jpg")
    _touch(tmp_path / "IMG_20241231_b.jpg")
    _touch(tmp_path / "IMG_20250115_c.jpg")

    plan = organize.build_plan(tmp_path, Config())
    summary = organize.summarize_plan(plan, full_list=True)

    # folders sorted alphabetically -> 2024-12-31 heading comes first
    dec_heading = summary.index("2024-12-31/  (1개)")
    jan_heading = summary.index("2025-01-15/  (2개)")
    b_pos = summary.index("IMG_20241231_b.jpg")
    a_pos = summary.index("IMG_20250115_a.jpg")
    c_pos = summary.index("IMG_20250115_c.jpg")

    assert dec_heading < jan_heading
    # the December file sits under its own heading, before the January one
    assert dec_heading < b_pos < jan_heading
    # both January files sit under the January heading, not scattered earlier
    assert jan_heading < a_pos and jan_heading < c_pos


def test_summarize_plan_full_list_omitted_when_nothing_to_move(tmp_path):
    summary = organize.summarize_plan(organize.OrganizePlan(), full_list=True)
    assert "전체 이동 목록" not in summary


# --- neighbor-based date estimation (for videos with no EXIF/media date) ---

def test_video_between_two_dated_photos_is_interpolated(tmp_path):
    # sorted order: a_20250110 < b_video < c_20250120; mtime agrees with the
    # interpolated midpoint, so the sanity check accepts the estimate.
    _touch(tmp_path / "a_20250110.jpg")
    _touch(tmp_path / "b_video.mp4", mtime=datetime(2025, 1, 15).timestamp())
    _touch(tmp_path / "c_20250120.jpg")

    plan = organize.build_plan(tmp_path, Config())
    video_move = next(mv for mv in plan.moves if mv.source.name == "b_video.mp4")

    assert video_move.date_source == "estimated"
    # halfway between 01-10 and 01-20 -> 01-15
    assert video_move.dest.parent.name == "2025-01-15"


def test_video_with_only_earlier_neighbor_uses_that_date(tmp_path):
    _touch(tmp_path / "a_20250110.jpg")
    _touch(tmp_path / "z_video.mp4", mtime=datetime(2025, 1, 10).timestamp())

    plan = organize.build_plan(tmp_path, Config())
    video_move = next(mv for mv in plan.moves if mv.source.name == "z_video.mp4")

    assert video_move.date_source == "estimated"
    assert video_move.dest.parent.name == "2025-01-10"


def test_video_with_only_later_neighbor_uses_that_date(tmp_path):
    _touch(tmp_path / "a_video.mp4", mtime=datetime(2025, 1, 10).timestamp())
    _touch(tmp_path / "z_20250110.jpg")

    plan = organize.build_plan(tmp_path, Config())
    video_move = next(mv for mv in plan.moves if mv.source.name == "a_video.mp4")

    assert video_move.date_source == "estimated"
    assert video_move.dest.parent.name == "2025-01-10"


def test_burst_of_same_day_videos_near_distant_photo_keeps_own_mtime(tmp_path):
    """Reproduces the real bug: P8034163.JPG (8/3, exif) ... P8124164-168.AVI
    (all actually shot 8/12, mtime says so) ... P8124169.JPG (8/12, exif).
    Naive interpolation smeared the AVIs across 8/5-8/11; since their own
    mtime already says 8/12 and disagrees with that smeared guess, the
    estimate must be discarded and mtime kept.
    """
    _touch(tmp_path / "P8034162.JPG")  # unused, just realistic clutter
    _touch(tmp_path / "P8034163.JPG", mtime=datetime(2012, 8, 3).timestamp())
    for n in range(164, 169):  # 164..168, all really shot 8/12
        _touch(tmp_path / f"P812{n}.AVI", mtime=datetime(2012, 8, 12, 13, 19).timestamp())
    _touch(tmp_path / "P8124169.JPG", mtime=datetime(2012, 8, 12, 13, 19).timestamp())

    plan = organize.build_plan(tmp_path, Config())

    for n in range(164, 169):
        mv = next(mv for mv in plan.moves if mv.source.name == f"P812{n}.AVI")
        assert mv.date_source == "mtime", f"P812{n}.AVI should keep its own mtime, not a smeared guess"
        assert mv.dest.parent.name == "2012-08-12"


def test_estimate_rejected_when_it_disagrees_with_own_mtime(tmp_path):
    _touch(tmp_path / "a_20250101.jpg")
    _touch(tmp_path / "b_video.mp4", mtime=datetime(2025, 1, 2, 12, 0, 0).timestamp())
    _touch(tmp_path / "c_20250131.jpg")

    cfg = Config(estimate_max_days_from_mtime=1.0)
    plan = organize.build_plan(tmp_path, cfg)
    video_move = next(mv for mv in plan.moves if mv.source.name == "b_video.mp4")

    # interpolated midpoint would be ~01-16, ~14 days from its own 01-02 mtime
    assert video_move.date_source == "mtime"
    assert video_move.dest.parent.name == "2025-01-02"


def test_video_with_no_reliable_neighbors_falls_back_to_mtime(tmp_path):
    _touch(tmp_path / "only_video.mp4", mtime=datetime(2021, 3, 9).timestamp())

    plan = organize.build_plan(tmp_path, Config())
    video_move = plan.moves[0]

    assert video_move.date_source == "mtime"
    assert video_move.dest.parent.name == "2021-03-09"


def test_estimation_can_be_disabled_via_config(tmp_path):
    _touch(tmp_path / "a_20250110.jpg")
    _touch(tmp_path / "b_video.mp4", mtime=datetime(1999, 1, 1).timestamp())
    _touch(tmp_path / "c_20250120.jpg")

    cfg = Config(estimate_missing_dates_from_neighbors=False)
    plan = organize.build_plan(tmp_path, cfg)
    video_move = next(mv for mv in plan.moves if mv.source.name == "b_video.mp4")

    assert video_move.date_source == "mtime"
    assert video_move.dest.parent.name == "1999-01-01"
