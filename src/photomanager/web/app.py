from __future__ import annotations

import io
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from PIL import Image
from pydantic import BaseModel

from ..clustering import propose_clusters_for_unassigned
from ..config import load_config
from ..db import connect

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

app = FastAPI(title="Photo Manager Review")
_cfg = load_config()

TEMPLATES_DIR = Path(__file__).parent / "templates"

FACE_CROP_MARGIN = 0.3
"""Extra padding around the detected bbox so hair/chin aren't cut off."""


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
        row = conn.execute(
            "SELECT vo.mount_root, fi.relative_path, fi.media_type, fa.bbox FROM faces fa "
            "JOIN files fi ON fi.id = fa.file_id "
            "JOIN volumes vo ON vo.id = fi.volume_id "
            "WHERE fa.id = ?",
            (face_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="face not found")
        if row["media_type"] != "photo":
            raise HTTPException(status_code=404, detail="preview not available for video faces yet")
        path = Path(row["mount_root"]) / row["relative_path"]
        if not path.exists():
            raise HTTPException(status_code=404, detail="source file not available")

        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            raise HTTPException(status_code=422, detail="could not decode source image")

        crop = _crop_face(image, row["bbox"])
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        return Response(content=buf.getvalue(), media_type="image/jpeg")
    finally:
        conn.close()


def _crop_face(image: Image.Image, bbox_str: str) -> Image.Image:
    x1, y1, x2, y2 = (float(v) for v in bbox_str.split(","))
    w, h = x2 - x1, y2 - y1
    x1 -= w * FACE_CROP_MARGIN
    x2 += w * FACE_CROP_MARGIN
    y1 -= h * FACE_CROP_MARGIN
    y2 += h * FACE_CROP_MARGIN
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(image.width, int(x2)), min(image.height, int(y2))
    return image.crop((x1, y1, x2, y2))


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
