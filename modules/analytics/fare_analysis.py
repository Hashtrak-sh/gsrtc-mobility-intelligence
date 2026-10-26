"""Fare analysis for the intercity corridors: time bands, break-even, differential fares, private comparison, fare band, what-if.

Simulated data for demonstration. Cost parameters are illustrative (see ``modules/analytics/cost_model.py``); elasticities and
fare rules are scenario assumptions, not fitted facts. "Contribution" = ticket revenue - TRIP OPERATING cost (not profit);
"full-cost margin" = ticket revenue - FULL cost (trip operating + fixed/overhead layer); still ticket revenue only (no subsidy).

Definitions (all from ``trips`` + ``tickets`` via the route_kpis pipeline; ratios are ratios of sums)
------------------------------------------------------------------------------------------------------
* passengers = sum(passenger_count); revenue = sum(ticket fare_inr) (actual, incl. concessions).
* load_factor = passenger-km / seat-km (seat-km = seats x route length_km per trip) - identical to ``route_kpis.load_factor_pct`` / 100.
* avg_fare_per_passenger = revenue / passengers; avg_trip_km = passenger-km / passengers;
  trip_length_share = avg_trip_km / route length_km; yield = revenue / passenger-km (INR per passenger-km).
* Revenue per trip = load_factor x seats x length_km x yield.
* Break-even load factor (cost per trip C):  BE_LF = C / (seats x length_km x yield)
  = C / (seats x avg_fare_per_passenger / trip_length_share).  At LF = BE_LF (same yield) revenue = C.
  Computed for both cost layers (``_trip`` = trip operating cost, ``_full`` = full cost). BE_LF > 1 means the class cannot
  break even even full, at this yield.
* Break-even fare per passenger at the current load:  C / passengers_per_trip (average realised fare, concessions included).
  At target load factor T: passengers_per_trip_T = T x seats / trip_length_share, fare = C / passengers_per_trip_T.
* ``be_adult_fare_target_*`` = full-route ADULT fare (comparable with the fare table and private fares) that would break even at
  the target load factor, assuming today's concession mix and trip-length mix: ``state_fare_full_length x (yield_T / yield)`` with
  ``yield_T = C / (T x seats x length_km)``.
* Peak/normal bands: see :func:`classify_time_bands` (derived from data, never hard-coded windows).
* Trip operating cost per trip for the timetable classes = cost_model rate (== ``constants.OPERATING_COST_PER_KM_INR``) x length_km
  (class rate, not route-specific speed), so it reconciles exactly with ``trips.operating_cost_inr`` at default parameters.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

import config
from modules.analytics import cost_model as cm
from modules.analytics.common import safe_div
from modules.analytics.scenarios import pricing_scenario
from modules.data_gen import constants as C

WHAT_IF_LABEL = "WHAT-IF (illustrative): not a forecast; cost parameters and elasticities are assumptions"
DEFAULT_PEAK_QUANTILE = 0.75
DEFAULT_PEAK_ELASTICITY = -0.3
DEFAULT_NORMAL_ELASTICITY = -0.7
BANDS = ("peak", "normal")

# Class -> competitor_services.bus_type used as the private comparator.
PRIVATE_TYPE_MAP: dict[str, str] = {
    "ordinary": "ordinary", "express": "ordinary", "AC_seater": "AC_seater", "AC_sleeper": "AC_sleeper",
    "volvo_ac": "premium", "non_ac_sleeper": "AC_sleeper", "e_bus": "AC_seater",
}
PRIVATE_TYPE_NOTE: dict[str, str] = {
    "ordinary": "private ordinary", "express": "private ordinary (no private express type; nearest available)",
    "AC_seater": "private AC seater", "AC_sleeper": "private AC sleeper", "volvo_ac": "private premium",
    "non_ac_sleeper": "private AC sleeper (no private non-AC sleeper type; nearest available, likely an over-estimate)",
    "e_bus": "private AC seater",
}


# ------------------------------------------------------------------ inputs
def load_inputs(base_dir=None, gp: cm.GlobalParams | None = None) -> dict[str, Any]:
    """Helper (file I/O). Returns ``tm`` (intercity trip metrics with ``corridor``/``band``), ``bands`` (hour table),
    ``routes``, ``competitors``, ``trips``, ``model`` (:class:`cost_model.CostModel`) and ``n_days`` (service dates per day type).

    Trip metrics are built with the same functions as ``modules.analytics.run`` (route_kpis definitions).
    """
    from modules.analytics import occupancy, route_kpis
    from modules.data import io

    names = ("trips", "tickets", "route_stops", "routes", "competitor_services")
    t = {n: io.read_table(n, "synthetic", base_dir) for n in names}
    legs = occupancy.ticket_legs(t["trips"], t["tickets"], t["route_stops"])
    profile = occupancy.trip_stop_profile(t["trips"], legs, t["route_stops"])
    ts = occupancy.trip_summary(t["trips"], t["tickets"], profile, t["routes"])
    tm_all = route_kpis.trip_metrics(ts, legs)
    n_days = tm_all.groupby("day_type")["service_date"].nunique()
    bands = classify_time_bands(tm_all, t["routes"])
    tm = assign_bands(tm_all, bands, t["routes"])
    model = cm.build_cost_model(t["trips"], t["routes"], gp)
    return {"tm": tm, "bands": bands, "routes": t["routes"], "competitors": t["competitor_services"], "trips": t["trips"],
            "model": model, "n_days": n_days}


# ------------------------------------------------------------------ time bands
def classify_time_bands(tm: pd.DataFrame, routes: pd.DataFrame, peak_quantile: float = DEFAULT_PEAK_QUANTILE) -> pd.DataFrame:
    """Peak / normal departure hours per intercity corridor x day type, derived from the data.

    Rule (parameter ``peak_quantile``, default 0.75): for each corridor x day type, take every departure clock hour with at
    least one trip ("served hours"); its load factor = sum(passenger-km) / sum(seat-km) over all trips of the corridor
    (all routes/classes, both directions) departing in that hour, over all service dates of the day type. An hour is
    ``peak`` when its load factor >= the ``peak_quantile`` quantile of the corridor-day-type's served-hour load factors AND
    is strictly above the minimum (so never every hour). Otherwise ``normal``. Load factor (not capped critical-link load)
    is used because it is not saturated at 100 % and so ranks hours without ties. A corridor-day-type with < 2 served hours
    has no peak.

    Columns: ``corridor, day_type, dep_hour, trips, boardings, passenger_km, seat_km, load_factor, threshold, band, rule``.
    """
    if not 0.0 < peak_quantile < 1.0:
        raise ValueError("peak_quantile must be in (0, 1)")
    t = tm.merge(routes[["route_id", "corridor"]], on="route_id", how="left", suffixes=("", "_r"))
    corr = "corridor_r" if "corridor_r" in t.columns else "corridor"
    t = t[t[corr].notna()]
    g = t.groupby([corr, "day_type", "dep_hour"]).agg(
        trips=("trip_id", "count"), boardings=("boardings", "sum"), passenger_km=("estimated_passenger_km", "sum"),
        seat_km=("seat_km", "sum")).reset_index().rename(columns={corr: "corridor"})
    g["dep_hour"] = g["dep_hour"].astype(int)
    g["load_factor"] = safe_div(g["passenger_km"], g["seat_km"])
    thr = g.groupby(["corridor", "day_type"])["load_factor"].transform(lambda s: s.quantile(peak_quantile))
    mn = g.groupby(["corridor", "day_type"])["load_factor"].transform("min")
    nh = g.groupby(["corridor", "day_type"])["dep_hour"].transform("count")
    g["threshold"] = thr
    g["band"] = np.where((g["load_factor"] >= thr) & (g["load_factor"] > mn) & (nh >= 2), "peak", "normal")
    g["rule"] = f"peak = departure-hour load factor >= {peak_quantile:.0%} quantile of the corridor-day-type's served hours (and > minimum)"
    return g.sort_values(["corridor", "day_type", "dep_hour"], kind="mergesort").reset_index(drop=True)


def assign_bands(tm: pd.DataFrame, bands: pd.DataFrame, routes: pd.DataFrame) -> pd.DataFrame:
    """Intercity rows of ``tm`` with ``corridor`` and ``band`` (from :func:`classify_time_bands`) attached."""
    t = tm.drop(columns=[c for c in ("corridor", "band") if c in tm.columns]).merge(
        routes[["route_id", "corridor"]], on="route_id", how="left")
    t = t[t["corridor"].notna()].copy()
    t["dep_hour"] = t["dep_hour"].astype(int)
    t = t.merge(bands[["corridor", "day_type", "dep_hour", "band"]], on=["corridor", "day_type", "dep_hour"], how="left")
    return t


# ------------------------------------------------------------------ band economics
def band_economics(tm_b: pd.DataFrame, model: cm.CostModel, routes: pd.DataFrame, *,
                   target_load_factor: float = config.SERVICE_TARGET_LOAD_FACTOR) -> pd.DataFrame:
    """Per route (= class) x day type x band economics (see module docstring for definitions).

    Columns: identity (``route_id, corridor, bus_class, day_type, band``), ``n_days, trips, trips_per_day, passengers,
    passengers_per_day, passenger_km, seat_km, vehicle_km, seats, length_km, revenue_inr, avg_fare_per_passenger_inr,
    avg_trip_km, trip_length_share, yield_inr_per_pax_km, load_factor, load_factor_pct, revenue_per_trip_inr,
    trip_operating_cost_per_trip_inr, full_cost_per_trip_inr, trip_operating_cost_inr, full_cost_inr, operating_cost_data_inr,
    contribution_per_trip_inr, full_cost_margin_per_trip_inr, contribution_per_seat_km_inr, full_cost_margin_per_seat_km_inr,
    state_fare_full_length_inr, be_load_factor_trip, be_load_factor_full, be_fare_current_lf_trip_inr,
    be_fare_current_lf_full_inr, be_fare_target_lf_trip_inr, be_fare_target_lf_full_inr, be_adult_fare_target_trip_inr,
    be_adult_fare_target_full_inr, target_load_factor``. ``*_inr`` sums are totals over the whole data period.
    """
    nd = tm_b.groupby("day_type")["service_date"].nunique()
    r = routes.set_index("route_id")
    g = tm_b.groupby(["route_id", "day_type", "band"]).agg(
        corridor=("corridor", "first"), bus_class=("bus_type", "first"), trips=("trip_id", "count"),
        passengers=("boardings", "sum"), passenger_km=("estimated_passenger_km", "sum"), seat_km=("seat_km", "sum"),
        vehicle_km=("vehicle_km", "sum"), seats=("seats", "mean"), revenue_inr=("ticket_revenue_inr", "sum"),
        operating_cost_data_inr=("operating_cost_inr", "sum")).reset_index()
    g["length_km"] = g["route_id"].map(r["length_km"]).astype(float)
    g["n_days"] = g["day_type"].map(nd).astype(float)
    g["trips_per_day"] = g["trips"] / g["n_days"]
    g["passengers_per_day"] = g["passengers"] / g["n_days"]
    g["load_factor"] = safe_div(g["passenger_km"], g["seat_km"])
    g["load_factor_pct"] = g["load_factor"] * 100.0
    g["avg_fare_per_passenger_inr"] = safe_div(g["revenue_inr"], g["passengers"])
    g["avg_trip_km"] = safe_div(g["passenger_km"], g["passengers"])
    g["trip_length_share"] = g["avg_trip_km"] / g["length_km"]
    g["yield_inr_per_pax_km"] = safe_div(g["revenue_inr"], g["passenger_km"])
    g["revenue_per_trip_inr"] = g["revenue_inr"] / g["trips"]

    tc_op, tc_full = [], []
    for row in g.itertuples():
        c = cm.trip_costs(model, row.bus_class, row.length_km, corridor=row.corridor, peak=(row.band == "peak"))
        tc_op.append(c["trip_operating_cost_inr"])
        tc_full.append(c["full_cost_inr"])
    g["trip_operating_cost_per_trip_inr"] = tc_op
    g["full_cost_per_trip_inr"] = tc_full
    g["trip_operating_cost_inr"] = g["trip_operating_cost_per_trip_inr"] * g["trips"]
    g["full_cost_inr"] = g["full_cost_per_trip_inr"] * g["trips"]
    g["contribution_per_trip_inr"] = g["revenue_per_trip_inr"] - g["trip_operating_cost_per_trip_inr"]
    g["full_cost_margin_per_trip_inr"] = g["revenue_per_trip_inr"] - g["full_cost_per_trip_inr"]
    seat_km_trip = g["seat_km"] / g["trips"]
    g["contribution_per_seat_km_inr"] = g["contribution_per_trip_inr"] / seat_km_trip
    g["full_cost_margin_per_seat_km_inr"] = g["full_cost_margin_per_trip_inr"] / seat_km_trip

    g["state_fare_full_length_inr"] = [cm.fare_per_passenger(model, b, l) for b, l in zip(g["bus_class"], g["length_km"])]
    cap_pk = g["seats"] * g["length_km"]
    pax_per_trip = g["passengers"] / g["trips"]
    pax_per_trip_t = target_load_factor * g["seats"] / g["trip_length_share"]
    for tag, col in (("trip", "trip_operating_cost_per_trip_inr"), ("full", "full_cost_per_trip_inr")):
        g[f"be_load_factor_{tag}"] = safe_div(g[col], cap_pk * g["yield_inr_per_pax_km"])
        g[f"be_fare_current_lf_{tag}_inr"] = safe_div(g[col], pax_per_trip)
        g[f"be_fare_target_lf_{tag}_inr"] = safe_div(g[col], pax_per_trip_t)
        yield_t = g[col] / (target_load_factor * cap_pk)
        g[f"be_adult_fare_target_{tag}_inr"] = g["state_fare_full_length_inr"] * safe_div(yield_t, g["yield_inr_per_pax_km"])
    g["target_load_factor"] = target_load_factor
    g["band"] = pd.Categorical(g["band"], categories=list(BANDS) + [b for b in g["band"].unique() if b not in BANDS], ordered=True)
    g = g.sort_values(["route_id", "day_type", "band"], kind="mergesort")
    g["band"] = g["band"].astype(str)
    return g.reset_index(drop=True)


# ------------------------------------------------------------------ private comparison
def private_fare_table(competitors: pd.DataFrame) -> pd.DataFrame:
    """Median private fares: ``corridor, day_type, private_bus_type, base_fare_median_inr, surge_fare_median_inr, n_services``."""
    g = competitors.groupby(["route_pair", "day_type", "bus_type"]).agg(
        base_fare_median_inr=("base_fare_inr", "median"), surge_fare_median_inr=("surge_fare_inr", "median"),
        n_services=("service_id", "count")).reset_index()
    return g.rename(columns={"route_pair": "corridor", "bus_type": "private_bus_type"})


def private_comparison(econ: pd.DataFrame, competitors: pd.DataFrame) -> pd.DataFrame:
    """Adds the private comparator to ``band_economics`` rows.

    Comparator = median private ``base_fare_inr`` for the normal band and median ``surge_fare_inr`` for the peak band, for the
    corridor x day type x mapped private bus type (``PRIVATE_TYPE_MAP``). A missing comparator stays NaN (shown as missing).
    Added columns: ``private_bus_type, private_comparator_inr, private_n_services, private_note, fare_index_vs_private``
    (state full-route adult fare / comparator; > 1 = state dearer), ``fare_gap_vs_private_inr`` (state - comparator).
    """
    pf = private_fare_table(competitors)
    e = econ.copy()
    e["private_bus_type"] = e["bus_class"].map(PRIVATE_TYPE_MAP)
    e = e.merge(pf, on=["corridor", "day_type", "private_bus_type"], how="left")
    peak = e["band"].eq("peak")
    e["private_comparator_inr"] = np.where(peak, e["surge_fare_median_inr"], e["base_fare_median_inr"])
    e["private_n_services"] = e["n_services"]
    e["private_note"] = e["bus_class"].map(PRIVATE_TYPE_NOTE) + np.where(
        e["private_comparator_inr"].isna(), "; NO comparator for this corridor/day type (missing, not estimated)", "")
    e["fare_index_vs_private"] = e["state_fare_full_length_inr"] / e["private_comparator_inr"]
    e["fare_gap_vs_private_inr"] = e["state_fare_full_length_inr"] - e["private_comparator_inr"]
    return e.drop(columns=["base_fare_median_inr", "surge_fare_median_inr", "n_services"])


# ------------------------------------------------------------------ differential fares
def differential_fares(econ: pd.DataFrame, *, peak_change_pct: float = 0.0, normal_change_pct: float = 0.0,
                       peak_elasticity: float = DEFAULT_PEAK_ELASTICITY, normal_elasticity: float = DEFAULT_NORMAL_ELASTICITY,
                       private_cap_ratio: float | None = None) -> pd.DataFrame:
    """Differential-fare scenario per route x day type x band, per AVERAGE service day.

    Fare change is applied to the average realised fare (concession mix unchanged). Demand = baseline passengers x
    (new/base fare) ** elasticity via ``scenarios.pricing_scenario`` (elasticity in ``config.PRICING_ELASTICITY_RANGE``),
    capped at the seat capacity expressed in passengers at today's trip length:
    ``capacity_passengers_per_day = trips_per_day x seats x length_km / avg_trip_km`` (so baseline load factor = baseline
    passengers / capacity, consistent with passenger-km / seat-km). Service (trips) and costs are unchanged.

    ``private_cap_ratio`` (e.g. 1.0 or ``config.COMPETITION_FARE_POSITION``): a fare INCREASE is limited so the full-route
    state fare does not exceed ratio x private comparator (never forces a cut; ignored where the comparator is missing).
    Needs the columns of :func:`private_comparison` only when a cap is used. Revenue is ticket revenue; contribution =
    revenue - trip operating cost; full-cost margin = revenue - full cost.

    Columns: identity + ``band_change_pct_requested, fare_change_pct_applied, capped, elasticity, baseline_fare_inr,
    new_fare_inr, capacity_passengers_per_day, baseline_*`` / scenario ``passengers_per_day, revenue_per_day_inr,
    load_factor, contribution_per_day_inr, full_cost_margin_per_day_inr``, ``trip_operating_cost_per_day_inr,
    full_cost_per_day_inr, spilled_passengers_per_day, label``.
    """
    rows = []
    for r in econ.itertuples():
        peak = r.band == "peak"
        chg = float(peak_change_pct if peak else normal_change_pct)
        el = float(peak_elasticity if peak else normal_elasticity)
        factor = 1.0 + chg / 100.0
        capped = False
        if private_cap_ratio is not None and chg > 0 and hasattr(r, "private_comparator_inr"):
            comp = r.private_comparator_inr
            if comp == comp and comp > 0 and r.state_fare_full_length_inr > 0:
                max_factor = max(1.0, private_cap_ratio * comp / r.state_fare_full_length_inr)
                if factor > max_factor:
                    factor, capped = max_factor, True
        bd, bf = r.passengers_per_day, r.avg_fare_per_passenger_inr
        cap = r.trips_per_day * r.seats * r.length_km / r.avg_trip_km if r.avg_trip_km and r.avg_trip_km == r.avg_trip_km else float("nan")
        op_day = r.trip_operating_cost_per_trip_inr * r.trips_per_day
        full_day = r.full_cost_per_trip_inr * r.trips_per_day
        base_rev = r.revenue_inr / r.n_days
        row = {"route_id": r.route_id, "corridor": r.corridor, "bus_class": r.bus_class, "day_type": r.day_type, "band": r.band,
               "band_change_pct_requested": chg, "fare_change_pct_applied": (factor - 1.0) * 100.0, "capped": capped,
               "elasticity": el, "baseline_fare_inr": bf, "new_fare_inr": bf * factor if bf == bf else float("nan"),
               "capacity_passengers_per_day": cap, "baseline_passengers_per_day": bd, "baseline_revenue_per_day_inr": base_rev,
               "baseline_load_factor": r.load_factor, "baseline_contribution_per_day_inr": base_rev - op_day,
               "baseline_full_cost_margin_per_day_inr": base_rev - full_day, "trip_operating_cost_per_day_inr": op_day,
               "full_cost_per_day_inr": full_day, "label": WHAT_IF_LABEL}
        if bd > 0 and bf == bf and bf > 0 and cap == cap:
            res = pricing_scenario(bd, bf, bf * factor, el, cap, op_day, fare_bounds=(bf * 1e-6, bf * 1e6))
            served = res["served_demand"]
            # like-for-like with the actual baseline revenue (baseline served == bd because load factor <= 1)
            row.update({"passengers_per_day": served, "revenue_per_day_inr": served * bf * factor,
                        "load_factor": served / cap, "spilled_passengers_per_day": res["spilled_demand"]})
        else:
            row.update({"passengers_per_day": float("nan"), "revenue_per_day_inr": float("nan"), "load_factor": float("nan"),
                        "spilled_passengers_per_day": float("nan")})
        row["contribution_per_day_inr"] = row["revenue_per_day_inr"] - op_day
        row["full_cost_margin_per_day_inr"] = row["revenue_per_day_inr"] - full_day
        rows.append(row)
    return pd.DataFrame(rows)


def differential_totals(scn: pd.DataFrame, by: tuple[str, ...] | list[str] | None = ("route_id", "day_type")) -> pd.DataFrame:
    """Sum the per-band scenario rows (per average day) over bands (and over ``by`` groups; ``by=None`` -> one total row).

    Load factors are recomputed from sums (passengers / capacity). Columns: ``by`` keys, baseline and scenario revenue,
    passengers, load factor, contribution, full-cost margin, and ``revenue_change_per_day_inr`` / ``..._pct``.
    """
    s = scn.copy()
    s["_all"] = "total"
    keys = list(by) if by else ["_all"]
    agg = s.groupby(keys).agg(
        baseline_passengers_per_day=("baseline_passengers_per_day", "sum"), passengers_per_day=("passengers_per_day", "sum"),
        baseline_revenue_per_day_inr=("baseline_revenue_per_day_inr", "sum"), revenue_per_day_inr=("revenue_per_day_inr", "sum"),
        capacity_passengers_per_day=("capacity_passengers_per_day", "sum"),
        trip_operating_cost_per_day_inr=("trip_operating_cost_per_day_inr", "sum"), full_cost_per_day_inr=("full_cost_per_day_inr", "sum"),
    ).reset_index()
    agg["baseline_load_factor"] = agg["baseline_passengers_per_day"] / agg["capacity_passengers_per_day"]
    agg["load_factor"] = agg["passengers_per_day"] / agg["capacity_passengers_per_day"]
    agg["baseline_contribution_per_day_inr"] = agg["baseline_revenue_per_day_inr"] - agg["trip_operating_cost_per_day_inr"]
    agg["contribution_per_day_inr"] = agg["revenue_per_day_inr"] - agg["trip_operating_cost_per_day_inr"]
    agg["baseline_full_cost_margin_per_day_inr"] = agg["baseline_revenue_per_day_inr"] - agg["full_cost_per_day_inr"]
    agg["full_cost_margin_per_day_inr"] = agg["revenue_per_day_inr"] - agg["full_cost_per_day_inr"]
    agg["revenue_change_per_day_inr"] = agg["revenue_per_day_inr"] - agg["baseline_revenue_per_day_inr"]
    agg["revenue_change_pct"] = agg["revenue_change_per_day_inr"] / agg["baseline_revenue_per_day_inr"] * 100.0
    return agg.drop(columns=["_all"], errors="ignore")


# ------------------------------------------------------------------ recommended fare band
def recommend_fare_band(econ_pc: pd.DataFrame, *, competition_position: float = config.COMPETITION_FARE_POSITION) -> pd.DataFrame:
    """Recommended full-route adult fare band per route (class) x corridor x day type x band. Documented rule:

    * ``current_fare_inr`` = state full-route adult fare from the fare table.
    * ``break_even_fare_inr`` = ``be_adult_fare_target_full_inr`` (FULL cost, at the target load factor, today's mix).
    * ``floor_inr = max(current_fare, break_even_fare)`` (the band never recommends a cut below today's tariff).
    * ``cap_inr = competition_position x private comparator`` (normal band: median base fare; peak band: median surge fare).
    * floor <= cap -> band [floor, cap], status ``viable``.
    * floor > cap and break-even <= cap (today's fare already above the cap) -> band [break-even, cap],
      status ``current fare above competitive cap - room to reduce``.
    * break-even > cap -> NO band, status ``not viable on fare alone - needs subsidy / cost reduction``.
    * no comparator -> ``band_low`` = floor, ``band_high`` NaN, status ``no private comparator - floor only``.

    ``econ_pc`` is the output of :func:`private_comparison`. Returns identity columns, the fare numbers, ``band_low_inr,
    band_high_inr, status, viable, evidence, assumptions``. Simulated data; the band is an illustrative decision aid.
    """
    rows = []
    for r in econ_pc.itertuples():
        cur, be, comp = r.state_fare_full_length_inr, r.be_adult_fare_target_full_inr, r.private_comparator_inr
        cap = competition_position * comp if comp == comp else float("nan")
        floor = max(cur, be) if be == be else float("nan")
        lo = hi = float("nan")
        if floor != floor:
            status, viable = "insufficient data (no passengers or revenue)", False
        elif cap != cap:
            lo, status, viable = floor, "no private comparator - floor only", True
        elif floor <= cap:
            lo, hi, status, viable = floor, cap, "viable", True
        elif be <= cap:
            lo, hi, status, viable = be, cap, "current fare above competitive cap - room to reduce", True
        else:
            status, viable = "not viable on fare alone - needs subsidy / cost reduction", False
        ev = (f"load factor {r.load_factor_pct:.0f}%; full cost per trip INR {r.full_cost_per_trip_inr:,.0f}; trip operating cost "
              f"INR {r.trip_operating_cost_per_trip_inr:,.0f}; revenue per trip INR {r.revenue_per_trip_inr:,.0f}; current fare INR {cur:,.0f}; "
              f"break-even fare at {r.target_load_factor:.0%} load INR {be:,.0f}; private comparator "
              + (f"INR {comp:,.0f} ({r.private_note})" if comp == comp else "missing"))
        rows.append({"route_id": r.route_id, "corridor": r.corridor, "bus_class": r.bus_class, "day_type": r.day_type,
                     "band": r.band, "current_fare_inr": cur, "break_even_fare_inr": be, "private_comparator_inr": comp,
                     "cap_inr": cap, "floor_inr": floor, "band_low_inr": lo, "band_high_inr": hi, "status": status,
                     "viable": viable, "evidence": ev,
                     "assumptions": (f"full cost = illustrative cost model (trip operating + fixed/overhead); target load factor "
                                     f"{r.target_load_factor:.0%}; cap = {competition_position:.0%} of private median; concession and "
                                     f"trip-length mix unchanged; ticket revenue only; simulated data")})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ new-class what-if
def new_class_whatif(tm_b: pd.DataFrame, model: cm.CostModel, *, corridor: str, day_type: str, band: str, bus_class: str,
                     elasticity: float = DEFAULT_NORMAL_ELASTICITY, fare_change_pct: float = 0.0,
                     trips_per_day: float | None = None,
                     target_load_factor: float = config.SERVICE_TARGET_LOAD_FACTOR) -> pd.DataFrame:
    """WHAT-IF: run the corridor-day-type-band's existing demand (all incumbent routes) on ``bus_class`` (any of 7 classes).

    Per average day. Steps (L = trip-weighted mean route length of the selection; avg_trip_km, yield from the incumbents):
      1. new fare = class fare-table fare at L x (1 + fare_change_pct/100); incumbent reference fare = trip-weighted mean of
         the incumbents' fare-table fares; ratio = new / incumbent.
      2. demand passengers = baseline passengers x ratio ** elasticity; demand passenger-km = passengers x avg_trip_km.
      3. trips = ``trips_per_day`` if given, else ``ceil(demand_pkm / (seats x L x target_load_factor))``; served passenger-km =
         min(demand, trips x seats x L); load factor = served / (trips x seats x L).
      4. revenue = served passenger-km x incumbent yield x ratio (concession mix unchanged); costs from the cost model at length L
         (class speed; ``intercity_speed_kmph`` override where set) with the band's peak factor.
      5. break-even: ``be_load_factor_full`` = full cost per trip / (seats x L x new yield); ``be_fare_current_lf_full_inr`` =
         full cost / served passengers; ``be_adult_fare_target_full_inr`` = new fare x (yield_T / new yield), yield_T = full cost per
         trip / (target x seats x L).
    With the incumbent class (single-route corridor), no fare change and ``trips_per_day`` = baseline trips per day the result
    reproduces the baseline (within float tolerance); on multi-route corridors lengths/classes are averaged so it is only approximate.

    Returns one row with ``baseline_*`` columns (incumbents as operated, cost model) and ``label`` (WHAT-IF).
    """
    if bus_class not in cm.ALL_CLASSES:
        raise ValueError(f"unknown bus class {bus_class!r}")
    sel = tm_b[(tm_b["corridor"] == corridor) & (tm_b["day_type"] == day_type) & (tm_b["band"] == band)]
    if sel.empty:
        raise ValueError(f"no trips for {corridor} / {day_type} / {band}")
    nd = float(tm_b.loc[tm_b["day_type"] == day_type, "service_date"].nunique())
    trips_d = len(sel) / nd
    pax_d = float(sel["boardings"].sum()) / nd
    pkm_d = float(sel["estimated_passenger_km"].sum()) / nd
    rev_d = float(sel["ticket_revenue_inr"].sum()) / nd
    avg_km = pkm_d / pax_d
    yld = rev_d / pkm_d
    L = float(sel["length_km"].mean())
    peak = band == "peak"
    # incumbents as operated
    inc_fares = np.array([cm.fare_per_passenger(model, b, l) for b, l in zip(sel["bus_type"], sel["length_km"])])
    inc_ref = float(inc_fares.mean())
    base_op = base_full = 0.0
    for (cls, rid), g in sel.groupby(["bus_type", "route_id"]):
        c = cm.trip_costs(model, cls, float(g["length_km"].iloc[0]), corridor=corridor, peak=peak)
        base_op += c["trip_operating_cost_inr"] * len(g) / nd
        base_full += c["full_cost_inr"] * len(g) / nd

    new_fare = cm.fare_per_passenger(model, bus_class, L) * (1.0 + fare_change_pct / 100.0)
    ratio = new_fare / inc_ref
    lo, hi = config.PRICING_ELASTICITY_RANGE
    if not lo <= elasticity <= hi:
        raise ValueError(f"elasticity must be within [{lo}, {hi}]")
    demand_pax = pax_d * ratio ** elasticity
    demand_pkm = demand_pax * avg_km
    seats = model.class_params[bus_class].seats
    trips_needed = int(math.ceil(round(demand_pkm / (seats * L * target_load_factor), 9)))
    trips_used = float(trips_per_day) if trips_per_day is not None else float(trips_needed)
    cap_pkm = trips_used * seats * L
    served_pkm = min(demand_pkm, cap_pkm)
    served_pax = served_pkm / avg_km
    new_yield = yld * ratio
    rev = served_pkm * new_yield
    c = cm.trip_costs(model, bus_class, L, corridor=corridor, peak=peak, speed_kmph=cm.running_speed(model, bus_class, intercity=True))
    op_cost, full_cost = c["trip_operating_cost_inr"] * trips_used, c["full_cost_inr"] * trips_used
    yield_t = c["full_cost_inr"] / (target_load_factor * seats * L)
    row = {
        "corridor": corridor, "day_type": day_type, "band": band, "bus_class": bus_class, "seats": seats,
        "baseline_incumbent_classes": ", ".join(sorted(sel["bus_type"].unique())), "route_length_km": L,
        "elasticity": elasticity, "fare_change_pct": fare_change_pct, "new_fare_full_length_inr": new_fare,
        "incumbent_fare_full_length_inr": inc_ref, "fare_ratio_vs_incumbent": ratio,
        "demand_passengers_per_day": demand_pax, "trips_needed_per_day": trips_needed, "trips_per_day": trips_used,
        "served_passengers_per_day": served_pax, "load_factor": served_pkm / cap_pkm if cap_pkm > 0 else float("nan"),
        "revenue_per_day_inr": rev, "trip_operating_cost_per_day_inr": op_cost, "full_cost_per_day_inr": full_cost,
        "contribution_per_day_inr": rev - op_cost, "full_cost_margin_per_day_inr": rev - full_cost,
        "be_load_factor_full": c["full_cost_inr"] / (seats * L * new_yield),
        "be_fare_current_lf_full_inr": full_cost / served_pax if served_pax > 0 else float("nan"),
        "be_adult_fare_target_full_inr": new_fare * yield_t / new_yield,
        "baseline_trips_per_day": trips_d, "baseline_passengers_per_day": pax_d, "baseline_revenue_per_day_inr": rev_d,
        "baseline_trip_operating_cost_per_day_inr": base_op, "baseline_full_cost_per_day_inr": base_full,
        "baseline_contribution_per_day_inr": rev_d - base_op, "baseline_full_cost_margin_per_day_inr": rev_d - base_full,
        "label": WHAT_IF_LABEL,
    }
    return pd.DataFrame([row])
