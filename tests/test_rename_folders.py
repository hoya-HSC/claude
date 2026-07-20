from photomanager import rename_folders


def test_users_exact_example():
    assert rename_folders.new_folder_name("20120114_무주리조트") == "2012-01-14_무주리조트"


def test_day_range_suffix_passes_through_untouched():
    # not computed from content -- just whatever text already followed the
    # 8-digit prefix, so "-16_..." naturally becomes the YYYY-MM-DD-DD form.
    assert rename_folders.new_folder_name("20120114-16_무주리조트") == "2012-01-14-16_무주리조트"


def test_bare_date_with_nothing_after():
    assert rename_folders.new_folder_name("20120114") == "2012-01-14"


def test_already_hyphenated_name_is_not_touched():
    assert rename_folders.new_folder_name("2012-01-14_무주리조트") is None


def test_non_date_prefix_is_not_touched():
    assert rename_folders.new_folder_name("무주리조트_20120114") is None
    assert rename_folders.new_folder_name("여행사진") is None


def test_invalid_calendar_date_is_not_touched():
    assert rename_folders.new_folder_name("20121399_x") is None  # month 13
    assert rename_folders.new_folder_name("20120230_x") is None  # Feb 30


def test_short_digit_run_is_not_touched():
    assert rename_folders.new_folder_name("2012011_x") is None  # only 7 digits


def test_build_rename_plan_finds_matching_folders(tmp_path):
    (tmp_path / "20120114_무주리조트").mkdir()
    (tmp_path / "이미정리됨").mkdir()
    (tmp_path / "2012-01-15_이미변환됨").mkdir()

    plan = rename_folders.build_rename_plan(tmp_path)

    names = {r.old_path.name: r.new_name for r in plan.renames}
    assert names == {"20120114_무주리조트": "2012-01-14_무주리조트"}


def test_build_rename_plan_recurses_into_subfolders(tmp_path):
    nested = tmp_path / "2012" / "20120114_무주리조트"
    nested.mkdir(parents=True)

    plan = rename_folders.build_rename_plan(tmp_path)

    assert len(plan.renames) == 1
    assert plan.renames[0].old_path == nested
    assert plan.renames[0].new_name == "2012-01-14_무주리조트"


def test_apply_renames_only_the_folder_not_its_contents(tmp_path):
    folder = tmp_path / "20120114_무주리조트"
    folder.mkdir()
    (folder / "photo.jpg").write_bytes(b"x")

    plan = rename_folders.build_rename_plan(tmp_path)
    renamed = rename_folders.apply_rename_plan(plan)

    assert renamed == 1
    new_folder = tmp_path / "2012-01-14_무주리조트"
    assert new_folder.is_dir()
    assert (new_folder / "photo.jpg").exists()
    assert not folder.exists()


def test_apply_renames_parent_and_nested_child_without_error(tmp_path):
    """If a parent folder AND a folder nested inside it both need renaming,
    applying must not break on the child's now-stale old path -- children
    are renamed before their ancestors."""
    parent = tmp_path / "20120101_여행"
    child = parent / "20120103_둘째날"
    child.mkdir(parents=True)
    (child / "vid.mp4").write_bytes(b"x")

    plan = rename_folders.build_rename_plan(tmp_path)
    assert len(plan.renames) == 2

    renamed = rename_folders.apply_rename_plan(plan)
    assert renamed == 2

    expected_child = tmp_path / "2012-01-01_여행" / "2012-01-03_둘째날"
    assert expected_child.is_dir()
    assert (expected_child / "vid.mp4").exists()


def test_target_name_collision_is_skipped_not_overwritten(tmp_path):
    (tmp_path / "20120114_무주리조트").mkdir()
    (tmp_path / "2012-01-14_무주리조트").mkdir()  # already occupies the target name
    (tmp_path / "2012-01-14_무주리조트" / "existing.jpg").write_bytes(b"keep-me")

    plan = rename_folders.build_rename_plan(tmp_path)

    assert plan.renames == []
    assert len(plan.skipped_collisions) == 1
    assert plan.skipped_collisions[0].name == "20120114_무주리조트"

    # nothing touched
    assert (tmp_path / "20120114_무주리조트").is_dir()
    assert (tmp_path / "2012-01-14_무주리조트" / "existing.jpg").read_bytes() == b"keep-me"


def test_dry_run_does_not_rename(tmp_path):
    folder = tmp_path / "20120114_무주리조트"
    folder.mkdir()
    rename_folders.build_rename_plan(tmp_path)  # planning only
    assert folder.is_dir()


def test_summarize_plan_lists_renames_and_collisions(tmp_path):
    (tmp_path / "20120114_무주리조트").mkdir()
    plan = rename_folders.build_rename_plan(tmp_path)
    summary = rename_folders.summarize_plan(plan)
    assert "이름 바꿀 폴더: 1개" in summary
    assert "20120114_무주리조트  ->  2012-01-14_무주리조트" in summary
