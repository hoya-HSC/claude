from datetime import datetime, timedelta

from photomanager.config import Config
from photomanager.events import TimelineItem, cluster_events


def dt(offset_hours: float) -> datetime:
    return datetime(2026, 1, 1) + timedelta(hours=offset_hours)


def test_single_photo_is_one_event():
    cfg = Config()
    items = [TimelineItem(file_id=1, taken_at=dt(0))]
    spans = cluster_events(items, cfg)
    assert len(spans) == 1
    assert spans[0].file_ids == [1]


def test_photos_within_gap_stay_in_same_event():
    cfg = Config(event_gap_hours=48)
    items = [
        TimelineItem(file_id=1, taken_at=dt(0)),
        TimelineItem(file_id=2, taken_at=dt(2)),
        TimelineItem(file_id=3, taken_at=dt(20)),
    ]
    spans = cluster_events(items, cfg)
    assert len(spans) == 1
    assert spans[0].file_ids == [1, 2, 3]


def test_large_time_gap_starts_new_event():
    cfg = Config(event_gap_hours=48)
    items = [
        TimelineItem(file_id=1, taken_at=dt(0)),
        TimelineItem(file_id=2, taken_at=dt(1)),
        TimelineItem(file_id=3, taken_at=dt(200)),
    ]
    spans = cluster_events(items, cfg)
    assert len(spans) == 2
    assert spans[0].file_ids == [1, 2]
    assert spans[1].file_ids == [3]


def test_gps_jump_starts_new_event_even_within_time_gap():
    cfg = Config(event_gap_hours=48, event_gap_km=50)
    items = [
        TimelineItem(file_id=1, taken_at=dt(0), lat=37.5665, lon=126.9780),   # Seoul
        TimelineItem(file_id=2, taken_at=dt(1), lat=35.1796, lon=129.0756),   # Busan, same day
    ]
    spans = cluster_events(items, cfg)
    assert len(spans) == 2


def test_unordered_input_is_sorted_first():
    cfg = Config(event_gap_hours=48)
    items = [
        TimelineItem(file_id=2, taken_at=dt(2)),
        TimelineItem(file_id=1, taken_at=dt(0)),
    ]
    spans = cluster_events(items, cfg)
    assert len(spans) == 1
    assert spans[0].file_ids == [1, 2]
