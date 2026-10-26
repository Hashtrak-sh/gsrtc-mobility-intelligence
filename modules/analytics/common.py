"""Shared helpers for the analytics engine: safe division, time helpers, capacity rules, labels."""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

import config
from modules.data_gen import constants as C

Tables = dict[str, pd.DataFrame]

SOURCE_TYPE = "synthetic"  # derived-from-synthetic metrics (RULES.md: provenance)
DAY_TYPES = C.DAY_TYPES
ASSUMPTION_BADGE = config.SIMULATION_BADGE_TEXT


def safe_div(num: Any, den: Any) -> Any:
    """num / den with NaN (not inf, not 0) where the denominator is zero or missing.

    Works on scalars, numpy arrays and pandas Series.
    """
    if isinstance(num, pd.Series) or isinstance(den, pd.Series):
        n = pd.to_numeric(num, errors="coerce") if isinstance(num, pd.Series) else num
        d = pd.to_numeric(den, errors="coerce") if isinstance(den, pd.Series) else den
        d_nz = d.where(d != 0) if isinstance(d, pd.Series) else (np.nan if d == 0 else d)
        return n / d_nz
    if num is None or den is None:
        return float("nan")
    try:
        if den == 0 or np.isnan(den) or np.isnan(num):
            return float("nan")
    except TypeError:
        return float("nan")
    return float(num) / float(den)


def dep_hour(departure_time: pd.Series) -> pd.Series:
    """Clock hour (0-23) of an ``HH:MM`` string column; NaN-safe (invalid -> <NA>)."""
    h = pd.to_numeric(departure_time.astype("string").str.slice(0, 2), errors="coerce")
    return h.astype("Int64")


def hour_window(h0: int, h1_inclusive: int) -> str:
    """Window label for whole clock hours, e.g. (7, 8) -> ``07:00-09:00`` (24-hour time)."""
    return f"{int(h0):02d}:00-{int(h1_inclusive) + 1:02d}:00"


def crush_factor(route_type: str) -> float:
    return C.LOCAL_CRUSH_FACTOR if route_type == "local" else C.INTERCITY_CRUSH_FACTOR


def n_days_by_day_type(trips: pd.DataFrame) -> pd.Series:
    """Number of distinct service dates for each day_type (denominator for average-day figures)."""
    if trips.empty:
        return pd.Series(dtype="int64")
    return trips.groupby("day_type")["service_date"].nunique()


def contiguous_runs(hours: list[int]) -> list[tuple[int, int]]:
    """Group sorted integer hours into runs of consecutive hours: [7, 8, 17] -> [(7, 8), (17, 17)]."""
    hs = sorted(set(int(h) for h in hours))
    runs: list[tuple[int, int]] = []
    for h in hs:
        if runs and h == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], h)
        else:
            runs.append((h, h))
    return runs


def jdump(obj: Any) -> str:
    """Deterministic JSON string (sorted keys, NaN -> null)."""
    def clean(o: Any) -> Any:
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating, float)):
            return None if np.isnan(o) or np.isinf(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, pd.Timestamp):
            return o.isoformat()
        return o
    return json.dumps(clean(obj), sort_keys=True, ensure_ascii=False)
