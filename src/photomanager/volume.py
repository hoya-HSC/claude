from __future__ import annotations

import platform
import uuid
from pathlib import Path


def volume_key_for(path: Path) -> tuple[str, str]:
    """Return (volume_key, root) identifying the physical drive containing path.

    volume_key stays stable across drive-letter reassignment (e.g. an external
    disk moving from D: to E:), so moved/renamed files are recognized by
    content hash instead of being treated as newly discovered.
    """
    root = _mount_root(path)
    if platform.system() == "Windows":
        key = _windows_volume_serial(root)
    else:
        key = _posix_volume_marker(root)
    return key, str(root)


def _mount_root(path: Path) -> Path:
    path = path.resolve()
    if path.drive:
        return Path(path.drive + "\\")
    current = path if path.is_dir() else path.parent
    while not current.is_mount() and current.parent != current:
        current = current.parent
    return current


def _windows_volume_serial(root: Path) -> str:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    serial = ctypes.c_uint32(0)
    kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(str(root)),
        None, 0,
        ctypes.byref(serial),
        None, None,
        None, 0,
    )
    return f"win-{serial.value:08x}"


def _posix_volume_marker(root: Path) -> str:
    """Persist a UUID marker file at the volume root so re-scans recognize it
    even if the mount point path changes (e.g. USB drive remounted elsewhere).
    """
    marker = root / ".photomanager_volume_id"
    if marker.exists():
        return marker.read_text().strip()
    key = f"posix-{uuid.uuid4().hex}"
    try:
        marker.write_text(key)
    except OSError:
        return f"posix-path-{root}"
    return key
