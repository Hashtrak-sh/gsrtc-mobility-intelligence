"""Tests for modules/analytics/cost_model.py (illustrative cost model; reads the committed synthetic layer)."""
from __future__ import annotations

import dataclasses

import pytest

from modules.analytics import cost_model as cm
from modules.data_gen import constants as C


@pytest.fixture(scope="module")
def inputs():
    return cm.load_cost_inputs()


@pytest.fixture(scope="module")
def model(inputs):
    trips, routes = inputs
    return cm.build_cost_model(trips, routes)


@pytest.mark.parametrize("cls", cm.EXISTING_CLASSES)
def test_trip_operating_cost_matches_base_rate_exactly(model, cls):
    assert cm.trip_operating_cost_per_km(model, cls) == pytest.approx(C.OPERATING_COST_PER_KM_INR[cls], rel=1e-9)
    # per trip too (rate x length)
    assert cm.trip_costs(model, cls, 100.0)["trip_operating_cost_inr"] == pytest.approx(100.0 * C.OPERATING_COST_PER_KM_INR[cls], rel=1e-9)


def test_maintenance_is_positive_balancing_item(model):
    for cls in cm.EXISTING_CLASSES:
        assert model.class_params[cls].maintenance_inr_per_km > 0


def test_reference_speed_is_vehicle_km_weighted(inputs, model):
    trips, routes = inputs
    t = trips[trips.bus_type == "express"].merge(routes[["route_id", "length_km"]], on="route_id")
    assert model.ref_speeds["express"] == pytest.approx(t.length_km.sum() / (t.scheduled_minutes.sum() / 60.0), rel=1e-12)


def test_parameter_sensitivity_diesel(model):
    base = cm.trip_operating_cost_per_km(model, "express")
    dearer = cm.trip_operating_cost_per_km(model.with_global(diesel_inr_per_l=110.0), "express")
    expected = (110.0 - 92.0) / model.class_params["express"].fuel_km_per_l
    assert dearer - base == pytest.approx(expected, rel=1e-9)
    assert dearer != pytest.approx(C.OPERATING_COST_PER_KM_INR["express"], rel=1e-6)
    # AC penalty scales the diesel increase
    ac = model.class_params["AC_seater"]
    d_ac = cm.trip_operating_cost_per_km(model.with_global(diesel_inr_per_l=110.0), "AC_seater") - cm.trip_operating_cost_per_km(model, "AC_seater")
    assert d_ac == pytest.approx(18.0 / ac.fuel_km_per_l * (1 + ac.ac_fuel_penalty), rel=1e-9)


def test_parameter_sensitivity_crew_and_class_override(model):
    m2 = model.with_global(driver_inr_per_hour=280.0)
    delta = 100.0 / model.ref_speeds["AC_sleeper"]
    assert cm.trip_operating_cost_per_km(m2, "AC_sleeper") - cm.trip_operating_cost_per_km(model, "AC_sleeper") == pytest.approx(delta, rel=1e-9)
    m3 = model.with_class("express", tyres_inr_per_km=4.5)
    assert cm.trip_operating_cost_per_km(m3, "express") - cm.trip_operating_cost_per_km(model, "express") == pytest.approx(2.0, rel=1e-9)
    # dataclasses.replace works on the frozen parameter objects
    gp = dataclasses.replace(model.global_params, overhead_share=0.15)
    assert dataclasses.replace(model, global_params=gp).global_params.overhead_share == 0.15
    with pytest.raises(dataclasses.FrozenInstanceError):
        model.global_params.diesel_inr_per_l = 1.0  # type: ignore[misc]


@pytest.mark.parametrize("cls", cm.ALL_CLASSES)
def test_full_cost_exceeds_trip_cost(model, cls):
    assert cm.full_cost_per_km(model, cls, corridor="Rajkot-Somnath", length_km=200.0) > cm.trip_operating_cost_per_km(model, cls)
    assert cm.full_cost_per_km(model, cls) > cm.trip_operating_cost_per_km(model, cls)


def test_e_bus_energy_uses_electricity_not_diesel(model):
    cp = model.class_params["e_bus"]
    c = cm.components_per_km(model, "e_bus")
    assert c["energy"] == pytest.approx(9.0 * cp.kwh_per_km)
    m_diesel = model.with_global(diesel_inr_per_l=200.0)
    assert cm.components_per_km(m_diesel, "e_bus")["energy"] == pytest.approx(c["energy"])
    m_elec = model.with_global(electricity_inr_per_kwh=12.0)
    assert cm.components_per_km(m_elec, "e_bus")["energy"] == pytest.approx(12.0 * cp.kwh_per_km)
    # and diesel classes ignore electricity
    assert cm.components_per_km(m_elec, "express")["energy"] == pytest.approx(cm.components_per_km(model, "express")["energy"])


def test_lease_replaces_depreciation(model):
    c = cm.components_per_km(model, "e_bus")
    assert c["depreciation_or_lease"] == pytest.approx(model.class_params["e_bus"].lease_inr_per_km)
    own = model.with_class("e_bus", lease_inr_per_km=None)
    cp = own.class_params["e_bus"]
    expected = cp.bus_price_inr * (1 - cp.residual_pct) / cp.life_years / (cp.daily_km * own.global_params.working_days_per_year)
    assert cm.components_per_km(own, "e_bus")["depreciation_or_lease"] == pytest.approx(expected)


def test_depreciation_and_overhead_formulas(model):
    cp = model.class_params["express"]
    gp = model.global_params
    c = cm.components_per_km(model, "express", corridor="Rajkot-Junagadh", length_km=100.0)
    assert c["depreciation_or_lease"] == pytest.approx(cp.bus_price_inr * 0.9 / cp.life_years / (cp.daily_km * gp.working_days_per_year))
    assert c["tolls"] == pytest.approx(250.0 / 100.0)
    assert c["dead_km_uplift"] == pytest.approx(gp.dead_km_share * (c["energy"] + c["tyres"] + c["maintenance_and_other_running"]))
    direct = sum(v for k, v in c.items() if k != "overhead")
    assert c["overhead"] == pytest.approx(gp.overhead_share * direct)


def test_component_table_sums_to_totals(model):
    for corridor, length in ((None, None), ("Rajkot-Ahmedabad", 231.66)):
        tab = cm.component_table(model, corridor=corridor, length_km=length)
        assert set(tab.columns) >= {"bus_class", "component", "layer", "inr_per_km"}
        assert set(tab.bus_class) == set(cm.ALL_CLASSES)
        for cls, g in tab.groupby("bus_class"):
            sp = cm.running_speed(model, cls, intercity=corridor is not None)
            assert g.inr_per_km.sum() == pytest.approx(cm.full_cost_per_km(model, cls, corridor=corridor, length_km=length, speed_kmph=sp), rel=1e-12)
            assert g[g.layer == cm.LAYER_TRIP].inr_per_km.sum() == pytest.approx(cm.trip_operating_cost_per_km(model, cls, speed_kmph=sp), rel=1e-12)
    assert "tolls" not in set(cm.component_table(model).component)


def test_peak_factor_default_has_no_effect_and_scales_crew(model, inputs):
    trips, _ = inputs
    assert (cm.timetable_running_time_check(trips).distinct_scheduled_minutes == 1).all()  # constant running time per route
    assert cm.trip_operating_cost_per_km(model, "express", peak=True) == pytest.approx(cm.trip_operating_cost_per_km(model, "express"))
    m = model.with_global(peak_running_time_factor=1.25)
    crew = cm.components_per_km(model, "express")["crew"]
    assert cm.trip_operating_cost_per_km(m, "express", peak=True) - cm.trip_operating_cost_per_km(m, "express") == pytest.approx(0.25 * crew)
    assert cm.trip_operating_cost_per_km(m, "express") == pytest.approx(C.OPERATING_COST_PER_KM_INR["express"], rel=1e-9)


def test_what_if_classes_present_and_fares(model):
    assert set(cm.WHAT_IF_CLASSES) <= set(model.class_params)
    assert all(model.class_params[c].is_what_if for c in cm.WHAT_IF_CLASSES)
    assert cm.fare_per_passenger(model, "AC_seater", 191.15) == 375.0  # same rounding as the generator's FARE_TABLE rule
    assert cm.fare_per_passenger(model, "volvo_ac", 200.0) > cm.fare_per_passenger(model, "AC_seater", 200.0)
    assert len(cm.cost_summary(model)) == 7
