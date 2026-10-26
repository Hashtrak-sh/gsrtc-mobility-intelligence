"""Hourly demand-vs-supply gap table (``hourly_demand_supply``).

Two row levels (column ``level``):

``route_direction``  one row per route x direction x day_type x clock hour (departure hour), for every route.
    * ``demand_estimate`` = average-day sum over the trips departing in the hour of the **critical-link onboard load**
      (the maximum load on any link of the trip). ``seats_offered`` = average-day sum of the seats of those trips.
    * IMPORTANT: ticketed demand is *censored* at capacity (standing limit on local buses, seats on intercity buses;
      excess demand is never ticketed). ``gap_count`` and ``gap_index`` are therefore **lower bounds** of unserved demand.
    * ``location_id`` = stop at which the average bus is fullest (max mean onboard load), ``zone_id`` its zone.
    * Hours inside the route's service span (first..last departure hour of that direction/day type) with no departure
      are emitted with ``seats_offered = 0``, ``status = no_scheduled_capacity``, demand and gap NULL (demand is not
      observable without service; never divided by zero).

``corridor``  intercity corridor-hour rows (route_id null, direction ``outbound`` = departures from the origin terminal,
    ``location_id`` = origin terminal stop).
    * ``demand_estimate`` = state critical-link load + **private-market proxy** (competitor seats departing in that
      hour x ``config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION``; an assumption, not an observation).
    * ``seats_offered`` = STATE seats only, so the gap is the market demand the state timetable does not seat.
      Hours with no state seats: ``gap_index`` NULL, ``status = no_scheduled_capacity`` and ``gap_count`` = proxy demand.
    * ``crowding_flag`` for corridor rows is based on the STATE buses only (state load / state seats > threshold), because
      private demand is served by private operators and does not crowd state buses.

``gap_count = max(0, demand - seats)``; ``gap_index = demand / seats`` (seats > 0); ``crowding_flag = gap_index >
config.CROWDING_GAP_INDEX_THRESHOLD``. ``service_date`` is NULL: values are for the average day of ``day_type``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from modules.analytics.common import SOURCE_TYPE, dep_hour, jdump, n_days_by_day_type, safe_div

STATUS_NO_CAPACITY = "no_scheduled_capacity"
STATUS_CROWDED = "crowded"
STATUS_AT_CAPACITY = "at_capacity"
STATUS_OK = "ok"

GAP_COLUMNS = [
    "zone_id", "location_id", "service_date", "hour", "demand_estimate", "seats_offered", "gap_count", "gap_index",
    "crowding_flag", "source_type", "assumptions_json",
    # M2 additive columns
    "level", "route_id", "corridor", "direction", "day_type", "status", "trips_per_day", "ticketed_boardings_per_day",
    "state_demand", "private_seats", "private_demand_proxy", "private_departures",
]


def gap_metrics(demand: pd.Series, seats: pd.Series, threshold: float | None = None) -> pd.DataFrame:
    """gap_count, gap_index, crowding_flag from demand and seats (NaN-safe; zero seats -> NaN index, never inf)."""
    thr = config.CROWDING_GAP_INDEX_THRESHOLD if threshold is None else threshold
    d = pd.to_numeric(demand, errors="coerce")
    s = pd.to_numeric(seats, errors="coerce")
    count = (d - s).clip(lower=0)
    count = count.where(d.notna() & s.notna())
    index = d / s.where(s > 0)
    return pd.DataFrame({"gap_count": count, "gap_index": index, "crowding_flag": (index > thr).fillna(False)})


def _assumptions(extra: dict | None = None) -> str:
    d = {
        "demand_estimate": "average-day sum of critical-link onboard load (ticketed, censored at capacity => gap is a lower bound)",
        "gap_count": "max(0, demand_estimate - seats_offered)",
        "gap_index": "demand_estimate / seats_offered where seats_offered > 0, else null",
        "crowding_threshold_gap_index": config.CROWDING_GAP_INDEX_THRESHOLD,
        "average_day": "values are per average service day of day_type (service_date is null)",
        "note": config.SIMULATION_BADGE_TEXT,
    }
    if extra:
        d.update(extra)
    return jdump(d)


def _location_of_max_load(profile: pd.DataFrame, trips_sum: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Per group (keys incl. ``dep_hour``): stop id where the mean onboard load is highest (ties -> earliest position)."""
    cols = ["trip_id", "day_type", "dep_hour"]
    p = profile.merge(trips_sum[cols], on="trip_id", how="inner")
    m = p.groupby(keys + ["position", "stop_id"], dropna=False)["onboard_after"].mean().reset_index()
    m = m.sort_values(keys + ["onboard_after", "position"], ascending=[True] * len(keys) + [False, True], kind="mergesort")
    return m.drop_duplicates(keys)[keys + ["stop_id"]].rename(columns={"stop_id": "location_id"})


def route_direction_rows(trips_sum: pd.DataFrame, profile: pd.DataFrame, stops: pd.DataFrame,
                         threshold: float | None = None) -> pd.DataFrame:
    if trips_sum.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)
    nd = n_days_by_day_type(trips_sum)
    keys = ["route_id", "direction", "day_type", "dep_hour"]
    g = trips_sum.groupby(keys, dropna=False).agg(
        n_trips=("trip_id", "count"), peak=("peak_onboard", "sum"), seats=("seats", "sum"), boardings=("boardings", "sum"),
        route_type=("route_type", "first"),
    ).reset_index()
    # fill service-span holes with explicit zero-seat rows
    span = g.groupby(["route_id", "direction", "day_type"]).agg(h0=("dep_hour", "min"), h1=("dep_hour", "max"),
                                                                 route_type=("route_type", "first")).reset_index()
    full = pd.DataFrame([(r.route_id, r.direction, r.day_type, h) for r in span.itertuples() for h in range(int(r.h0), int(r.h1) + 1)],
                        columns=keys)
    full["dep_hour"] = full["dep_hour"].astype("Int64")
    g["dep_hour"] = g["dep_hour"].astype("Int64")
    g = full.merge(g, on=keys, how="left")
    g["route_type"] = g["route_type"].fillna(g["route_id"].map(span.drop_duplicates("route_id").set_index("route_id")["route_type"]))
    has = g["n_trips"].notna()
    days = g["day_type"].map(nd).astype(float)
    g["trips_per_day"] = (g["n_trips"] / days).fillna(0.0)
    g["seats_offered"] = (g["seats"] / days).fillna(0.0)
    g["demand_estimate"] = (g["peak"] / days).where(has)
    g["ticketed_boardings_per_day"] = (g["boardings"] / days).where(has)
    loc = _location_of_max_load(profile, trips_sum, keys)
    loc["dep_hour"] = loc["dep_hour"].astype("Int64")
    g = g.merge(loc, on=keys, how="left")
    g["zone_id"] = g["location_id"].map(stops.set_index("stop_id")["zone_id"])
    gm = gap_metrics(g["demand_estimate"], g["seats_offered"], threshold)
    g = pd.concat([g.reset_index(drop=True), gm], axis=1)
    inter = g["route_type"].eq("intercity")
    status = np.select(
        [g["seats_offered"] <= 0, g["crowding_flag"], inter & (g["gap_index"] >= config.AT_CAPACITY_LOAD_FACTOR)],
        [STATUS_NO_CAPACITY, STATUS_CROWDED, STATUS_AT_CAPACITY], default=STATUS_OK)
    g["status"] = status
    g["level"] = "route_direction"
    g["corridor"] = None
    g["hour"] = g["dep_hour"].astype(int)
    g["service_date"] = None
    for c in ("state_demand", "private_seats", "private_demand_proxy", "private_departures"):
        g[c] = np.nan
    g["source_type"] = SOURCE_TYPE
    g["assumptions_json"] = _assumptions({"level": "route_direction"})
    return g[GAP_COLUMNS]


def corridor_rows(trips_sum: pd.DataFrame, profile: pd.DataFrame, routes: pd.DataFrame, stops: pd.DataFrame,
                  competitors: pd.DataFrame, private_occupancy: float | None = None,
                  threshold: float | None = None) -> pd.DataFrame:
    """Intercity corridor-hour rows (state outbound departures + private-market proxy). See module docstring."""
    occ = config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION if private_occupancy is None else private_occupancy
    if not 0.0 <= occ <= 1.0:
        raise ValueError(f"private_occupancy must be within [0, 1], got {occ}")
    thr = config.CROWDING_GAP_INDEX_THRESHOLD if threshold is None else threshold
    inter = routes[routes["route_type"].eq("intercity") & routes["corridor"].notna()]
    if inter.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)
    nd = n_days_by_day_type(trips_sum)
    cm = inter.set_index("route_id")["corridor"]
    origin = inter.groupby("corridor")["origin_stop_id"].first()
    st = trips_sum[trips_sum["route_id"].isin(cm.index) & trips_sum["direction"].eq("outbound")].copy()
    st["corridor"] = st["route_id"].map(cm)
    sg = st.groupby(["corridor", "day_type", "dep_hour"]).agg(
        n_trips=("trip_id", "count"), peak=("peak_onboard", "sum"), seats=("seats", "sum"), boardings=("boardings", "sum")
    ).reset_index().rename(columns={"dep_hour": "hour"})
    comp = competitors.copy()
    if comp.empty:
        comp = pd.DataFrame(columns=["route_pair", "day_type", "departure_time", "seats"])
    comp["hour"] = dep_hour(comp["departure_time"])
    cg = comp.groupby(["route_pair", "day_type", "hour"]).agg(private_departures=("seats", "count"), private_seats=("seats", "sum")).reset_index()
    cg = cg.rename(columns={"route_pair": "corridor"})
    sg["hour"] = sg["hour"].astype("Int64")
    cg["hour"] = cg["hour"].astype("Int64")
    rows = []
    for (cor, dtp), _ in sg.groupby(["corridor", "day_type"]):
        s_part = sg[(sg["corridor"] == cor) & (sg["day_type"] == dtp)]
        c_part = cg[(cg["corridor"] == cor) & (cg["day_type"] == dtp)]
        hrs = sorted(set(s_part["hour"].dropna().astype(int)) | set(c_part["hour"].dropna().astype(int)))
        if not hrs:
            continue
        for h in range(hrs[0], hrs[-1] + 1):
            s = s_part[s_part["hour"] == h]
            c = c_part[c_part["hour"] == h]
            rows.append({"corridor": cor, "day_type": dtp, "hour": h,
                         "n_trips": float(s["n_trips"].sum()), "peak": float(s["peak"].sum()), "seats": float(s["seats"].sum()),
                         "boardings": float(s["boardings"].sum()),
                         "private_departures": float(c["private_departures"].sum()), "private_seats_total": float(c["private_seats"].sum())})
    g = pd.DataFrame(rows)
    if g.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)
    days = g["day_type"].map(nd).astype(float)
    g["trips_per_day"] = g["n_trips"] / days
    state_seats = g["seats"] / days
    state_demand = g["peak"] / days
    proxy = g["private_seats_total"] * occ  # competitor rows are one per service per day type = per average day
    no_state = state_seats <= 0
    no_anything = no_state & (g["private_seats_total"] <= 0)
    demand = (state_demand + proxy).where(~no_anything)  # nothing observable and nothing offered -> unknown, not 0
    gm = gap_metrics(demand, state_seats, thr)
    crowd = (safe_div(state_demand, state_seats) > thr).fillna(False)
    status = np.select([no_state, crowd], [STATUS_NO_CAPACITY, STATUS_CROWDED], default=STATUS_OK)
    # intercity hard-cap: state buses essentially full
    full = (~no_state) & (safe_div(state_demand, state_seats) >= config.AT_CAPACITY_LOAD_FACTOR) & ~crowd
    status = np.where(full, STATUS_AT_CAPACITY, status)
    out = pd.DataFrame({
        "location_id": g["corridor"].map(origin),
        "service_date": None,
        "hour": g["hour"].astype(int),
        "demand_estimate": demand,
        "seats_offered": state_seats,
        "gap_count": gm["gap_count"],
        "gap_index": gm["gap_index"],
        "crowding_flag": crowd,
        "level": "corridor",
        "route_id": None,
        "corridor": g["corridor"],
        "direction": "outbound",
        "day_type": g["day_type"],
        "status": status,
        "trips_per_day": g["trips_per_day"],
        "ticketed_boardings_per_day": (g["boardings"] / days).where(~no_state),
        "state_demand": state_demand.where(~no_state, 0.0),
        "private_seats": g["private_seats_total"],
        "private_demand_proxy": proxy,
        "private_departures": g["private_departures"],
    })
    out["zone_id"] = out["location_id"].map(stops.set_index("stop_id")["zone_id"])
    out["source_type"] = SOURCE_TYPE
    out["assumptions_json"] = _assumptions({
        "level": "corridor",
        "private_market_proxy": "competitor seats departing in the hour x assumed private occupancy (assumption, not observed)",
        "private_occupancy_assumption": occ,
        "seats_offered": "state seats only; gap = market demand the state timetable does not seat",
        "crowding_flag": "state load / state seats > threshold (private demand does not crowd state buses)",
    })
    return out[GAP_COLUMNS]


def hourly_demand_supply(trips_sum: pd.DataFrame, profile: pd.DataFrame, routes: pd.DataFrame, stops: pd.DataFrame,
                         competitors: pd.DataFrame, private_occupancy: float | None = None,
                         threshold: float | None = None) -> pd.DataFrame:
    """Route-direction rows + corridor rows, sorted deterministically."""
    a = route_direction_rows(trips_sum, profile, stops, threshold)
    b = corridor_rows(trips_sum, profile, routes, stops, competitors, private_occupancy, threshold)
    parts = [x for x in (a, b) if not x.empty]
    if not parts:
        return pd.DataFrame(columns=GAP_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    out["_lvl"] = out["level"].map({"route_direction": 0, "corridor": 1})
    out = out.sort_values(["_lvl", "route_id", "corridor", "day_type", "direction", "hour"], na_position="last", kind="mergesort")
    return out.drop(columns="_lvl").reset_index(drop=True)


def route_hour_load(trips_sum: pd.DataFrame, day_type: str = "weekday") -> pd.DataFrame:
    """Route x departure-hour load measures with both directions together (seat-weighted, for planted-finding checks).

    Columns: ``route_id, hour, trips, boardings, seats, boardings_per_seat, peak_load_factor`` where
    ``peak_load_factor = sum(trip peak onboard) / sum(seats)``.
    """
    t = trips_sum[trips_sum["day_type"] == day_type]
    g = t.groupby(["route_id", "dep_hour"]).agg(trips=("trip_id", "count"), boardings=("boardings", "sum"),
                                                 seats=("seats", "sum"), peak=("peak_onboard", "sum")).reset_index()
    g = g.rename(columns={"dep_hour": "hour"})
    g["boardings_per_seat"] = safe_div(g["boardings"], g["seats"])
    g["peak_load_factor"] = safe_div(g["peak"], g["seats"])
    return g.drop(columns="peak")
