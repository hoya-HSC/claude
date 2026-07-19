from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Config
from .geocode import haversine_km


@dataclass
class TimelineItem:
    file_id: int
    taken_at: datetime
    lat: float | None = None
    lon: float | None = None


@dataclass
class EventSpan:
    file_ids: list[int]
    start_at: datetime
    end_at: datetime


def cluster_events(items: list[TimelineItem], cfg: Config) -> list[EventSpan]:
    """Group a timeline of files into trip/event spans.

    A new event starts whenever the gap since the previous photo exceeds
    cfg.event_gap_hours, or the GPS position jumps more than cfg.event_gap_km
    (when both photos have coordinates). This is a pure time/space heuristic
    with no training required.
    """
    if not items:
        return []

    ordered = sorted(items, key=lambda i: i.taken_at)
    spans: list[EventSpan] = []
    current = [ordered[0]]

    for prev, item in zip(ordered, ordered[1:]):
        gap_hours = (item.taken_at - prev.taken_at).total_seconds() / 3600.0
        gps_jump = (
            prev.lat is not None and prev.lon is not None
            and item.lat is not None and item.lon is not None
            and haversine_km(prev.lat, prev.lon, item.lat, item.lon) > cfg.event_gap_km
        )
        if gap_hours > cfg.event_gap_hours or gps_jump:
            spans.append(_to_span(current))
            current = [item]
        else:
            current.append(item)

    spans.append(_to_span(current))
    return spans


def _to_span(items: list[TimelineItem]) -> EventSpan:
    return EventSpan(
        file_ids=[i.file_id for i in items],
        start_at=items[0].taken_at,
        end_at=items[-1].taken_at,
    )
