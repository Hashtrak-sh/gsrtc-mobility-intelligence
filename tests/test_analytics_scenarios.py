"""Scenario functions: service frequency and pricing (pure functions)."""
import math

import numpy as np
import pytest

import config
from modules.analytics import scenarios as S


# ----------------------------------------------------------------------------- service frequency
def test_required_departures_ceil():
    assert S.required_departures(100, 40, 0.85) == 3            # 100 / 34 = 2.94 -> 3
    assert S.required_departures(34, 40, 0.85) == 1             # exactly 1.0 -> 1 (no float overshoot)
    assert S.required_departures(35, 40, 0.85) == 2
    assert S.required_departures(0, 40, 0.85) == 0
    assert S.required_departures(40, 40, 1.0) == 1


def test_service_frequency_scenario_numbers():
    r = S.service_frequency_scenario(100, 40, 0.85, existing_departures=2, trip_km=15, cost_per_km=52, fare_per_passenger=8)
    assert r["label"] == "illustrative service scenario"
    assert r["required_departures"] == 3 and r["additional_departures"] == 1 and r["total_departures_after"] == 3
    assert r["incremental_vehicle_km"] == pytest.approx(15) and r["incremental_operating_cost_inr"] == pytest.approx(780)
    assert r["load_factor_before"] == pytest.approx(1.25) and r["projected_load_factor_after"] == pytest.approx(100 / 120)
    assert r["incremental_passengers"] == pytest.approx(20)       # 100 - min(100, 2 x 40 seats)
    assert r["incremental_revenue_inr"] == pytest.approx(160) and r["incremental_contribution_inr"] == pytest.approx(160 - 780)
    assert r["fleet_constraint_not_modelled"] is True and r["within_available_buses"] is None
    assert any("not modelled" in c for c in r["constraints"])


def test_service_scenario_fleet_flag_and_no_removal():
    r = S.service_frequency_scenario(100, 40, 0.85, 2, 15, 52, available_buses=0)
    assert r["fleet_constraint_not_modelled"] is False and r["within_available_buses"] is False
    assert np.isnan(r["incremental_revenue_inr"])                 # no fare given -> not invented
    low = S.service_frequency_scenario(10, 40, 0.85, existing_departures=5, trip_km=15, cost_per_km=52)
    assert low["additional_departures"] == 0 and low["incremental_operating_cost_inr"] == 0   # never removes service


def test_service_scenario_edge_cases():
    z = S.service_frequency_scenario(0, 40, 0.85, 0, 10, 50)
    assert z["required_departures"] == 0 and np.isnan(z["projected_load_factor_after"]) and np.isnan(z["load_factor_before"])
    for bad in [dict(seats_per_bus=0), dict(target_load_factor=0), dict(projected_passengers=-1), dict(projected_passengers=float("nan")),
                dict(trip_km=-1), dict(existing_departures=-1), dict(target_load_factor=3.0)]:
        kw = dict(projected_passengers=100, seats_per_bus=40, target_load_factor=0.85, existing_departures=2, trip_km=15, cost_per_km=52)
        kw.update(bad)
        with pytest.raises(ValueError):
            S.service_frequency_scenario(**kw)


# ----------------------------------------------------------------------------- pricing
def test_fare_unchanged_or_zero_elasticity_leaves_demand_unchanged():
    r = S.pricing_scenario(100, 100, 100, -0.6, 200, 1000)
    assert r["demand_unconstrained"] == pytest.approx(100) and r["revenue_inr"] == pytest.approx(r["baseline_revenue_inr"])
    z = S.pricing_scenario(100, 100, 130, 0.0, 200, 1000)
    assert z["demand_unconstrained"] == pytest.approx(100) and z["revenue_inr"] == pytest.approx(13000)


def test_pricing_known_numeric_case():
    r = S.pricing_scenario(100, 100, 200, -1.0, 200, 1000)       # unit elasticity: demand halves, revenue unchanged
    assert r["demand_unconstrained"] == pytest.approx(50) and r["revenue_inr"] == pytest.approx(10000)
    assert r["occupancy"] == pytest.approx(0.25) and r["contribution_inr"] == pytest.approx(9000)
    assert r["fare_change_pct"] == pytest.approx(100.0) and r["spilled_demand"] == 0
    r2 = S.pricing_scenario(100, 100, 110, -0.5, 200, 1000)
    d = 100 * (1.1 ** -0.5)
    assert r2["served_demand"] == pytest.approx(d) and r2["revenue_inr"] == pytest.approx(d * 110)
    assert r2["revenue_change_inr"] == pytest.approx(d * 110 - 10000)


def test_pricing_capacity_cap_and_spill():
    r = S.pricing_scenario(100, 100, 100, -0.4, 80, 500)
    assert r["served_demand"] == 80 and r["spilled_demand"] == pytest.approx(20) and r["occupancy"] == pytest.approx(1.0)
    assert r["baseline_revenue_inr"] == pytest.approx(8000)       # baseline capped too (like for like)
    cut = S.pricing_scenario(100, 100, 50, -1.0, 80, 500)         # fare halves -> demand 200, served 80
    assert cut["demand_unconstrained"] == pytest.approx(200) and cut["spilled_demand"] == pytest.approx(120) and cut["revenue_inr"] == pytest.approx(4000)
    nos = S.pricing_scenario(100, 100, 120, -0.4, 0, 500)
    assert nos["served_demand"] == 0 and np.isnan(nos["occupancy"]) and nos["contribution_inr"] == -500   # zero seats: no division


def test_pricing_validation_errors():
    ok = dict(baseline_demand=100, baseline_fare=100, new_fare=110, elasticity=-0.4, seats_offered=40, operating_cost=100)
    S.pricing_scenario(**ok)
    for bad in [dict(baseline_fare=0), dict(baseline_fare=-5), dict(new_fare=0), dict(new_fare=float("nan")), dict(elasticity=-5.0),
                dict(elasticity=0.3), dict(baseline_demand=-1), dict(seats_offered=-1), dict(operating_cost=-1), dict(new_fare=500),
                dict(new_fare=10), dict(fare_bounds=(120, 100)), dict(fare_bounds=(0, 200)), dict(new_fare=150, fare_bounds=(90, 120))]:
        with pytest.raises(ValueError):
            S.pricing_scenario(**{**ok, **bad})
    assert S.pricing_scenario(**{**ok, "new_fare": 150, "fare_bounds": (90, 200)})["new_fare_inr"] == 150
    assert S.pricing_scenario(**{**ok, "baseline_demand": 0})["served_demand"] == 0     # zero passengers handled


def test_pricing_sensitivity_table():
    t = S.pricing_sensitivity(100, 100, 120, 200, 1000)
    assert list(t["elasticity"]) == list(config.PRICING_ELASTICITY_SENSITIVITY) == [-0.2, -0.4, -0.6, -0.8, -1.0]
    assert t["demand_unconstrained"].is_monotonic_decreasing    # fare up -> more elastic = less demand
    assert t["demand_unconstrained"].iloc[0] == pytest.approx(100 * 1.2 ** -0.2)
    assert t["revenue_inr"].iloc[-1] == pytest.approx(100 * 1.2 ** -1.0 * 120)
    flat = S.pricing_sensitivity(100, 100, 100, 200, 1000)
    assert np.allclose(flat["demand_unconstrained"], 100)         # fare unchanged -> demand unchanged for every elasticity
    custom = S.pricing_sensitivity(100, 100, 120, 200, 1000, elasticities=[-0.3, -0.5])
    assert len(custom) == 2
    with pytest.raises(ValueError):
        S.pricing_sensitivity(100, 100, 120, 200, 1000, elasticities=[])
    assert not math.isnan(config.PRICING_ELASTICITY_DEFAULT) and config.PRICING_ELASTICITY_DEFAULT < 0
