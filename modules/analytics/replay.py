"""Operations Replay: pure per-minute snapshot computations over ONE synthetic service day.

Nothing here is streamed. Every function takes the stored tables (already filtered to one service date by
:func:`prepare_day`) and a clock ``t`` in minutes since 00:00 of the service date (values >= 1440 are after midnight,
used by late trips and their tickets). Simulated data for demonstration.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from modules.analytics.reliability import on_time_flag, reliability_pct

LATE_ALERT_MIN = 15.0  # departures later than this many minutes are listed as alerts
OVER_CAPACITY_GAP_INDEX = 1.0  # demand / seats above 1.0 means more estimated load than seats


def _hhmm_to_min(s: pd.Series) -> pd.Series:
    p = s.astype("string").str.split(":", expand=True)
    return pd.to_numeric(p[0], errors="coerce") * 60 + pd.to_numeric(p[1], errors="coerce")


def prepare_day(trips: pd.DataFrame, tickets: pd.DataFrame, service_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trips and tickets of one service date with minute columns.

    trips gain ``dep_min`` (timetable), ``start_min`` (actual departure where available, else timetable) and ``end_min``
    (= start + scheduled_minutes). tickets (matched through trip_id, so after-midnight tickets stay on their service day)
    gain ``route_id`` and ``t_min`` = minutes since 00:00 of the service date.
    """
    td = trips[trips["service_date"].astype(str) == str(service_date)].copy()
    dep = _hhmm_to_min(td["departure_time"])
    if "actual_departure_time" in td:
        act = _hhmm_to_min(td["actual_departure_time"])
    else:
        act = pd.Series(np.nan, index=td.index)
    act = act.where(act.isna() | ((act - dep) >= -720), act + 1440)  # actual departure after midnight
    td["dep_min"] = dep
    td["start_min"] = act.fillna(dep)
    td["end_min"] = td["start_min"] + td["scheduled_minutes"]
    tk = tickets[tickets["trip_id"].isin(td["trip_id"])].copy()
    tk["route_id"] = tk["trip_id"].map(dict(zip(td["trip_id"], td["route_id"])))
    tk["t_min"] = (tk["timestamp"] - pd.Timestamp(str(service_date))).dt.total_seconds() / 60.0
    return td, tk


def clock_bounds(td: pd.DataFrame, tk: pd.DataFrame, step: int) -> tuple[int, int]:
    """First/last clock value covering every departure and ticket of the day (end is a multiple of ``step``)."""
    lo = float(td["start_min"].min()) if len(td) else 0.0
    hi = max(float(td["end_min"].max()) if len(td) else 0.0, float(tk["t_min"].max()) if len(tk) else 0.0)
    return int(lo // 60 * 60), int(-(-hi // step) * step)


def clock_label(t: float) -> str:
    """24-hour label; after midnight shows e.g. ``00:30 (+1 day)``."""
    t = int(t)
    return f"{(t // 60) % 24:02d}:{t % 60:02d}" + (" (+1 day)" if t >= 1440 else "")


def in_service_mask(td: pd.DataFrame, t: float) -> pd.Series:
    return (td["start_min"] <= t) & (t < td["end_min"])


def buses_in_service(td: pd.DataFrame, t: float) -> int:
    return int(in_service_mask(td, t).sum())


def boardings_so_far(tk: pd.DataFrame, t: float) -> int:
    return int(tk.loc[tk["t_min"] <= t, "passenger_count"].sum())


def boardings_last_hour(tk: pd.DataFrame, t: float, window: float = 60.0) -> int:
    m = (tk["t_min"] > t - window) & (tk["t_min"] <= t)
    return int(tk.loc[m, "passenger_count"].sum())


def departures_status(td: pd.DataFrame, t: float) -> dict:
    """Departures so far (actual departure <= t) split with the shared on-time band (reliability.py)."""
    dep = td[td["start_min"] <= t]
    lo, hi = config.RELIABILITY_ON_TIME_BAND_MIN
    flag = on_time_flag(dep["departure_delay_min"])
    d = pd.to_numeric(dep["departure_delay_min"], errors="coerce")
    return {
        "departed": int(len(dep)),
        "known": int(flag.notna().sum()),
        "on_time": int(flag.fillna(False).astype(bool).sum()),
        "late": int((d > hi).sum()),
        "early": int((d < lo).sum()),
        "on_time_pct": reliability_pct(dep["departure_delay_min"]),
    }


def route_direction_hours(hourly: pd.DataFrame, day_type: str) -> pd.DataFrame:
    return hourly[(hourly["level"] == "route_direction") & (hourly["day_type"] == day_type)]


def crowded_at_hour(hourly: pd.DataFrame, day_type: str, t: float) -> dict:
    """Crowded route-direction hours at the clock hour (table is per AVERAGE service day of the day type)."""
    h = route_direction_hours(hourly, day_type)
    h = h[h["hour"] == int(t // 60) % 24]
    scheduled = h[h["seats_offered"].fillna(0) > 0]
    return {"hour": int(t // 60) % 24, "crowded": int(scheduled["crowding_flag"].fillna(False).astype(bool).sum()),
            "scheduled": int(len(scheduled)), "rows": scheduled}


def stop_boardings(tk: pd.DataFrame, t: float, window: float = 60.0) -> pd.Series:
    m = (tk["t_min"] > t - window) & (tk["t_min"] <= t)
    return tk.loc[m].groupby("origin_stop_id")["passenger_count"].sum()


def cumulative_curve(tk: pd.DataFrame, grid) -> pd.DataFrame:
    """Cumulative boardings at each grid minute (monotonic; last value = day total once the grid covers all tickets)."""
    order = np.argsort(tk["t_min"].to_numpy())
    ts = tk["t_min"].to_numpy()[order]
    cs = np.concatenate([[0], np.cumsum(tk["passenger_count"].to_numpy()[order])])
    idx = np.searchsorted(ts, np.asarray(grid, dtype=float), side="right")
    return pd.DataFrame({"t_min": np.asarray(grid), "cumulative": cs[idx]})


def bus_positions(td: pd.DataFrame, route_stops: pd.DataFrame, stops: pd.DataFrame, t: float) -> pd.DataFrame:
    """ESTIMATED positions of buses in service: elapsed share of scheduled running time mapped onto the route's stop
    sequence (cum_minutes), straight lines between stops. Inbound trips run the stop order in reverse (assumption).
    Not GPS."""
    ll = stops.set_index("stop_id")[["lat", "lon"]]
    rows = []
    for _, tr in td[in_service_mask(td, t)].iterrows():
        rs = route_stops[route_stops["route_id"] == tr["route_id"]].sort_values("stop_seq")
        rs = rs[rs["stop_id"].isin(ll.index)]
        if len(rs) < 2 or not tr["scheduled_minutes"] > 0:
            continue
        cum = rs["cum_minutes"].to_numpy(float)
        lat, lon = ll.loc[rs["stop_id"], "lat"].to_numpy(), ll.loc[rs["stop_id"], "lon"].to_numpy()
        total = cum[-1]
        if tr.get("direction") == "inbound":
            cum, lat, lon = total - cum[::-1], lat[::-1], lon[::-1]
        prog = (t - tr["start_min"]) / tr["scheduled_minutes"]
        rows.append({"trip_id": tr["trip_id"], "route_id": tr["route_id"], "lat": float(np.interp(prog * total, cum, lat)),
                     "lon": float(np.interp(prog * total, cum, lon)), "progress": float(prog)})
    return pd.DataFrame(rows, columns=["trip_id", "route_id", "lat", "lon", "progress"])


def alerts(td: pd.DataFrame, hourly: pd.DataFrame, day_type: str, t: float, route_name: dict[str, str] | None = None,
           limit: int = 6) -> list[str]:
    """Plain-text alerts: departures >15 min late in the last hour, and route-hours over 100% load at this clock hour."""
    names = route_name or {}
    out: list[str] = []
    recent = td[(td["start_min"] <= t) & (td["start_min"] > t - 60) & (td["departure_delay_min"] > LATE_ALERT_MIN)]
    for _, r in recent.sort_values("departure_delay_min", ascending=False).iterrows():
        out.append(f"Late departure: {names.get(r['route_id'], r['route_id'])} ({r['direction']}), timetable {r['departure_time']}, "
                   f"left {r['departure_delay_min']:.0f} min late.")
    rows = crowded_at_hour(hourly, day_type, t)["rows"]
    over = rows[rows["gap_index"] > OVER_CAPACITY_GAP_INDEX].sort_values("gap_index", ascending=False)
    for _, r in over.iterrows():
        out.append(f"Over 100% load (average-day estimate): {names.get(r['route_id'], r['route_id'])} ({r['direction']}) at "
                   f"{int(r['hour']):02d}:00, demand is {r['gap_index'] * 100:.0f}% of seats.")
    return out[:limit] if limit else out


def snapshot(td: pd.DataFrame, tk: pd.DataFrame, hourly: pd.DataFrame, day_type: str, t: float) -> dict:
    return {"buses": buses_in_service(td, t), "so_far": boardings_so_far(tk, t), "last_hour": boardings_last_hour(tk, t),
            "dep": departures_status(td, t), "crowd": crowded_at_hour(hourly, day_type, t)}


def takeaway(clock: str, snap: dict) -> str:
    """One-paragraph reading of the snapshot, built only from the numbers in ``snap``."""
    s = (f"At {clock} on this simulated day, {snap['buses']} buses are in service and {snap['so_far']:,} passengers have boarded so far "
         f"({snap['last_hour']:,} in the last hour). ")
    d = snap["dep"]
    if d["known"]:
        s += f"Of {d['departed']} departures so far, {d['on_time_pct']:.0f}% left on time ({d['late']} late, {d['early']} early). "
    else:
        s += "No departures have happened yet. "
    c = snap["crowd"]
    s += (f"In the average-day table for this day type, {c['crowded']} of {c['scheduled']} scheduled route-directions are crowded at "
          f"{c['hour']:02d}:00. A real-time view would update these numbers from ETM and AVL feeds.")
    return s
