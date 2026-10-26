"""Stop-level boarding / alighting activity for the geographic demand heatmap (pure functions, no Streamlit).

Formula and units
-----------------
``stop_occupancy`` holds, for every route x direction x day type x departure hour x stop, the *average bus's* boardings and
alightings per trip (``avg_boardings``, ``avg_alightings``) and ``trips_per_day`` (trips of that group per average service
day of the day type). Therefore, per average service day of the day type:

    boardings_per_day(stop)  = sum over (route, direction, hour in window) of avg_boardings  x trips_per_day   [passengers/day]
    alightings_per_day(stop) = sum over the same rows of            avg_alightings x trips_per_day             [passengers/day]
    net_per_day(stop)        = boardings_per_day - alightings_per_day                                          [passengers/day]

Summed over all stops this equals ``route_summary.boardings_per_day_<day_type>`` summed over the same routes (tested).
A stop shared by several routes sums their activity. All passenger values are simulated; stop positions come from
``stops.coord_source`` (OpenStreetMap, OpenStreetMap-offset or manual demo input).
"""
from __future__ import annotations

import math
from collections.abc import Iterable

import pandas as pd

METRICS: dict[str, str] = {"boardings": "Boardings", "alightings": "Alightings", "net": "Net (boardings - alightings)"}
OUT_COLUMNS = ["stop_id", "name", "lat", "lon", "coord_source", "boardings_per_day", "alightings_per_day", "net_per_day"]
RAJKOT_CENTRE = (22.3039, 70.8022)      # (lat, lon) Rajkot city centre, used only to split city stops from corridor stops
CITY_RADIUS_KM = 25.0


def stop_activity(stop_occ: pd.DataFrame, stops: pd.DataFrame, *, day_type: str, hour_lo: int = 0, hour_hi: int = 24,
                  route_ids: Iterable[str] | None = None) -> pd.DataFrame:
    """Per-stop boardings, alightings and net per average service day (passengers/day); see module docstring.

    Window is the half-open clock window [hour_lo, hour_hi) on the departure hour. ``route_ids=None`` means all routes.
    Stops without coordinates are kept with NaN lat/lon (shown as missing, never invented).
    """
    s = stop_occ[(stop_occ["day_type"] == day_type) & (stop_occ["hour"] >= hour_lo) & (stop_occ["hour"] < hour_hi)]
    if route_ids is not None:
        s = s[s["route_id"].isin(list(route_ids))]
    s = s.assign(b=s["avg_boardings"] * s["trips_per_day"], a=s["avg_alightings"] * s["trips_per_day"])
    g = s.groupby("stop_id", as_index=False).agg(boardings_per_day=("b", "sum"), alightings_per_day=("a", "sum"))
    g["net_per_day"] = g["boardings_per_day"] - g["alightings_per_day"]
    cols = [c for c in ("stop_id", "name", "lat", "lon", "coord_source") if c in stops.columns]
    out = g.merge(stops[cols].drop_duplicates("stop_id"), on="stop_id", how="left")
    for c in OUT_COLUMNS:
        if c not in out.columns:
            out[c] = float("nan") if c in ("lat", "lon") else None
    return out[OUT_COLUMNS].sort_values("boardings_per_day", ascending=False, kind="mergesort").reset_index(drop=True)


def _km(lat: float, lon: float) -> float:
    la0, lo0 = RAJKOT_CENTRE
    dx = (lon - lo0) * 111.32 * math.cos(math.radians(la0))
    dy = (lat - la0) * 110.57
    return math.hypot(dx, dy)


def in_city(act: pd.DataFrame, radius_km: float = CITY_RADIUS_KM) -> pd.Series:
    """Boolean mask of stops within ``radius_km`` of the Rajkot centre (NaN coordinates -> False)."""
    return pd.Series([bool(pd.notna(la) and pd.notna(lo) and _km(la, lo) <= radius_km) for la, lo in zip(act["lat"], act["lon"])],
                     index=act.index, dtype=bool)


def metric_column(metric: str) -> str:
    return {"boardings": "boardings_per_day", "alightings": "alightings_per_day", "net": "net_per_day"}[metric]


def takeaway(act: pd.DataFrame, metric: str = "boardings") -> str:
    """One sentence computed from the data: the stop with the highest value and its share of the total."""
    col = metric_column(metric)
    a = act.dropna(subset=[col])
    if a.empty:
        return "No stop activity matches the current filters."
    if metric == "net":
        r = a.loc[a[col].abs().idxmax()]
        side = "board than alight" if r[col] >= 0 else "alight than board"
        return f"{r['name'] or r['stop_id']} has the largest imbalance: {abs(r[col]):,.0f} more passengers/day {side} (simulated)."
    total = float(a[col].sum())
    r = a.loc[a[col].idxmax()]
    share = r[col] / total * 100 if total else float("nan")
    verb = "boardings" if metric == "boardings" else "alightings"
    return (f"{r['name'] or r['stop_id']} has the most {verb}: {r[col]:,.0f} per average day, "
            f"{share:.0f}% of the {total:,.0f} across the {len(a)} stops shown (simulated).")
