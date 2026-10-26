"""M4 tests: Route Intelligence page (map, candidates, recommendations), route paths, candidate comparability, no network."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.data import io
from modules.routing import candidates as C
from modules.routing import network as N
from modules.routing import run as routing_run
from modules.routing import settings as S

ROOT = Path(__file__).resolve().parents[1]
PAGE = "pages/2_Route_Intelligence.py"
needs_processed = pytest.mark.skipif(
    not all((config.PROCESSED_DIR / f"{t}.parquet").is_file() for t in ("route_summary", "route_paths", "route_candidates", "recommendations")),
    reason="processed data not generated (python -m modules.analytics.run; python -m modules.routing.run)")


def run_page(**state) -> AppTest:
    at = AppTest.from_file(str(ROOT / PAGE), default_timeout=120)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def tables(at: AppTest) -> list[pd.DataFrame]:
    return [d.value for d in at.dataframe]


def md(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


# ------------------------------------------------------------------ route scores on known synthetic cases
@pytest.mark.skipif(not (config.PROCESSED_DIR / "route_scores.parquet").is_file(), reason="processed data not generated")
def test_route_score_ordering_known_cases():
    sc = pd.read_parquet(config.PROCESSED_DIR / "route_scores.parquet")
    local = sc[sc["route_type"] == "local"].sort_values("rank_within_type")
    assert local.iloc[0]["route_id"] == "L05"                                   # planted unmet-demand / crowding route
    l05 = sc.set_index("route_id").loc["L05"]
    assert l05["unmet_demand_score"] == sc[sc["route_type"] == "local"]["unmet_demand_score"].max()
    assert l05["load_factor_score"] == sc[sc["route_type"] == "local"]["load_factor_score"].max()
    prot = sc[sc["protected_minimum_service"]]
    assert set(prot["route_id"]) == {"L09", "L10"}
    assert (prot["social_importance_score"] > 0).all()
    assert set(prot["route_id"]) <= set(local.tail(3)["route_id"])               # low commercial score, still protected
    recs = pd.read_parquet(config.PROCESSED_DIR / "recommendations.parquet")
    p = recs[recs["route_id"].isin(["L09", "L10"])]
    assert set(p["category"]) == {"protect_minimum_service"}                     # never a removal recommendation


# ------------------------------------------------------------------ path / stop IDs
@needs_processed
def test_route_paths_cover_routes_and_stop_ids_resolve():
    rp = io.read_table("route_paths", "processed")
    routes, rs = io.read_table("routes", "synthetic"), io.read_table("route_stops", "synthetic")
    stops = io.read_table("stops", "synthetic")
    assert set(rp["route_id"]) == set(routes["route_id"])
    assert set(rs["stop_id"]) <= set(stops["stop_id"])
    cands = io.read_table("route_candidates", "processed")
    for s in cands["stop_ids_json"]:
        assert set(json.loads(s)) <= set(stops["stop_id"])
    idx = stops.set_index("stop_id")
    for r in rp.itertuples():
        assert r.path_source in ("openstreetmap", "straight_line_fallback")
        coords = json.loads(r.path_geojson)["coordinates"]
        first = rs[rs["route_id"] == r.route_id].sort_values("stop_seq")["stop_id"]
        a, b = idx.loc[first.iloc[0]], idx.loc[first.iloc[-1]]
        limit = (S.MAX_SNAP_M + 300) / 1000
        assert N.haversine_km(a.lat, a.lon, coords[0][1], coords[0][0]) <= limit
        assert N.haversine_km(b.lat, b.lon, coords[-1][1], coords[-1][0]) <= limit


@needs_processed
@pytest.mark.parametrize("route_id", ["L05", "IC02"])
def test_page_shows_stop_sequence_in_route_stops_order(route_id):
    at = run_page(sel_route=route_id)
    assert not at.exception, [e.value for e in at.exception]
    rs = io.read_table("route_stops", "synthetic").query("route_id == @route_id").sort_values("stop_seq")
    seq = next(t for t in tables(at) if "Stop ID" in t.columns)
    assert seq["Stop ID"].tolist() == rs["stop_id"].tolist()                    # outbound is the default direction
    assert len(at.get("plotly_chart")) >= 1
    text = md(at)
    assert "Path source" in text and "OpenStreetMap" in " ".join(c.value for c in at.caption)
    assert len(at.metric) <= 4


@needs_processed
def test_page_route_with_osm_path_and_with_fallback_if_any():
    rp = io.read_table("route_paths", "processed")
    osm = rp[rp["path_source"] == "openstreetmap"]["route_id"].iloc[0]
    assert "real OpenStreetMap roads" in md(run_page(sel_route=osm))
    fb = rp[rp["path_source"] != "openstreetmap"]["route_id"]
    if len(fb):
        at = run_page(sel_route=fb.iloc[0])
        assert not at.exception
        assert "straight-line fallback" in md(at)


@needs_processed
@pytest.mark.parametrize("route_id", ["L05", "L09", "IC02", "L07"])
def test_page_recommendations_equal_table_rows(route_id):
    at = run_page(sel_route=route_id)
    assert not at.exception, [e.value for e in at.exception]
    recs = io.read_table("recommendations", "processed")
    expect = recs[recs["route_id"] == route_id]
    shown = [t for t in tables(at) if "Action" in t.columns and "ID" in t.columns and "Time window" in t.columns]
    if expect.empty:
        assert not shown
    else:
        assert len(shown) == 1
        assert set(shown[0]["ID"]) == set(expect["recommendation_id"])
        assert set(shown[0]["Action"]) == set(expect["title"])
        assert set(shown[0]["Time window"]) == set(expect["time_window"])


@needs_processed
def test_page_candidates_section_flags_and_bounds():
    at = run_page(sel_route="L05")
    text = md(at)
    assert "Candidate routes (illustrative)" in " ".join(h.value for h in at.subheader)
    assert "Illustrative candidate" in " ".join(w.value for w in at.warning)
    assert "Not modelled: fleet size" in text and "L09, L10" in text
    assert "Score breakdown" in " ".join(e.label for e in at.expander)
    cand = next(t for t in tables(at) if "Candidate" in t.columns)
    cdf = io.read_table("route_candidates", "processed")
    assert set(cand["ID"]) <= set(cdf["candidate_id"])


def test_page_without_m4_tables_shows_empty_states(monkeypatch, tmp_path):
    if not (config.PROCESSED_DIR / "route_summary.parquet").is_file():
        pytest.skip("processed data not generated")
    import shutil
    proc = tmp_path / "processed"
    shutil.copytree(config.PROCESSED_DIR, proc, ignore=shutil.ignore_patterns("route_paths*", "route_candidates*"))
    monkeypatch.setattr(config, "LAYER_DIRS", {**config.LAYER_DIRS, "processed": proc})
    at = run_page(sel_route="L05")
    assert not at.exception, [e.value for e in at.exception]
    assert "Route paths not built yet" in md(at) and "Candidate routes not built yet" in md(at)


# ------------------------------------------------------------------ candidate comparability and weights
def test_candidate_weights_in_config_sum_to_one():
    assert sum(config.CANDIDATE_SCORE_WEIGHTS.components().values()) == pytest.approx(1.0)
    assert C.SCORE_WEIGHTS == config.CANDIDATE_SCORE_WEIGHTS.components()
    with pytest.raises(ValueError):
        config.CandidateScoreWeights(population_covered=0.9).validate()


def test_fallback_candidates_are_flagged_not_comparable_and_not_scored():
    df = pd.DataFrame({
        "candidate_id": ["a", "b", "c"], "corridor": ["x"] * 3, "population_covered": [100, 50, 400], "jobs_covered": [10, 20, 400],
        "travel_time_penalty_pct": [0.0, 50.0, 0.0], "existing_route_overlap_pct": [20.0, 0.0, 0.0],
        "path_source": ["openstreetmap", "openstreetmap", "straight_line_fallback"],
    })
    out = C.score_candidates(df).set_index("candidate_id")
    assert out.loc["c", "rank_flag"] == C.NOT_COMPARABLE and np.isnan(out.loc["c", "score"]) and np.isnan(out.loc["c", "rank_in_corridor"])
    assert out.loc["a", "rank_flag"] == "ranked" and out.loc["a", "rank_in_corridor"] == 1
    # the fallback row must not influence the OSM rows' scaling (its large population would otherwise change 'a')
    assert out.loc["a", "score"] == pytest.approx(100 * (0.3 * 1 + 0.3 * 0.5 + 0.2 * 1 + 0.2 * 0.8), abs=0.01)
    assert "not_comparable" in json.loads(out.loc["c", "score_breakdown_json"])


@needs_processed
def test_candidates_table_flags_match_path_source():
    cdf = io.read_table("route_candidates", "processed")
    fb = cdf["path_source"] != "openstreetmap"
    assert (cdf.loc[fb, "rank_flag"] == C.NOT_COMPARABLE).all() and cdf.loc[fb, "score"].isna().all()
    assert (cdf.loc[~fb, "rank_flag"] == "ranked").all() and cdf.loc[~fb, "score"].notna().all()
    assert cdf["source_type"].eq("model_output").all()


# ------------------------------------------------------------------ no network
def _boom(*a, **k):
    raise AssertionError("network access attempted")


def test_rebuild_never_touches_network_with_missing_graphs(monkeypatch, tmp_path):
    if not io.table_exists("routes", "synthetic"):
        pytest.skip("synthetic data not generated")
    import requests
    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)
    monkeypatch.setattr(requests.Session, "request", _boom)
    N.clear_graph_cache()
    paths, cands = routing_run.rebuild(raw_dir=tmp_path, write=False)
    assert set(paths["path_source"]) == {"straight_line_fallback"}
    assert set(cands["rank_flag"]) == {C.NOT_COMPARABLE} and cands["score"].isna().all()


@pytest.mark.skipif(not N.graph_available("city"), reason="city graph cache missing")
def test_rebuild_with_cached_graphs_never_touches_network(monkeypatch):
    import osmnx as ox
    import requests
    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)
    monkeypatch.setattr(requests.Session, "request", _boom)
    monkeypatch.setattr(ox, "graph_from_bbox", _boom, raising=False)
    N.clear_graph_cache()
    paths, cands = routing_run.rebuild(write=False)
    assert (paths["path_source"] == "openstreetmap").sum() >= 9
