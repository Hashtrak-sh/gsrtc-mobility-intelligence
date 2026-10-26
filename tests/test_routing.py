"""Milestone 4 routing tests: guarded imports, labelled fallback, path/stop IDs, score transparency, cache-only loading."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import config
from modules.data import io
from modules.routing import candidates as C
from modules.routing import network as N
from modules.routing import settings as S

# Intercity endpoints that lie outside PILOT_BBOX by design (docs/DATA_SCHEMA.md "Geography").
OUT_OF_BBOX_STOPS = {"S35", "S36"}  # Jamnagar, Ahmedabad bus stands


@pytest.fixture(scope="module")
def stops() -> pd.DataFrame:
    if not io.table_exists("stops", "synthetic"):
        pytest.skip("synthetic data not generated")
    return io.read_table("stops", "synthetic")


@pytest.fixture(scope="module")
def zones() -> pd.DataFrame:
    if not io.table_exists("zones", "synthetic"):
        pytest.skip("synthetic data not generated")
    return io.read_table("zones", "synthetic")


@pytest.fixture
def no_geo(monkeypatch):
    """Simulate osmnx / networkx not being installed."""
    monkeypatch.setattr(N, "ox", None)
    monkeypatch.setattr(N, "nx", None)
    N.clear_graph_cache()
    yield
    N.clear_graph_cache()


def _in_bbox(lon: float, lat: float) -> bool:
    return config.PILOT_BBOX.contains(lat, lon)


def test_module_degrades_without_osmnx(no_geo, stops):
    assert not N.geo_available()
    assert not N.graph_available("city") and not N.graph_available("corridor")
    assert N.load_graph("city") is None
    res = N.route_path(["S01", "S03"], stops)
    assert res["source"] == N.SOURCE_FALLBACK


def test_fallback_is_labelled_and_uses_documented_detour(no_geo, stops):
    ids = ["S01", "S31", "S34"]
    res = N.route_path(ids, stops, "corridor")
    assert res["source"] == "straight_line_fallback"
    assert res["graph_kind"] is None and res["note"]
    idx = stops.set_index("stop_id")
    straight = sum(N.haversine_km(idx.at[a, "lat"], idx.at[a, "lon"], idx.at[b, "lat"], idx.at[b, "lon"])
                   for a, b in zip(ids, ids[1:]))
    assert res["length_km"] == pytest.approx(straight * S.STRAIGHT_LINE_DETOUR_FACTOR, rel=1e-3)
    assert res["travel_time_min"] > 0
    assert len(res["path"]) == len(ids)


def test_missing_cache_gives_fallback(tmp_path, stops):
    assert not N.graph_available("city", tmp_path)
    assert N.load_graph("corridor", tmp_path) is None
    assert N.route_path(["S01", "S03"], stops, "auto", tmp_path)["source"] == N.SOURCE_FALLBACK


def test_unknown_stop_and_kind_raise(stops):
    with pytest.raises(KeyError):
        N.route_path(["S01", "S999"], stops)
    with pytest.raises(ValueError):
        N.graph_path("nope")


def test_fallback_coordinates_inside_pilot_bbox_except_documented(no_geo, stops):
    rs = io.read_table("route_stops", "synthetic").sort_values(["route_id", "stop_seq"])
    for rid, g in rs.groupby("route_id"):
        ids = g["stop_id"].tolist()
        res = N.route_path(ids, stops)
        exempt = bool(set(ids) & OUT_OF_BBOX_STOPS)
        inside = all(_in_bbox(lon, lat) for lon, lat in res["path"])
        assert inside or exempt, f"{rid} leaves PILOT_BBOX without a documented exception"


def test_candidate_specs_resolve_to_stops_and_weights_sum_to_one(stops):
    known = set(stops["stop_id"])
    for spec in C.CANDIDATE_SPECS:
        assert set(spec.stops) <= known, spec.candidate_id
        assert len(spec.stops) >= 2
    assert len({s.candidate_id for s in C.CANDIDATE_SPECS}) == len(C.CANDIDATE_SPECS)
    assert sum(C.SCORE_WEIGHTS.values()) == pytest.approx(1.0)


def test_score_components_are_visible_and_consistent():
    df = pd.DataFrame({
        "candidate_id": ["a", "b"], "corridor": ["x", "x"], "population_covered": [100, 50], "jobs_covered": [10, 20],
        "travel_time_penalty_pct": [0.0, 50.0], "existing_route_overlap_pct": [20.0, 0.0],
    })
    out = C.score_candidates(df)
    for r in out.itertuples():
        b = json.loads(r.score_breakdown_json)
        assert set(b["components_0_1"]) == set(C.SCORE_WEIGHTS)
        assert b["weights"] == C.SCORE_WEIGHTS
        assert 100 * sum(b["weighted_contribution"].values()) == pytest.approx(r.score, abs=0.05)
    assert out.loc[0, "score"] == pytest.approx(100 * (0.3 * 1 + 0.3 * 0.5 + 0.2 * 1 + 0.2 * 0.8), abs=0.01)
    with pytest.raises(ValueError):
        C.score_candidates(df, {"population_covered": 0.5})


def test_geometry_helpers():
    path = [[70.80, 22.30], [70.81, 22.30]]  # ~1.03 km east-west
    pts = np.array([[70.805, 22.30], [70.805, 22.3045]])  # on the line; ~500 m north of it
    d = C.min_dist_m(pts, path)
    assert d[0] < 1 and 450 < d[1] < 550
    assert 0 < len(C.densify(path)) and C.overlap_pct(path, [path]) == 100.0
    assert C.overlap_pct(path, [[[70.9, 22.5], [70.91, 22.5]]]) == 0.0


def test_build_paths_without_cache_is_all_labelled_fallback(tmp_path):
    if not io.table_exists("routes", "synthetic"):
        pytest.skip("synthetic data not generated")
    from modules.routing import build_paths
    df = build_paths.build(raw_dir=tmp_path)
    assert set(df["path_source"]) == {N.SOURCE_FALLBACK}
    routes = io.read_table("routes", "synthetic")
    assert set(df["route_id"]) == set(routes["route_id"])
    assert df["length_ratio"].notna().all()


# ---- graph-dependent tests (skipped when the cache has not been fetched) ----------------------------------------
needs_city = pytest.mark.skipif(not N.graph_available("city"), reason="city graph cache missing (run modules.routing.fetch_network)")
needs_corridor = pytest.mark.skipif(not N.graph_available("corridor"), reason="corridor graph cache missing")


@needs_city
def test_graph_load_uses_cache_without_network(monkeypatch, stops):
    import osmnx as ox

    def boom(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(ox, "graph_from_bbox", boom, raising=False)
    monkeypatch.setattr(ox, "graph_from_place", boom, raising=False)
    monkeypatch.setattr("requests.get", boom)
    monkeypatch.setattr("requests.post", boom)
    N.clear_graph_cache()
    G = N.load_graph("city")
    assert G is not None and N.load_graph("city") is G  # lru_cache returns the same object
    res = N.route_path(["S14", "S13", "S05", "S02", "S01", "S03"], stops, "city")
    assert res["source"] == "openstreetmap" and res["graph_kind"] == "city"
    assert all(_in_bbox(lon, lat) for lon, lat in res["path"])
    assert res["length_km"] > 0 and res["travel_time_min"] > 0
    snap = N.snap_stops(stops[stops["stop_id"].isin(["S01", "S03"])], G)
    assert snap["snapped"].all()


@needs_corridor
def test_corridor_path_rajkot_somnath_is_osm(stops):
    res = N.route_path(["S01", "S31", "S34"], stops, "corridor")
    assert res["source"] == "openstreetmap"
    assert 150 < res["length_km"] < 260
    assert all(_in_bbox(lon, lat) for lon, lat in res["path"])


@needs_corridor
def test_candidates_table_consistent(stops, zones):
    df = C.build()
    known = set(stops["stop_id"])
    assert len(df) == len(C.CANDIDATE_SPECS)
    for r in df.itertuples():
        assert set(json.loads(r.stop_ids_json)) <= known
        assert json.loads(r.path_geojson)["type"] == "LineString"
        assert 0 <= r.existing_route_overlap_pct <= 100 and r.travel_time_penalty_pct >= 0
        assert r.population_covered <= zones["population"].sum()
        assert r.source_type == "model_output" and "Illustrative" in r.label
