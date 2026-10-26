"""Synthetic source-table generation (Milestone 1).

    python -m modules.data_gen.generate [--seed 42] [--out DIR] [--days 42] [--no-osm]

* NEVER touches the network. Real OSM coordinates come from the cache written by
  ``python -m modules.data_gen.fetch_osm`` (``data/raw/osm_places.parquet``); anything missing from the cache
  uses the hand-entered ``manual_demo_input`` fallback table and is labelled as such (``coord_source`` column).
* Fully deterministic for a given seed: every draw comes from ``np.random.default_rng([seed, stage_id])``;
  no wall-clock values inside table contents (timestamps live only in provenance sidecars).
* ``out_dir`` is a data ROOT (tables go to ``<out_dir>/synthetic/*.parquet``); default is ``config.DATA_DIR``.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import config
from modules.data import io
from modules.data.provenance import make_provenance
from modules.data_gen import assets as A
from modules.data_gen import cctv as CC
from modules.data_gen import competition as CP
from modules.data_gen import constants as C
from modules.data_gen import geography as G
from modules.data_gen import network as N
from modules.data_gen import surveys as SV
from modules.data_gen import tickets as TK
from modules.data_gen import trips as TR

TABLE_ORDER = ("zones", "stops", "routes", "route_stops", "trips", "tickets", "cctv_counts", "survey_responses",
               "competitor_services", "reviews", "assets_assessment", "digital_assessment")
N_REVIEWS = 420

TRIP_COLUMNS = ["trip_id", "route_id", "service_date", "departure_time", "day_type", "seats", "operator", "bus_type",
                "scheduled_minutes", "operating_cost_inr", "source_type", "direction", "actual_departure_time",
                "departure_delay_min"]


def _rng(seed: int, stage: int) -> np.random.Generator:
    return np.random.default_rng([int(seed), int(stage)])


def generate_all(seed: int = config.SEED, out_dir: Path | str | None = None, *, days: int = C.N_DAYS,
                 use_osm: bool = True, osm_dir: Path | str | None = None, write: bool = True,
                 verbose: bool = False) -> dict[str, pd.DataFrame]:
    """Generate all source tables. Returns ``{table_name: DataFrame}``; writes parquet + provenance unless ``write=False``."""
    t0 = time.perf_counter()

    def log(msg: str) -> None:
        if verbose:
            print(f"[{time.perf_counter() - t0:6.1f}s] {msg}")

    osm = G.load_osm_cache(osm_dir) if use_osm else None
    resolver = G.CoordResolver(osm)
    osm_state = f"{resolver.n_osm_keys} OSM-cached anchor(s)" if resolver.n_osm_keys else "no OSM cache (manual_demo_input fallback)"
    log(f"geography: {osm_state}")

    zones = G.build_zones(resolver, _rng(seed, C.STAGE_ZONES), seed)
    stops = G.build_stops(resolver)
    routes, route_stops = N.build_route_tables(stops)
    log("zones/stops/routes")

    trips = TR.generate_trips(routes, route_stops, days, _rng(seed, C.STAGE_TRIPS))
    log(f"trips: {len(trips)}")
    grid = TK.RouteGrid.build(route_stops, stops)
    tickets, aux = TK.generate_tickets(trips, grid, zones, stops, _rng(seed, C.STAGE_TICKETS))
    log(f"tickets: {len(tickets)}")
    cctv = CC.generate_cctv(trips, grid, aux, days, _rng(seed, C.STAGE_CCTV))
    log(f"cctv: {len(cctv)}")
    survey = SV.generate_survey(zones, C.N_SURVEY_RESPONSES, _rng(seed, C.STAGE_SURVEY), seed)
    corridor_km = routes.dropna(subset=["corridor"]).groupby("corridor")["length_km"].max().to_dict()
    competitors = CP.generate_competitors(corridor_km, _rng(seed, C.STAGE_COMPETITION))
    reviews = SV.generate_reviews(N_REVIEWS, _rng(seed, C.STAGE_REVIEWS))
    assets_df, digital_df = A.generate_assets(_rng(seed, C.STAGE_ASSETS))

    trips = trips[TRIP_COLUMNS].reset_index(drop=True)
    tables = {
        "zones": zones, "stops": stops, "routes": routes, "route_stops": route_stops, "trips": trips,
        "tickets": tickets, "cctv_counts": cctv, "survey_responses": survey, "competitor_services": competitors,
        "reviews": reviews, "assets_assessment": assets_df, "digital_assessment": digital_df,
    }
    if write:
        _write_all(tables, seed, out_dir, days, osm_state)
        log("written")
    return tables


def _provenance_for(name: str, seed: int, days: int, osm_state: str):
    common = {"days": days, "start_date": str(C.START_DATE), "festival_dates": [str(d) for d in C.FESTIVAL_DATES],
              "festival_name": C.FESTIVAL_NAME, "geography": osm_state}
    desc = {
        "zones": "Synthetic demo zones (attributes synthetic). Coordinates: see coord_source (OSM cache or manual_demo_input).",
        "stops": "Synthetic demo stops placed at/near real places. Coordinates: see coord_source.",
        "routes": "SYNTHETIC DEMONSTRATION ROUTES. Not real GSRTC/RMTS routes or timetables.",
        "route_stops": "Ordered stop list with cumulative km/minutes (outbound frame) for each synthetic route.",
        "trips": "Synthetic state-operated trips with synthetic departure delays and per-km operating cost assumptions.",
        "tickets": "Synthetic tickets simulated from a latent demand process; excess demand is unmet and not ticketed.",
        "cctv_counts": "SYNTHETIC aggregate CCTV counts (5-minute buckets). Not detector output.",
        "survey_responses": "Synthetic survey responses; switch_intent from a documented logistic mechanism.",
        "competitor_services": "Synthetic private competitor services/fares/ratings. Not scraped or real.",
        "reviews": "Synthetic template-based reviews with themes tagged at generation time.",
        "assets_assessment": "Synthetic infrastructure assessment scores (0-5).",
        "digital_assessment": "Synthetic digital maturity scores (0-5).",
    }[name]
    assumptions: dict = dict(common)
    if name in ("trips", "routes"):
        assumptions.update({"operating_cost_per_km_inr": C.OPERATING_COST_PER_KM_INR, "bus_type_seats": C.BUS_TYPE_SEATS,
                            "speed_kmph": C.SPEED_KMPH, "road_factor_local": C.ROAD_FACTOR_LOCAL,
                            "road_factor_intercity": C.ROAD_FACTOR_INTERCITY,
                            "on_time_tolerance_min_suggested": C.DELAY_ON_TIME_TOLERANCE_MIN})
    if name == "tickets":
        assumptions.update({"fare_table": C.FARE_TABLE, "concession_factor": C.CONCESSION_FACTOR,
                            "local_crush_factor": C.LOCAL_CRUSH_FACTOR, "intercity_crush_factor": C.INTERCITY_CRUSH_FACTOR,
                            "group_merge_prob": C.GROUP_MERGE_PROB, "fare_inr_semantics": "total paid for the ticket (all passengers)"})
    if name == "cctv_counts":
        assumptions.update({"bucket_minutes": CC.BUCKET_MIN, "window": "05:00-23:00", "locations": list(G.CCTV_LOCATIONS)})
    if name == "survey_responses":
        assumptions.update({"intent_intercept": C.INTENT_INTERCEPT, "intent_coef": C.INTENT_COEF, "n": C.N_SURVEY_RESPONSES})
    st = "synthetic"
    return make_provenance(st, seed=seed, assumptions=assumptions, description=desc)


def _write_all(tables: dict[str, pd.DataFrame], seed: int, out_dir, days: int, osm_state: str) -> None:
    for name in TABLE_ORDER:
        io.write_table(tables[name], name, "synthetic", base_dir=out_dir, provenance=_provenance_for(name, seed, days, osm_state))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic source tables (offline, deterministic).")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--out", type=Path, default=None, help="data root (default: repo data/ directory)")
    ap.add_argument("--days", type=int, default=C.N_DAYS)
    ap.add_argument("--no-osm", action="store_true", help="ignore the OSM cache and use manual_demo_input coordinates")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    tables = generate_all(args.seed, args.out, days=args.days, use_osm=not args.no_osm, verbose=True)
    elapsed = time.perf_counter() - t0
    print(f"\nSimulated data for demonstration. Generated in {elapsed:.1f}s (seed={args.seed}, days={args.days}):")
    for name in TABLE_ORDER:
        print(f"  {name:22s} {len(tables[name]):>9,d} rows")
    if args.no_validate:
        return 0
    from modules.data_gen import validate
    return validate.run(tables, verbose=True)


if __name__ == "__main__":
    sys.exit(main())
