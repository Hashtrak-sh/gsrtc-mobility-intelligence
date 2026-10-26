"""Competition comparison built directly from source tables (state trips vs synthetic private competitor services).

Illustrative only: competitor services, fares and the state tariff are synthetic demonstration values, not verified
operator data. This module covers departure-slot comparison, fare by bus type and the pricing what-if baseline; the
``competition_analysis`` table and competitive gap score (M5) live in ``modules/competition/gap_score.py``. Competitor
departure times are from the corridor origin (Rajkot) only; the opposite direction is assumed to mirror them (M1).

Pricing baseline unit: **full-journey equivalents per average day** = estimated passenger-km / route length_km. Dividing
by seats offered per day then gives exactly the route load factor (passenger-km / seat-km), so the scenario's baseline
occupancy equals the load factor shown on the Route Intelligence page for the same day type, and the baseline fare is the
average ticket revenue per full-journey equivalent.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from modules.analytics.recommendations import full_route_fare_inr
from modules.analytics.common import dep_hour

STATE_LABEL = "State (GSRTC demo)"
PRIVATE_LABEL = "Private (synthetic)"


def corridor_route_ids(routes: pd.DataFrame, corridor: str) -> list[str]:
    return sorted(routes.loc[routes["corridor"] == corridor, "route_id"])


def slot_comparison(trips: pd.DataFrame, competitors: pd.DataFrame, routes: pd.DataFrame, corridor: str, day_type: str) -> pd.DataFrame:
    """Departures and seats per average day by clock hour (departures from the corridor origin, outbound).

    State = outbound trips on the corridor's routes / number of dates of ``day_type``; private = competitor services of the
    corridor and day type (one row per service). ``state_gap`` marks hours with private departures but no state departure.
    """
    ids = corridor_route_ids(routes, corridor)
    t = trips[trips["route_id"].isin(ids) & (trips["direction"] == "outbound") & (trips["day_type"] == day_type)]
    n_days = trips.loc[trips["day_type"] == day_type, "service_date"].nunique()
    if t.empty or n_days == 0:
        st_ = pd.DataFrame(columns=["hour", "state_departures", "state_seats"])
    else:
        t = t.assign(hour=dep_hour(t["departure_time"]))
        st_ = t.groupby("hour").agg(state_departures=("trip_id", "count"), state_seats=("seats", "sum")).reset_index()
        st_[["state_departures", "state_seats"]] = st_[["state_departures", "state_seats"]] / n_days
    c = competitors[(competitors["route_pair"] == corridor) & (competitors["day_type"] == day_type)]
    if c.empty:
        pv = pd.DataFrame(columns=["hour", "private_departures", "private_seats"])
    else:
        c = c.assign(hour=dep_hour(c["departure_time"]))
        pv = c.groupby("hour").agg(private_departures=("service_id", "count"), private_seats=("seats", "sum")).reset_index()
    out = pd.DataFrame({"hour": range(0, 24)}).merge(st_, on="hour", how="left").merge(pv, on="hour", how="left").fillna(0.0)
    out = out[(out["state_departures"] > 0) | (out["private_departures"] > 0)].reset_index(drop=True)
    out["state_gap"] = (out["state_departures"] == 0) & (out["private_departures"] > 0)
    return out


def fare_comparison(competitors: pd.DataFrame, routes: pd.DataFrame, corridor: str, day_type: str) -> pd.DataFrame:
    """Fare by bus type: state full-route fare (illustrative tariff) vs private median base/surge fare (INR per passenger)."""
    r = routes[routes["corridor"] == corridor]
    state = (r.assign(state_fare_inr=[full_route_fare_inr(b, float(k)) for b, k in zip(r["bus_type"], r["length_km"])])
             .groupby("bus_type", as_index=False)["state_fare_inr"].mean())
    c = competitors[(competitors["route_pair"] == corridor) & (competitors["day_type"] == day_type)]
    private = c.groupby("bus_type").agg(private_services=("service_id", "count"), private_base_fare_inr=("base_fare_inr", "median"),
                                        private_surge_fare_inr=("surge_fare_inr", "median"),
                                        private_min_fare_inr=("base_fare_inr", "min"),
                                        private_max_surge_fare_inr=("surge_fare_inr", "max")).reset_index()
    out = state.merge(private, on="bus_type", how="outer")
    out["fare_index"] = out["state_fare_inr"] / out["private_base_fare_inr"]  # NaN where either side is absent
    order = {"ordinary": 0, "express": 1, "AC_seater": 2, "AC_sleeper": 3, "premium": 4}
    return out.sort_values("bus_type", key=lambda s: s.map(order).fillna(9)).reset_index(drop=True)


def pricing_baseline(kpis: pd.DataFrame, route: pd.Series, day_type: str) -> dict[str, Any]:
    """Baseline inputs for ``pricing_scenario`` for one route on an average day of ``day_type`` (see module docstring).

    Raises ValueError when the route has no service on that day type (nothing to price).
    """
    k = kpis[(kpis["route_id"] == route["route_id"]) & (kpis["day_type"] == day_type)]
    n_days = int(k["service_date"].nunique())
    length = float(route["length_km"])
    if n_days == 0 or length <= 0:
        raise ValueError(f"No service days of type {day_type!r} for route {route['route_id']}")
    equiv = float(k["estimated_passenger_km"].sum()) / length / n_days
    revenue = float(k["ticket_revenue_inr"].sum()) / n_days
    seats = float(k["seat_km"].sum()) / length / n_days  # seats offered per day (trip seats)
    cost = float(k["operating_cost_inr"].sum()) / n_days
    if equiv <= 0:
        raise ValueError(f"Route {route['route_id']} carried no passenger-km on {day_type} days")
    return {"route_id": route["route_id"], "day_type": day_type, "n_days": n_days, "baseline_demand": equiv,
            "baseline_fare": revenue / equiv, "seats_offered": seats, "operating_cost": cost,
            "baseline_revenue": revenue, "load_factor_pct": equiv / seats * 100 if seats > 0 else float("nan")}


def private_fare_reference(competitors: pd.DataFrame, corridor: str, day_type: str, bus_type: str | None = None) -> float:
    """Median private base fare on the corridor (optionally for one bus type); NaN if none."""
    c = competitors[(competitors["route_pair"] == corridor) & (competitors["day_type"] == day_type)]
    if bus_type:
        cb = c[c["bus_type"] == bus_type]
        c = cb if len(cb) else c
    return float(c["base_fare_inr"].median()) if len(c) else float("nan")
