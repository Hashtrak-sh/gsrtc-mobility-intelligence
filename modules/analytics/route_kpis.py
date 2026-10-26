"""Route KPIs: ``route_kpis`` (route x service_date) and ``route_summary`` (route level).

``route_summary`` is the single source of truth for every route KPI shown in the UI, recommendations and report.
All aggregates are computed from trip-level sums (never by averaging percentages):

* ``load_factor_pct``   = passenger-km / seat-km x 100, seat-km = sum(seats x route length_km) over the trips.
* ``epkm_inr``          = ticket revenue / vehicle-km  (TICKET revenue only; no subsidy, advertising or other income).
* ``revenue_per_passenger_inr`` = ticket revenue / passengers (``sum(passenger_count)``).
* ``contribution_inr``  = ticket revenue - trip operating cost (``trips.operating_cost_inr`` = per-km rate x route
  length). It is NOT profit: depot overheads, staff, depreciation, taxes and subsidies are not in the cost model.
* ``reliability_pct``   = % of trips with -1 <= departure delay <= +5 min (``config.RELIABILITY_ON_TIME_BAND_MIN``).
* ``boardings_per_seat`` = passengers / seats offered (turnover, supporting metric; not a load factor).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from modules.analytics.common import SOURCE_TYPE, hour_window, jdump, n_days_by_day_type, safe_div
from modules.analytics.reliability import on_time_flag
from modules.data_gen import constants as C

KPI_ASSUMPTIONS = {
    "load_factor_pct": "passenger-km / seat-km x 100 (seat-km = seats x route length_km per trip)",
    "epkm_inr": "ticket revenue / vehicle-km; ticket revenue only",
    "revenue_per_passenger_inr": "ticket revenue / sum(passenger_count)",
    "contribution_inr": "ticket revenue - trip operating cost; NOT profit (no overheads, staff, depreciation, subsidy)",
    "reliability_pct": "share of trips with delay within the on-time band (minutes, inclusive)",
    "operating_cost_inr_per_vehicle_km": C.OPERATING_COST_PER_KM_INR,
}


def reliability_band_label() -> str:
    lo, hi = config.RELIABILITY_ON_TIME_BAND_MIN
    return f"{lo:+g}..{hi:+g} min"


def kpi_assumptions_json() -> str:
    d = dict(KPI_ASSUMPTIONS)
    d["reliability_band_min"] = list(config.RELIABILITY_ON_TIME_BAND_MIN)
    d["note"] = config.SIMULATION_BADGE_TEXT
    return jdump(d)


def trip_metrics(trips_sum: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    """Trip-level table with revenue, passenger-km, vehicle-km, seat-km and the on-time flag."""
    by_trip = legs.groupby("trip_id").agg(ticket_revenue_inr=("fare_inr", "sum"), estimated_passenger_km=("pax_km", "sum"))
    t = trips_sum.join(by_trip, on="trip_id")
    t["ticket_revenue_inr"] = t["ticket_revenue_inr"].fillna(0.0)
    t["estimated_passenger_km"] = t["estimated_passenger_km"].fillna(0.0)
    t["vehicle_km"] = t["length_km"].astype(float)
    t["seat_km"] = t["seats"].astype(float) * t["length_km"].astype(float)
    t["on_time"] = on_time_flag(t["departure_delay_min"])
    t["has_delay"] = t["departure_delay_min"].notna()
    return t


def aggregate_kpis(tm: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Aggregate the trip-level table ``tm`` to ``keys`` and derive all ratio KPIs from the sums."""
    if tm.empty:
        cols = keys + ["trips", "boardings", "estimated_passenger_km", "vehicle_km", "seat_km", "ticket_revenue_inr",
                       "operating_cost_inr", "available_seats", "load_factor_pct", "epkm_inr", "revenue_per_passenger_inr",
                       "contribution_inr", "reliability_pct", "mean_delay_min", "boardings_per_seat"]
        return pd.DataFrame(columns=cols)
    g = tm.groupby(keys, dropna=False)
    out = g.agg(
        trips=("trip_id", "count"),
        boardings=("boardings", "sum"),
        estimated_passenger_km=("estimated_passenger_km", "sum"),
        vehicle_km=("vehicle_km", "sum"),
        seat_km=("seat_km", "sum"),
        ticket_revenue_inr=("ticket_revenue_inr", "sum"),
        operating_cost_inr=("operating_cost_inr", "sum"),
        available_seats=("seats", "sum"),
        _on_time=("on_time", lambda s: int(s.fillna(False).astype(bool).sum())),
        _with_delay=("has_delay", "sum"),
        mean_delay_min=("departure_delay_min", "mean"),
        peak_load_factor_max=("peak_load_factor", "max"),
    ).reset_index()
    out["load_factor_pct"] = safe_div(out["estimated_passenger_km"], out["seat_km"]) * 100.0
    out["epkm_inr"] = safe_div(out["ticket_revenue_inr"], out["vehicle_km"])
    out["revenue_per_passenger_inr"] = safe_div(out["ticket_revenue_inr"], out["boardings"])
    out["contribution_inr"] = out["ticket_revenue_inr"] - out["operating_cost_inr"]
    out["reliability_pct"] = safe_div(out["_on_time"], out["_with_delay"]) * 100.0
    out["boardings_per_seat"] = safe_div(out["boardings"], out["available_seats"])
    return out.drop(columns=["_on_time", "_with_delay"])


def route_kpis(tm: pd.DataFrame) -> pd.DataFrame:
    """Route x service_date KPIs (schema columns + documented extras)."""
    out = aggregate_kpis(tm, ["route_id", "service_date", "day_type"])
    out["source_type"] = SOURCE_TYPE
    out["assumptions_json"] = kpi_assumptions_json()
    cols = ["route_id", "service_date", "day_type", "trips", "boardings", "estimated_passenger_km", "vehicle_km", "seat_km",
            "ticket_revenue_inr", "operating_cost_inr", "available_seats", "load_factor_pct", "epkm_inr",
            "revenue_per_passenger_inr", "contribution_inr", "reliability_pct", "mean_delay_min", "boardings_per_seat",
            "peak_load_factor_max", "source_type", "assumptions_json"]
    return out[cols].sort_values(["route_id", "service_date"], kind="mergesort").reset_index(drop=True)


def peak_hour_by_route(tm: pd.DataFrame, day_type: str | None = None) -> pd.DataFrame:
    """Per route, the departure hour with the highest seat-weighted peak load factor (sum of trip peak onboard / sum seats,
    both directions together) on ``day_type`` (falls back to all days when the route has none). Ties -> earliest hour."""
    rows = []
    for rid, g in tm.groupby("route_id"):
        sel = g[g["day_type"] == day_type] if day_type else g
        if sel.empty:
            sel = g
        h = sel.groupby("dep_hour").agg(pk=("peak_onboard", "sum"), s=("seats", "sum"), n=("trip_id", "count")).reset_index()
        h["plf"] = safe_div(h["pk"], h["s"])
        h = h.dropna(subset=["plf"]).sort_values(["plf", "dep_hour"], ascending=[False, True])
        if h.empty:
            rows.append({"route_id": rid, "peak_hour": np.nan, "peak_hour_window": None, "peak_hour_load_factor": np.nan})
        else:
            r = h.iloc[0]
            rows.append({"route_id": rid, "peak_hour": int(r["dep_hour"]), "peak_hour_window": hour_window(r["dep_hour"], r["dep_hour"]),
                         "peak_hour_load_factor": float(r["plf"])})
    return pd.DataFrame(rows, columns=["route_id", "peak_hour", "peak_hour_window", "peak_hour_load_factor"])


def route_summary(tm: pd.DataFrame, routes: pd.DataFrame, trips: pd.DataFrame | None = None) -> pd.DataFrame:
    """Route-level summary: THE source of truth for route KPIs (all service dates, seat/km-weighted).

    Extra columns: boardings per day by day type (``boardings_per_day_weekday/weekend/festival`` = total over the day
    type / number of dates of that type), ``avg_boardings_per_day`` (all days), ``peak_hour`` /
    ``peak_hour_window`` / ``peak_hour_load_factor`` (weekday, peak load factor = max-link onboard / seats),
    ``revenue_per_day_inr`` and ``contribution_per_day_inr`` (all days), ``trips_per_day_weekday``.
    """
    base = aggregate_kpis(tm, ["route_id"])
    nd = n_days_by_day_type(tm if trips is None else trips)
    n_all = int(tm["service_date"].nunique()) if len(tm) else 0
    for dtp in C.DAY_TYPES:
        b = tm[tm["day_type"] == dtp].groupby("route_id")["boardings"].sum()
        days = int(nd.get(dtp, 0))
        base[f"boardings_per_day_{dtp}"] = base["route_id"].map(b).fillna(0.0) / days if days else np.nan
    base["avg_boardings_per_day"] = base["boardings"] / n_all if n_all else np.nan
    base["revenue_per_day_inr"] = base["ticket_revenue_inr"] / n_all if n_all else np.nan
    base["contribution_per_day_inr"] = base["contribution_inr"] / n_all if n_all else np.nan
    wk = tm[tm["day_type"] == config.PEAK_DAY_TYPE].groupby("route_id")["trip_id"].count()
    d_wk = int(nd.get(config.PEAK_DAY_TYPE, 0))
    base["trips_per_day_weekday"] = base["route_id"].map(wk).fillna(0.0) / d_wk if d_wk else np.nan
    base = base.merge(peak_hour_by_route(tm, config.PEAK_DAY_TYPE), on="route_id", how="left")
    r = routes[["route_id", "name", "route_type", "corridor", "bus_type", "length_km", "minimum_service"]]
    out = r.merge(base, on="route_id", how="left")
    out["source_type"] = SOURCE_TYPE
    out["assumptions_json"] = kpi_assumptions_json()
    return out.sort_values("route_id", kind="mergesort").reset_index(drop=True)
