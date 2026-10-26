"""Ticket simulation: latent demand per trip -> origin/destination pairs -> served passengers -> tickets.

Process (all randomness from the passed Generator):
1. Per trip: expected demand (pax) = base x hour profile x day factor x direction/phase multiplier x planted boosts
   x lognormal noise; realised demand ~ Poisson.
2. Demand is split over boarding/alighting stop pairs (boarding stop strictly before alighting stop in the trip's
   direction) with a multinomial over documented pair weights (res/job gravity for local, population gravity for
   intercity).
3. Stops are processed in order; boardings are served while onboard load <= cap (local: 1.6 x seats standing allowed,
   intercity: seats). Excess demand is unmet (not ticketed). Onboard load can therefore never go negative.
4. Passengers become tickets (some same-OD adult/other tickets are merged into group bookings), with fare by
   distance and bus type with concessions, and timestamp = actual departure + cum_minutes of the boarding stop.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from modules.data_gen import constants as C
from modules.data_gen import geography as G
from modules.data_gen import network as N

MAXN = 8
_DIR = {"outbound": 0, "inbound": 1}


@dataclass
class RouteGrid:
    route_ids: list[str]
    stop_ids: list[str]            # global stop id list (index space)
    stop_idx: np.ndarray           # [route, dir, pos] -> global stop index or -1
    cum_km: np.ndarray             # [route, dir, pos]
    cum_min: np.ndarray            # [route, dir, pos]
    n_stops: np.ndarray            # [route]
    length_km: np.ndarray
    sched_min: np.ndarray

    @classmethod
    def build(cls, route_stops: pd.DataFrame, stops: pd.DataFrame) -> "RouteGrid":
        stop_ids = list(stops["stop_id"])
        sidx = {s: i for i, s in enumerate(stop_ids)}
        rids = [s.route_id for s in N.ROUTE_SPECS]
        R = len(rids)
        stop_idx = -np.ones((R, 2, MAXN), dtype=int)
        cum_km = np.zeros((R, 2, MAXN))
        cum_min = np.zeros((R, 2, MAXN))
        n_stops = np.zeros(R, dtype=int)
        length = np.zeros(R)
        sched = np.zeros(R)
        for r, rid in enumerate(rids):
            g = route_stops[route_stops["route_id"] == rid].sort_values("stop_seq")
            n = len(g)
            n_stops[r] = n
            ids = np.array([sidx[s] for s in g["stop_id"]])
            km = g["cum_km"].to_numpy()
            mn = g["cum_minutes"].to_numpy()
            length[r], sched[r] = km[-1], mn[-1]
            stop_idx[r, 0, :n], cum_km[r, 0, :n], cum_min[r, 0, :n] = ids, km, mn
            stop_idx[r, 1, :n], cum_km[r, 1, :n], cum_min[r, 1, :n] = ids[::-1], km[-1] - km[::-1], mn[-1] - mn[::-1]
        return cls(rids, stop_ids, stop_idx, cum_km, cum_min, n_stops, length, sched)


def _phase(dt: str, hour: int) -> str:
    if dt != "weekday":
        return "offday"
    if 6 <= hour < 10:
        return "morning"
    if 16 <= hour < 20:
        return "evening"
    return "midday"


def _expected_pax(spec: N.RouteSpec, direction: str, dt: str, dep_min: int, seats: int) -> float:
    hour = dep_min // 60
    if spec.route_type == "local":
        prof = C.LOCAL_HOUR_PROFILE_WEEKDAY if dt == "weekday" else C.LOCAL_HOUR_PROFILE_WEEKEND
        ph = _phase(dt, hour)
        if ph == "morning":
            dm = spec.out_morning if direction == "outbound" else spec.in_morning
        elif ph == "evening":
            dm = spec.out_evening if direction == "outbound" else spec.in_evening
        else:
            dm = 1.0
        boost = spec.hour_boost.get((direction, hour, dt), 1.0)
        return spec.base * prof.get(hour, 0.3) * C.LOCAL_DAY_FACTOR[dt] * dm * boost
    dayf = (spec.day_factor or C.INTERCITY_DAY_FACTOR_DEFAULT)[dt]
    hhmm = f"{dep_min // 60:02d}:{dep_min % 60:02d}"
    boost = spec.trip_boost.get((direction, hhmm, dt), 1.0)
    dirf = 1.0 if direction == "outbound" else 0.9
    return seats * spec.base * C.INTERCITY_HOUR_PROFILE.get(hour, 0.7) * dayf * dirf * boost


def generate_tickets(trips: pd.DataFrame, grid: RouteGrid, zones: pd.DataFrame, stops: pd.DataFrame,
                     rng: np.random.Generator) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Return (tickets, aux) where aux holds footfall components for CCTV (not part of the public schema)."""
    attr = N.stop_attractors(zones, stops)
    rindex = {rid: i for i, rid in enumerate(grid.route_ids)}
    spec_of = {s.route_id: s for s in N.ROUTE_SPECS}
    n_trips = len(trips)

    t_route = trips["route_id"].map(rindex).to_numpy()
    t_dir = trips["direction"].map(_DIR).to_numpy()
    t_dep = trips["_dep_min"].to_numpy()
    t_dt = trips["day_type"].to_numpy()
    t_seats = trips["seats"].to_numpy()
    route_ids = trips["route_id"].to_numpy()
    direction = trips["direction"].to_numpy()

    mean = np.empty(n_trips)
    is_local = np.empty(n_trips, dtype=bool)
    phase_arr = np.empty(n_trips, dtype=object)
    for k in range(n_trips):
        spec = spec_of[route_ids[k]]
        mean[k] = _expected_pax(spec, direction[k], t_dt[k], int(t_dep[k]), int(t_seats[k]))
        is_local[k] = spec.route_type == "local"
        phase_arr[k] = _phase(t_dt[k], int(t_dep[k]) // 60)
    sigma = np.where(is_local, 0.18, 0.12)
    mean = mean * np.exp(rng.normal(0.0, sigma))
    demand = rng.poisson(mean)

    cap_arr = np.where(is_local, (t_seats * C.LOCAL_CRUSH_FACTOR).astype(int), (t_seats * C.INTERCITY_CRUSH_FACTOR).astype(int))

    prob_cache: dict[tuple, np.ndarray] = {}

    def pair_probs(r: int, d: int, phase: str) -> np.ndarray:
        spec = spec_of[grid.route_ids[r]]
        key = (r, d, phase if spec.route_type == "local" else "-")
        if key not in prob_cache:
            n = grid.n_stops[r]
            sids = [grid.stop_ids[i] for i in grid.stop_idx[r, d, :n]]
            km = grid.cum_km[r, d, :n]
            prob_cache[key] = (N.local_pair_probs(spec, "outbound" if d == 0 else "inbound", phase, attr, km, sids)
                               if spec.route_type == "local" else N.intercity_pair_probs(sids, km))
        return prob_cache[key]

    e_trip: list[np.ndarray] = []
    e_i: list[np.ndarray] = []
    e_j: list[np.ndarray] = []
    e_n: list[np.ndarray] = []
    u_trip: list[int] = []
    u_pos: list[int] = []
    u_n: list[int] = []
    for k in np.flatnonzero(demand > 0):
        r, d = int(t_route[k]), int(t_dir[k])
        n = int(grid.n_stops[r])
        iu, ju = np.triu_indices(n, 1)
        counts = rng.multinomial(int(demand[k]), pair_probs(r, d, phase_arr[k]))
        C_mat = np.zeros((n, n), dtype=np.int64)
        C_mat[iu, ju] = counts
        S = np.zeros((n, n), dtype=np.int64)
        onboard = 0
        cap = int(cap_arr[k])
        for s in range(n - 1):
            onboard -= int(S[:, s].sum())
            want = C_mat[s, s + 1:]
            w = int(want.sum())
            if w == 0:
                continue
            room = max(cap - onboard, 0)
            if w <= room:
                S[s, s + 1:] = want
                served = w
            else:
                served = room
                if served > 0:
                    S[s, s + 1:] = rng.multivariate_hypergeometric(want, served)
                u_trip.append(int(k)); u_pos.append(s); u_n.append(w - served)
            onboard += served
        ii, jj = np.nonzero(S)
        if len(ii):
            e_trip.append(np.full(len(ii), k)); e_i.append(ii); e_j.append(jj); e_n.append(S[ii, jj])
    e_trip_a = np.concatenate(e_trip); e_i_a = np.concatenate(e_i)
    e_j_a = np.concatenate(e_j); e_n_a = np.concatenate(e_n)

    # --- expand to individual passengers, then merge some into group bookings ---
    ent = np.repeat(np.arange(len(e_n_a)), e_n_a)
    ind_trip, ind_i, ind_j = e_trip_a[ent], e_i_a[ent], e_j_a[ent]
    n_ind = len(ent)
    u = rng.random(n_ind)
    ptypes = np.array(C.PASSENGER_TYPES)
    cl = np.cumsum([C.PASSENGER_TYPE_PROBS_LOCAL[t] for t in C.PASSENGER_TYPES])
    ci = np.cumsum([C.PASSENGER_TYPE_PROBS_INTERCITY[t] for t in C.PASSENGER_TYPES])
    loc_flag = is_local[ind_trip]
    tcode = np.where(loc_flag, np.searchsorted(cl, u, side="right"), np.searchsorted(ci, u, side="right")).clip(0, 3)
    mergeable = np.isin(tcode, [0, 3])  # adult / other
    same_prev = np.zeros(n_ind, dtype=bool)
    same_prev[1:] = (ent[1:] == ent[:-1]) & (tcode[1:] == tcode[:-1]) & mergeable[1:]
    merge = same_prev & (rng.random(n_ind) < C.GROUP_MERGE_PROB)
    start = ~merge
    grp = np.cumsum(start) - 1
    first = np.flatnonzero(start)[grp]
    start = start | ((np.arange(n_ind) - first) % 4 == 0)  # cap group size at 4
    grp = np.cumsum(start) - 1
    pc = np.bincount(grp)
    st = np.flatnonzero(start)
    g_trip, g_i, g_j, g_t = ind_trip[st], ind_i[st], ind_j[st], tcode[st]

    # --- fares and timestamps ---
    r_of = t_route[g_trip]
    d_of = t_dir[g_trip]
    km = grid.cum_km[r_of, d_of, g_j] - grid.cum_km[r_of, d_of, g_i]
    bt = trips["bus_type"].to_numpy()[g_trip]
    base = np.array([C.FARE_TABLE[b]["base"] for b in bt])
    perkm = np.array([C.FARE_TABLE[b]["per_km"] for b in bt])
    minf = np.array([C.FARE_TABLE[b]["min_fare"] for b in bt])
    rnd = np.array([C.FARE_TABLE[b]["round_to"] for b in bt])
    fare_pp = np.maximum(minf, np.round((base + perkm * km) / rnd) * rnd)
    conc = np.array([C.CONCESSION_FACTOR[t] for t in ptypes])[g_t]
    fare = np.round(fare_pp * conc * pc, 2)

    date_ns = pd.to_datetime(trips["service_date"]).to_numpy().astype("datetime64[ns]").astype(np.int64)
    exact_dep_min = t_dep + trips["departure_delay_min"].to_numpy()
    trip_base_ns = date_ns + np.round(exact_dep_min * 60e9).astype(np.int64)
    board_min = grid.cum_min[r_of, d_of, g_i]
    sec = rng.integers(0, 60, len(st))
    ts_ns = trip_base_ns[g_trip] + np.round(board_min * 60e9).astype(np.int64) + sec * 1_000_000_000
    ride_min = grid.cum_min[r_of, d_of, g_j] - grid.cum_min[r_of, d_of, g_i]
    alight_ns = ts_ns + np.round(ride_min * 60e9).astype(np.int64)

    order = np.argsort(ts_ns, kind="stable")
    sid = np.array(grid.stop_ids, dtype=object)
    o_stop = sid[grid.stop_idx[r_of, d_of, g_i]][order]
    d_stop = sid[grid.stop_idx[r_of, d_of, g_j]][order]
    tickets = pd.DataFrame({
        "ticket_id": [f"TK{i + 1:07d}" for i in range(len(order))],
        "trip_id": trips["trip_id"].to_numpy()[g_trip][order],
        "origin_stop_id": o_stop,
        "dest_stop_id": d_stop,
        "timestamp": ts_ns[order].astype("datetime64[ns]"),
        "fare_inr": fare[order],
        "passenger_type": ptypes[g_t][order],
        "passenger_count": pc[order].astype(np.int64),
        "source_type": "synthetic",
    })

    # --- aux footfall components for CCTV (cctv locations only) ---
    cctv = set(G.CCTV_LOCATIONS)
    board_df = pd.DataFrame({"location_id": o_stop, "ts": ts_ns[order].astype("datetime64[ns]"), "pc": pc[order]})
    alight_df = pd.DataFrame({"location_id": d_stop, "ts": alight_ns[order].astype("datetime64[ns]"), "pc": pc[order]})
    board_df = board_df[board_df["location_id"].isin(cctv)].reset_index(drop=True)
    alight_df = alight_df[alight_df["location_id"].isin(cctv)].reset_index(drop=True)
    ut = np.array(u_trip, dtype=int)
    up = np.array(u_pos, dtype=int)
    un = np.array(u_n, dtype=int)
    if len(ut):
        ur, ud = t_route[ut], t_dir[ut]
        u_stop = sid[grid.stop_idx[ur, ud, up]]
        u_ns = trip_base_ns[ut] + np.round(grid.cum_min[ur, ud, up] * 60e9).astype(np.int64)
        unmet_df = pd.DataFrame({"location_id": u_stop, "ts": u_ns.astype("datetime64[ns]"), "pc": un})
        unmet_df = unmet_df[unmet_df["location_id"].isin(cctv)].reset_index(drop=True)
    else:
        unmet_df = pd.DataFrame({"location_id": [], "ts": pd.to_datetime([]), "pc": []})
    return tickets, {"board": board_df, "alight": alight_df, "unmet": unmet_df}
