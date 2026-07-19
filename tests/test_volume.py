from photomanager.volume import _posix_volume_marker


def test_marker_is_persisted_and_reused(tmp_path):
    first = _posix_volume_marker(tmp_path)
    second = _posix_volume_marker(tmp_path)
    assert first == second
    assert (tmp_path / ".photomanager_volume_id").exists()


def test_marker_differs_across_distinct_roots(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    assert _posix_volume_marker(root_a) != _posix_volume_marker(root_b)
