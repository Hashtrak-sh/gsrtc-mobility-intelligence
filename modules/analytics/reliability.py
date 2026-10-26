"""Schedule reliability: share of trips departing within a tolerance band of the timetable.

A trip is on time when ``lo <= departure_delay_min <= hi`` (inclusive; default -1..+5 min, see
``config.RELIABILITY_ON_TIME_BAND_MIN``). Trips with a missing delay are excluded from both numerator and
denominator (never counted as on time); if no trip has a delay the result is NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def on_time_flag(delay_min: pd.Series, band: tuple[float, float] | None = None) -> pd.Series:
    """Nullable boolean: True inside the band (inclusive), False outside, <NA> for a missing delay."""
    lo, hi = band or config.RELIABILITY_ON_TIME_BAND_MIN
    d = pd.to_numeric(delay_min, errors="coerce")
    out = ((d >= lo) & (d <= hi)).astype("boolean")
    return out.mask(d.isna())


def reliability_pct(delay_min: pd.Series, band: tuple[float, float] | None = None) -> float:
    """Percentage of trips (with a known delay) inside the band; NaN when there are none."""
    f = on_time_flag(delay_min, band).dropna()
    return float(f.mean() * 100.0) if len(f) else float("nan")


def mean_delay_min(delay_min: pd.Series) -> float:
    d = pd.to_numeric(delay_min, errors="coerce").dropna()
    return float(d.mean()) if len(d) else float("nan")


def reliability_by(trips: pd.DataFrame, keys: list[str], band: tuple[float, float] | None = None) -> pd.DataFrame:
    """Reliability and mean delay per group: columns keys + ``trips_with_delay``, ``on_time_trips``,
    ``reliability_pct``, ``mean_delay_min``."""
    t = trips.copy()
    t["_ot"] = on_time_flag(t["departure_delay_min"], band)
    g = t.groupby(keys, dropna=False)
    out = g.agg(
        trips_with_delay=("_ot", "count"),
        on_time_trips=("_ot", lambda s: int(s.fillna(False).astype(bool).sum())),
        mean_delay_min=("departure_delay_min", lambda s: mean_delay_min(s)),
    ).reset_index()
    out["reliability_pct"] = np.where(out["trips_with_delay"] > 0, out["on_time_trips"] / out["trips_with_delay"].replace(0, np.nan) * 100.0, np.nan)
    return out
