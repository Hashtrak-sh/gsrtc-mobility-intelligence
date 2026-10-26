"""M3: formatters, shared filters, presentation queries and the helper modules behind the dashboard pages."""
import json
import io

import numpy as np
import pandas as pd
import pytest

import config
from modules.analytics import assets as A
from modules.analytics import cctv as CC
from modules.analytics import queries as Q
from modules.competition import analysis as CA
from modules.analytics import scenarios as SC
from modules.reporting import exports as X
from modules.survey import summaries as SV
from modules.ui import filters as F
from modules.ui import fmt, narrative as N


# ---------------------------------------------------------------- formatters
def test_inr_indian_grouping():
    assert fmt.inr(123456) == "₹1,23,456"
    assert fmt.inr(1234567) == "₹12,34,567"
    assert fmt.inr(999) == "₹999"
    assert fmt.inr(1000) == "₹1,000"
    assert fmt.inr(12345678.9) == "₹1,23,45,679"
    assert fmt.inr(-437150.45) == "-₹4,37,150"
    assert fmt.inr(1234.5, 1) == "₹1,234.5"
    assert fmt.inr(0) == "₹0"
    assert fmt.inr(-0.2) == "₹0"  # no negative zero


def test_formatters_missing_values_are_na_not_nan():
    for bad in (None, float("nan"), float("inf")):
        assert fmt.inr(bad) == fmt.NA and fmt.pct(bad) == fmt.NA and fmt.number(bad) == fmt.NA
        assert fmt.times(bad) == fmt.NA and fmt.hhmm(bad) == fmt.NA
    assert "nan" not in fmt.inr_compact(float("nan")).lower()


def test_compact_and_time_formats():
    assert fmt.inr_compact(1850000) == "₹18.50 lakh"
    assert fmt.inr_compact(25000000) == "₹2.50 crore"
    assert fmt.hhmm(7) == "07:00" and fmt.hour_window(7, 9) == "07:00–09:00"
    assert fmt.contiguous_windows([18, 19, 20, 21, 12]) == [(12, 13), (18, 22)]
    assert fmt.ratio_pct(0.85) == "85%" and fmt.pct(64.44) == "64.4%" and fmt.km(12.82) == "12.8 km"


# ------------------------------------------------------------------- filters
def test_filters_validation_and_describe():
    f = F.Filters(F.LOCAL, "weekend", 7, 10)
    assert f.hours_label == "07:00–10:00" and "Rajkot local network" in f.describe() and "weekend" in f.describe()
    assert f.describe(corridor=False, hours=False) == "Day type: weekend"
    for kwargs in ({"corridor": "Nowhere"}, {"day_type": "monday"}, {"hour_lo": 5, "hour_hi": 5}, {"hour_hi": 25}):
        with pytest.raises(ValueError):
            F.Filters(**kwargs)


def test_scope_routes_semantics(analytics):
    rs = analytics["route_summary"]
    assert set(F.route_ids(rs, F.LOCAL)) == {f"L{i:02d}" for i in range(1, 11)}
    assert set(F.route_ids(rs, "Rajkot-Somnath")) == {"IC01", "IC02", "IC03"}
    assert F.route_ids(rs, F.ALL) == sorted(rs["route_id"])
    assert len(F.scope_routes(rs, "Rajkot-Ahmedabad")) == 1


def test_filter_hourly_semantics(analytics):
    h, rs = analytics["hourly_demand_supply"], analytics["route_summary"]
    f = F.Filters(F.LOCAL, "weekday", 7, 9)
    r = F.filter_hourly(h, f, rs)
    assert set(r["level"]) == {"route_direction"} and set(r["day_type"]) == {"weekday"}
    assert r["hour"].between(7, 8).all() and r["route_id"].str.startswith("L").all()  # half-open [7, 9)
    c = F.filter_hourly(h, F.Filters("Rajkot-Somnath", "weekday"), rs)
    assert set(c.loc[c["level"] == "corridor", "corridor"]) == {"Rajkot-Somnath"}
    assert set(c.loc[c["level"] == "route_direction", "route_id"]) == {"IC01", "IC02", "IC03"}
    assert len(F.filter_hourly(h, F.Filters(), rs, hours=False)) == int((h["day_type"] == "weekday").sum())


def test_filter_od_reconciles_with_route_summary(analytics, tables):
    od, rs = analytics["od_flows"], analytics["route_summary"]
    for dt in F.DAY_TYPES:
        col = f"boardings_per_day_{dt}"
        allf = F.filter_od(od, F.Filters(F.ALL, dt), rs, tables["route_stops"], tables["stops"])
        loc = F.filter_od(od, F.Filters(F.LOCAL, dt), rs, tables["route_stops"], tables["stops"])
        assert allf["passenger_count"].sum() == pytest.approx(rs[col].sum())
        # local scope reconciles with route_summary within the rounding of intra-zone pairs shared with intercity stops
        assert loc["passenger_count"].sum() == pytest.approx(rs.loc[rs["route_type"] == "local", col].sum(), rel=0.01)


def test_filter_recommendations_and_cctv(analytics):
    rs, rec = analytics["route_summary"], analytics["recommendations"]
    assert set(F.filter_recommendations(rec, F.Filters("Rajkot-Somnath"), rs)["route_id"]) <= {"IC01", "IC02", "IC03"}
    assert len(F.filter_recommendations(rec, F.Filters(), rs)) == len(rec)
    p = F.filter_cctv(analytics["cctv_hourly_profile"], F.Filters(day_type="weekday", hour_lo=7, hour_hi=9))
    assert set(p["hour"]) == {7, 8} and set(p["day_type"]) == {"weekday"}


# ------------------------------------------------------------------- queries
def test_scope_kpis_ratio_of_sums(analytics):
    rs = analytics["route_summary"]
    k = Q.scope_kpis(rs)
    assert k["boardings"] == int(rs["boardings"].sum())
    assert k["load_factor_pct"] == pytest.approx(rs["estimated_passenger_km"].sum() / rs["seat_km"].sum() * 100)
    assert k["avg_boardings_per_day"] == pytest.approx(rs["boardings"].sum() / 42)
    assert k["contribution_per_day_inr"] == pytest.approx(rs["contribution_inr"].sum() / 42)
    one = Q.scope_kpis(rs[rs["route_id"] == "IC06"])
    assert one["load_factor_pct"] == pytest.approx(float(rs.loc[rs["route_id"] == "IC06", "load_factor_pct"].iloc[0]))
    assert np.isnan(Q.scope_kpis(rs.iloc[0:0])["load_factor_pct"])


def test_recommendation_windows_match_gap_tables(analytics):
    h, rec, rs = analytics["hourly_demand_supply"], analytics["recommendations"], analytics["route_summary"]
    # every recommendation window equals the window built from its own gap rows
    for _, r in rec[rec["category"].str.startswith(("add_service", "add_capacity"))].iterrows():
        rows = json.loads(r["evidence_json"])["gap_rows"]
        assert Q.window_from_rows(rows) == r["time_window"]
    # and the live gap tables reproduce the recommended peak windows and the corridor slot
    wk = F.filter_hourly(h, F.Filters(F.ALL, "weekday"), rs)
    wins = Q.gap_windows(wk)
    for _, w in wins.iterrows():
        m = Q.matching_recommendation(rec, route_id=w["route_id"], direction=w["direction"], start_hour=w["start_hour"], end_hour=w["end_hour"])
        assert m is not None and m["time_window"] == f"{w['start_hour']:02d}:00-{w['end_hour']:02d}:00"
    unc = Q.uncovered_windows(wk).iloc[0]
    r1 = rec[rec["category"] == "add_service_corridor_slot"].iloc[0]
    assert (unc["corridor"], f"{unc['start_hour']:02d}:00-{unc['end_hour']:02d}:00") == (r1["corridor"], r1["time_window"])
    assert unc["proxy_demand"] == pytest.approx(json.loads(r1["evidence_json"])["figures"]["private_market_proxy_demand_per_day"])


def test_hour_grid_marks_no_capacity_distinctly(analytics):
    h = F.filter_hourly(analytics["hourly_demand_supply"], F.Filters("Rajkot-Somnath", "weekday"), analytics["route_summary"])
    g = Q.hour_grid(h, {}, {})
    ev = g[(g["row_label"] == "Rajkot-Somnath corridor") & g["hour"].between(18, 21)]
    assert (ev["status"] == "no_scheduled_capacity").all() and ev["gap_index"].isna().all()  # NaN, never 0
    assert g.loc[g["row_label"].str.endswith("corridor"), "order"].eq(0).all()  # corridor rows sort first in the chart


def test_occupancy_progression_and_od(analytics):
    so, od = analytics["stop_occupancy"], analytics["od_flows"]
    p = Q.occupancy_progression(so, "L05", "outbound", 7)
    assert list(p["position"]) == sorted(p["position"]) and (p["avg_onboard"] >= 0).all() and p["seats"].iloc[0] == 40
    assert Q.occupancy_progression(so, "L05", "outbound", 3).empty
    pairs = Q.od_pairs(od[od["day_type"] == "weekday"], top=5)
    assert len(pairs) == 5 and pairs["passengers_total"].is_monotonic_decreasing
    m = Q.od_matrix(od[od["day_type"] == "weekday"])
    assert list(m.index) == list(m.columns)


def test_score_weights_and_components(analytics):
    sc, rs = analytics["route_scores"], analytics["route_summary"]
    w = Q.score_weights(sc)
    assert sum(w.values()) == pytest.approx(1.0) and w == config.ROUTE_SCORE_WEIGHTS.components()
    ranked = Q.ranked_scores(sc, rs, "local")
    wc = Q.weighted_components(ranked, w)
    tot = wc.groupby("route_id")["points"].sum()
    for _, r in ranked.iterrows():
        assert tot[r["route_id"]] == pytest.approx(r["total_score"], abs=1e-6)
    assert ranked["rank_within_type"].is_monotonic_increasing


# ------------------------------------------------------------- competition
def test_slot_comparison_matches_corridor_gap_rows(tables, analytics):
    slots = CA.slot_comparison(tables["trips"], tables["competitor_services"], tables["routes"], config.PRIMARY_CORRIDOR, "weekday")
    h = analytics["hourly_demand_supply"]
    c = h[(h["level"] == "corridor") & (h["corridor"] == config.PRIMARY_CORRIDOR) & (h["day_type"] == "weekday")].set_index("hour")
    for _, r in slots.iterrows():
        assert r["state_seats"] == pytest.approx(c.loc[int(r["hour"]), "seats_offered"])
        assert r["private_seats"] == pytest.approx(c.loc[int(r["hour"]), "private_seats"])
    assert set(slots.loc[slots["state_gap"], "hour"]) >= {18, 19, 20, 21}  # the planted evening gap is visible


def test_fares_and_pricing_baseline(tables, analytics):
    fares = CA.fare_comparison(tables["competitor_services"], tables["routes"], "Rajkot-Somnath", "weekday")
    assert {"AC_seater", "AC_sleeper"} <= set(fares["bus_type"])
    assert (fares["private_surge_fare_inr"].dropna() >= fares["private_base_fare_inr"].dropna()).all()
    rs, kp = analytics["route_summary"], analytics["route_kpis"]
    row = rs[rs["route_id"] == "IC02"].iloc[0]
    b = CA.pricing_baseline(kp, row, "weekday")
    res = SC.pricing_scenario(b["baseline_demand"], b["baseline_fare"], b["baseline_fare"], config.PRICING_ELASTICITY_DEFAULT, b["seats_offered"], b["operating_cost"])
    # baseline occupancy is the route load factor of that day type; unchanged fare changes nothing
    k = kp[(kp["route_id"] == "IC02") & (kp["day_type"] == "weekday")]
    assert b["load_factor_pct"] == pytest.approx(k["estimated_passenger_km"].sum() / k["seat_km"].sum() * 100)
    assert res["revenue_change_inr"] == pytest.approx(0) and res["occupancy"] == pytest.approx(b["load_factor_pct"] / 100)
    assert b["baseline_revenue"] == pytest.approx(k["ticket_revenue_inr"].sum() / k["service_date"].nunique())
    with pytest.raises(ValueError):
        CA.pricing_baseline(kp.iloc[0:0], row, "weekday")


# ------------------------------------------------------- assets, survey, cctv
def test_assets_improvement_ranking(tables):
    a, d = tables["assets_assessment"], tables["digital_assessment"]
    names = dict(zip(a["asset_id"], a["asset_name"]))
    imp = A.improvement_list(a, d, names)
    assert len(imp) == len(a) + len(d) and imp["score"].is_monotonic_increasing and imp["rank"].tolist() == list(range(1, len(imp) + 1))
    assert (imp["points_to_target"] == 5 - imp["score"]).all() and imp["asset"].isin(names.values()).all()
    s = A.assets_summary(a, d)
    assert s["n_below_threshold"] == int((a["score"] < 2.5).sum() + (d["maturity_score"] < 2.5).sum())
    assert A.asset_matrix(a).shape == (a["asset_id"].nunique(), a["dimension"].nunique())


def test_survey_summaries(tables):
    s = tables["survey_responses"]
    meta = SV.survey_meta(s)
    assert meta["n"] == len(s) and meta["source_types"] == ["synthetic"]
    assert SV.mode_summary(s)["share_pct"].sum() == pytest.approx(100)
    priv = SV.private_mode_users(s)
    r = SV.private_use_reasons(s)
    first = r.iloc[0]
    assert first["responses"] == sum(first["category"] in json.loads(x) for x in priv["reasons"])
    assert first["share_pct"] == pytest.approx(first["responses"] / len(priv) * 100)
    assert 0 <= SV.stated_switch_intent(s)["share_pct"] <= 100
    assert SV.switch_conditions(s.iloc[0:0]).empty


def test_detector_status_never_claims_output():
    assert CC.detector_status({"ultralytics": False, "supervision": False, "cv2": False})["state"] == "unavailable"
    ok = CC.detector_status({"ultralytics": True, "supervision": True, "cv2": True})
    assert ok["state"] == "no_output" and "no real counts" in ok["message"]


# ------------------------------------------------------------------- exports
def test_csv_export_has_provenance_and_matches_filters(analytics, tables):
    rs = analytics["route_summary"]
    ctx = {"route_summary": rs, "route_stops": tables["route_stops"], "stops": tables["stops"]}
    f = F.Filters("Rajkot-Somnath", "weekday", 7, 10)
    prov = {"source_type": "synthetic", "seed": 42, "generated_at": "2026-01-01T00:00:00+00:00"}
    avail = {n: analytics[n] for n in X.EXPORTS if n in analytics}  # M7 model tables (predictions, metrics, paths...) come from separate commands
    assert {"route_summary", "hourly_demand_supply", "od_flows", "recommendations"} <= set(avail)
    out = X.build_exports(avail, f, ctx, lambda n: prov)
    assert set(out) == set(avail)
    df, data = out["hourly_demand_supply"]
    text = data.decode("utf-8")
    head = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert any("Simulated data for demonstration" in ln for ln in head) and any("seed: 42" in ln for ln in head)
    assert any("Rajkot-Somnath" in ln for ln in head) and any("rows: %d" % len(df) in ln for ln in head)
    back = pd.read_csv(io.StringIO(text), comment="#")
    assert len(back) == len(df) and df["hour"].between(7, 9).all() and set(df["day_type"]) == {"weekday"}
    assert out["route_summary"][0]["boardings"].sum() == rs[rs["corridor"] == "Rajkot-Somnath"]["boardings"].sum()
    bundle = json.loads(X.provenance_bundle(f, {"route_summary": prov}, {"route_summary": 3}))
    assert bundle["filters"]["hours"] == "07:00–10:00" and bundle["tables"]["route_summary"]["rows"] == 3


# ----------------------------------------------------------------- narrative
def test_narrative_text_from_data(analytics):
    rec = analytics["recommendations"]
    r1 = rec[rec["category"] == "add_service_corridor_slot"].iloc[0]
    txt = N.impact_summary(r1)
    assert "₹" in txt and "not profit" in txt and "nan" not in txt.lower()
    assert len(N.capture_sensitivity_lines(r1)) == len(config.STATE_CAPTURE_SHARE_SENSITIVITY)
    prot = rec[rec["category"] == "protect_minimum_service"].iloc[0]
    assert "not a commercial test" in N.impact_summary(prot)
    assert N.describe_value("fare_per_passenger_inr", 375.0) == "fare per passenger inr: ₹375"
    assert N.describe_value("private_occupancy_assumption", 0.75).endswith("75%")
    assert N.describe_value("nested", {"a": {"b": 1}}) is None
