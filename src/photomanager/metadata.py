from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image


@dataclass
class MediaMetadata:
    taken_at: datetime | None
    gps_lat: float | None
    gps_lon: float | None


_GPS_TAG_ID = next((k for k, v in ExifTags.TAGS.items() if v == "GPSInfo"), None)

# DateTimeOriginal / DateTimeDigitized live in the Exif sub-IFD (pointer
# 0x8769), NOT the main IFD that img.getexif() returns. Reading them off the
# main IFD always yields None -- which silently sent every photo to its file
# modification time. DateTime (306) is the one datetime that IS in the main
# IFD, used only as a last resort (it's the file-edit time, less reliable
# than the capture time, but still better than mtime).
_EXIF_IFD_POINTER = 0x8769
_DATETIME_ORIGINAL = 36867
_DATETIME_DIGITIZED = 36868
_DATETIME_MAIN = 306


def extract_photo_metadata(path: Path) -> MediaMetadata:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except Exception:
        return MediaMetadata(None, None, None)

    if not exif:
        return MediaMetadata(None, None, None)

    taken_at = None
    exif_ifd = exif.get_ifd(_EXIF_IFD_POINTER)
    for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED):
        taken_at = _parse_exif_datetime(exif_ifd.get(tag))
        if taken_at is not None:
            break
    if taken_at is None:
        taken_at = _parse_exif_datetime(exif.get(_DATETIME_MAIN))

    lat = lon = None
    if _GPS_TAG_ID in exif:
        gps_ifd = exif.get_ifd(_GPS_TAG_ID)
        lat, lon = _parse_gps_ifd(gps_ifd)

    return MediaMetadata(taken_at=taken_at, gps_lat=lat, gps_lon=lon)


def _parse_exif_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _parse_gps_ifd(gps_ifd: dict) -> tuple[float | None, float | None]:
    def to_degrees(dms, ref) -> float | None:
        if not dms:
            return None
        degrees, minutes, seconds = (float(v) for v in dms)
        value = degrees + minutes / 60.0 + seconds / 3600.0
        return -value if ref in ("S", "W") else value

    lat = to_degrees(gps_ifd.get(2), gps_ifd.get(1))
    lon = to_degrees(gps_ifd.get(4), gps_ifd.get(3))
    return lat, lon


def extract_video_metadata(path: Path) -> MediaMetadata:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_entries", "format_tags",
                str(path),
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return MediaMetadata(None, None, None)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return MediaMetadata(None, None, None)

    tags = data.get("format", {}).get("tags", {})
    taken_at = _parse_video_datetime(tags.get("creation_time"))
    lat, lon = _parse_video_gps(tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709"))

    return MediaMetadata(taken_at=taken_at, gps_lat=lat, gps_lon=lon)


def _parse_video_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_video_gps(iso6709: str | None) -> tuple[float | None, float | None]:
    """Parse ISO 6709 location strings such as '+37.5665+126.9780/'."""
    if not iso6709:
        return None, None
    import re

    match = re.match(r"^([+-]\d+\.\d+)([+-]\d+\.\d+)", iso6709)
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2))


def extract_metadata(path: Path, media_type: str) -> MediaMetadata:
    if media_type == "photo":
        return extract_photo_metadata(path)
    return extract_video_metadata(path)
