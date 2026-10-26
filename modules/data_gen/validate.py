"""Validation of the generated source tables.

    python -m modules.data_gen.validate [--data-dir DIR]

Checks columns, primary keys, foreign keys, enum values, non-negativity / positivity, occupancy progression,
coordinates in the pilot bounding box (documented exceptions only), JSON encoding and the planted findings.
Exits non-zero if any check fails; prints a readable report.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config
from modules.data import io
from modules.data_gen import checks as K
from modules.data_gen import constants as C

EXPECTED_COLUMNS: dict[str, list[str]] = {
    "zones": ["zone_id", "h3_id", "name", "lat", "lon", "population", "workers_resident", "jobs", "poi_counts",
              "zone_type", "source_type", "seed", "coord_source"],
    "stops": ["stop_id", "name", "lat", "lon", "zone_id", "is_bus_stand", "stop_type", "source_type", "coord_source"],
    "routes": ["route_id", "name", "route_type", "origin_stop_id", "destination_stop_id", "stop_sequence", "length_km",
               "bus_type", "minimum_service", "source_type", "corridor"],
    "route_stops": ["route_id", "stop_seq", "stop_id", "cum_km", "cum_minutes"],
    "trips": ["trip_id", "route_id", "service_date", "departure_time", "day_type", "seats", "operator", "bus_type",
              "scheduled_minutes", "operating_cost_inr", "source_type", "direction", "actual_departure_time",
              "departure_delay_min"],
    "tickets": ["ticket_id", "trip_id", "origin_stop_id", "dest_stop_id", "timestamp", "fare_inr", "passenger_type",
                "passenger_count", "source_type"],
    "cctv_counts": ["location_id", "timestamp_min", "direction", "class", "count", "measurement_method", "source_type"],
    "survey_responses": ["response_id", "timestamp", "current_mode", "trip_purpose", "origin_zone_id", "dest_zone_id",
                         "reasons", "open_text", "switch_conditions", "income_band", "switch_intent", "source_type"],
    "competitor_services": ["service_id", "route_pair", "operator", "departure_time", "day_type", "bus_type",
                            "base_fare_inr", "surge_fare_inr", "seats", "rating", "source_type"],
    "reviews": ["review_id", "operator_type", "route_pair", "rating", "text", "themes", "sentiment", "source_type"],
    "assets_assessment": ["asset_id", "asset_name", "asset_type", "dimension", "score", "evidence_note", "source_type"],
    "digital_assessment": ["assessment_id", "asset_id", "capability", "maturity_score", "evidence_note", "source_type"],
}
PRIMARY_KEYS = {"zones": "zone_id", "stops": "stop_id", "routes": "route_id", "trips": "trip_id", "tickets": "ticket_id",
                "survey_responses": "response_id", "competitor_services": "service_id", "reviews": "review_id",
                "digital_assessment": "assessment_id"}
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


def _fk(child: pd.Series, parent: pd.Series) -> int:
    return int((~child.isin(set(parent))).sum())


def validate_tables(t: dict[str, pd.DataFrame]) -> list[Result]:
    R: list[Result] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        R.append(Result(name, bool(ok), detail))

    missing = [n for n in EXPECTED_COLUMNS if n not in t]
    add("all tables present", not missing, f"missing={missing}" if missing else f"{len(t)} tables")
    if missing:
        return R
    for n, cols in EXPECTED_COLUMNS.items():
        add(f"{n}: columns match contract", list(t[n].columns) == cols,
            "" if list(t[n].columns) == cols else f"got {list(t[n].columns)}")
        add(f"{n}: not empty", len(t[n]) > 0, f"{len(t[n])} rows")
    for n, k in PRIMARY_KEYS.items():
        add(f"{n}: {k} unique and non-null", t[n][k].notna().all() and t[n][k].is_unique)
    add("route_stops: (route_id, stop_seq) unique", not t["route_stops"].duplicated(["route_id", "stop_seq"]).any())

    z, s, r, rs, tr, tk = t["zones"], t["stops"], t["routes"], t["route_stops"], t["trips"], t["tickets"]
    sv, cc = t["survey_responses"], t["cctv_counts"]

    # --- foreign keys
    add("FK stops.zone_id -> zones", _fk(s["zone_id"], z["zone_id"]) == 0)
    add("FK routes.origin/destination_stop_id -> stops",
        _fk(r["origin_stop_id"], s["stop_id"]) == 0 and _fk(r["destination_stop_id"], s["stop_id"]) == 0)
    add("FK route_stops.route_id -> routes", _fk(rs["route_id"], r["route_id"]) == 0)
    add("FK route_stops.stop_id -> stops", _fk(rs["stop_id"], s["stop_id"]) == 0)
    seq_ok = all(json.loads(row.stop_sequence) == list(rs[rs["route_id"] == row.route_id].sort_values("stop_seq")["stop_id"])
                 for row in r.itertuples())
    add("routes.stop_sequence JSON == route_stops order", seq_ok)
    add("FK trips.route_id -> routes", _fk(tr["route_id"], r["route_id"]) == 0)
    add("FK tickets.trip_id -> trips", _fk(tk["trip_id"], tr["trip_id"]) == 0)
    add("FK tickets.origin/dest_stop_id -> stops",
        _fk(tk["origin_stop_id"], s["stop_id"]) == 0 and _fk(tk["dest_stop_id"], s["stop_id"]) == 0)
    add("FK survey origin/dest_zone_id -> zones", _fk(sv["origin_zone_id"], z["zone_id"]) == 0 and _fk(sv["dest_zone_id"], z["zone_id"]) == 0)
    add("FK cctv_counts.location_id -> stops", _fk(cc["location_id"], s["stop_id"]) == 0)
    add("FK digital_assessment.asset_id -> assets_assessment", _fk(t["digital_assessment"]["asset_id"], t["assets_assessment"]["asset_id"]) == 0)
    add("tickets: boarding stop before alighting stop in trip direction", K.ticket_stop_order_violations(t) == 0,
        f"violations={K.ticket_stop_order_violations(t)}")

    # --- enums
    def enum(name: str, ser: pd.Series, allowed) -> None:
        bad = sorted(set(ser.dropna().unique()) - set(allowed))
        add(f"enum {name}", not bad, f"unexpected={bad}" if bad else "")

    enum("zones.zone_type", z["zone_type"], C.ZONE_TYPES)
    enum("stops.stop_type", s["stop_type"], C.STOP_TYPES)
    enum("routes.route_type", r["route_type"], C.ROUTE_TYPES)
    enum("routes.bus_type", r["bus_type"], C.BUS_TYPES)
    enum("trips.bus_type", tr["bus_type"], C.TRIP_BUS_TYPES)
    enum("trips.day_type", tr["day_type"], C.DAY_TYPES)
    enum("trips.operator", tr["operator"], ("state",))
    enum("trips.direction", tr["direction"], ("outbound", "inbound"))
    enum("tickets.passenger_type", tk["passenger_type"], C.PASSENGER_TYPES)
    enum("cctv.class", cc["class"], C.CCTV_CLASSES)
    enum("cctv.direction", cc["direction"], C.CCTV_DIRECTIONS)
    enum("cctv.measurement_method", cc["measurement_method"], C.CCTV_METHODS)
    enum("survey.current_mode", sv["current_mode"], C.MODES)
    enum("survey.trip_purpose", sv["trip_purpose"], C.PURPOSES)
    enum("survey.income_band", sv["income_band"], C.SURVEY_INCOME_BANDS)
    enum("competitor.bus_type", t["competitor_services"]["bus_type"], C.COMPETITOR_BUS_TYPES)
    enum("competitor.day_type", t["competitor_services"]["day_type"], C.DAY_TYPES)
    enum("reviews.operator_type", t["reviews"]["operator_type"], ("state", "private"))
    enum("assets.asset_type", t["assets_assessment"]["asset_type"], C.ASSET_TYPES)
    enum("assets.dimension", t["assets_assessment"]["dimension"], C.ASSET_DIMENSIONS)
    enum("digital.capability", t["digital_assessment"]["capability"], C.DIGITAL_CAPABILITIES)
    enum("zones/stops coord_source", pd.concat([z["coord_source"], s["coord_source"]]), C.COORD_SOURCES)
    for n, df in t.items():
        if "source_type" in df.columns:
            enum(f"{n}.source_type", df["source_type"], C.SOURCE_TYPES)

    # --- positivity / non-negativity
    add("zones: population, workers, jobs non-negative", bool((z[["population", "workers_resident", "jobs"]] >= 0).all().all()))
    add("trips: seats > 0, scheduled_minutes > 0, operating_cost_inr > 0",
        bool((tr["seats"] > 0).all() and (tr["scheduled_minutes"] > 0).all() and (tr["operating_cost_inr"] > 0).all()))
    add("routes: length_km > 0; route_stops cum_km/cum_minutes non-negative and increasing",
        bool((r["length_km"] > 0).all() and (rs["cum_km"] >= 0).all()
             and rs.sort_values(["route_id", "stop_seq"]).groupby("route_id")["cum_km"].apply(lambda x: x.is_monotonic_increasing).all()
             and rs.sort_values(["route_id", "stop_seq"]).groupby("route_id")["cum_minutes"].apply(lambda x: x.is_monotonic_increasing).all()))
    add("tickets: fare_inr > 0 and passenger_count >= 1", bool((tk["fare_inr"] > 0).all() and (tk["passenger_count"] >= 1).all()))
    add("cctv: count >= 0", bool((cc["count"] >= 0).all()))
    add("competitor: seats > 0, fares > 0, surge >= base",
        bool((t["competitor_services"][["seats", "base_fare_inr", "surge_fare_inr"]] > 0).all().all()
             and (t["competitor_services"]["surge_fare_inr"] >= t["competitor_services"]["base_fare_inr"]).all()))
    add("scores within 0-5", bool(t["assets_assessment"]["score"].between(0, 5).all()
                                  and t["digital_assessment"]["maturity_score"].between(0, 5).all()))
    add("ratings within 1-5", bool(t["reviews"]["rating"].between(1, 5).all()
                                   and t["competitor_services"]["rating"].dropna().between(1, 5).all()))
    add("time strings are HH:MM",
        bool(tr["departure_time"].str.match(HHMM).all() and tr["actual_departure_time"].str.match(HHMM).all()
             and t["competitor_services"]["departure_time"].str.match(HHMM).all()))
    add("switch_intent is 0/1 or null", bool(sv["switch_intent"].dropna().isin([0, 1]).all()))

    # --- occupancy progression and capacity rules
    occ = K.occupancy_by_trip(tr, tk, rs)
    add("occupancy never negative and trips end empty", bool((occ["min_onboard"] >= 0).all() and (occ["final_onboard"] == 0).all()),
        f"min_onboard={occ['min_onboard'].min()}")
    o = occ.merge(tr[["trip_id", "route_id", "seats"]], on="trip_id").merge(r[["route_id", "route_type"]], on="route_id")
    cap = np.where(o["route_type"] == "local", np.floor(o["seats"] * C.LOCAL_CRUSH_FACTOR), o["seats"] * C.INTERCITY_CRUSH_FACTOR)
    add("onboard load <= crush limit (local 1.6x seats standing, intercity seats)", bool((o["peak_onboard"] <= cap).all()),
        f"max local peak/seat={(o[o.route_type == 'local'].peak_onboard / o[o.route_type == 'local'].seats).max():.2f}")
    d = pd.to_datetime(tr["service_date"])
    ts = tk["timestamp"]
    add("trip/ticket dates inside service period",
        bool(d.min() == pd.Timestamp(C.START_DATE) and (ts >= d.min()).all() and (ts < d.max() + pd.Timedelta(days=2)).all()))

    # --- coordinates
    exc_stops = set(s.loc[s["name"].isin(C.BBOX_EXCEPTION_STOP_NAMES), "stop_id"])
    exc_zones = set(s.loc[s["stop_id"].isin(exc_stops), "zone_id"])
    sin = np.array([config.PILOT_BBOX.contains(a, b) for a, b in zip(s["lat"], s["lon"])])
    zin = np.array([config.PILOT_BBOX.contains(a, b) for a, b in zip(z["lat"], z["lon"])])
    s_bad = set(s.loc[~sin, "stop_id"]) - exc_stops
    z_bad = set(z.loc[~zin, "zone_id"]) - exc_zones
    add("coordinates inside PILOT_BBOX (documented exceptions: Jamnagar, Ahmedabad)", not s_bad and not z_bad,
        f"stops_outside={sorted(s_bad)} zones_outside={sorted(z_bad)}")
    add("stops outside bbox are only the documented exceptions", set(s.loc[~sin, "stop_id"]) <= exc_stops)

    # --- JSON encoding
    def json_ok(ser: pd.Series, kind: type) -> bool:
        try:
            return all(isinstance(json.loads(x), kind) for x in ser)
        except (TypeError, ValueError):
            return False

    add("JSON columns parse (poi_counts dict; stop_sequence/reasons/switch_conditions/themes list)",
        json_ok(z["poi_counts"], dict) and json_ok(r["stop_sequence"], list) and json_ok(sv["reasons"], list)
        and json_ok(sv["switch_conditions"], list) and json_ok(t["reviews"]["themes"], list))

    # --- planted findings (full 42-day period only)
    if K.is_full_period(t):
        for c in K.evaluate_planted(t):
            add(f"planted: {c.name}", c.ok, c.detail)
    else:
        add("planted findings", True, "skipped (reduced-day run)")
    return R


def run(tables: dict[str, pd.DataFrame], verbose: bool = True) -> int:
    results = validate_tables(tables)
    failed = [x for x in results if not x.ok]
    if verbose:
        print("\nValidation report (Simulated data for demonstration)")
        print("-" * 72)
        for x in results:
            print(f"  [{'PASS' if x.ok else 'FAIL'}] {x.name}" + (f"  -- {x.detail}" if x.detail else ""))
        print("-" * 72)
        print(f"  {len(results) - len(failed)}/{len(results)} checks passed" + ("" if not failed else f"; {len(failed)} FAILED"))
    return 1 if failed else 0


def load_tables(data_dir=None) -> dict[str, pd.DataFrame]:
    return {n: io.read_table(n, "synthetic", base_dir=data_dir) for n in EXPECTED_COLUMNS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate generated synthetic tables.")
    ap.add_argument("--data-dir", default=None, help="data root containing synthetic/ (default: repo data/)")
    args = ap.parse_args(argv)
    try:
        tables = load_tables(args.data_dir)
    except FileNotFoundError as exc:
        print(f"{exc}\nRun: python -m modules.data_gen.generate", file=sys.stderr)
        return 2
    return run(tables)


if __name__ == "__main__":
    sys.exit(main())
