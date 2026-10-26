"""Pure counting/aggregation logic for the CCTV proof of concept (no cv2/ultralytics/torch imports).

Track ids appear ONLY inside ``LineCounter`` memory while a clip is processed, to avoid counting the same object twice;
they are never returned, stored or exported. Output rows are aggregate counts only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

OUTPUT_COLUMNS = ["location_id", "timestamp_min", "clip_minute", "direction", "class", "count",
                  "measurement_method", "source_type", "time_basis"]
MEASUREMENT_METHOD = "actual_detector"
SOURCE_TYPE = "cctv_detector_prerecorded_clip"
TIME_BASIS = "clip_relative"
# clip-relative timestamps are offsets from this reference; it is NOT a recording date.
CLIP_EPOCH = pd.Timestamp("1970-01-01 00:00:00")
DIRECTIONS = ("inbound", "outbound", "unknown")
CLASSES = ("person", "car", "two_wheeler", "auto", "bus", "truck", "other")
FORBIDDEN_COLUMN_PARTS = ("track", "face", "identity", "person_id", "embedding")
# COCO class id -> project class
COCO_TO_CLASS = {0: "person", 2: "car", 3: "two_wheeler", 5: "bus", 7: "truck"}


def side_of_line(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> int:
    """+1 / -1 for the side of directed line a->b that point p lies on (0 when exactly on it)."""
    v = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return (v > 0) - (v < 0)


def _within_segment(p0, p1, a, b) -> bool:
    """Whether the movement p0->p1 crosses the finite segment a-b (not just its infinite extension)."""
    def ccw(u, v, w):
        return (w[1] - u[1]) * (v[0] - u[0]) - (v[1] - u[1]) * (w[0] - u[0])
    d1, d2 = ccw(a, b, p0), ccw(a, b, p1)
    d3, d4 = ccw(p0, p1, a), ccw(p0, p1, b)
    return (d1 * d2 <= 0) and (d3 * d4 <= 0)


def crossing_direction(prev: tuple[float, float], cur: tuple[float, float], a, b,
                       positive_is: str = "inbound") -> str | None:
    """Direction label if prev->cur crosses segment a-b, else None. Moving from the negative to the positive side of
    the directed line a->b is ``positive_is``; the other way is the opposite label."""
    s0, s1 = side_of_line(prev, a, b), side_of_line(cur, a, b)
    if s0 == 0 or s1 == 0 or s0 == s1:
        return None
    if not _within_segment(prev, cur, a, b):
        return None
    other = "outbound" if positive_is == "inbound" else "inbound"
    return positive_is if s1 > 0 else other


def minute_bucket(t_seconds: float) -> int:
    return int(t_seconds // 60)


@dataclass
class LineCounter:
    """Counts line crossings per (minute, direction, class). Tracks are keyed by an ephemeral id held in memory only."""
    a: tuple[float, float]
    b: tuple[float, float]
    positive_is: str = "inbound"
    _last: dict = field(default_factory=dict, repr=False)
    _counted: set = field(default_factory=set, repr=False)
    tallies: dict = field(default_factory=dict)

    def update(self, t_seconds: float, tracks) -> int:
        """tracks: iterable of (ephemeral_id, (x, y) anchor point, class name). Returns new crossings this frame.
        An id is counted at most once per direction change (re-crossing the other way counts as the other direction)."""
        n = 0
        for tid, pt, cls in tracks:
            prev = self._last.get(tid)
            self._last[tid] = pt
            if prev is None:
                continue
            d = crossing_direction(prev, pt, self.a, self.b, self.positive_is)
            if d is None:
                continue
            key = (tid, d)
            if key in self._counted:
                continue
            self._counted.add(key)
            self._counted.discard((tid, "outbound" if d == "inbound" else "inbound"))  # allow a genuine return crossing
            k = (minute_bucket(t_seconds), d, cls)
            self.tallies[k] = self.tallies.get(k, 0) + 1
            n += 1
        return n

    def totals(self) -> dict[tuple[str, str], int]:
        out: dict[tuple[str, str], int] = {}
        for (_, d, c), v in self.tallies.items():
            out[(d, c)] = out.get((d, c), 0) + v
        return out


def tallies_to_frame(tallies: dict, location_id: str, n_minutes: int, classes=("person",) ) -> pd.DataFrame:
    """Minute-bucket table. Every minute of the processed segment is present for every (direction, class) observed or
    listed in ``classes`` x inbound/outbound, with explicit zeros (a measured zero, not a missing value)."""
    combos = {(d, c) for d in ("inbound", "outbound") for c in classes} | {(d, c) for (_, d, c) in tallies}
    rows = []
    for m in range(max(n_minutes, 1)):
        for d, c in sorted(combos):
            rows.append({"location_id": location_id, "timestamp_min": CLIP_EPOCH + pd.Timedelta(minutes=m), "clip_minute": m,
                         "direction": d, "class": c, "count": int(tallies.get((m, d, c), 0)),
                         "measurement_method": MEASUREMENT_METHOD, "source_type": SOURCE_TYPE, "time_basis": TIME_BASIS})
    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    validate_output(df)
    return df


def validate_output(df: pd.DataFrame) -> None:
    """Raise ValueError if the table violates the output contract (schema, enums, no identity columns)."""
    missing = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    bad = [c for c in df.columns if any(p in c.lower() for p in FORBIDDEN_COLUMN_PARTS)]
    if bad:
        raise ValueError(f"identity-like columns are not allowed: {bad}")
    if (df["count"] < 0).any():
        raise ValueError("negative count")
    if not df["direction"].isin(DIRECTIONS).all():
        raise ValueError("invalid direction")
    if not df["class"].isin(CLASSES).all():
        raise ValueError("invalid class")
    if not (df["measurement_method"] == MEASUREMENT_METHOD).all():
        raise ValueError("measurement_method must be actual_detector")
