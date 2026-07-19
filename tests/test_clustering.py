import numpy as np
import pytest

from photomanager.clustering import assign_face, cosine_distance
from photomanager.config import Config


def unit(vec: list[float]) -> np.ndarray:
    arr = np.array(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def test_cosine_distance_identical_vectors_is_zero():
    v = unit([1.0, 2.0, 3.0])
    assert cosine_distance(v, v) == pytest.approx(0.0, abs=1e-4)


def test_cosine_distance_opposite_vectors_is_two():
    v = unit([1.0, 0.0])
    assert cosine_distance(v, -v) == pytest.approx(2.0, abs=1e-4)


def test_assign_face_with_no_centroids_needs_review():
    cfg = Config()
    result = assign_face(unit([1.0, 0.0, 0.0]), {}, cfg)
    assert result.person_id is None
    assert result.needs_review is True


def test_assign_face_close_match_auto_assigns_confidently():
    cfg = Config(face_match_threshold=0.45, face_review_margin=0.10)
    centroids = {1: unit([1.0, 0.0, 0.0])}
    result = assign_face(unit([1.0, 0.001, 0.0]), centroids, cfg)
    assert result.person_id == 1
    assert result.needs_review is False


def test_assign_face_far_match_is_unassigned():
    cfg = Config(face_match_threshold=0.45, face_review_margin=0.10)
    centroids = {1: unit([1.0, 0.0, 0.0])}
    result = assign_face(unit([0.0, 1.0, 0.0]), centroids, cfg)
    assert result.person_id is None
    assert result.needs_review is True


def test_assign_face_borderline_match_is_flagged_for_review():
    cfg = Config(face_match_threshold=0.45, face_review_margin=0.10)
    centroids = {1: unit([1.0, 0.0])}
    # pick an angle whose cosine distance lands right at the threshold
    angle = np.arccos(1 - cfg.face_match_threshold)
    borderline = unit([np.cos(angle), np.sin(angle)])
    result = assign_face(borderline, centroids, cfg)
    assert result.person_id == 1
    assert result.needs_review is True


def test_assign_face_picks_nearest_of_multiple_people():
    cfg = Config(face_match_threshold=0.45, face_review_margin=0.05)
    centroids = {
        1: unit([1.0, 0.0, 0.0]),
        2: unit([0.0, 1.0, 0.0]),
    }
    result = assign_face(unit([0.05, 1.0, 0.0]), centroids, cfg)
    assert result.person_id == 2
