import os
import time

import pytest

from photomanager import scanner
from photomanager.config import Config
from photomanager.db import connect


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    monkeypatch.setattr(
        scanner, "volume_key_for", lambda path: ("test-volume", str(root))
    )
    conn = connect(tmp_path / "db.sqlite3")
    cfg = Config(db_path=str(tmp_path / "db.sqlite3"), scan_roots=[str(root)])
    return conn, cfg, root


def test_new_file_is_discovered(env):
    conn, cfg, root = env
    (root / "a.jpg").write_bytes(b"hello world")

    result = scanner.scan(conn, cfg)

    assert len(result.new_files) == 1
    assert result.moved_files == 0
    row = conn.execute("SELECT * FROM files").fetchone()
    assert row["media_type"] == "photo"
    assert row["status"] == "active"


def test_second_scan_of_unchanged_file_is_fast_path(env):
    conn, cfg, root = env
    (root / "a.jpg").write_bytes(b"hello world")
    scanner.scan(conn, cfg)

    result = scanner.scan(conn, cfg)

    assert result.new_files == []
    assert result.unchanged_files == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"] == 1


def test_renamed_file_is_recognized_by_hash_not_reprocessed(env):
    conn, cfg, root = env
    original = root / "a.jpg"
    original.write_bytes(b"hello world")
    scanner.scan(conn, cfg)
    file_id_before = conn.execute("SELECT id FROM files").fetchone()["id"]

    original.rename(root / "renamed.jpg")
    result = scanner.scan(conn, cfg)

    assert result.new_files == []
    assert result.moved_files == 1
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id_before,)).fetchone()
    assert row["relative_path"] == "renamed.jpg"
    assert conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"] == 1


def test_deleted_file_marked_missing_not_removed(env):
    conn, cfg, root = env
    path = root / "a.jpg"
    path.write_bytes(b"hello world")
    scanner.scan(conn, cfg)

    path.unlink()
    result = scanner.scan(conn, cfg)

    assert result.missing_files == 1
    row = conn.execute("SELECT * FROM files").fetchone()
    assert row["status"] == "missing"


def test_modified_file_content_is_rehashed(env):
    conn, cfg, root = env
    path = root / "a.jpg"
    path.write_bytes(b"hello world")
    scanner.scan(conn, cfg)
    original_hash = conn.execute("SELECT content_hash FROM files").fetchone()["content_hash"]

    time.sleep(1.1)
    path.write_bytes(b"different content now")
    os.utime(path, None)
    scanner.scan(conn, cfg)

    assert conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"] == 1
    new_hash = conn.execute("SELECT content_hash FROM files").fetchone()["content_hash"]
    assert new_hash != original_hash


def test_non_media_extension_is_ignored(env):
    conn, cfg, root = env
    (root / "notes.txt").write_text("not a photo")

    scanner.scan(conn, cfg)

    assert conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"] == 0
