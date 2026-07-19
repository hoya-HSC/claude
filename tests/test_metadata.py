from datetime import datetime

from photomanager.metadata import (
    _parse_exif_datetime,
    _parse_gps_ifd,
    _parse_video_datetime,
    _parse_video_gps,
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
