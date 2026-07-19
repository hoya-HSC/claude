import subprocess
from datetime import datetime
from unittest.mock import patch

from photomanager.metadata import (
    _parse_exif_datetime,
    _parse_gps_ifd,
    _parse_video_datetime,
    _parse_video_gps,
    extract_video_metadata,
)


def test_parse_exif_datetime_valid():
    assert _parse_exif_datetime("2026:07:19 14:30:00") == datetime(2026, 7, 19, 14, 30, 0)


def test_parse_exif_datetime_missing():
    assert _parse_exif_datetime(None) is None


def test_parse_exif_datetime_malformed():
    assert _parse_exif_datetime("not a date") is None


def test_parse_gps_ifd_north_east():
    gps_ifd = {1: "N", 2: (37.0, 33.0, 54.0), 3: "E", 4: (126.0, 58.0, 40.8)}
    lat, lon = _parse_gps_ifd(gps_ifd)
    assert lat == 37.565
    assert round(lon, 4) == 126.9780


def test_parse_gps_ifd_south_west_is_negative():
    gps_ifd = {1: "S", 2: (33.0, 0.0, 0.0), 3: "W", 4: (70.0, 0.0, 0.0)}
    lat, lon = _parse_gps_ifd(gps_ifd)
    assert lat == -33.0
    assert lon == -70.0


def test_parse_gps_ifd_empty():
    assert _parse_gps_ifd({}) == (None, None)


def test_parse_video_datetime_with_fraction():
    assert _parse_video_datetime("2026-07-19T05:30:00.000000Z") == datetime(2026, 7, 19, 5, 30, 0)


def test_parse_video_gps_iso6709():
    lat, lon = _parse_video_gps("+37.5665-126.9780/")
    assert lat == 37.5665
    assert lon == -126.9780


def test_parse_video_gps_missing():
    assert _parse_video_gps(None) == (None, None)


def _fake_proc(stdout):
    return subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=stdout, stderr="")


def test_extract_video_metadata_handles_none_stdout(tmp_path):
    """ffprobe can return an empty/None stdout for a corrupt or unreadable
    video; json.loads(None) raises TypeError, not JSONDecodeError, which the
    original except clause didn't catch -- surfaced as 'the JSON object must
    be str, bytes or bytearray, not NoneType' crashing the whole organize run."""
    p = tmp_path / "broken.mp4"
    p.write_bytes(b"")
    with patch("subprocess.run", return_value=_fake_proc(None)):
        meta = extract_video_metadata(p)
    assert meta.taken_at is None
    assert meta.gps_lat is None


def test_extract_video_metadata_handles_empty_stdout(tmp_path):
    p = tmp_path / "broken.mp4"
    p.write_bytes(b"")
    with patch("subprocess.run", return_value=_fake_proc("")):
        meta = extract_video_metadata(p)
    assert meta.taken_at is None


def test_extract_video_metadata_handles_malformed_json(tmp_path):
    p = tmp_path / "broken.mp4"
    p.write_bytes(b"")
    with patch("subprocess.run", return_value=_fake_proc("not json")):
        meta = extract_video_metadata(p)
    assert meta.taken_at is None


def test_extract_video_metadata_parses_valid_output(tmp_path):
    p = tmp_path / "ok.mp4"
    p.write_bytes(b"")
    stdout = '{"format": {"tags": {"creation_time": "2025-01-15T10:00:00.000000Z"}}}'
    with patch("subprocess.run", return_value=_fake_proc(stdout)):
        meta = extract_video_metadata(p)
    assert meta.taken_at == datetime(2025, 1, 15, 10, 0, 0)
