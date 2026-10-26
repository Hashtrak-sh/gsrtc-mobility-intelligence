"""SYNTHETIC aggregate CCTV counts (measurement_method='synthetic') at three bus stands.

This is NOT detector output. Real detector output (M6) is a separate stream and must not be merged with this.
No person-level identifiers exist anywhere; only aggregate counts per 5-minute bucket.

Components of person counts at a stand (bucket = 5 minutes, 05:00-22:55):
* ticketed passengers: boardings at the stand arrive 3-15 min before departure (inbound); alighters leave (outbound);
* unmet intercity demand: people who came for a seat that was full (inbound; leave 20-60 min later, outbound);
* unticketed footfall: escorts, transfers, season-pass travellers and walk-through; a documented per-location profile.
  PLANTED: the Rajkot Central stand has a weekday 07:00-09:00 peak (finding 6).
Bus counts come from the trip schedule at actual arrival/departure times.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.data_gen import constants as C
from modules.data_gen import geography as G
from modules.data_gen.tickets import RouteGrid

BUCKET_MIN = 5
FIRST_MIN, LAST_MIN = 5 * 60, 23 * 60
N_BUCKETS = (LAST_MIN - FIRST_MIN) // BUCKET_MIN  # 216

# unticketed footfall lambda per 5-minute bucket, by hour (inbound); outbound = OUT_RATIO x inbound
_RAJKOT_WEEKDAY = {5: 6, 6: 14, 7: 52, 8: 58, 9: 30, 10: 15, 11: 12, 12: 12, 13: 12, 14: 12, 15: 14, 16: 20, 17: 28, 18: 30, 19: 18, 20: 11, 21: 7, 22: 4}
_RAJKOT_OFFDAY = {5: 4, 6: 8, 7: 12, 8: 16, 9: 20, 10: 22, 11: 22, 12: 20, 13: 18, 14: 18, 15: 20, 16: 22, 17: 24, 18: 22, 19: 16, 20: 10, 21: 6, 22: 3}
_PILGRIM_WEEKDAY = {h: v for h, v in zip(range(5, 23), [2, 4, 6, 9, 11, 12, 11, 9, 8, 9, 10, 11, 10, 8, 6, 4, 3, 2])}
_PILGRIM_OFFDAY = {h: v * 1.8 for h, v in _PILGRIM_WEEKDAY.items()}
_TOWN = {h: v for h, v in zip(range(5, 23), [2, 4, 7, 9, 8, 6, 5, 5, 5, 5, 6, 7, 9, 9, 7, 5, 3, 2])}
OUT_RATIO = 0.6
_FESTIVAL_PILGRIM_BOOST = 1.8


def _lam(location: str, dt: str, hour: int) -> float:
    if location == "S01":
        tab = _RAJKOT_WEEKDAY if dt == "weekday" else _RAJKOT_OFFDAY
        return float(tab[hour])
    if location == "S34":
        tab = _PILGRIM_WEEKDAY if dt == "weekday" else _PILGRIM_OFFDAY
        return float(tab[hour]) * (_FESTIVAL_PILGRIM_BOOST if dt == "festival" else 1.0)
    return float(_TOWN[hour]) * (1.0 if dt == "weekday" else 1.2)


def generate_cctv(trips: pd.DataFrame, grid: RouteGrid, aux: dict[str, pd.DataFrame], days: int,
                  rng: np.random.Generator) -> pd.DataFrame:
    dates = C.service_dates(days)
    day0 = np.datetime64(dates[0], "D")
    locs = list(G.CCTV_LOCATIONS)
    L, D, B = len(locs), days, N_BUCKETS
    lidx = {l: i for i, l in enumerate(locs)}

    def bucketize(ts: np.ndarray, loc: np.ndarray, w: np.ndarray, shift_min: np.ndarray | None = None) -> np.ndarray:
        out = np.zeros(L * D * B)
        if len(ts) == 0:
            return out.reshape(L, D, B)
        t = ts.astype("datetime64[ns]")
        if shift_min is not None:
            t = t + (shift_min * 60_000_000_000).astype("timedelta64[ns]")
        day = ((t.astype("datetime64[D]") - day0).astype(int))
        minute = ((t - t.astype("datetime64[D]")).astype("timedelta64[m]").astype(int))
        b = (minute - FIRST_MIN) // BUCKET_MIN
        ok = (day >= 0) & (day < D) & (b >= 0) & (b < B)
        li = np.array([lidx[x] for x in loc])
        np.add.at(out, (li[ok] * D + day[ok]) * B + b[ok], w[ok])
        return out.reshape(L, D, B)

    bd, ad, ud = aux["board"], aux["alight"], aux["unmet"]
    wait = rng.integers(3, 16, len(bd))
    inb_board = bucketize(bd["ts"].to_numpy(), bd["location_id"].to_numpy(), bd["pc"].to_numpy().astype(float), -wait)
    out_alight = bucketize(ad["ts"].to_numpy(), ad["location_id"].to_numpy(), ad["pc"].to_numpy().astype(float))
    uw = rng.integers(3, 16, len(ud))
    inb_unmet = bucketize(ud["ts"].to_numpy(), ud["location_id"].to_numpy(), ud["pc"].to_numpy().astype(float), -uw)
    ul = rng.integers(20, 61, len(ud))
    out_unmet = bucketize(ud["ts"].to_numpy(), ud["location_id"].to_numpy(), ud["pc"].to_numpy().astype(float), ul)

    # unticketed footfall
    lam_in = np.zeros((L, D, B))
    for li, loc in enumerate(locs):
        for di, d in enumerate(dates):
            dt = C.day_type(d)
            hours = (FIRST_MIN + np.arange(B) * BUCKET_MIN) // 60
            lam_in[li, di] = [_lam(loc, dt, int(h)) for h in hours]
    foot_in = rng.poisson(lam_in)
    foot_out = rng.poisson(lam_in * OUT_RATIO)
    person_in = np.rint(inb_board + inb_unmet).astype(int) + foot_in
    person_out = np.rint(out_alight + out_unmet).astype(int) + foot_out

    # buses at stands: arrivals (inbound) and departures (outbound) from the schedule
    t_route = trips["route_id"].map({r: i for i, r in enumerate(grid.route_ids)}).to_numpy()
    t_dir = trips["direction"].map({"outbound": 0, "inbound": 1}).to_numpy()
    date_ns = pd.to_datetime(trips["service_date"]).to_numpy().astype("datetime64[ns]").astype(np.int64)
    base_ns = date_ns + np.round((trips["_dep_min"].to_numpy() + trips["departure_delay_min"].to_numpy()) * 60e9).astype(np.int64)
    bus_in_l, bus_out_l = [], []
    for loc in locs:
        sidx = grid.stop_ids.index(loc)
        in_ts, in_w, out_ts, out_w = [], [], [], []
        for pos in range(8):
            sel = (grid.stop_idx[t_route, t_dir, pos] == sidx)
            if not sel.any():
                continue
            n_r = grid.n_stops[t_route[sel]]
            ts = base_ns[sel] + np.round(grid.cum_min[t_route[sel], t_dir[sel], pos] * 60e9).astype(np.int64)
            if pos > 0:  # a bus arrives at every stop except its origin
                in_ts.append(ts)
            out_ts.append(ts[pos < (n_r - 1)])  # and departs from every stop except its destination
        bus_in_l.append(np.concatenate(in_ts) if in_ts else np.array([], dtype=np.int64))
        bus_out_l.append(np.concatenate(out_ts) if out_ts else np.array([], dtype=np.int64))

    def bus_grid(per_loc: list[np.ndarray]) -> np.ndarray:
        ts = np.concatenate(per_loc).astype("datetime64[ns]")
        loc = np.concatenate([np.full(len(a), locs[i], dtype=object) for i, a in enumerate(per_loc)])
        return bucketize(ts, loc, np.ones(len(ts)))

    bus_in = np.rint(bus_grid(bus_in_l)).astype(int)
    bus_out = np.rint(bus_grid(bus_out_l)).astype(int)

    start = (np.array([np.datetime64(d, "D") for d in dates]).astype("datetime64[m]")[:, None]
             + (FIRST_MIN + np.arange(B) * BUCKET_MIN).astype("timedelta64[m]")[None, :])  # [D, B]
    frames = []
    for li, loc in enumerate(locs):
        for direction, cls, arr in (("inbound", "person", person_in), ("outbound", "person", person_out),
                                    ("inbound", "bus", bus_in), ("outbound", "bus", bus_out)):
            frames.append(pd.DataFrame({
                "location_id": loc, "timestamp_min": start.reshape(-1).astype("datetime64[ns]"),
                "direction": direction, "class": cls, "count": arr[li].reshape(-1).astype(np.int64),
            }))
    out = pd.concat(frames, ignore_index=True)
    out["measurement_method"] = "synthetic"
    out["source_type"] = "synthetic"
    out = out.sort_values(["location_id", "timestamp_min", "class", "direction"], kind="stable").reset_index(drop=True)
    return out[["location_id", "timestamp_min", "direction", "class", "count", "measurement_method", "source_type"]]
