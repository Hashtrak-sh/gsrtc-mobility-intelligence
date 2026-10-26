"""Small CCTV summary: mean inbound person count per hour per average day, by location and day type.

Works on the SYNTHETIC ``cctv_counts`` stream only (``measurement_method = synthetic``). Aggregate counts, no identities.
"""
from __future__ import annotations

import pandas as pd

from modules.analytics.common import SOURCE_TYPE

COLUMNS = ["location_id", "day_type", "hour", "mean_inbound_persons", "n_days", "measurement_method", "source_type"]


def cctv_hourly_profile(cctv: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Mean inbound person count per hour per day (rows: location x day_type x hour)."""
    if cctv.empty or trips.empty:
        return pd.DataFrame(columns=COLUMNS)
    c = cctv[(cctv["class"] == "person") & (cctv["direction"] == "inbound")].copy()
    cal = trips[["service_date", "day_type"]].drop_duplicates()
    cal = cal.assign(date=pd.to_datetime(cal["service_date"]))[["date", "day_type"]]
    c["date"] = c["timestamp_min"].dt.normalize()
    c["hour"] = c["timestamp_min"].dt.hour
    c = c.merge(cal, on="date", how="inner")
    per = c.groupby(["location_id", "day_type", "date", "hour"])["count"].sum().reset_index()
    g = per.groupby(["location_id", "day_type", "hour"]).agg(mean_inbound_persons=("count", "mean"), n_days=("date", "nunique")).reset_index()
    methods = "|".join(sorted(cctv["measurement_method"].dropna().unique()))
    g["measurement_method"] = methods
    g["source_type"] = SOURCE_TYPE
    return g[COLUMNS]
