from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from ..clustering import propose_clusters_for_unassigned
from ..config import load_config
from ..db import connect

app = FastAPI(title="Photo Manager Review")
_cfg = load_config()

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _conn():
    return connect(_cfg.db_path)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/clusters")
def list_clusters(min_size: int = 3, limit: int = 20):
    conn = _conn()
    try:
        clusters = propose_clusters_for_unassigned(conn, min_cluster_size=min_size)
        result = []
        for label, face_ids in list(clusters.items())[:limit]:
            result.append({
                "cluster_label": label,
                "size": len(face_ids),
                "sample_face_ids": face_ids[:8],
            })
        return result
    finally:
        conn.close()


@app.get("/api/review-queue")
def review_queue(limit: int = 50):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT f.id AS face_id, f.file_id, f.person_id, f.distance_to_person, p.name AS suggested_name "
            "FROM faces f LEFT JOIN people p ON p.id = f.person_id "
            "WHERE f.review_status = 'pending' AND f.person_id IS NOT NULL "
            "ORDER BY f.distance_to_person DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/api/faces/{face_id}/image")
def face_image(face_id: int):
    conn = _conn()
    try:
        row = conn.execute("SELECT thumbnail FROM faces WHERE id = ?", (face_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="face not found")
        if row["thumbnail"] is None:
            # Faces stored before the thumbnail column existed; re-running the
            # pipeline on their file will backfill it (faces_processed is
            # keyed per-file, so a full run only touches unprocessed files --
            # see the migration note in db.py for how to force a refresh).
            raise HTTPException(status_code=404, detail="thumbnail not available for this face")
        return Response(content=row["thumbnail"], media_type="image/jpeg")
    finally:
        conn.close()


class NameClusterRequest(BaseModel):
    name: str
    face_ids: list[int]


@app.post("/api/people/name-cluster")
def name_cluster(req: NameClusterRequest):
    conn = _conn()
    try:
        existing = conn.execute(
            "SELECT id FROM people WHERE name = ?", (req.name,)
        ).fetchone()
        person_id = existing["id"] if existing else conn.execute(
            "INSERT INTO people (name) VALUES (?)", (req.name,)
        ).lastrowid

        conn.executemany(
            "UPDATE faces SET person_id = ?, review_status = 'confirmed' WHERE id = ?",
            [(person_id, fid) for fid in req.face_ids],
        )
        conn.commit()
        return {"person_id": person_id, "assigned": len(req.face_ids)}
    finally:
        conn.close()


@app.post("/api/faces/{face_id}/confirm")
def confirm_face(face_id: int):
    conn = _conn()
    try:
        conn.execute(
            "UPDATE faces SET review_status = 'confirmed' WHERE id = ?", (face_id,)
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/faces/{face_id}/reject")
def reject_face(face_id: int):
    conn = _conn()
    try:
        conn.execute(
            "UPDATE faces SET person_id = NULL, review_status = 'rejected' WHERE id = ?",
            (face_id,),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


class MergeRequest(BaseModel):
    keep_person_id: int
    merge_person_id: int


@app.post("/api/people/merge")
def merge_people(req: MergeRequest):
    conn = _conn()
    try:
        conn.execute(
            "UPDATE faces SET person_id = ? WHERE person_id = ?",
            (req.keep_person_id, req.merge_person_id),
        )
        conn.execute("DELETE FROM people WHERE id = ?", (req.merge_person_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/people")
def list_people():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT p.id, p.name, COUNT(f.id) AS photo_count "
            "FROM people p LEFT JOIN faces f ON f.person_id = p.id AND f.review_status = 'confirmed' "
            "GROUP BY p.id ORDER BY photo_count DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/api/places")
def list_places():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT pl.id, pl.name, pl.lat, pl.lon, COUNT(fi.id) AS photo_count "
            "FROM places pl LEFT JOIN files fi ON fi.place_id = pl.id "
            "GROUP BY pl.id ORDER BY photo_count DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/api/events")
def list_events():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT ev.id, ev.start_at, ev.end_at, pl.name AS place_name, COUNT(fi.id) AS photo_count "
            "FROM events ev LEFT JOIN files fi ON fi.event_id = ev.id "
            "LEFT JOIN places pl ON pl.id = ev.place_id "
            "GROUP BY ev.id ORDER BY ev.start_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
