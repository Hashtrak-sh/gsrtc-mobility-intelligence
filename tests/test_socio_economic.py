"""Tests for modules.analytics.socio_economic (illustrative CBA; simulated inputs)."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from modules.analytics import socio_economic as se
from modules.analytics.socio_economic import SocioEconomicParams as P


def make_inputs(pax=1000.0, trip_km=200.0, bus_km=2000.0, fare=200.0, full_cost=300000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "corridor": ["A", "B"],
        "passengers_per_day": [pax, pax * 2],
        "passenger_km_per_day": [pax * trip_km, pax * 2 * trip_km],
        "bus_km_per_day": [bus_km, bus_km],
        "average_fare_inr": [fare, fare],
        "trip_operating_cost_per_day_inr": [200000.0, 200000.0],
        "full_cost_per_day_inr": [full_cost, full_cost],
        "revenue_per_day_inr": [pax * fare, pax * 2 * fare],
    })


def test_shares_must_sum_to_one():
    with pytest.raises(ValueError):
        dataclasses.replace(P(), share_car=0.5)
    assert abs(sum(getattr(P(), f) for f in se.SHARE_FIELDS) - 1) < 1e-9
    q = se.rebalance_shares(P(), share_car=0.4)
    assert q.share_car == pytest.approx(0.4)
    assert sum(getattr(q, f) for f in se.SHARE_FIELDS) == pytest.approx(1.0)


def test_zero_passengers_zero_benefits():
    df = make_inputs(pax=0.0, bus_km=0.0, full_cost=1000.0)
    r = se.compute_cba(df)
    assert (r["social_benefit_per_day_inr"] == 0).all()
    assert (r["car_km_avoided_per_day"] == 0).all()
    assert (r["co2_tonnes_saved"] == 0).all()


def test_car_km_avoided_hand_check():
    r = se.compute_cba(make_inputs()).iloc[0]
    # 1000 pax x 0.25 x 200 km / 2.5 occupancy = 20,000 car-km
    assert r["car_km_avoided_per_day"] == pytest.approx(20000.0)
    # 1000 x 0.10 x 200 / 1.5
    assert r["two_wheeler_km_avoided_per_day"] == pytest.approx(1000 * 0.10 * 200 / 1.5)


def test_co2_sign_and_units():
    p = P()
    r = se.compute_cba(make_inputs(bus_km=0.0), p).iloc[0]
    assert r["co2_tonnes_saved"] > 0  # no bus emissions: only avoided emissions
    expected_private_t = (20000 * p.co2_car_kg_per_km + 1000 * 0.10 * 200 / 1.5 * p.co2_two_wheeler_kg_per_km
                          + 1000 * 0.05 * 200 / 5 * p.co2_shared_taxi_kg_per_km
                          + 200000 * (p.share_private_bus * p.co2_private_bus_kg_per_pkm
                                      + p.share_rail * p.co2_rail_kg_per_pkm)) / 1000
    assert r["co2_tonnes_private_avoided"] == pytest.approx(expected_private_t)
    assert r["co2_value_inr"] == pytest.approx(r["co2_tonnes_saved"] * p.carbon_price_inr_per_tonne)
    # a huge bus-km makes the net negative (honest)
    assert se.compute_cba(make_inputs(bus_km=1e6), p).iloc[0]["co2_tonnes_saved"] < 0
    # e-bus lowers bus emissions
    e = dataclasses.replace(p, electric_bus_share=1.0)
    assert e.bus_co2_kg_per_km < p.bus_co2_kg_per_km


def test_bcr_identity_and_nan_without_cost():
    r = se.compute_cba(make_inputs()).iloc[0]
    assert r["bcr"] == pytest.approx((r["social_benefit_per_day_inr"] + r["revenue_per_day_inr"]) / 300000.0)
    assert r["net_social_benefit_per_day_inr"] == pytest.approx(
        r["social_benefit_per_day_inr"] + r["revenue_per_day_inr"] - 300000.0)
    assert r["financial_result_per_day_inr"] == pytest.approx(r["revenue_per_day_inr"] - 300000.0)
    assert r["social_benefit_per_year_inr"] == pytest.approx(r["social_benefit_per_day_inr"] * 365)
    miss = make_inputs()
    miss["full_cost_per_day_inr"] = np.nan
    rm = se.compute_cba(miss)
    assert rm["bcr"].isna().all() and rm["net_social_benefit_per_day_inr"].isna().all()
    assert rm["social_benefit_per_day_inr"].notna().all()


def test_component_table_sums():
    res = se.compute_cba(make_inputs())
    t = se.component_table(res)
    for _, r in res.iterrows():
        sub = t[t["corridor"] == r["corridor"]]
        assert sub[sub["group"] == "social"]["INR_per_day"].sum() == pytest.approx(r["social_benefit_per_day_inr"])
        assert sub["INR_per_day"].sum() == pytest.approx(r["net_social_benefit_per_day_inr"])
    assert set(t["sign"]) <= {1, -1}
    assert set(se.component_assumptions()) >= set(t["component"])


def test_value_of_time_monotonic():
    fast = dataclasses.replace(P(), speed_bus_kmph=200.0, access_wait_bus_h=0.0)  # bus faster than all modes
    slow = P()  # default: bus slower than the alternatives
    df = make_inputs()
    lo_f = se.compute_cba(df, dataclasses.replace(fast, value_of_time_inr_per_hour=50))["time_benefit_inr"]
    hi_f = se.compute_cba(df, dataclasses.replace(fast, value_of_time_inr_per_hour=200))["time_benefit_inr"]
    assert (hi_f > lo_f).all() and (lo_f > 0).all()
    lo_s = se.compute_cba(df, dataclasses.replace(slow, value_of_time_inr_per_hour=50))["time_benefit_inr"]
    hi_s = se.compute_cba(df, dataclasses.replace(slow, value_of_time_inr_per_hour=200))["time_benefit_inr"]
    assert (hi_s < lo_s).all() and (hi_s < 0).all()


def test_sensitivity_and_takeaway():
    df = make_inputs()
    sens = se.sensitivity_table(df)
    assert set(sens["parameter"]) == set(se.DEFAULT_SENSITIVITY)
    base = se.compute_cba(df).set_index("corridor")["bcr"]
    cen = sens[sens["level"] == "central"].drop_duplicates(["corridor", "parameter"])
    for _, r in cen.iterrows():
        assert r["bcr"] == pytest.approx(base[r["corridor"]])
    # higher carbon price -> higher BCR when bus emissions are small relative to avoided ones
    tor = se.tornado_table(sens)
    assert {"bcr_low", "bcr_high", "bcr_swing"} <= set(tor.columns)
    s = se.takeaway(se.compute_cba(df))
    assert "Illustrative" in s and s.count(".") >= 1
    miss = df.assign(full_cost_per_day_inr=np.nan)
    assert "cannot be computed" in se.takeaway(se.compute_cba(miss))


def test_default_inputs_from_committed_data():
    from modules.data.io import read_table
    rs = read_table("route_summary", "processed")
    c = se.build_default_inputs(rs)
    assert len(c) == rs.loc[rs["route_type"] == "intercity", "corridor"].nunique() == 4
    assert (c["passengers_per_day"] > 0).all() and c["full_cost_per_day_inr"].isna().all()
    assert set(se.REQUIRED_COLUMNS) <= set(c.columns)
    r = se.build_default_inputs(rs, by="route")
    assert len(r) == (rs["route_type"] == "intercity").sum()
    assert r["passengers_per_day"].sum() == pytest.approx(c["passengers_per_day"].sum())
    out = se.compute_cba(c)
    assert len(out) == 4 and np.isfinite(out["social_benefit_per_day_inr"]).all()
    agg = se.aggregate_to_corridor(se.compute_cba(r))
    assert agg["social_benefit_per_day_inr"].sum() == pytest.approx(out["social_benefit_per_day_inr"].sum())


def test_survey_split_optional():
    survey = pd.DataFrame({"current_mode": ["car"] * 3 + ["two_wheeler"]})
    q = se.params_with_survey_split(P(), survey)
    assert q.share_car == pytest.approx((P().share_car + P().share_two_wheeler) * 0.75)
