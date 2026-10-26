"""Ticket legs, per-trip occupancy progression, trip load factors and the ``stop_occupancy`` table.

Definitions (see docs/ANALYTICS_AND_ALGORITHMS.md and docs/DATA_SCHEMA.md, M2 section):

* Occupancy progression: ``onboard_after(stop) = previous onboard + boardings(stop) - alightings(stop)`` along the trip's
  direction (outbound position = ``stop_seq``; inbound position = ``n_stops + 1 - stop_seq``). ``onboard_after`` is the
  load on the link leaving the stop. Impossible values (negative onboard, onboard above the physical cap, a trip that
  does not end empty) are FLAGGED, never clamped.
* ``peak_onboard`` = max ``onboard_after`` over the trip; ``peak_load_factor`` = ``peak_onboard / seats`` (<= 1.6 on local
  buses that allow standing, <= 1.0 on intercity reserved buses).
* ``boardings_per_seat`` = ``sum(passenger_count) / seats`` (passenger turnover; NOT a load factor).
* Passenger-km of a ticket = ``passenger_count x |cum_km(dest) - cum_km(origin)|`` (direction independent).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.analytics.common import SOURCE_TYPE, dep_hour, jdump, n_days_by_day_type
from modules.data_gen import constants as C


# ------------------------------------------------------------------ ticket legs
def ticket_legs(trips: pd.DataFrame, tickets: pd.DataFrame, route_stops: pd.DataFrame) -> pd.DataFrame:
    """Tickets enriched with route/direction, boarding/alighting positions in the trip's direction and passenger-km.

    Columns: all ticket columns + ``route_id``, ``direction``, ``o_pos``, ``d_pos``, ``pax_km``, ``leg_valid``.
    ``leg_valid`` is False when a stop is not on the route or the boarding position is not strictly before the
    alighting position; such tickets keep their boardings/revenue but get NaN passenger-km and are reported.
    """
    cols = ["ticket_id", "trip_id", "origin_stop_id", "dest_stop_id", "timestamp", "fare_inr", "passenger_count"]
    tk = tickets[[c for c in cols if c in tickets.columns]].merge(
        trips[["trip_id", "route_id", "direction"]], on="trip_id", how="left")
    n_stops = route_stops.groupby("route_id")["stop_seq"].max().rename("n_stops")
    tk = tk.join(n_stops, on="route_id")
    seq = route_stops.set_index(["route_id", "stop_id"])["stop_seq"]
    km = route_stops.set_index(["route_id", "stop_id"])["cum_km"]
    o_idx = pd.MultiIndex.from_arrays([tk["route_id"], tk["origin_stop_id"]])
    d_idx = pd.MultiIndex.from_arrays([tk["route_id"], tk["dest_stop_id"]])
    o_seq = seq.reindex(o_idx).to_numpy(dtype=float)
    d_seq = seq.reindex(d_idx).to_numpy(dtype=float)
    inb = tk["direction"].eq("inbound").to_numpy()
    n = tk["n_stops"].to_numpy(dtype=float)
    tk["o_pos"] = np.where(inb, n + 1 - o_seq, o_seq)
    tk["d_pos"] = np.where(inb, n + 1 - d_seq, d_seq)
    tk["pax_km"] = tk["passenger_count"].to_numpy(dtype=float) * np.abs(
        km.reindex(d_idx).to_numpy(dtype=float) - km.reindex(o_idx).to_numpy(dtype=float))
    tk["leg_valid"] = (tk["o_pos"] < tk["d_pos"]) & ~np.isnan(tk["o_pos"]) & ~np.isnan(tk["d_pos"])
    tk.loc[~tk["leg_valid"], "pax_km"] = np.nan
    return tk.drop(columns=["n_stops"])


# ------------------------------------------------------------------ progression
def trip_stop_profile(trips: pd.DataFrame, legs: pd.DataFrame, route_stops: pd.DataFrame) -> pd.DataFrame:
    """One row per (trip, stop in direction order) with boardings, alightings and the onboard progression.

    Columns: ``trip_id, route_id, direction, position, stop_seq, stop_id, boardings, alightings, onboard_after``.
    Every trip gets every stop of its route (zeros where nobody boards/alights). Legs whose stops are not on the
    route are ignored here (they cannot be placed) and counted via ``ticket_legs.leg_valid``.
    """
    grid = trips[["trip_id", "route_id", "direction"]].merge(
        route_stops[["route_id", "stop_seq", "stop_id"]], on="route_id", how="inner")
    n_stops = route_stops.groupby("route_id")["stop_seq"].max()
    n = grid["route_id"].map(n_stops).to_numpy(dtype=float)
    inb = grid["direction"].eq("inbound").to_numpy()
    grid["position"] = np.where(inb, n + 1 - grid["stop_seq"].to_numpy(dtype=float), grid["stop_seq"].to_numpy(dtype=float)).astype(int)

    placed = legs[legs["o_pos"].notna() & legs["d_pos"].notna()]
    board = placed.groupby(["trip_id", "o_pos"])["passenger_count"].sum().rename("boardings")
    board.index = board.index.set_names(["trip_id", "position"])
    alight = placed.groupby(["trip_id", "d_pos"])["passenger_count"].sum().rename("alightings")
    alight.index = alight.index.set_names(["trip_id", "position"])
    ev = pd.concat([board, alight], axis=1).reset_index()
    ev["position"] = ev["position"].astype(int)
    out = grid.merge(ev, on=["trip_id", "position"], how="left").fillna({"boardings": 0, "alightings": 0})
    out = out.sort_values(["trip_id", "position"], kind="mergesort").reset_index(drop=True)
    out["boardings"] = out["boardings"].astype(int)
    out["alightings"] = out["alightings"].astype(int)
    out["onboard_after"] = (out["boardings"] - out["alightings"]).groupby(out["trip_id"]).cumsum()
    return out


def trip_summary(trips: pd.DataFrame, tickets: pd.DataFrame, profile: pd.DataFrame, routes: pd.DataFrame) -> pd.DataFrame:
    """Per-trip load measures and data-quality flags.

    Columns: trip columns used downstream + ``dep_hour``, ``boardings`` (sum passenger_count), ``boardings_per_seat``,
    ``peak_onboard``, ``peak_stop_id``, ``peak_position``, ``peak_load_factor``, ``min_onboard``, ``final_onboard``,
    ``onboard_cap``, ``negative_flag``, ``over_capacity_flag``, ``not_empty_at_end_flag``.
    """
    pax = tickets.groupby("trip_id")["passenger_count"].sum()
    t = trips.copy()
    t["dep_hour"] = dep_hour(t["departure_time"])
    t["boardings"] = t["trip_id"].map(pax).fillna(0).astype(int)
    t["route_type"] = t["route_id"].map(routes.set_index("route_id")["route_type"])
    t["length_km"] = t["route_id"].map(routes.set_index("route_id")["length_km"])
    factor = np.where(t["route_type"].eq("local"), C.LOCAL_CRUSH_FACTOR, C.INTERCITY_CRUSH_FACTOR)
    t["onboard_cap"] = np.floor(t["seats"].to_numpy(dtype=float) * factor + 1e-9).astype(int)

    if profile.empty:
        for c in ("peak_onboard", "min_onboard", "final_onboard", "peak_position"):
            t[c] = pd.Series(dtype="float64")
        t["peak_stop_id"] = pd.Series(dtype="object")
    else:
        g = profile.groupby("trip_id")["onboard_after"]
        agg = pd.DataFrame({"peak_onboard": g.max(), "min_onboard": g.min(), "final_onboard": g.last()})
        pk = profile.loc[g.idxmax(), ["trip_id", "stop_id", "position"]].set_index("trip_id")
        agg["peak_stop_id"] = pk["stop_id"]
        agg["peak_position"] = pk["position"]
        t = t.join(agg, on="trip_id")
    t["peak_onboard"] = t["peak_onboard"].fillna(0).astype(int)
    t["min_onboard"] = t["min_onboard"].fillna(0).astype(int)
    t["final_onboard"] = t["final_onboard"].fillna(0).astype(int)
    t["boardings_per_seat"] = _ratio(t["boardings"], t["seats"])
    t["peak_load_factor"] = _ratio(t["peak_onboard"], t["seats"])
    t["negative_flag"] = t["min_onboard"] < 0
    t["over_capacity_flag"] = t["peak_onboard"] > t["onboard_cap"]
    t["not_empty_at_end_flag"] = t["final_onboard"] != 0
    return t


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    d = den.astype(float).where(den != 0)
    return num.astype(float) / d


def load_factor_pct(pax_km: float, seat_km: float) -> float:
    """Route-day load factor (%) = passenger-km / seat-km x 100; NaN when seat-km is zero/missing."""
    if seat_km is None or pax_km is None or np.isnan(seat_km) or np.isnan(pax_km) or seat_km <= 0:
        return float("nan")
    return float(pax_km) / float(seat_km) * 100.0


# ------------------------------------------------------------------ stop_occupancy table
def stop_occupancy(trips_sum: pd.DataFrame, profile: pd.DataFrame) -> pd.DataFrame:
    """Average-bus occupancy progression by route x direction x day_type x departure hour x stop.

    Columns: ``route_id, direction, day_type, hour, stop_seq`` (route_stops, outbound frame), ``position`` (in the
    direction of travel), ``stop_id, n_trips, trips_per_day, avg_boardings, avg_alightings`` (per trip),
    ``avg_onboard`` (per trip, load leaving the stop), ``seats`` (mean per trip), ``onboard_pct`` (avg_onboard / seats
    x 100; can exceed 100 only where standing is allowed), ``max_onboard`` (worst single trip),
    ``negative_flag`` / ``over_capacity_flag`` (any trip in the group has an impossible value), ``source_type``.
    Averages are per trip; the same trips in different stop rows are the same bus, so ``avg_onboard`` rows can be
    plotted as a progression chart.
    """
    cols = ["trip_id", "service_date", "day_type", "dep_hour", "seats", "onboard_cap"]
    p = profile.merge(trips_sum[cols], on="trip_id", how="inner")
    p = p.rename(columns={"dep_hour": "hour"})
    p["_neg"] = p["onboard_after"] < 0
    p["_over"] = p["onboard_after"] > p["onboard_cap"]
    keys = ["route_id", "direction", "day_type", "hour", "stop_seq", "position", "stop_id"]
    g = p.groupby(keys, dropna=False)
    out = g.agg(
        n_trips=("trip_id", "nunique"),
        avg_boardings=("boardings", "mean"),
        avg_alightings=("alightings", "mean"),
        avg_onboard=("onboard_after", "mean"),
        seats=("seats", "mean"),
        max_onboard=("onboard_after", "max"),
        negative_flag=("_neg", "any"),
        over_capacity_flag=("_over", "any"),
    ).reset_index()
    nd = n_days_by_day_type(trips_sum)
    out["trips_per_day"] = out["n_trips"] / out["day_type"].map(nd)
    out["onboard_pct"] = out["avg_onboard"] / out["seats"].where(out["seats"] > 0) * 100.0
    out["source_type"] = SOURCE_TYPE
    out = out.sort_values(["route_id", "direction", "day_type", "hour", "position"], kind="mergesort").reset_index(drop=True)
    return out[["route_id", "direction", "day_type", "hour", "stop_seq", "position", "stop_id", "n_trips", "trips_per_day",
                "avg_boardings", "avg_alightings", "avg_onboard", "seats", "onboard_pct", "max_onboard",
                "negative_flag", "over_capacity_flag", "source_type"]]


def occupancy_assumptions() -> str:
    return jdump({
        "occupancy": "onboard_after = previous onboard + boardings - alightings along the trip direction; flags, never clamps",
        "avg_basis": "averages are per trip (average bus) for the route-direction-day_type-hour group",
        "local_crush_factor": C.LOCAL_CRUSH_FACTOR,
        "intercity_crush_factor": C.INTERCITY_CRUSH_FACTOR,
    })
