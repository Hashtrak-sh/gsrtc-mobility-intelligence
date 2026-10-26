"""Build the processed analytics tables (Milestone 2).

Usage: ``python -m modules.analytics.run [--out-dir DIR]``. Reads the source tables from ``data/synthetic/`` and writes the
derived tables to ``data/processed/`` with provenance sidecars. Deterministic: same inputs -> identical tables.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

import config
from modules.analytics import cctv as CC
from modules.analytics import findings as FD
from modules.analytics import gaps, occupancy, od, recommendations, route_kpis, scoring
from modules.competition import gap_score as CG
from modules.data import io
from modules.data.provenance import make_provenance
from modules.survey import mode_choice

OUTPUT_TABLES = ("route_kpis", "route_summary", "hourly_demand_supply", "stop_occupancy", "od_flows", "route_scores",
                 "recommendations", "cctv_hourly_profile", "competition_analysis")

DESCRIPTIONS = {
    "route_kpis": "Route x service-date KPIs derived from synthetic tickets/trips. Load factor = passenger-km / seat-km.",
    "route_summary": "Route-level KPI summary (single source of truth for route KPIs), derived from synthetic data.",
    "hourly_demand_supply": "Average-day demand vs seats by route-direction-hour and corridor-hour; ticketed demand is censored (gaps are lower bounds); private-market demand is an assumption.",
    "stop_occupancy": "Average-bus occupancy progression by stop (boardings - alightings), flags not clamps.",
    "od_flows": "Zone-pair x hour x day-type passenger flows derived from synthetic tickets.",
    "route_scores": "Transparent rule-based route potential score (demo-v1 weights). Not an AI prediction.",
    "recommendations": "Rule-generated recommendations with evidence, assumptions, expected impact and constraints.",
    "cctv_hourly_profile": "Mean inbound persons per hour from SYNTHETIC CCTV counts.",
    "competition_analysis": "Corridor x hour x day-type state vs synthetic private departures, fare index (normal/surge) and competitive gap score (demo-comp-v1 weights). Competitor departures are from Rajkot only; both directions assumed to mirror.",
}


def load_sources(base_dir: Path | str | None = None) -> dict[str, pd.DataFrame]:
    return {n: io.read_table(n, "synthetic", base_dir) for n in io.SOURCE_TABLES}


def compute_all(t: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """All derived tables (plus intermediates ``trips_sum`` and ``legs``, which are not written) from source tables."""
    legs = occupancy.ticket_legs(t["trips"], t["tickets"], t["route_stops"])
    profile = occupancy.trip_stop_profile(t["trips"], legs, t["route_stops"])
    ts = occupancy.trip_summary(t["trips"], t["tickets"], profile, t["routes"])
    tm = route_kpis.trip_metrics(ts, legs)
    kpis = route_kpis.route_kpis(tm)
    summary = route_kpis.route_summary(tm, t["routes"], t["trips"])
    hourly = gaps.hourly_demand_supply(ts, profile, t["routes"], t["stops"], t["competitor_services"])
    stop_occ = occupancy.stop_occupancy(ts, profile)
    flows = od.od_flows(legs, t["trips"], t["stops"], t["routes"])
    scores = scoring.route_scores(summary, hourly, t["routes"], t["route_stops"], t["stops"], t["zones"], t["trips"])
    comp = CG.competition_analysis(t["trips"], t["competitor_services"], t["routes"], t["reviews"])
    recs = recommendations.generate_recommendations(hourly, summary, scores, t["routes"], ts, t["stops"], t["competitor_services"], legs, comp)
    cctv = CC.cctv_hourly_profile(t["cctv_counts"], t["trips"])
    return {"route_kpis": kpis, "route_summary": summary, "hourly_demand_supply": hourly, "stop_occupancy": stop_occ,
            "od_flows": flows, "route_scores": scores, "recommendations": recs, "cctv_hourly_profile": cctv, "competition_analysis": comp,
            "trips_sum": ts, "legs": legs}


def assumptions() -> dict:
    return {
        "load_factor_pct": "passenger-km / seat-km x 100", "peak_load_factor": "max link onboard / seats",
        "boardings_per_seat": "passengers / seats (turnover)",
        "reliability_band_min": list(config.RELIABILITY_ON_TIME_BAND_MIN),
        "crowding_gap_index_threshold": config.CROWDING_GAP_INDEX_THRESHOLD,
        "private_market_occupancy_assumption": config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION,
        "service_target_load_factor": config.SERVICE_TARGET_LOAD_FACTOR,
        "state_capture_share_assumption": config.STATE_CAPTURE_SHARE,
        "competitive_gap_weights": config.COMPETITIVE_GAP_WEIGHTS.components(),
        "competitive_gap_weight_version": config.COMPETITIVE_GAP_WEIGHTS.weight_version,
        "route_score_weights": config.ROUTE_SCORE_WEIGHTS.components(),
        "weight_version": config.ROUTE_SCORE_WEIGHTS.weight_version,
        "ticket_revenue_only": True, "contribution_is_not_profit": True,
    }


def write_all(res: dict[str, pd.DataFrame], base_dir: Path | str | None = None) -> None:
    for name in OUTPUT_TABLES:
        prov = make_provenance("synthetic", assumptions=assumptions(), description=DESCRIPTIONS[name])
        io.write_table(res[name], name, "processed", base_dir=base_dir, provenance=prov)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compute and write processed analytics tables.")
    ap.add_argument("--base-dir", default=None, help="data root override (default: repo data/)")
    args = ap.parse_args(argv)
    t0 = time.time()
    try:
        tables = load_sources(args.base_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}\nRun: python -m modules.data_gen.generate", file=sys.stderr)
        return 1
    res = compute_all(tables)
    write_all(res, args.base_dir)
    print(f"{config.SIMULATION_BADGE_TEXT}. Processed tables written in {time.time() - t0:.1f}s:")
    for n in OUTPUT_TABLES:
        print(f"  {n:22s} {len(res[n]):>7,d} rows x {res[n].shape[1]} cols")
    model = mode_choice.run_and_write(tables["survey_responses"], args.base_dir)
    if model is None:
        print("Survey switch-intent model: skipped (see note above; optional, needs scikit-learn).")
    else:
        m = model["metrics"].set_index("metric")
        print(f"Survey switch-intent model written ({mode_choice.TABLE_COEF}, {mode_choice.TABLE_METRICS}); test ROC-AUC "
              f"{m.loc['roc_auc', 'model']:.3f} (baseline 0.5), Brier {m.loc['brier_score', 'model']:.3f} "
              f"(baseline {m.loc['brier_score', 'baseline']:.3f}). {mode_choice.ILLUSTRATIVE_LABEL}.")
    print("Planted findings (detected from analytics outputs):")
    for f in FD.detect_planted(res, tables):
        print(f"  [{'PASS' if f.ok else 'FAIL'}] {f.name}: {f.detail}")
    print(f"Recommendations ({len(res['recommendations'])}):")
    for r in res["recommendations"].itertuples():
        print(f"  {r.recommendation_id} [{r.priority}] {r.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
