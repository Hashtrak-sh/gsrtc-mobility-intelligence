"""Presentation-support queries over the processed tables (pure pandas; no Streamlit, no I/O).

Everything here is a deterministic transformation of ``route_summary``, ``hourly_demand_supply``, ``od_flows``,
``stop_occupancy`` and ``route_kpis``; the dashboard pages only call these and render. Route KPIs always come from
``route_summary`` (single source of truth) so Overview, Route Intelligence, recommendations and exports agree.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

import config
from modules.analytics import gaps as G

NAN = float("nan")


# ---------------------------------------------------------------------------
# Route KPIs (route_summary)
# ---------------------------------------------------------------------------
def scope_kpis(rs: pd.DataFrame) -> dict[str, Any]:
    """Aggregate KPIs over the ``route_summary`` rows in scope (ratios of sums, never averages of percentages)."""
    if rs.empty:
        return {"n_routes": 0, "boardings": 0, "avg_boardings_per_day": NAN, "load_factor_pct": NAN, "reliability_pct": NAN,
                "contribution_per_day_inr": NAN, "revenue_per_passenger_inr": NAN, "epkm_inr": NAN}
    seat_km = rs["seat_km"].sum()
    veh_km = rs["vehicle_km"].sum()
    pax = rs["boardings"].sum()
    rel = rs.dropna(subset=["reliability_pct"])
    return {
        "n_routes": int(len(rs)),
        "boardings": int(pax),
        "avg_boardings_per_day": float(rs["avg_boardings_per_day"].sum()),
        "load_factor_pct": float(rs["estimated_passenger_km"].sum() / seat_km * 100) if seat_km > 0 else NAN,
        "reliability_pct": float((rel["reliability_pct"] * rel["trips"]).sum() / rel["trips"].sum()) if rel["trips"].sum() > 0 else NAN,
        "contribution_per_day_inr": float(rs["contribution_per_day_inr"].sum()),
        "revenue_per_passenger_inr": float(rs["ticket_revenue_inr"].sum() / pax) if pax > 0 else NAN,
        "epkm_inr": float(rs["ticket_revenue_inr"].sum() / veh_km) if veh_km > 0 else NAN,
    }


def route_profile(rs: pd.DataFrame, route_id: str) -> dict[str, Any]:
    """The ``route_summary`` row of one route as a plain dict (raises KeyError if the route is unknown)."""
    r = rs[rs["route_id"] == route_id]
    if r.empty:
        raise KeyError(f"Unknown route {route_id!r}")
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in r.iloc[0].to_dict().items()}


def route_label(route_id: str, name: str) -> str:
    """'L05 - Mavdi - Kotharia - ...' with the trailing '(demo...)' marker kept (synthetic routes)."""
    return f"{route_id} – {name}"


def ranked_scores(scores: pd.DataFrame, rs: pd.DataFrame, route_type: str, corridor_ids: list[str] | None = None) -> pd.DataFrame:
    """Scores joined to route names for one route type, ranked within type (1 = highest score)."""
    s = scores[scores["route_type"] == route_type].merge(rs[["route_id", "name", "corridor", "bus_type"]], on="route_id", how="left")
    if corridor_ids is not None:
        s = s[s["route_id"].isin(corridor_ids)]
    return s.sort_values(["rank_within_type", "route_id"]).reset_index(drop=True)


COMPONENT_COLUMNS = {
    "demand_potential": "demand_score",
    "unmet_demand": "unmet_demand_score",
    "load_factor": "load_factor_score",
    "reliability_gap": "reliability_gap_score",
    "revenue_potential": "revenue_potential_score",
    "social_importance": "social_importance_score",
    "feasibility": "feasibility_score",
}
COMPONENT_LABELS = {
    "demand_potential": "Demand potential", "unmet_demand": "Unmet demand", "load_factor": "Load factor",
    "reliability_gap": "Reliability gap", "revenue_potential": "Revenue potential",
    "social_importance": "Social importance", "feasibility": "Feasibility",
}


def score_weights(scores: pd.DataFrame) -> dict[str, float]:
    """Component weights as stored with the scores (``weights_json`` of the first row); falls back to config."""
    if not scores.empty:
        try:
            w = json.loads(scores["weights_json"].iloc[0])
            return {comp: float(w[col]) for comp, col in COMPONENT_COLUMNS.items()}
        except (KeyError, ValueError, TypeError):
            pass
    return config.ROUTE_SCORE_WEIGHTS.components()


def weighted_components(ranked: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Long frame (route_id, component, weight, score, points) where points = weight x score (sum = total score)."""
    rows = []
    for _, r in ranked.iterrows():
        for comp, col in COMPONENT_COLUMNS.items():
            sc = r[col]
            rows.append({"route_id": r["route_id"], "component": comp, "label": COMPONENT_LABELS[comp], "weight": weights[comp],
                         "score": sc, "points": (weights[comp] * sc) if pd.notna(sc) else NAN})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Hourly demand-supply
# ---------------------------------------------------------------------------
def route_rows(h: pd.DataFrame) -> pd.DataFrame:
    return h[h["level"] == "route_direction"]


def corridor_rows(h: pd.DataFrame) -> pd.DataFrame:
    return h[h["level"] == "corridor"]


def crowded_route_hours(h: pd.DataFrame) -> pd.DataFrame:
    """Route-direction rows flagged crowded or at capacity, highest gap index first."""
    r = route_rows(h)
    r = r[r["status"].isin([G.STATUS_CROWDED, G.STATUS_AT_CAPACITY])]
    return r.sort_values(["gap_index", "route_id", "hour"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)


def uncovered_windows(h: pd.DataFrame) -> pd.DataFrame:
    """Contiguous runs of corridor hours with no scheduled state seats but private-market proxy demand.

    One row per (corridor, run): ``start_hour`` (inclusive), ``end_hour`` (exclusive), ``private_departures``,
    ``proxy_demand`` (passengers per average day, assumption-based), ``private_seats``.
    """
    c = corridor_rows(h)
    c = c[(c["status"] == G.STATUS_NO_CAPACITY) & (c["private_demand_proxy"].fillna(0) > 0)]
    rows = []
    for corridor, g in c.groupby("corridor"):
        hours = sorted(int(x) for x in g["hour"])
        run: list[int] = []
        for hh in hours + [None]:
            if hh is not None and (not run or hh == run[-1] + 1):
                run.append(hh)
                continue
            if run:
                sel = g[g["hour"].isin(run)]
                rows.append({"corridor": corridor, "start_hour": run[0], "end_hour": run[-1] + 1,
                             "private_departures": float(sel["private_departures"].sum()),
                             "private_seats": float(sel["private_seats"].sum()),
                             "proxy_demand": float(sel["private_demand_proxy"].sum())})
            run = [hh] if hh is not None else []
    cols = ["corridor", "start_hour", "end_hour", "private_departures", "private_seats", "proxy_demand"]
    return pd.DataFrame(rows, columns=cols).sort_values("proxy_demand", ascending=False, kind="mergesort").reset_index(drop=True)


def _runs(hours: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for hh in sorted(set(int(x) for x in hours)):
        if out and out[-1][-1] == hh - 1:
            out[-1].append(hh)
        else:
            out.append([hh])
    return out


def gap_windows(h: pd.DataFrame) -> pd.DataFrame:
    """Contiguous runs of crowded / at-capacity hours per route and direction (the unit a service change is sized on).

    Columns: route_id, direction, start_hour, end_hour (exclusive), demand, seats, existing_departures (per average day),
    max_gap_index, status (``crowded`` if any hour is crowded, else ``at_capacity``), location_id (fullest stop of the worst hour).
    ``demand`` is the summed critical-link load and a lower bound (ticketed demand is censored at capacity).
    """
    r = crowded_route_hours(h)
    rows = []
    for (rid, d), g in r.groupby(["route_id", "direction"]):
        for run in _runs(list(g["hour"])):
            sel = g[g["hour"].isin(run)]
            worst = sel.sort_values("gap_index", ascending=False).iloc[0]
            rows.append({"route_id": rid, "direction": d, "start_hour": run[0], "end_hour": run[-1] + 1,
                         "demand": float(sel["demand_estimate"].sum()), "seats": float(sel["seats_offered"].sum()),
                         "existing_departures": float(sel["trips_per_day"].sum()), "max_gap_index": float(sel["gap_index"].max()),
                         "status": G.STATUS_CROWDED if (sel["status"] == G.STATUS_CROWDED).any() else G.STATUS_AT_CAPACITY,
                         "location_id": worst["location_id"]})
    cols = ["route_id", "direction", "start_hour", "end_hour", "demand", "seats", "existing_departures", "max_gap_index", "status", "location_id"]
    return pd.DataFrame(rows, columns=cols).sort_values(["max_gap_index", "route_id", "start_hour"], ascending=[False, True, True],
                                                        kind="mergesort").reset_index(drop=True)


def matching_recommendation(recs: pd.DataFrame, *, route_id: str | None = None, direction: str | None = None, corridor: str | None = None,
                            start_hour: int, end_hour: int) -> pd.Series | None:
    """The recommendation whose ``HH:00-HH:00`` window overlaps [start_hour, end_hour) for the route (or corridor slot), else None."""
    for _, rec in recs.sort_values("priority_rank").iterrows():
        tw = str(rec["time_window"])
        if "-" not in tw or not tw[:2].isdigit():
            continue
        lo, hi = int(tw[:2]), int(tw.split("-")[1][:2])
        if not (lo < end_hour and start_hour < hi):
            continue
        if corridor is not None:
            if rec["category"] == "add_service_corridor_slot" and rec["corridor"] == corridor:
                return rec
        elif rec["category"] != "add_service_corridor_slot" and rec["route_id"] == route_id and (direction is None or rec["direction"] == direction):
            return rec
    return None


def gap_summary(h: pd.DataFrame) -> dict[str, Any]:
    """KPIs for the Gaps page from already-filtered hourly rows."""
    crowded = crowded_route_hours(h)
    unc = uncovered_windows(h)
    c = corridor_rows(h)
    unc_hours = c[(c["status"] == G.STATUS_NO_CAPACITY) & (c["private_demand_proxy"].fillna(0) > 0)]
    return {
        "crowded_route_hours": int(len(crowded)),
        "max_gap_index": float(crowded["gap_index"].max()) if len(crowded) else NAN,
        "uncovered_corridor_hours": int(len(unc_hours)),
        "uncovered_windows": int(len(unc)),
        "uncovered_proxy_demand": float(unc_hours["private_demand_proxy"].sum()),
    }


def hour_grid(h: pd.DataFrame, stop_name: dict[str, str], route_name: dict[str, str]) -> pd.DataFrame:
    """Heat-map frame: one row per 'location' (intercity corridor, or route + direction) and hour, with hover text.

    Columns: ``row_label``, ``order`` (corridors first), ``hour``, ``gap_index`` (NaN where no scheduled capacity), ``status``,
    ``demand``, ``seats``, ``hover``. Corridor rows compare market demand (state + private-operator proxy) with STATE seats;
    route rows compare ticketed critical-link load with seats (a lower bound). Hours outside a route's service span have no
    row at all (rendered blank, distinct from 'no scheduled capacity').
    """
    cols = ["row_label", "order", "route_id", "direction", "hour", "gap_index", "status", "demand", "seats", "hover"]
    if h.empty:
        return pd.DataFrame(columns=cols)
    status_txt = {G.STATUS_NO_CAPACITY: "No scheduled state capacity", G.STATUS_CROWDED: "Crowded",
                  G.STATUS_AT_CAPACITY: "At seat capacity", G.STATUS_OK: "OK"}
    hour_txt = h["hour"].map(lambda x: f"{int(x):02d}:00")
    out = h.copy()
    is_c = out["level"] == "corridor"
    out["row_label"] = np.where(is_c, out["corridor"].astype(str) + " corridor", out["route_id"].astype(str) + " " + out["direction"].astype(str))
    out["order"] = np.where(is_c, 0, 1)
    full = out["route_id"].map(route_name).fillna(out["route_id"].astype(str))
    crit = out["location_id"].map(stop_name)
    st_txt = out["status"].map(status_txt)
    route_hover = (full + "<br>" + out["direction"].astype(str) + " departures at " + hour_txt + "<br>" + st_txt
                   + np.where(crit.notna(), "<br>Fullest point: " + crit.fillna(""), ""))
    corr_hover = (out["corridor"].astype(str) + " corridor, departures from the origin terminal at " + hour_txt + "<br>" + st_txt
                  + "<br>State seats: " + out["seats_offered"].map(lambda v: f"{v:,.0f}")
                  + "<br>Private seats (synthetic): " + out["private_seats"].map(lambda v: "n/a" if pd.isna(v) else f"{v:,.0f}")
                  + "<br>Private-market proxy demand: " + out["private_demand_proxy"].map(lambda v: "n/a" if pd.isna(v) else f"{v:,.0f}"))
    out["hover"] = np.where(is_c, corr_hover, route_hover)
    out = out.rename(columns={"demand_estimate": "demand", "seats_offered": "seats"})
    return out[cols]


def corridor_hour_frame(h: pd.DataFrame, corridor: str) -> pd.DataFrame:
    """Corridor-hour supply: state seats vs private seats and the proxy demand, with a no-capacity flag."""
    c = corridor_rows(h)
    c = c[c["corridor"] == corridor].sort_values("hour")
    out = pd.DataFrame({
        "hour": c["hour"].astype(int), "state_seats": c["seats_offered"], "private_seats": c["private_seats"],
        "state_demand": c["state_demand"], "private_demand_proxy": c["private_demand_proxy"],
        "private_departures": c["private_departures"], "status": c["status"],
    })
    out["no_state_capacity"] = out["status"] == G.STATUS_NO_CAPACITY
    return out.reset_index(drop=True)


def demand_vs_seats_by_hour(h: pd.DataFrame) -> pd.DataFrame:
    """Average-day demand estimate and state seats summed by hour over route-direction rows (rows with demand only)."""
    r = route_rows(h)
    r = r[r["status"] != G.STATUS_NO_CAPACITY]
    g = r.groupby("hour").agg(demand=("demand_estimate", "sum"), seats=("seats_offered", "sum")).reset_index()
    return g


def recommendation_window_matches(rec: pd.Series, hour: int, route_id: str | None, corridor: str | None) -> bool:
    """True if a recommendation covers the given route-hour (or corridor-hour) by its ``HH:00-HH:00`` window."""
    tw = str(rec["time_window"])
    if "-" not in tw or not tw[:2].isdigit():
        return False
    lo, hi = int(tw[:2]), int(tw.split("-")[1][:2])
    if not lo <= hour < hi:
        return False
    if corridor and rec.get("corridor") == corridor and rec.get("category") == "add_service_corridor_slot":
        return True
    return route_id is not None and rec.get("route_id") == route_id and rec.get("category") != "add_service_corridor_slot"


def window_from_rows(rows: list[dict]) -> str:
    """``HH:00-HH:00`` text from evidence ``gap_rows`` (min hour .. max hour + 1); mirrors the recommendation builder."""
    hs = [int(r["hour"]) for r in rows]
    return f"{min(hs):02d}:00-{max(hs) + 1:02d}:00"


# ---------------------------------------------------------------------------
# Stop occupancy
# ---------------------------------------------------------------------------
def occupancy_progression(so: pd.DataFrame, route_id: str, direction: str, hour: int | None = None) -> pd.DataFrame:
    """Mean onboard load by stop position for one route/direction (trip-weighted over the hours present, or one ``hour``).

    ``avg_onboard`` is per bus on the link leaving the stop; ``seats`` is the mean seats per trip.
    """
    s = so[(so["route_id"] == route_id) & (so["direction"] == direction)]
    if hour is not None:
        s = s[s["hour"] == hour]
    if s.empty:
        return pd.DataFrame(columns=["position", "stop_id", "avg_onboard", "seats", "onboard_pct", "n_trips"])
    s = s.assign(w=s["n_trips"].astype(float))
    g = s.groupby(["position", "stop_id"]).apply(
        lambda d: pd.Series({"avg_onboard": float(np.average(d["avg_onboard"], weights=d["w"])),
                             "seats": float(np.average(d["seats"], weights=d["w"])), "n_trips": int(d["n_trips"].sum()),
                             "max_onboard": float(d["max_onboard"].max())}), include_groups=False).reset_index()
    g["onboard_pct"] = g["avg_onboard"] / g["seats"] * 100
    return g.sort_values("position").reset_index(drop=True)


# ---------------------------------------------------------------------------
# O-D
# ---------------------------------------------------------------------------
def od_pairs(od: pd.DataFrame, top: int = 10, include_intra_zone: bool = True) -> pd.DataFrame:
    """Top pairs by average-day passengers over the (already filtered) rows."""
    o = od if include_intra_zone else od[~od["is_intra_zone"]]
    g = o.groupby(["origin_zone_id", "dest_zone_id"], dropna=False).agg(
        passengers_per_day=("passenger_count", "sum"), passengers_total=("passengers_total", "sum"),
        passenger_km_per_day=("estimated_passenger_km", "sum")).reset_index()
    return g.sort_values(["passengers_total", "origin_zone_id", "dest_zone_id"], ascending=[False, True, True],
                         kind="mergesort").head(top).reset_index(drop=True)


def od_matrix(od: pd.DataFrame, max_zones: int = 22) -> pd.DataFrame:
    """Origin x destination matrix of average-day passengers (zones sorted by total flow, at most ``max_zones``)."""
    if od.empty:
        return pd.DataFrame()
    m = od.pivot_table(index="origin_zone_id", columns="dest_zone_id", values="passenger_count", aggfunc="sum", fill_value=0.0)
    tot = m.sum(axis=1).add(m.sum(axis=0), fill_value=0).sort_values(ascending=False)
    zones = list(tot.index[:max_zones])
    return m.reindex(index=zones, columns=zones, fill_value=0.0)


def directional_profile(od: pd.DataFrame, zone_type: dict[str, str]) -> pd.DataFrame:
    """Passengers per average day by boarding hour split by commute direction (relative to employment-type zones)."""
    o = od.copy()
    ot = o["origin_zone_id"].map(zone_type)
    dt = o["dest_zone_id"].map(zone_type)
    o["flow"] = np.where((dt == "employment") & (ot != "employment"), "Towards employment zones",
                         np.where((ot == "employment") & (dt != "employment"), "From employment zones", "Other movements"))
    return o.groupby(["hour", "flow"])["passenger_count"].sum().reset_index()


def chart_label(route_id: str, name: str, width: int = 38) -> str:
    """Compact axis label: 'L05 Mavdi - Kotharia - Aji GIDC Indus...' (the '(demo...)' marker is dropped for space)."""
    i = name.rfind(" (demo")
    base = name[:i] if i > 0 else name
    base = base if len(base) <= width else base[: width - 1].rstrip() + "…"
    return f"{route_id} {base}"
