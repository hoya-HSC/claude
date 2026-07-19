"""Round-trip EXIF tests with real JPEG files.

These would have caught the bug where DateTimeOriginal was read off the main
IFD (always None) instead of the Exif sub-IFD, silently sending every photo
to its file modification time.
"""
import os
from datetime import datetime

import piexif
import pytest
from PIL import Image

from photomanager.metadata import extract_photo_metadata


def _make_jpeg(path, *, dt_original=None, dt_digitized=None, dt_main=None, gps=None):
    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if dt_original:
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_original.encode()
    if dt_digitized:
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_digitized.encode()
    if dt_main:
        exif_dict["0th"][piexif.ImageIFD.DateTime] = dt_main.encode()
    if gps:
        exif_dict["GPS"] = gps
    Image.new("RGB", (4, 4), (10, 20, 30)).save(path, exif=piexif.dump(exif_dict))


def test_datetime_original_is_read_from_exif_subifd(tmp_path):
    p = tmp_path / "a.jpg"
    _make_jpeg(p, dt_original="2004:12:21 17:57:00")
    meta = extract_photo_metadata(p)
    assert meta.taken_at == datetime(2004, 12, 21, 17, 57, 0)


def test_falls_back_to_digitized_then_main(tmp_path):
    p = tmp_path / "b.jpg"
    _make_jpeg(p, dt_digitized="2010:05:06 08:00:00")
    assert extract_photo_metadata(p).taken_at == datetime(2010, 5, 6, 8, 0, 0)

    q = tmp_path / "c.jpg"
    _make_jpeg(q, dt_main="2011:07:08 09:10:11")
    assert extract_photo_metadata(q).taken_at == datetime(2011, 7, 8, 9, 10, 11)


def test_no_exif_datetime_returns_none(tmp_path):
    p = tmp_path / "d.jpg"
    _make_jpeg(p)  # no datetime tags at all
    assert extract_photo_metadata(p).taken_at is None


def test_gps_is_read_from_gps_ifd(tmp_path):
    p = tmp_path / "e.jpg"
    gps = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: ((37, 1), (33, 1), (54, 1)),
        piexif.GPSIFD.GPSLongitudeRef: b"E",
        piexif.GPSIFD.GPSLongitude: ((126, 1), (58, 1), (40, 1)),
    }
    _make_jpeg(p, dt_original="2004:12:21 17:57:00", gps=gps)
    meta = extract_photo_metadata(p)
    assert meta.gps_lat == pytest.approx(37.565, abs=1e-3)
    assert meta.gps_lon == pytest.approx(126.9778, abs=1e-3)


def test_organizer_prefers_exif_over_mtime(tmp_path):
    """End-to-end: a file whose mtime disagrees with its EXIF sorts by EXIF."""
    from photomanager import organize
    from photomanager.config import Config

    p = tmp_path / "사진 585.jpg"
    _make_jpeg(p, dt_original="2004:12:21 17:57:00")
    os.utime(p, (datetime(2005, 1, 2).timestamp(),) * 2)  # mtime says 2005

    plan = organize.build_plan(tmp_path, Config())
    assert len(plan.moves) == 1
    assert plan.moves[0].dest.parent.name == "2004-12-21"
    assert plan.moves[0].date_source == "exif"
