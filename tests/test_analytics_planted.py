"""Analytics on the full synthetic data: planted findings, reconciliation, scores, recommendations, determinism."""
import json
import re

import numpy as np
import pandas as pd
import pytest

import config
from modules.analytics import findings as FD
from modules.analytics import gaps, run, scoring
from modules.analytics.common import hour_window
from modules.data import io

PEAK = config.PEAK_DAY_TYPE


# ----------------------------------------------------------------------------- planted findings via analytics
def test_all_planted_findings_detected_by_analytics(analytics, tables):
    results = FD.detect_planted(analytics, tables)
    assert len(results) == 6
    failed = [f for f in results if not f.ok]
    assert not failed, [(f.name, f.detail) for f in failed]


def test_f1_peak_load_factor_route_hours(analytics):
    rh = gaps.route_hour_load(analytics["trips_sum"], "weekday").set_index(["route_id", "hour"])["peak_load_factor"]
    hi = rh[rh > config.HIGH_PEAK_LOAD_FACTOR]
    assert set(hi.index) == {("L05", 7), ("L05", 8), ("L05", 17), ("L07", 7)}
    assert hi.max() <= 1.6 + 1e-9                                  # physically plausible: never above the crush limit
    assert hi[("L05", 8)] == pytest.approx(1.40, abs=0.02) and hi[("L07", 7)] == pytest.approx(1.23, abs=0.02)
    h = analytics["hourly_demand_supply"]
    crowded = h[(h["level"] == "route_direction") & (h["day_type"] == "weekday") & (h["status"] == "crowded")]
    assert set(zip(crowded["route_id"], crowded["hour"])) == {("L05", 7), ("L05", 8), ("L05", 17), ("L07", 7)}
    assert (crowded["gap_index"] > config.CROWDING_GAP_INDEX_THRESHOLD).all() and crowded["crowding_flag"].all()


def test_no_trip_exceeds_physical_cap_and_progression_is_clean(analytics):
    ts = analytics["trips_sum"]
    assert not ts["over_capacity_flag"].any() and not ts["negative_flag"].any() and not ts["not_empty_at_end_flag"].any()
    assert (ts["peak_load_factor"] <= 1.6 + 1e-9).all()
    assert ts.loc[ts["route_type"] == "intercity", "peak_load_factor"].max() <= 1.0
    occ = analytics["stop_occupancy"]
    assert not occ["negative_flag"].any() and not occ["over_capacity_flag"].any()
    assert analytics["legs"]["leg_valid"].all()


def test_f1b_intercity_weekend_at_capacity(analytics):
    h = analytics["hourly_demand_supply"]
    r = h[(h["route_id"] == "IC02") & (h["direction"] == "outbound") & (h["hour"] == 8) & (h["status"] == "at_capacity")]
    assert {"weekend", "festival"} <= set(r["day_type"]) and (r["gap_index"] >= config.AT_CAPACITY_LOAD_FACTOR).all()


def test_f2_shapar_gap(analytics):
    h = analytics["hourly_demand_supply"]
    r = h[(h["route_id"] == "L07") & (h["day_type"] == "weekday") & (h["hour"] == 7) & (h["direction"] == "outbound")].iloc[0]
    assert r["trips_per_day"] == 1.0 and r["seats_offered"] == 40 and r["zone_id"] == "Z13" and r["status"] == "crowded"
    rec = analytics["recommendations"]
    l07 = rec[(rec["route_id"] == "L07") & (rec["category"] == "add_service_peak")].iloc[0]
    fig = json.loads(l07["evidence_json"])["figures"]
    assert fig["top_destination_zones_pax_per_day"]["Z13"] >= fig["seats_offered_per_day_on_these_trips"]  # 72 pax vs 40 seats


def test_f3_top_od_pair(analytics):
    od = analytics["od_flows"]
    from modules.analytics.od import top_od_pairs

    top = top_od_pairs(od, "weekday", (7, 10), top=3)
    assert (top.iloc[0]["origin_zone_id"], top.iloc[0]["dest_zone_id"]) == ("Z05", "Z11")      # Kotharia -> Aji GIDC


def test_f4_rajkot_somnath_evening_gap(analytics):
    h = analytics["hourly_demand_supply"]
    c = h[(h["level"] == "corridor") & (h["corridor"] == "Rajkot-Somnath") & (h["day_type"] == "weekday")].set_index("hour")
    for hr in (18, 19, 20, 21):
        assert c.loc[hr, "status"] == "no_scheduled_capacity" and c.loc[hr, "seats_offered"] == 0
        assert pd.isna(c.loc[hr, "gap_index"]) and c.loc[hr, "demand_estimate"] > 0
        assert c.loc[hr, "private_demand_proxy"] == pytest.approx(c.loc[hr, "private_seats"] * config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION)
        assert c.loc[hr, "gap_count"] == pytest.approx(c.loc[hr, "demand_estimate"])
    assert c.loc[17, "status"] != "no_scheduled_capacity"


def test_f6_cctv_peak(analytics):
    p = analytics["cctv_hourly_profile"]
    s = p[(p["location_id"] == "S01") & (p["day_type"] == "weekday")].set_index("hour")["mean_inbound_persons"]
    assert s.idxmax() in (7, 8)
    w = p[(p["location_id"] == "S01") & (p["day_type"] == "weekend")].set_index("hour")["mean_inbound_persons"]
    assert w.loc[[7, 8]].mean() / w.drop([7, 8]).mean() < 2.0
    assert (p["measurement_method"] == "synthetic").all()


# ----------------------------------------------------------------------------- reconciliation
def test_route_kpis_reconcile_with_sources(analytics, tables):
    k, tk, trips, routes = analytics["route_kpis"], tables["tickets"], tables["trips"], tables["routes"]
    assert k["ticket_revenue_inr"].sum() == pytest.approx(tk["fare_inr"].sum())
    assert k["boardings"].sum() == tk["passenger_count"].sum()
    km = trips["route_id"].map(routes.set_index("route_id")["length_km"]).sum()
    assert k["vehicle_km"].sum() == pytest.approx(km)
    assert k["operating_cost_inr"].sum() == pytest.approx(trips["operating_cost_inr"].sum())
    assert k["available_seats"].sum() == trips["seats"].sum()
    assert len(k) == len(routes) * trips["service_date"].nunique()
    lf = k["load_factor_pct"]
    assert ((lf >= 0) & (lf <= 160)).all()
    # per-route revenue
    per = tk.merge(trips[["trip_id", "route_id"]], on="trip_id").groupby("route_id")["fare_inr"].sum()
    got = k.groupby("route_id")["ticket_revenue_inr"].sum()
    assert np.allclose(per.sort_index().to_numpy(), got.sort_index().to_numpy())


def test_route_summary_consistent_with_route_kpis(analytics):
    k, s = analytics["route_kpis"], analytics["route_summary"].set_index("route_id")
    g = k.groupby("route_id")[["boardings", "ticket_revenue_inr", "vehicle_km", "operating_cost_inr", "estimated_passenger_km", "seat_km", "available_seats"]].sum()
    for c in g.columns:
        assert np.allclose(g[c], s.loc[g.index, c]), c
    assert np.allclose(s["epkm_inr"], s["ticket_revenue_inr"] / s["vehicle_km"])
    assert np.allclose(s["revenue_per_passenger_inr"], s["ticket_revenue_inr"] / s["boardings"])
    assert np.allclose(s["contribution_inr"], s["ticket_revenue_inr"] - s["operating_cost_inr"])
    assert np.allclose(s["load_factor_pct"], s["estimated_passenger_km"] / s["seat_km"] * 100)
    assert np.allclose(s["avg_boardings_per_day"] * 42, s["boardings"])
    assert s["reliability_pct"].between(0, 100).all()
    assert (s["peak_hour_load_factor"] <= 1.6 + 1e-9).all()
    assert s.loc["L05", "peak_hour"] == 8 and s.loc["L07", "peak_hour"] == 7
    assert "NOT profit" in s["assumptions_json"].iloc[0]


def test_od_flows_reconcile(analytics, tables):
    od = analytics["od_flows"]
    assert od["passengers_total"].sum() == tables["tickets"]["passenger_count"].sum()
    assert od["passenger_km_total"].sum() == pytest.approx(analytics["route_kpis"]["estimated_passenger_km"].sum())
    wd = od[od["day_type"] == "weekday"]
    assert np.allclose(wd["passenger_count"] * wd["n_days"], wd["passengers_total"])
    assert set(od["origin_zone_id"]) <= set(tables["zones"]["zone_id"])


def test_stop_occupancy_progression_identity(analytics):
    occ = analytics["stop_occupancy"].sort_values(["route_id", "direction", "day_type", "hour", "position"])
    g = occ.groupby(["route_id", "direction", "day_type", "hour"])
    diff = (occ["avg_boardings"] - occ["avg_alightings"]).groupby([occ[c] for c in ["route_id", "direction", "day_type", "hour"]]).cumsum()
    assert np.allclose(diff, occ["avg_onboard"])
    last = g.tail(1)
    assert np.allclose(last["avg_onboard"], 0)


def test_hourly_table_internal_consistency(analytics):
    h = analytics["hourly_demand_supply"]
    ok = h["seats_offered"] > 0
    assert (h.loc[~ok, "gap_index"].isna()).all() and (h.loc[~ok, "status"] == "no_scheduled_capacity").all()
    d = h[ok & h["demand_estimate"].notna()]
    assert np.allclose(d["gap_count"], (d["demand_estimate"] - d["seats_offered"]).clip(lower=0))
    assert np.allclose(d["gap_index"], d["demand_estimate"] / d["seats_offered"])
    rd = d[d["level"] == "route_direction"]
    assert (rd["crowding_flag"] == (rd["gap_index"] > config.CROWDING_GAP_INDEX_THRESHOLD)).all()
    assert not np.isinf(h[["gap_index", "gap_count", "demand_estimate"]].to_numpy(dtype=float)).any()
    assert h["service_date"].isna().all() and set(h["day_type"]) == {"weekday", "weekend", "festival"}
    assert set(h["status"]) <= {"ok", "crowded", "at_capacity", "no_scheduled_capacity"}


# ----------------------------------------------------------------------------- scores
def test_route_scores_structure_weights_and_protection(analytics, tables):
    sc = analytics["route_scores"]
    assert len(sc) == len(tables["routes"]) and sc["weight_version"].eq("demo-v1").all()
    comps = scoring.COMPONENTS
    assert sc[comps + ["total_score"]].apply(lambda c: c.between(0, 100)).all().all()
    w = config.ROUTE_SCORE_WEIGHTS.components()
    wts = np.array([w[k] for k in ["demand_potential", "unmet_demand", "load_factor", "reliability_gap", "revenue_potential",
                                   "social_importance", "feasibility"]])
    expect = sc[comps].to_numpy() @ wts
    assert np.allclose(expect, sc["total_score"])                   # no missing inputs on the full data
    assert set(sc.loc[sc["protected_minimum_service"], "route_id"]) == {"L09", "L10"}
    assert sc["explanation"].str.contains("not an AI prediction").all()
    assert sc.set_index("route_id").loc["L05", "rank_within_type"] == 1
    assert sc.set_index("route_id").loc["L09", "social_importance_score"] == pytest.approx(100.0)
    assert json.loads(sc["weights_json"].iloc[0])["weight_version"] == "demo-v1"
    assert sc["explanation"][sc["route_id"] == "L09"].iloc[0].count("never a removal candidate") == 1


def test_minmax_within_groups_and_missing_handling():
    v = pd.Series([10.0, 20.0, 30.0, np.nan, 5.0, 5.0])
    g = pd.Series(["a", "a", "a", "a", "b", "b"])
    m = scoring.minmax_within(v, g)
    assert m.iloc[:3].tolist() == [0.0, 50.0, 100.0] and np.isnan(m.iloc[3])
    assert m.iloc[4] == 50.0 and m.iloc[5] == 50.0                  # identical inputs -> neutral 50
    assert scoring.minmax_within(v, g, invert=True).iloc[0] == 100.0
    assert scoring.minmax_within(pd.Series([np.nan, np.nan]), pd.Series(["a", "a"])).isna().all()


def test_route_scores_reweight_when_component_missing(analytics, tables):
    summ = analytics["route_summary"].copy()
    summ.loc[summ["route_id"] == "L01", "reliability_pct"] = np.nan
    sc = scoring.route_scores(summ, analytics["hourly_demand_supply"], tables["routes"], tables["route_stops"], tables["stops"],
                              tables["zones"], tables["trips"]).set_index("route_id")
    row = sc.loc["L01"]
    assert row["missing_components"] == "reliability_gap_score" and np.isnan(row["reliability_gap_score"])
    w = config.ROUTE_SCORE_WEIGHTS
    comp = {"demand_score": w.demand_potential, "unmet_demand_score": w.unmet_demand, "load_factor_score": w.load_factor,
            "revenue_potential_score": w.revenue_potential, "social_importance_score": w.social_importance, "feasibility_score": w.feasibility}
    manual = sum(row[k] * x for k, x in comp.items()) / sum(comp.values())
    assert row["total_score"] == pytest.approx(manual) and "re-weighted" in row["explanation"]
    assert sc.drop(index="L01")["missing_components"].eq("").all()


# ----------------------------------------------------------------------------- recommendations
def _gap_keys(rec_row):
    ev = json.loads(rec_row["evidence_json"])
    return ev, ev["gap_rows"]


def test_recommendations_reference_existing_gap_rows_with_identical_windows(analytics):
    rec, h = analytics["recommendations"], analytics["hourly_demand_supply"]
    gap_recs = rec[rec["category"] != "protect_minimum_service"]
    assert len(gap_recs) >= 4
    for _, r in gap_recs.iterrows():
        ev, rows = _gap_keys(r)
        assert ev["table"] == "hourly_demand_supply" and rows
        hours = sorted({x["hour"] for x in rows})
        assert r["time_window"] == hour_window(min(hours), max(hours))         # window identical to the gap-table window
        assert hours == list(range(min(hours), max(hours) + 1)) or r["category"] == "add_capacity_weekend"
        for x in rows:
            m = h[(h["level"] == x["level"]) & (h["day_type"] == x["day_type"]) & (h["hour"] == x["hour"]) & (h["direction"] == x["direction"])]
            m = m[(m["route_id"] == x["route_id"])] if x["route_id"] else m[m["corridor"] == x["corridor"]]
            assert len(m) == 1
            assert m.iloc[0]["demand_estimate"] == pytest.approx(x["demand_estimate"]) and m.iloc[0]["status"] == x["status"]


def test_recommendation_contents(analytics):
    rec = analytics["recommendations"].set_index("recommendation_id")
    titles = " | ".join(rec["title"])
    assert re.search(r"L05 07:00-09:00", titles) and re.search(r"L05 17:00-18:00", titles) and re.search(r"L07 07:00-08:00", titles)
    assert re.search(r"Rajkot-Somnath 18:00-22:00", titles)
    assert set(rec["category"]) == {"add_service_peak", "add_service_corridor_slot", "add_capacity_weekend", "protect_minimum_service"}
    assert (rec["confidence_label"] == config.CONFIDENCE_LABEL).all() and rec["source_type"].eq("synthetic").all()
    for c in ["evidence_json", "assumptions_json", "expected_impact_json", "constraints_json"]:
        assert rec[c].map(lambda s: isinstance(json.loads(s), (dict, list))).all()
    for _, r in rec[rec["category"] != "protect_minimum_service"].iterrows():
        imp = json.loads(r["expected_impact_json"])
        assert imp["label"] == "illustrative service scenario" and imp["fleet_constraint_not_modelled"] is True
        assert imp["additional_departures"] >= 1
        assert any("not modelled" in c.lower() for c in json.loads(r["constraints_json"]))
        assert "route_summary" in json.loads(r["evidence_json"])
    l05 = rec[rec["title"].str.contains("L05 07:00-09:00")].iloc[0]
    imp = json.loads(l05["expected_impact_json"])
    assert imp["projected_load_factor_after"] <= config.SERVICE_TARGET_LOAD_FACTOR + 1e-9    # the recommended supply closes the gap
    f4 = rec[rec["category"] == "add_service_corridor_slot"].iloc[0]
    a = json.loads(f4["assumptions_json"])
    assert a["private_occupancy_assumption"] == config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION and "assumption" in a["private_market"]
    assert rec["priority_rank"].is_unique and list(rec.index) == [f"REC-{i:03d}" for i in range(1, len(rec) + 1)]


def test_minimum_service_routes_are_protected_never_removed(analytics, tables):
    rec = analytics["recommendations"]
    ms = set(tables["routes"].loc[tables["routes"]["minimum_service"], "route_id"])
    assert ms == {"L09", "L10"}
    prot = rec[rec["category"] == "protect_minimum_service"]
    assert set(prot["route_id"]) == ms
    mine = rec[rec["route_id"].isin(ms)]
    for _, r in mine.iterrows():
        text = r["title"] + " " + r["action"]
        assert not re.search(r"\b(remove|discontinue|cancel|scrap|abolish)\b", text, re.I), text
        assert r["category"] == "protect_minimum_service"
    assert "never" in " ".join(analytics["route_scores"].set_index("route_id").loc[list(ms), "explanation"])


# ----------------------------------------------------------------------------- determinism and runner
OUT = list(run.OUTPUT_TABLES)


def test_analytics_are_deterministic(tables, analytics):
    again = run.compute_all(tables)
    for n in OUT + ["trips_sum", "legs"]:
        pd.testing.assert_frame_equal(analytics[n], again[n], check_exact=True, obj=n)


def test_runner_writes_tables_with_provenance_and_is_repeatable(tmp_path, tables, analytics):
    for i in range(2):
        base = tmp_path / f"run{i}"
        for n, df in tables.items():
            io.write_table(df, n, "synthetic", base_dir=base)
        res = run.compute_all(run.load_sources(base))
        run.write_all(res, base)
    for n in OUT:
        a = io.read_table(n, "processed", tmp_path / "run0")
        b = io.read_table(n, "processed", tmp_path / "run1")
        pd.testing.assert_frame_equal(a, b, check_exact=True, obj=n)
        assert len(a) == len(analytics[n])
        prov = io.read_provenance(n, "processed", tmp_path / "run0")
        assert prov.source_type.value == "synthetic" and prov.assumptions["contribution_is_not_profit"] is True
    assert run.main(["--base-dir", str(tmp_path / "does_not_exist")]) == 1          # missing sources -> clear failure, not a crash


def test_main_prints_summary_and_passes_findings(tmp_path, tables, capsys):
    for n, df in tables.items():
        io.write_table(df, n, "synthetic", base_dir=tmp_path)
    assert run.main(["--base-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Simulated data for demonstration" in out and "FAIL" not in out and out.count("[PASS]") == 6
    assert not io.missing_tables("processed", tmp_path) == list(io.DERIVED_TABLES)
