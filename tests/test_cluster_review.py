"""DB-level tests for the review flow: clustering proposals and rejection.

These exercise the real hdbscan path with synthetic embeddings, so they
verify that rejected faces are actually excluded from future proposals.
"""
import numpy as np
import pytest

from photomanager.clustering import propose_clusters_for_unassigned
from photomanager.db import connect
from photomanager.faces import embedding_to_blob


def _unit(vec):
    arr = np.array(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def _insert_face(conn, file_id, embedding, review_status="pending", person_id=None):
    return conn.execute(
        "INSERT INTO faces (file_id, bbox, embedding, person_id, review_status) "
        "VALUES (?, '0,0,1,1', ?, ?, ?)",
        (file_id, embedding_to_blob(embedding), person_id, review_status),
    ).lastrowid


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "review.sqlite3")
    c.execute(
        "INSERT INTO volumes (volume_key, mount_root) VALUES ('v', '/tmp')"
    )
    c.execute(
        "INSERT INTO files (content_hash, volume_id, relative_path, size, mtime, "
        "media_type, first_seen_at, last_seen_at) "
        "VALUES ('h', 1, 'a.jpg', 1, 1.0, 'photo', 'now', 'now')"
    )
    return c


_DIM = 16


def _add_group(conn, direction, n, jitter=0.03):
    """Insert n faces tightly clustered around a unit direction."""
    rng = np.random.default_rng(hash(tuple(direction)) & 0xFFFF)
    base = np.zeros(_DIM)
    base[direction[0]] = 1.0
    ids = []
    for _ in range(n):
        v = _unit(base + rng.normal(0, jitter, _DIM))
        ids.append(_insert_face(conn, 1, v))
    return ids


def _two_distinct_groups(conn, n=8):
    """Two well-separated blobs give HDBSCAN clear density to work with."""
    a = _add_group(conn, (0,), n)
    b = _add_group(conn, (8,), n)
    return a, b


def test_pending_faces_form_clusters(conn):
    _two_distinct_groups(conn)
    clusters = propose_clusters_for_unassigned(conn, min_cluster_size=3)
    assert len(clusters) >= 1
    assert max(len(v) for v in clusters.values()) >= 3


def test_rejected_faces_are_excluded_from_proposals(conn):
    a, b = _two_distinct_groups(conn)
    conn.executemany(
        "UPDATE faces SET review_status = 'rejected' WHERE id = ?",
        [(i,) for i in a + b],
    )
    clusters = propose_clusters_for_unassigned(conn, min_cluster_size=3)
    assert clusters == {}


def test_confirmed_faces_are_excluded_from_proposals(conn):
    a, b = _two_distinct_groups(conn)
    conn.execute("INSERT INTO people (name) VALUES ('someone')")
    conn.executemany(
        "UPDATE faces SET review_status = 'confirmed', person_id = 1 WHERE id = ?",
        [(i,) for i in a + b],
    )
    clusters = propose_clusters_for_unassigned(conn, min_cluster_size=3)
    assert clusters == {}
