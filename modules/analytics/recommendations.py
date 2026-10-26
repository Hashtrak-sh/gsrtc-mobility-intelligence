"""Recommendation records generated from the gap table, route summary and route scores (no hardcoded numbers).

Categories
* ``add_service_peak``          crowded route-direction-hours on the peak day type (gap_index > threshold).
* ``add_service_corridor_slot`` intercity corridor window with NO state seats but private-market proxy demand
                                (e.g. Rajkot-Somnath evening).
* ``add_capacity_weekend``      intercity buses at their hard seat cap on recurring (weekday/weekend) days.
* ``protect_minimum_service``   minimum-service routes: retain and review the timetable. Never a removal action.

Every record has evidence (table, filter, the exact gap rows used), assumptions, an expected impact computed with
``scenarios.service_frequency_scenario`` and constraints. ``time_window`` is built from the evidence rows' hours
(``hour_window(min_hour, max_hour)``), so it always matches the gap table windows exactly.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import config
from modules.analytics.common import SOURCE_TYPE, contiguous_runs, hour_window, jdump, n_days_by_day_type
from modules.analytics.gaps import STATUS_AT_CAPACITY, STATUS_CROWDED, STATUS_NO_CAPACITY
from modules.analytics.scenarios import service_frequency_scenario
from modules.data_gen import constants as C

REC_COLUMNS = ["recommendation_id", "priority", "category", "title", "route_id", "location_id", "time_window", "action",
               "evidence_json", "assumptions_json", "expected_impact_json", "constraints_json", "confidence_label",
               "source_type", "priority_rank", "day_type", "corridor", "direction"]

_GAP_EVIDENCE_COLS = ["level", "route_id", "corridor", "direction", "day_type", "hour", "location_id", "zone_id",
                      "demand_estimate", "seats_offered", "gap_count", "gap_index", "status", "trips_per_day",
                      "private_seats", "private_demand_proxy"]
_STD_CONSTRAINTS = ["fleet availability, driver duty hours, depot capacity and bus turnaround are NOT modelled",
                    "demand is ticketed demand censored at capacity: gaps are lower bounds",
                    "contribution = ticket revenue - operating cost, not profit"]


def full_route_fare_inr(bus_type: str, length_km: float) -> float:
    """Illustrative full-route per-passenger fare from ``constants.FARE_TABLE`` (adult, no concession)."""
    ft = C.FARE_TABLE[bus_type]
    raw = max(ft["min_fare"], ft["base"] + ft["per_km"] * length_km)
    r = ft["round_to"]
    return float(round(raw / r) * r)


def _rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = [c for c in _GAP_EVIDENCE_COLS if c in df.columns]
    return df[cols].sort_values(["day_type", "direction", "hour"]).to_dict("records")


def _window_gap(rows: pd.DataFrame) -> float:
    return float(rows["gap_count"].fillna(0).sum())


def _priority(total_gap: float, min_service: bool = False) -> str:
    if min_service:
        return "Medium"
    return "High" if total_gap >= config.RECOMMENDATION_HIGH_GAP else "Medium"


def _dest_zone_evidence(rows: pd.DataFrame, legs: pd.DataFrame | None, trips_sum: pd.DataFrame, stops: pd.DataFrame) -> dict[str, Any]:
    """Passengers per average day by destination zone on the trips that make up the evidence rows (top 3 zones)."""
    if legs is None or rows.empty:
        return {}
    nd = n_days_by_day_type(trips_sum)
    zmap = stops.set_index("stop_id")["zone_id"]
    per_zone: dict[str, float] = {}
    seats_day = 0.0
    for r in rows.itertuples():
        sel = trips_sum[(trips_sum["route_id"] == r.route_id) & (trips_sum["direction"] == r.direction)
                        & (trips_sum["day_type"] == r.day_type) & (trips_sum["dep_hour"] == r.hour)]
        days = float(nd.get(r.day_type, 0))
        if sel.empty or days <= 0:
            continue
        seats_day += float(sel["seats"].sum()) / days
        lg = legs[legs["trip_id"].isin(sel["trip_id"])]
        for z, v in lg.groupby(lg["dest_stop_id"].map(zmap))["passenger_count"].sum().items():
            per_zone[str(z)] = per_zone.get(str(z), 0.0) + float(v) / days
    if not per_zone:
        return {}
    top = sorted(per_zone.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return {"top_destination_zones_pax_per_day": {k: round(v, 1) for k, v in top},
            "seats_offered_per_day_on_these_trips": round(seats_day, 1)}


def _route_facts(summary: pd.DataFrame, scores: pd.DataFrame, route_id: str) -> dict[str, Any]:
    s = summary[summary["route_id"] == route_id]
    out: dict[str, Any] = {}
    if len(s):
        r = s.iloc[0]
        out["route_summary"] = {k: (None if pd.isna(r[k]) else (r[k].item() if hasattr(r[k], "item") else r[k]))
                                for k in ["route_id", "name", "route_type", "avg_boardings_per_day", "load_factor_pct",
                                          "peak_hour_window", "peak_hour_load_factor", "epkm_inr", "revenue_per_passenger_inr",
                                          "contribution_inr", "reliability_pct", "minimum_service"]}
    sc = scores[scores["route_id"] == route_id]
    if len(sc):
        out["route_score"] = {"total_score": None if pd.isna(sc.iloc[0]["total_score"]) else float(sc.iloc[0]["total_score"]),
                              "rank_within_type": None if pd.isna(sc.iloc[0]["rank_within_type"]) else int(sc.iloc[0]["rank_within_type"]),
                              "weight_version": sc.iloc[0]["weight_version"]}
    return out


def _cost_per_km(bus_type: str) -> float:
    return float(C.OPERATING_COST_PER_KM_INR[bus_type])


def generate_recommendations(hourly: pd.DataFrame, summary: pd.DataFrame, scores: pd.DataFrame, routes: pd.DataFrame,
                             trips_sum: pd.DataFrame, stops: pd.DataFrame, competitors: pd.DataFrame,
                             legs: pd.DataFrame | None = None) -> pd.DataFrame:
    recs: list[dict[str, Any]] = []
    rt = routes.set_index("route_id")
    peak = config.PEAK_DAY_TYPE
    tlf = config.SERVICE_TARGET_LOAD_FACTOR
    if not hourly.empty:
        rd = hourly[hourly["level"] == "route_direction"]
        # ------------------------------------------------------------ crowded peak route-direction-hours
        cr = rd[(rd["day_type"] == peak) & (rd["status"] == STATUS_CROWDED)]
        for rid, g in cr.groupby("route_id"):
            for h0, h1 in contiguous_runs(g["hour"].tolist()):
                rows = g[(g["hour"] >= h0) & (g["hour"] <= h1)]
                recs.append(_crowded_rec(rid, rows, h0, h1, rt, summary, scores, trips_sum, stops, legs, tlf))
        # ------------------------------------------------------------ corridor no-state-capacity windows
        co = hourly[(hourly["level"] == "corridor") & (hourly["day_type"] == peak) & (hourly["status"] == STATUS_NO_CAPACITY)
                    & (hourly["gap_count"].fillna(0) > 0)]
        for cor, g in co.groupby("corridor"):
            for h0, h1 in contiguous_runs(g["hour"].tolist()):
                rows = g[(g["hour"] >= h0) & (g["hour"] <= h1)]
                if _window_gap(rows) < config.RECOMMENDATION_MIN_CORRIDOR_WINDOW_GAP:
                    continue
                r = _corridor_rec(cor, rows, h0, h1, routes, summary, scores, competitors, tlf, peak)
                if r is not None:
                    recs.append(r)
        # ------------------------------------------------------------ intercity at hard capacity on recurring days
        ac = rd[rd["status"] == STATUS_AT_CAPACITY]
        for (rid, direction), g in ac.groupby(["route_id", "direction"]):
            recurring = g[g["day_type"].isin(["weekday", "weekend"])]
            for h0, h1 in contiguous_runs(recurring["hour"].tolist()):
                rows = g[(g["hour"] >= h0) & (g["hour"] <= h1)]
                recs.append(_capacity_rec(rid, direction, rows, h0, h1, rt, summary, scores, tlf))
    # ---------------------------------------------------------------- minimum-service protection (always listed)
    for r in routes[routes["minimum_service"].astype(bool)].itertuples():
        recs.append(_protect_rec(r.route_id, rt, summary, scores, hourly))

    if not recs:
        return pd.DataFrame(columns=REC_COLUMNS)
    df = pd.DataFrame(recs)
    order = {"High": 0, "Medium": 1, "Low": 2}
    df["_p"] = df["priority"].map(order)
    df["_gap"] = -df["_gap"].astype(float)
    df = df.sort_values(["_p", "_gap", "category", "route_id"], kind="mergesort").reset_index(drop=True)
    df["priority_rank"] = np.arange(1, len(df) + 1)
    df["recommendation_id"] = [f"REC-{i:03d}" for i in df["priority_rank"]]
    df["source_type"] = SOURCE_TYPE
    df["confidence_label"] = config.CONFIDENCE_LABEL
    return df[REC_COLUMNS]


# ---------------------------------------------------------------------------------------------- builders
def _crowded_rec(rid, rows, h0, h1, rt, summary, scores, trips_sum, stops, legs, tlf) -> dict[str, Any]:
    r = rt.loc[rid]
    total_gap = _window_gap(rows)
    demand = float(rows["demand_estimate"].sum())
    existing = int(round(float(rows["trips_per_day"].sum())))
    seats_per_bus = float(rows["seats_offered"].sum() / rows["trips_per_day"].sum())
    fare = _route_fare(summary, rid)
    scen = service_frequency_scenario(demand, seats_per_bus, tlf, existing, float(r["length_km"]), _cost_per_km(r["bus_type"]),
                                      fare_per_passenger=fare)
    top = rows.sort_values(["gap_count", "gap_index"], ascending=False).iloc[0]
    window = hour_window(h0, h1)
    peak_idx = float(rows["gap_index"].max())
    dirs = sorted(rows["direction"].unique())
    ev = {"table": "hourly_demand_supply",
          "filter": {"level": "route_direction", "route_id": rid, "day_type": config.PEAK_DAY_TYPE, "status": STATUS_CROWDED,
                     "hours": f"{h0}-{h1}"},
          "gap_rows": _rows(rows),
          "figures": {"summed_gap_count_per_average_day": total_gap, "max_gap_index": peak_idx,
                      "demand_estimate_sum": demand, "seats_offered_sum": float(rows["seats_offered"].sum())},
          **_route_facts(summary, scores, rid)}
    ev["figures"].update(_dest_zone_evidence(rows, legs, trips_sum, stops))
    return {
        "priority": _priority(total_gap), "category": "add_service_peak",
        "title": f"Add {scen['additional_departures']} peak departure(s) on {rid} {window} (weekdays)",
        "route_id": rid, "location_id": top["location_id"], "time_window": window, "day_type": config.PEAK_DAY_TYPE,
        "corridor": r["corridor"], "direction": "+".join(dirs),
        "action": (f"Add about {scen['additional_departures']} departure(s) on {rid} in {window} on weekdays "
                   f"({' and '.join(dirs)}); crowding peaks near stop {top['location_id']} (peak load factor up to {peak_idx:.2f} "
                   f"of seats). Illustrative service scenario: target load factor {tlf:.0%} of seats."),
        "evidence_json": jdump(ev),
        "assumptions_json": jdump({"target_load_factor": tlf, "demand_basis": "average-day sum of critical-link onboard loads of the crowded rows",
                                   "fare_per_passenger_inr": fare, "fare_basis": "route revenue per passenger (route_summary)",
                                   "cost_per_vehicle_km_inr": _cost_per_km(r["bus_type"]), "note": config.SIMULATION_BADGE_TEXT}),
        "expected_impact_json": jdump({**scen, "demand_is_lower_bound": True}),
        "constraints_json": jdump(_STD_CONSTRAINTS + (["minimum-service route: protected"] if bool(r["minimum_service"]) else [])),
        "_gap": total_gap,
    }


def _route_fare(summary: pd.DataFrame, rid: str) -> float | None:
    s = summary[summary["route_id"] == rid]
    if s.empty or pd.isna(s.iloc[0]["revenue_per_passenger_inr"]):
        return None
    return float(s.iloc[0]["revenue_per_passenger_inr"])


def _corridor_rec(cor, rows, h0, h1, routes, summary, scores, competitors, tlf, peak) -> dict[str, Any] | None:
    state_routes = routes[routes["corridor"] == cor]
    if state_routes.empty:
        return None
    comp = competitors[(competitors["route_pair"] == cor) & (competitors["day_type"] == peak)].copy()
    comp["hour"] = pd.to_numeric(comp["departure_time"].str[:2], errors="coerce")
    inw = comp[(comp["hour"] >= h0) & (comp["hour"] <= h1)]
    seat_by_type = inw.groupby("bus_type")["seats"].sum().sort_values(ascending=False)
    candidates = [b for b in seat_by_type.index if b in set(state_routes["bus_type"])]
    if candidates:
        bus = candidates[0]
    else:  # no like-for-like state bus type: choose the state route type with the highest EPKM
        s = summary[summary["route_id"].isin(state_routes["route_id"])].sort_values("epkm_inr", ascending=False)
        bus = state_routes.set_index("route_id").loc[s.iloc[0]["route_id"], "bus_type"] if len(s) else state_routes.iloc[0]["bus_type"]
    route = state_routes[state_routes["bus_type"] == bus].iloc[0]
    seats = float(C.BUS_TYPE_SEATS[bus])
    proxy = float(rows["private_demand_proxy"].sum())
    total_gap = _window_gap(rows)
    projected = proxy * config.STATE_CAPTURE_SHARE
    fare = full_route_fare_inr(bus, float(route["length_km"]))
    scen = service_frequency_scenario(projected, seats, tlf, 0, float(route["length_km"]), _cost_per_km(bus), fare_per_passenger=fare)
    window = hour_window(h0, h1)
    pr_hours = sorted(inw["departure_time"].unique())
    ev = {"table": "hourly_demand_supply",
          "filter": {"level": "corridor", "corridor": cor, "day_type": peak, "status": STATUS_NO_CAPACITY, "hours": f"{h0}-{h1}"},
          "gap_rows": _rows(rows),
          "figures": {"state_seats_in_window": float(rows["seats_offered"].sum()), "private_seats_in_window_per_day": float(rows["private_seats"].sum()),
                      "private_market_proxy_demand_per_day": proxy, "summed_gap_count_per_average_day": total_gap,
                      "private_departure_times": pr_hours, "private_bus_types_by_seats": {k: float(v) for k, v in seat_by_type.items()}},
          **_route_facts(summary, scores, str(route["route_id"]))}
    return {
        "priority": _priority(total_gap), "category": "add_service_corridor_slot",
        "title": f"Add {scen['additional_departures']} {bus.replace('_', ' ')} departure(s) on {cor} {window}",
        "route_id": str(route["route_id"]), "location_id": rows.iloc[0]["location_id"], "time_window": window, "day_type": peak,
        "corridor": cor, "direction": "outbound",
        "action": (f"State timetable has no seats on {cor} in {window}; private operators run {int(rows['private_departures'].sum())} departures "
                   f"there (about {proxy:.0f} passengers/day at the assumed {config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION:.0%} occupancy). "
                   f"Pilot {scen['additional_departures']} {bus.replace('_', ' ')} departure(s) via {route['route_id']}; assumes the state captures "
                   f"{config.STATE_CAPTURE_SHARE:.0%} of that market. Illustrative service scenario."),
        "evidence_json": jdump(ev),
        "assumptions_json": jdump({"private_occupancy_assumption": config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION,
                                   "state_capture_share_assumption": config.STATE_CAPTURE_SHARE, "target_load_factor": tlf,
                                   "fare_per_passenger_inr": fare, "fare_basis": "full-route fare from constants.FARE_TABLE (illustrative demo tariff)",
                                   "bus_type_choice": "state bus type matching the most private seats in the window",
                                   "private_market": "synthetic competitor services; proxy demand is an assumption, not observed",
                                   "note": config.SIMULATION_BADGE_TEXT}),
        "expected_impact_json": jdump({**scen, "demand_is_lower_bound": True}),
        "constraints_json": jdump(_STD_CONSTRAINTS + ["private-market demand is a proxy (assumed occupancy), not observed",
                                                      "capture share of the private market is an assumption"]),
        "_gap": total_gap,
    }


def _capacity_rec(rid, direction, rows, h0, h1, rt, summary, scores, tlf) -> dict[str, Any]:
    r = rt.loc[rid]
    window = hour_window(h0, h1)
    dts = sorted(rows["day_type"].unique())
    per_dt = rows.groupby("day_type").agg(d=("demand_estimate", "sum"), t=("trips_per_day", "sum"), s=("seats_offered", "sum"))
    worst = per_dt.sort_values("d", ascending=False).iloc[0]
    seats_per_bus = float(worst["s"] / worst["t"])
    fare = full_route_fare_inr(r["bus_type"], float(r["length_km"]))
    scen = service_frequency_scenario(float(worst["d"]), seats_per_bus, tlf, int(round(worst["t"])), float(r["length_km"]),
                                      _cost_per_km(r["bus_type"]), fare_per_passenger=None)
    scen["incremental_revenue_note"] = ("not estimated: demand above the seat cap is censored (never ticketed), so the "
                                        "passengers an extra departure would carry are not observable")
    total_gap = _window_gap(rows)
    top = rows.sort_values("gap_index", ascending=False).iloc[0]
    ev = {"table": "hourly_demand_supply",
          "filter": {"level": "route_direction", "route_id": rid, "direction": direction, "status": STATUS_AT_CAPACITY,
                     "day_types": dts, "hours": f"{h0}-{h1}"},
          "gap_rows": _rows(rows),
          "figures": {"max_gap_index": float(rows["gap_index"].max()), "demand_estimate_is_lower_bound": True},
          **_route_facts(summary, scores, rid)}
    return {
        "priority": "Medium", "category": "add_capacity_weekend",
        "title": f"Add capacity on {rid} {direction} {window} ({'/'.join(dts)})",
        "route_id": rid, "location_id": top["location_id"], "time_window": window, "day_type": "+".join(dts),
        "corridor": r["corridor"], "direction": direction,
        "action": (f"{rid} {direction} departures in {window} run at their seat cap on {', '.join(dts)} days (peak load factor "
                   f"{float(rows['gap_index'].max()):.2f}); ticketed demand is censored at seats, so true demand is higher. "
                   f"Add about {scen['additional_departures']} departure(s) on those days. Illustrative service scenario."),
        "evidence_json": jdump(ev),
        "assumptions_json": jdump({"target_load_factor": tlf, "demand_basis": "critical-link load = seats (censored at cap); lower bound",
                                   "fare_per_passenger_inr": fare, "note": config.SIMULATION_BADGE_TEXT}),
        "expected_impact_json": jdump({**scen, "demand_is_lower_bound": True}),
        "constraints_json": jdump(_STD_CONSTRAINTS),
        "_gap": total_gap,
    }


def _protect_rec(rid, rt, summary, scores, hourly) -> dict[str, Any]:
    r = rt.loc[rid]
    facts = _route_facts(summary, scores, rid)
    s = summary[summary["route_id"] == rid].iloc[0]
    ev = {"table": "route_summary", "filter": {"route_id": rid}, **facts,
          "figures": {"load_factor_pct": None if pd.isna(s["load_factor_pct"]) else float(s["load_factor_pct"]),
                      "avg_boardings_per_day": None if pd.isna(s["avg_boardings_per_day"]) else float(s["avg_boardings_per_day"]),
                      "contribution_per_day_inr": None if pd.isna(s["contribution_per_day_inr"]) else float(s["contribution_per_day_inr"]),
                      "minimum_service": True}}
    return {
        "priority": "Medium", "category": "protect_minimum_service",
        "title": f"Protect minimum service on {rid}: retain and review timetable",
        "route_id": rid, "location_id": rt.loc[rid, "origin_stop_id"], "time_window": "all service hours", "day_type": "all",
        "corridor": r["corridor"], "direction": "both",
        "action": (f"Retain {rid} as an essential minimum-service route even though its commercial indicators are low "
                   f"(load factor {s['load_factor_pct']:.0f}%, contribution {s['contribution_per_day_inr']:.0f} INR/day). "
                   f"Review the timetable (departure times against local demand) rather than withdrawing service."),
        "evidence_json": jdump(ev),
        "assumptions_json": jdump({"policy": "minimum_service routes are protected regardless of commercial score",
                                   "note": config.SIMULATION_BADGE_TEXT}),
        "expected_impact_json": jdump({"service_retained": True, "label": "illustrative; cost of protection shown as contribution",
                                       "contribution_per_day_inr": None if pd.isna(s["contribution_per_day_inr"]) else float(s["contribution_per_day_inr"])}),
        "constraints_json": jdump(["social-service obligation: low commercial score is NOT a removal criterion",
                                   "contribution excludes overheads; not profit"]),
        "_gap": 0.0,
    }
