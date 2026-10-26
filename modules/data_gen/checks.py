"""Simple detectors for the planted findings, computed ONLY from the generated source tables.

These are verification helpers for tests and ``validate`` (not M2 analytics). They intentionally use plain pandas
and the definitions written down in ``data/synthetic/planted_findings.md``.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

Tables = dict[str, pd.DataFrame]


# ----------------------------------------------------------------- shared helpers
def trip_boardings(trips: pd.DataFrame, tickets: pd.DataFrame) -> pd.DataFrame:
    """trips + ``boardings`` (sum of passenger_count over the trip's tickets) + ``dep_hour``."""
    pax = tickets.groupby("trip_id")["passenger_count"].sum()
    t = trips.copy()
    t["boardings"] = t["trip_id"].map(pax).fillna(0).astype(int)
    t["dep_hour"] = t["departure_time"].str[:2].astype(int)
    return t


def occupancy_by_trip(trips: pd.DataFrame, tickets: pd.DataFrame, route_stops: pd.DataFrame) -> pd.DataFrame:
    """Occupancy progression per trip: after each stop, previous + boardings - alightings. Returns min/max onboard.

    Stop position in a trip's direction: outbound = stop_seq, inbound = n_stops + 1 - stop_seq.
    """
    n_stops = route_stops.groupby("route_id")["stop_seq"].max().rename("n_stops")
    seq = route_stops.set_index(["route_id", "stop_id"])["stop_seq"]
    tk = tickets.merge(trips[["trip_id", "route_id", "direction"]], on="trip_id")
    tk = tk.join(n_stops, on="route_id")
    tk["o_seq"] = seq.reindex(pd.MultiIndex.from_arrays([tk["route_id"], tk["origin_stop_id"]])).to_numpy()
    tk["d_seq"] = seq.reindex(pd.MultiIndex.from_arrays([tk["route_id"], tk["dest_stop_id"]])).to_numpy()
    inb = tk["direction"].eq("inbound")
    tk["o_pos"] = np.where(inb, tk["n_stops"] + 1 - tk["o_seq"], tk["o_seq"])
    tk["d_pos"] = np.where(inb, tk["n_stops"] + 1 - tk["d_seq"], tk["d_seq"])
    ev = pd.concat([
        pd.DataFrame({"trip_id": tk["trip_id"], "pos": tk["o_pos"], "delta": tk["passenger_count"]}),
        pd.DataFrame({"trip_id": tk["trip_id"], "pos": tk["d_pos"], "delta": -tk["passenger_count"]}),
    ])
    ev = ev.groupby(["trip_id", "pos"], sort=True)["delta"].sum().reset_index()
    ev["onboard"] = ev.groupby("trip_id")["delta"].cumsum()
    out = ev.groupby("trip_id")["onboard"].agg(peak_onboard="max", min_onboard="min", final_onboard="last").reset_index()
    return out


def stop_zone_map(stops: pd.DataFrame) -> pd.Series:
    return stops.set_index("stop_id")["zone_id"]


# ----------------------------------------------------------------- finding 1: high load route-hours
def high_load_route_hours(tables: Tables, min_bps: float = 1.4, day_type: str = "weekday") -> pd.DataFrame:
    """Route-hours (all weekday trips scheduled to depart in the hour, both directions) with boardings per seat > min_bps.

    boardings_per_seat = sum(boardings) / sum(seats)  (seat-weighted passenger TURNOVER, not a load factor: passengers who
    board and alight along the route are counted once each, so it can exceed the 1.6 crush limit on local routes.
    The physical load measure is the peak load factor computed by ``modules.analytics``).
    """
    t = trip_boardings(tables["trips"], tables["tickets"])
    t = t[t["day_type"] == day_type]
    routes = tables["routes"].set_index("route_id")
    g = t.groupby(["route_id", "dep_hour"]).agg(boardings=("boardings", "sum"), seats=("seats", "sum"), trips=("trip_id", "count")).reset_index()
    g["boardings_per_seat"] = g["boardings"] / g["seats"]
    g["route_type"] = g["route_id"].map(routes["route_type"])
    return g[g["boardings_per_seat"] > min_bps].sort_values("boardings_per_seat", ascending=False).reset_index(drop=True)


def intercity_weekend_load(tables: Tables, route_id: str = "IC02", departure_time: str = "08:30",
                           direction: str = "outbound") -> pd.DataFrame:
    """Per weekend date: boardings/seats and peak onboard/seats for one intercity departure."""
    t = trip_boardings(tables["trips"], tables["tickets"])
    sel = t[(t["route_id"] == route_id) & (t["departure_time"] == departure_time) & (t["direction"] == direction)
            & (t["day_type"] == "weekend")]
    occ = occupancy_by_trip(sel, tables["tickets"][tables["tickets"]["trip_id"].isin(sel["trip_id"])], tables["route_stops"])
    out = sel.merge(occ, on="trip_id")
    out["boardings_per_seat"] = out["boardings"] / out["seats"]
    out["peak_onboard_per_seat"] = out["peak_onboard"] / out["seats"]
    return out[["service_date", "trip_id", "seats", "boardings", "boardings_per_seat", "peak_onboard", "peak_onboard_per_seat"]]


# ----------------------------------------------------------------- finding 2: demand with low state capacity
def capacity_gap_window(tables: Tables, zone_id: str = "Z13", hour: int = 7) -> dict:
    """Weekday trips departing in ``hour`` that serve ``zone_id``, and how loaded they are.

    Returns trips per weekday, seats offered per weekday, mean boardings/seat, mean peak onboard/seat and the same
    boardings per seat for the other weekday hours of the same routes (for contrast).
    """
    stops, rs = tables["stops"], tables["route_stops"]
    zone_stops = set(stops.loc[stops["zone_id"] == zone_id, "stop_id"])
    serving_routes = set(rs.loc[rs["stop_id"].isin(zone_stops), "route_id"])
    t = trip_boardings(tables["trips"], tables["tickets"])
    t = t[(t["day_type"] == "weekday") & t["route_id"].isin(serving_routes)]
    n_days = t["service_date"].nunique()
    win = t[t["dep_hour"] == hour]
    occ = occupancy_by_trip(win, tables["tickets"][tables["tickets"]["trip_id"].isin(win["trip_id"])], rs)
    win = win.merge(occ, on="trip_id", how="left")
    other = t[t["dep_hour"] != hour]
    # passengers headed to the zone on those trips
    tk = tables["tickets"]
    to_zone = tk[tk["trip_id"].isin(win["trip_id"]) & tk["dest_stop_id"].isin(zone_stops)]["passenger_count"].sum()
    return {
        "serving_routes": sorted(serving_routes),
        "trips_per_weekday": len(win) / n_days,
        "seats_per_weekday": win["seats"].sum() / n_days,
        "boardings_per_seat": win["boardings"].sum() / win["seats"].sum(),
        "peak_onboard_per_seat": float((win["peak_onboard"] / win["seats"]).mean()),
        "pax_to_zone_per_weekday": float(to_zone / n_days),
        "other_hours_boardings_per_seat": other["boardings"].sum() / other["seats"].sum(),
    }


# ----------------------------------------------------------------- finding 3: morning O-D toward employment
def top_od_pairs(tables: Tables, hours: tuple[int, int] = (7, 10), top: int = 5) -> pd.DataFrame:
    """Top weekday zone-to-zone pairs by passengers whose boarding timestamp hour is in [hours[0], hours[1])."""
    tk = tables["tickets"].merge(tables["trips"][["trip_id", "day_type"]], on="trip_id")
    tk = tk[(tk["day_type"] == "weekday") & tk["timestamp"].dt.hour.between(hours[0], hours[1] - 1)]
    z = stop_zone_map(tables["stops"])
    tk = tk.assign(origin_zone_id=tk["origin_stop_id"].map(z), dest_zone_id=tk["dest_stop_id"].map(z))
    g = tk.groupby(["origin_zone_id", "dest_zone_id"])["passenger_count"].sum().sort_values(ascending=False).head(top).reset_index()
    zt = tables["zones"].set_index("zone_id")["zone_type"]
    g["origin_type"] = g["origin_zone_id"].map(zt)
    g["dest_type"] = g["dest_zone_id"].map(zt)
    return g


# ----------------------------------------------------------------- finding 4: evening intercity slot gap
def evening_slot_gap(tables: Tables, corridor: str = "Rajkot-Somnath", start: str = "18:00", end: str = "22:30") -> dict:
    routes = tables["routes"]
    rids = set(routes.loc[routes["corridor"] == corridor, "route_id"])
    t = tables["trips"]
    st = t[t["route_id"].isin(rids) & (t["departure_time"] >= start) & (t["departure_time"] <= end)]
    comp = tables["competitor_services"]
    c = comp[(comp["route_pair"] == corridor) & (comp["day_type"] == "weekday")]
    slot = c[(c["departure_time"] >= start) & (c["departure_time"] <= end)]
    ac_slot = slot[slot["bus_type"].isin(["AC_seater", "AC_sleeper", "premium"])]
    rest = c[~c.index.isin(slot.index)]
    # state fare for the same corridor (median ticket fare per passenger for the longest origin-destination pair)
    reviews = tables["reviews"]
    rv = reviews[reviews["route_pair"] == corridor]
    return {
        "state_trips_in_window": len(st),
        "private_services_in_window": len(slot),
        "private_ac_services_in_window": len(ac_slot),
        "private_rating_in_window": float(slot["rating"].mean()),
        "private_rating_outside_window": float(rest["rating"].mean()) if len(rest) else float("nan"),
        "private_median_base_fare_in_window": float(slot["base_fare_inr"].median()),
        "private_median_surge_fare_in_window": float(slot["surge_fare_inr"].median()),
        "state_review_rating": float(rv.loc[rv["operator_type"] == "state", "rating"].mean()),
        "private_review_rating": float(rv.loc[rv["operator_type"] == "private", "rating"].mean()),
    }


# ----------------------------------------------------------------- finding 5: survey
def switch_condition_counts(survey: pd.DataFrame) -> pd.Series:
    priv = survey[survey["current_mode"].isin(["car", "two_wheeler"])]
    lists = priv["switch_conditions"].map(json.loads)
    return pd.Series([c for l in lists for c in l]).value_counts()


def fit_logistic(X: np.ndarray, y: np.ndarray, iters: int = 50) -> np.ndarray:
    """Plain IRLS logistic regression (intercept first). Small helper so tests need no extra dependency."""
    Xd = np.column_stack([np.ones(len(X)), X])
    beta = np.zeros(Xd.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xd @ beta))
        W = p * (1 - p)
        H = Xd.T @ (Xd * W[:, None]) + 1e-8 * np.eye(len(beta))
        step = np.linalg.solve(H, Xd.T @ (y - p))
        beta += step
        if np.abs(step).max() < 1e-9:
            break
    return beta


def survey_design_matrix(survey: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    s = survey[survey["switch_intent"].notna()].copy()
    conds = s["switch_conditions"].map(json.loads)
    X = pd.DataFrame({
        "cond_reliability": conds.map(lambda c: int("reliability" in c)),
        "cond_ac_comfort": conds.map(lambda c: int("ac_comfort" in c)),
        "cond_frequency": conds.map(lambda c: int("frequency" in c)),
        "cond_lower_fare": conds.map(lambda c: int("lower_fare" in c)),
        "mode_car": (s["current_mode"] == "car").astype(int),
        "purpose_work": (s["trip_purpose"] == "work").astype(int),
        "income_high": s["income_band"].isin(["upper_middle", "high"]).astype(int),
    })
    return X, s["switch_intent"].astype(int).to_numpy()


# ----------------------------------------------------------------- finding 6: CCTV peak
def cctv_hourly_profile(tables: Tables, location_id: str = "S01", day_type: str = "weekday") -> pd.Series:
    """Mean inbound person count per hour per day at a location on days of ``day_type``."""
    c = tables["cctv_counts"]
    c = c[(c["location_id"] == location_id) & (c["class"] == "person") & (c["direction"] == "inbound")].copy()
    trips = tables["trips"][["service_date", "day_type"]].drop_duplicates()
    trips = trips.assign(date=pd.to_datetime(trips["service_date"]))
    c["date"] = c["timestamp_min"].dt.normalize()
    c = c.merge(trips[["date", "day_type"]], on="date")
    c = c[c["day_type"] == day_type]
    c["hour"] = c["timestamp_min"].dt.hour
    per_day_hour = c.groupby(["date", "hour"])["count"].sum().reset_index()
    return per_day_hour.groupby("hour")["count"].mean()


def planted_summary(tables: Tables) -> dict:
    """Everything the validate CLI prints about the planted findings."""
    hl = high_load_route_hours(tables)
    wk = intercity_weekend_load(tables)
    prof = cctv_hourly_profile(tables)
    X, y = survey_design_matrix(tables["survey_responses"])
    return {
        "high_load_route_hours": hl[["route_id", "dep_hour", "boardings_per_seat"]].round(2).to_dict("records"),
        "intercity_weekend_ac_min_boardings_per_seat": float(wk["boardings_per_seat"].min()),
        "intercity_weekend_ac_min_peak_onboard_per_seat": float(wk["peak_onboard_per_seat"].min()),
        "capacity_gap_z13_hour7": capacity_gap_window(tables),
        "top_od_weekday_07_10": top_od_pairs(tables, top=3).to_dict("records"),
        "evening_gap_rajkot_somnath": evening_slot_gap(tables),
        "top3_switch_conditions": switch_condition_counts(tables["survey_responses"]).head(3).to_dict(),
        "cctv_s01_weekday_peak_hour": int(prof.idxmax()),
        "cctv_s01_weekday_peak_vs_other_ratio": float(prof.loc[[7, 8]].mean() / prof.drop([7, 8]).mean()),
        "survey_logistic_n": int(len(y)),
    }


# ----------------------------------------------------------------- pass/fail evaluation of planted findings
from dataclasses import dataclass  # noqa: E402

from modules.data_gen import constants as _C  # noqa: E402

EXPECTED_HIGH_LOAD = {("L05", 7), ("L05", 8), ("L05", 17), ("L07", 7)}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def ticket_stop_order_violations(tables: Tables) -> int:
    """Tickets whose boarding stop is not strictly before the alighting stop in the trip's direction."""
    trips, tk, rs = tables["trips"], tables["tickets"], tables["route_stops"]
    n_stops = rs.groupby("route_id")["stop_seq"].max()
    seq = rs.set_index(["route_id", "stop_id"])["stop_seq"]
    m = tk.merge(trips[["trip_id", "route_id", "direction"]], on="trip_id")
    o = seq.reindex(pd.MultiIndex.from_arrays([m["route_id"], m["origin_stop_id"]])).to_numpy()
    d = seq.reindex(pd.MultiIndex.from_arrays([m["route_id"], m["dest_stop_id"]])).to_numpy()
    inb = m["direction"].eq("inbound").to_numpy()
    bad = np.where(inb, o <= d, o >= d) | np.isnan(o) | np.isnan(d)
    return int(bad.sum())


def is_full_period(tables: Tables) -> bool:
    return tables["trips"]["service_date"].nunique() >= _C.N_DAYS


def evaluate_planted(tables: Tables) -> list[Check]:
    """Pass/fail for each planted finding (valid for the full 42-day period; see ``is_full_period``)."""
    out: list[Check] = []
    hl = high_load_route_hours(tables)
    got = set(zip(hl["route_id"], hl["dep_hour"]))
    out.append(Check("F1 high-load local route-hours == planted set (+L07 07h gap consequence)", got == EXPECTED_HIGH_LOAD,
                     f"detected={sorted(got)} min boardings/seat={hl['boardings_per_seat'].min():.2f}"))
    wk = intercity_weekend_load(tables)
    ok = len(wk) >= 10 and wk["boardings_per_seat"].min() >= 0.95 and wk["peak_onboard_per_seat"].min() >= 0.95
    out.append(Check("F1 Rajkot->Somnath 08:30 AC seater ~full every weekend", bool(ok),
                     f"dates={len(wk)} min boardings/seat={wk['boardings_per_seat'].min():.2f} min peak/seat={wk['peak_onboard_per_seat'].min():.2f}"))
    g = capacity_gap_window(tables)
    ok = (g["serving_routes"] == ["L07"] and g["trips_per_weekday"] == 1.0 and g["boardings_per_seat"] >= 1.5
          and g["other_hours_boardings_per_seat"] <= 1.0 and g["pax_to_zone_per_weekday"] >= g["seats_per_weekday"])
    out.append(Check("F2 Shapar-Veraval (Z13) weekday 07h: demand with one trip", bool(ok),
                     f"trips/day={g['trips_per_weekday']:.1f} boardings/seat={g['boardings_per_seat']:.2f} pax_to_zone/day={g['pax_to_zone_per_weekday']:.0f} seats/day={g['seats_per_weekday']:.0f}"))
    od = top_od_pairs(tables, top=10)
    top = od.iloc[0]
    best_non_emp = od[od["dest_type"] != "employment"]["passenger_count"].max()
    ok = top["origin_type"] == "residential" and top["dest_type"] == "employment" and top["passenger_count"] >= 1.2 * best_non_emp
    out.append(Check("F3 top weekday 07-10 O-D is residential -> employment", bool(ok),
                     f"{top['origin_zone_id']}->{top['dest_zone_id']} pax={top['passenger_count']} best_non_employment_dest={best_non_emp}"))
    e = evening_slot_gap(tables)
    ok = (e["state_trips_in_window"] == 0 and e["private_ac_services_in_window"] >= 5
          and e["private_rating_in_window"] >= 4.3 and e["private_rating_in_window"] - e["private_rating_outside_window"] >= 0.3
          and e["state_review_rating"] < e["private_review_rating"])
    out.append(Check("F4 Rajkot-Somnath evening slot 18:00-22:30: no state trips, private AC services", bool(ok),
                     f"state={e['state_trips_in_window']} private_ac={e['private_ac_services_in_window']} rating_in={e['private_rating_in_window']:.2f}"))
    top3 = set(switch_condition_counts(tables["survey_responses"]).head(3).index)
    X, y = survey_design_matrix(tables["survey_responses"])
    beta = dict(zip(["intercept"] + list(X.columns), fit_logistic(X.to_numpy(float), y.astype(float))))
    true = _C.INTENT_COEF
    coef_ok = all(beta[k] > 0 and abs(beta[k] - true[k]) < 0.6 for k in ("cond_reliability", "cond_ac_comfort", "cond_frequency"))
    out.append(Check("F5 survey top-3 switch conditions = reliability, AC comfort, frequency; logistic recovers signs",
                     top3 == {"reliability", "ac_comfort", "frequency"} and coef_ok,
                     f"top3={sorted(top3)} fitted={{{', '.join(f'{k}: {beta[k]:.2f}' for k in ('cond_reliability', 'cond_ac_comfort', 'cond_frequency'))}}}"))
    prof = cctv_hourly_profile(tables)
    ratio = float(prof.loc[[7, 8]].mean() / prof.drop([7, 8]).mean())
    out.append(Check("F6 Rajkot Central CCTV weekday footfall peaks 07:00-09:00", int(prof.idxmax()) in (7, 8) and ratio >= 2.0,
                     f"peak_hour={int(prof.idxmax())} ratio_vs_other_hours={ratio:.2f}"))
    return out
