from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS volumes (
    id INTEGER PRIMARY KEY,
    volume_key TEXT UNIQUE NOT NULL,
    mount_root TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY,
    name TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    name TEXT,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    place_id INTEGER REFERENCES places(id)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,
    volume_id INTEGER NOT NULL REFERENCES volumes(id),
    relative_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('photo', 'video')),
    taken_at TEXT,
    gps_lat REAL,
    gps_lon REAL,
    place_id INTEGER REFERENCES places(id),
    event_id INTEGER REFERENCES events(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'missing')),
    metadata_processed INTEGER NOT NULL DEFAULT 0,
    faces_processed INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (volume_id, relative_path)
);

CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id),
    bbox TEXT NOT NULL,
    embedding BLOB NOT NULL,
    person_id INTEGER REFERENCES people(id),
    distance_to_person REAL,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'confirmed', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_files_hash ON files(content_hash);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_taken_at ON files(taken_at);
CREATE INDEX IF NOT EXISTS idx_files_metadata_pending ON files(metadata_processed) WHERE metadata_processed = 0;
CREATE INDEX IF NOT EXISTS idx_files_faces_pending ON files(faces_processed) WHERE faces_processed = 0;
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_faces_review ON faces(review_status);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(db_path: str | Path):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
