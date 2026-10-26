"""M5 competition: fare elasticity / surge index, competitive gap score components and weights, competition_analysis table,
and the competition-enriched recommendation."""
import json

import numpy as np
import pandas as pd
import pytest

import config
from modules.analytics import scenarios as S
from modules.competition import gap_score as G


# ------------------------------------------------------------------------------------------ elasticity and fare index
def test_elasticity_formula_and_revenue():
    r = S.pricing_scenario(100, 400, 440, -0.5, seats_offered=1000, operating_cost=20000)
    assert r["demand_unconstrained"] == pytest.approx(100 * (440 / 400) ** -0.5)
    assert r["revenue_inr"] == pytest.approx(r["served_demand"] * 440)
    assert r["contribution_inr"] == pytest.approx(r["revenue_inr"] - 20000)
    assert r["occupancy"] == pytest.approx(r["served_demand"] / 1000)
    # unit elasticity keeps revenue constant; inelastic demand raises revenue with the fare
    unit = S.pricing_scenario(100, 400, 500, -1.0, 1000, 0)
    assert unit["revenue_inr"] == pytest.approx(unit["baseline_revenue_inr"])
    assert S.pricing_scenario(100, 400, 500, -0.4, 1000, 0)["revenue_change_inr"] > 0
    assert S.pricing_scenario(100, 400, 500, -1.6, 1000, 0)["revenue_change_inr"] < 0


def test_pricing_capacity_cap_and_division_guards():
    capped = S.pricing_scenario(100, 400, 300, -0.8, seats_offered=90, operating_cost=0)   # lower fare, demand > seats
    assert capped["served_demand"] == 90 and capped["spilled_demand"] > 0 and capped["occupancy"] == 1.0
    assert np.isnan(S.pricing_scenario(100, 400, 400, -0.4, seats_offered=0, operating_cost=0)["occupancy"])   # no seats -> NaN, no crash
    for bad in (dict(baseline_fare=0), dict(new_fare=0), dict(new_fare=-5), dict(baseline_demand=-1), dict(elasticity=-4.0),
                dict(new_fare=100000), dict(baseline_fare=float("nan"))):
        kw = dict(baseline_demand=100, baseline_fare=400, new_fare=420, elasticity=-0.4, seats_offered=100, operating_cost=0)
        kw.update(bad)
        with pytest.raises(ValueError):
            S.pricing_scenario(**kw)


def test_sensitivity_covers_config_elasticities_and_is_monotone():
    sens = S.pricing_sensitivity(100, 400, 480, 1000, 0)
    assert list(sens["elasticity"]) == list(config.PRICING_ELASTICITY_SENSITIVITY)
    assert (np.diff(sens["served_demand"].to_numpy()) < 0).all()          # a higher fare lowers demand more as elasticity gets more negative


def test_fare_index_normal_and_surge(analytics):
    c = analytics["competition_analysis"]
    f = c.dropna(subset=["fare_index"])
    assert len(f) > 0
    assert np.allclose(f["fare_index"], f["state_fare_inr"] / f["median_private_fare_inr"])
    assert np.allclose(f["fare_index_surge"], f["state_fare_inr"] / f["median_private_surge_fare_inr"])
    assert (f["fare_index_surge"] <= f["fare_index"] + 1e-12).all()          # surge fare >= base fare, so the index can only fall
    fest = f[(f["route_pair"] == "Rajkot-Somnath") & (f["hour"] == 19)].set_index("day_type")
    assert fest.loc["festival", "fare_index_surge"] < fest.loc["weekday", "fare_index_surge"]   # festival surge is larger
    assert (f["fare_index"] < 1).all()           # synthetic private fares are deliberately above the state tariff
    # missing fares stay missing, never 0
    nofare = c[c["private_departures"] == 0]
    assert nofare["fare_index"].isna().all() and nofare["median_private_fare_inr"].isna().all()


# ------------------------------------------------------------------------------------------ gap score components
def test_weights_sum_to_one_and_are_versioned():
    w = config.COMPETITIVE_GAP_WEIGHTS
    assert sum(w.components().values()) == pytest.approx(1.0) and w.weight_version
    assert set(w.components()) == set(G.COMPONENT_COLUMNS)
    with pytest.raises(ValueError):
        config.CompetitiveGapWeights(departure_slot_gap=0.9).validate()


KW = dict(state_deps=0.0, private_deps=2.0, state_seats=0.0, private_seats=60.0, premium_gap=2.0, fare_index=0.7, review_deficit=0.3)


def test_score_components_known_cases():
    c = G.score_components(**KW)
    assert c["departure_slot_gap"] == 1.0 and c["seat_share_gap"] == 1.0 and c["premium_gap"] == 1.0
    assert c["fare_disadvantage"] == 0.0            # state cheaper than private: no fare disadvantage
    assert c["review_theme_deficit"] == 1.0         # 0.3 above the 0.15 saturation, capped
    # equal state and private service -> no departure or seat gap
    eq = G.score_components(**{**KW, "state_deps": 2.0, "state_seats": 60.0})
    assert eq["departure_slot_gap"] == 0 and eq["seat_share_gap"] == 0
    # state above the private median fare: disadvantage grows to its cap
    assert G.score_components(**{**KW, "fare_index": 1.125})["fare_disadvantage"] == pytest.approx(0.5)
    assert G.score_components(**{**KW, "fare_index": 2.0})["fare_disadvantage"] == 1.0
    # no private service -> nothing to measure
    assert set(G.score_components(**{**KW, "private_deps": 0.0}).values()) == {0.0}
    # unavailable inputs stay NaN (not 0)
    nan = G.score_components(**{**KW, "fare_index": float("nan"), "review_deficit": float("nan")})
    assert np.isnan(nan["fare_disadvantage"]) and np.isnan(nan["review_theme_deficit"])


def test_combine_score_weights_rescale_and_bounds():
    ones = {k: 1.0 for k in config.COMPETITIVE_GAP_WEIGHTS.components()}
    assert G.combine_score(ones) == (pytest.approx(100.0), [])
    assert G.combine_score({k: 0.0 for k in ones})[0] == 0.0
    part = {**ones, "fare_disadvantage": float("nan")}
    score, missing = G.combine_score(part)
    assert score == pytest.approx(100.0) and missing == ["fare_disadvantage"]      # re-weighted over the available components
    half = {**{k: 0.0 for k in ones}, "departure_slot_gap": 1.0}
    assert G.combine_score(half)[0] == pytest.approx(30.0)                          # 0.30 weight x 100
    assert np.isnan(G.combine_score({k: float("nan") for k in ones})[0])


# ------------------------------------------------------------------------------------------ competition_analysis table
def test_competition_analysis_schema_and_scores(analytics):
    c = analytics["competition_analysis"]
    contract = ["route_pair", "hour", "state_departures", "private_departures", "state_seats", "private_seats", "state_fare_inr",
                "median_private_fare_inr", "fare_index", "premium_bus_gap", "review_theme_summary", "competitive_gap_score", "source_type"]
    assert set(contract) <= set(c.columns) and {"day_type", "fare_index_surge", "weights_json", "weight_version"} <= set(c.columns)
    assert set(c["route_pair"]) == set(config.INTERCITY_CORRIDORS) and set(c["day_type"]) == {"weekday", "weekend", "festival"}
    assert c["competitive_gap_score"].between(0, 100).all() and not c["competitive_gap_score"].isna().any()
    assert not c.duplicated(["route_pair", "hour", "day_type"]).any()
    assert (c.loc[c["private_departures"] == 0, "competitive_gap_score"] == 0).all()
    w = json.loads(c["weights_json"].iloc[0])
    assert sum(v for k, v in w.items() if k != "weight_version") == pytest.approx(1.0) and w["weight_version"] == c["weight_version"].iloc[0]
    # the score really is the documented weighted sum of the stored components
    comps = {k: c[col] for k, col in G.COMPONENT_COLUMNS.items()}
    full = c[c["missing_components"] == ""]
    recomputed = sum(float(w[k]) * comps[k][full.index] for k in comps) * 100
    assert np.allclose(recomputed, full["competitive_gap_score"])
    summ = json.loads(c["review_theme_summary"].iloc[0])
    assert {"state", "private", "method"} <= set(summ) and summ["state"]["n_reviews"] > 0


def test_evening_somnath_slot_is_among_the_highest_gaps(analytics):
    c = analytics["competition_analysis"]
    wk = c[c["day_type"] == "weekday"]
    som = wk[wk["route_pair"] == "Rajkot-Somnath"].sort_values("competitive_gap_score", ascending=False)
    assert set(som["hour"].head(3)) == {19, 20, 21}                                  # the planted 18:00-22:30 gap
    assert (som[som["hour"].between(18, 21)]["state_departures"] == 0).all()
    assert som[som["hour"].between(18, 21)]["competitive_gap_score"].min() >= 60
    # top third of all weekday corridor-hours with private service, and far above hours where the state also runs
    priv = wk[wk["private_departures"] > 0]["competitive_gap_score"]
    assert som[som["hour"].between(19, 21)]["competitive_gap_score"].min() >= priv.quantile(2 / 3)
    both_served = som[(som["state_departures"] > 0) & (som["private_departures"] > 0)]
    assert som[som["hour"] == 19]["competitive_gap_score"].iloc[0] > both_served["competitive_gap_score"].max()
    # premium gap: sleepers and the premium service in the evening have no state equivalent
    assert som[som["hour"].isin([19, 20, 21])]["premium_bus_gap"].min() >= 1 and som[som["hour"] == 22]["premium_bus_gap"].iloc[0] == 2


def test_top_gap_slots_ordering_and_fare_view(analytics):
    c = analytics["competition_analysis"]
    top = G.top_gap_slots(c, day_type="weekday", top=5)
    assert len(top) == 5 and top["competitive_gap_score"].is_monotonic_decreasing
    view = G.fare_index_view(c, "Rajkot-Somnath", "weekday")
    assert view["fare_index"].notna().all() and list(view["hour"]) == sorted(view["hour"])


def test_competition_analysis_is_deterministic(tables):
    a = G.competition_analysis(tables["trips"], tables["competitor_services"], tables["routes"], tables["reviews"])
    b = G.competition_analysis(tables["trips"], tables["competitor_services"], tables["routes"], tables["reviews"])
    pd.testing.assert_frame_equal(a, b)


def test_competition_analysis_handles_missing_reviews(tables):
    c = G.competition_analysis(tables["trips"], tables["competitor_services"], tables["routes"], tables["reviews"].iloc[0:0])
    assert c.loc[c["private_departures"] > 0, "review_theme_deficit"].isna().all()
    assert c["competitive_gap_score"].between(0, 100).all()          # re-weighted over the remaining components, not NaN
    assert (c.loc[c["private_departures"] > 0, "missing_components"].str.contains("review_theme_deficit")).all()


# ------------------------------------------------------------------------------------------ recommendation enrichment
def test_corridor_slot_recommendation_is_enriched_not_duplicated(analytics):
    rec = analytics["recommendations"]
    slot = rec[(rec["category"] == "add_service_corridor_slot") & (rec["corridor"] == "Rajkot-Somnath")]
    assert len(slot) == 1                                                            # no contradictory duplicate
    r = slot.iloc[0]
    assert r["time_window"] == "18:00-22:00" and r["recommendation_id"] == "REC-001"
    ev = json.loads(r["evidence_json"])
    assert ev["table"] == "hourly_demand_supply" and ev["competition"]["table"] == "competition_analysis"
    fig = ev["competition"]["figures"]
    assert fig["max_competitive_gap_score"] > 60 and fig["top_hour"] in (19, 20, 21) and fig["premium_bus_gap_services"] >= 3
    assert fig["mean_fare_index_surge"] < fig["mean_fare_index_normal"] < 1
    fs = json.loads(r["expected_impact_json"])["fare_scenario"]
    assert 0 < fs["projected_occupancy_at_tariff"] <= 1 and 0 < fs["projected_occupancy_at_proposed_fare"] <= 1
    assert fs["proposed_fare_inr"] == pytest.approx(config.COMPETITION_FARE_POSITION * fs["private_median_base_fare_inr"])
    assert len(fs["elasticity_sensitivity"]) == len(config.PRICING_ELASTICITY_SENSITIVITY)
    assert fs["contribution_at_proposed_fare_inr"] == pytest.approx(fs["revenue_at_proposed_fare_inr"] - fs["operating_cost_inr"])
    assert any("not profit" in a for a in fs["assumptions"])
    assert "Competition evidence" in r["action"] and "Fare scenario" in r["action"]
    assert "capture_share_sensitivity" in json.loads(r["expected_impact_json"])           # REC-001's existing impact is preserved


def test_recommendations_without_competition_table_still_work(tables, analytics):
    from modules.analytics import recommendations as R

    res = analytics
    base = R.generate_recommendations(res["hourly_demand_supply"], res["route_summary"], res["route_scores"], tables["routes"], res["trips_sum"],
                                      tables["stops"], tables["competitor_services"], res["legs"])
    assert len(base) == len(res["recommendations"]) and "competition" not in json.loads(base.iloc[0]["evidence_json"])
