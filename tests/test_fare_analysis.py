"""Tests for modules/analytics/fare_analysis.py (reads the committed synthetic + processed layers; nothing is written)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import config
from modules.analytics import cost_model as cm
from modules.analytics import fare_analysis as fa
from modules.data import io


@pytest.fixture(scope="module")
def d():
    return fa.load_inputs()


@pytest.fixture(scope="module")
def econ(d):
    return fa.band_economics(d["tm"], d["model"], d["routes"])


@pytest.fixture(scope="module")
def pc(econ, d):
    return fa.private_comparison(econ, d["competitors"])


def test_bands_derived_and_nonempty_for_somnath_weekday(d):
    b = d["bands"]
    s = b[(b.corridor == "Rajkot-Somnath") & (b.day_type == "weekday")]
    assert set(s.band) == {"peak", "normal"}
    # peak hours are exactly the high-load ones (rule, not hard-coded windows)
    assert s[s.band == "peak"].load_factor.min() >= s[s.band == "normal"].load_factor.max()
    assert (s.loc[s.band == "peak", "load_factor"] >= s.loc[s.band == "peak", "threshold"]).all()
    assert d["tm"]["band"].notna().all()


def test_peak_quantile_parameter_changes_bands(d):
    tm = d["tm"]
    lo = fa.classify_time_bands(tm, d["routes"], peak_quantile=0.5)
    hi = fa.classify_time_bands(tm, d["routes"], peak_quantile=0.9)
    assert (lo.band == "peak").sum() > (hi.band == "peak").sum() > 0
    with pytest.raises(ValueError):
        fa.classify_time_bands(tm, d["routes"], peak_quantile=1.5)


def test_reconciliation_with_route_summary_and_trips(d, econ):
    rs = io.read_table("route_summary", "processed").set_index("route_id")
    trips = d["trips"]
    g = econ.groupby("route_id")[["revenue_inr", "trip_operating_cost_inr", "operating_cost_data_inr", "trips", "passengers",
                                  "passenger_km", "seat_km"]].sum()
    for rid, row in g.iterrows():
        assert row.revenue_inr == pytest.approx(rs.loc[rid, "ticket_revenue_inr"], rel=1e-9)
        assert row.trip_operating_cost_inr == pytest.approx(rs.loc[rid, "operating_cost_inr"], rel=1e-9)
        assert row.operating_cost_data_inr == pytest.approx(rs.loc[rid, "operating_cost_inr"], rel=1e-9)
        assert row.trips == rs.loc[rid, "trips"]
        assert row.passengers == rs.loc[rid, "boardings"]
        assert row.passenger_km / row.seat_km * 100 == pytest.approx(rs.loc[rid, "load_factor_pct"], rel=1e-9)
        assert row.trip_operating_cost_inr == pytest.approx(trips[trips.route_id == rid].operating_cost_inr.sum(), rel=1e-9)
    assert set(g.index) == {f"IC0{i}" for i in range(1, 7)}
    kp = io.read_table("route_kpis", "processed")
    k = kp[kp.route_id.str.startswith("IC")].groupby("route_id").ticket_revenue_inr.sum()
    assert g.revenue_inr.sub(k).abs().max() < 1e-6  # float tolerance (INR)


def test_break_even_identities(econ):
    e = econ.dropna(subset=["yield_inr_per_pax_km"])
    for tag, col in (("trip", "trip_operating_cost_per_trip_inr"), ("full", "full_cost_per_trip_inr")):
        # at the break-even load factor (same yield) revenue per trip == cost per trip
        rev_at_be = e[f"be_load_factor_{tag}"] * e.seats * e.length_km * e.yield_inr_per_pax_km
        assert np.allclose(rev_at_be, e[col], rtol=1e-9)
        # break-even fare at the current load: margin == 0
        pax_trip = e.passengers / e.trips
        assert np.allclose(e[f"be_fare_current_lf_{tag}_inr"] * pax_trip, e[col], rtol=1e-9)
        # at the target load factor
        pax_t = e.target_load_factor * e.seats / e.trip_length_share
        assert np.allclose(e[f"be_fare_target_lf_{tag}_inr"] * pax_t, e[col], rtol=1e-9)
        # adult-equivalent fare scales yield to break-even at the target load
        y = e.yield_inr_per_pax_km * e[f"be_adult_fare_target_{tag}_inr"] / e.state_fare_full_length_inr
        assert np.allclose(y * e.target_load_factor * e.seats * e.length_km, e[col], rtol=1e-9)
    assert (e.full_cost_per_trip_inr > e.trip_operating_cost_per_trip_inr).all()
    assert np.allclose(e.contribution_per_trip_inr, e.revenue_per_trip_inr - e.trip_operating_cost_per_trip_inr)
    assert np.allclose(e.full_cost_margin_per_trip_inr, e.revenue_per_trip_inr - e.full_cost_per_trip_inr)
    assert (e.load_factor <= 1.0 + 1e-9).all()


def test_private_comparison_mapping_and_missing(pc, d):
    assert set(pc.private_bus_type) <= {"ordinary", "AC_seater", "AC_sleeper", "premium"}
    comp = d["competitors"]
    r = pc[(pc.route_id == "IC02") & (pc.day_type == "weekday") & (pc.band == "normal")].iloc[0]
    sel = comp[(comp.route_pair == "Rajkot-Somnath") & (comp.day_type == "weekday") & (comp.bus_type == "AC_seater")]
    assert r.private_comparator_inr == pytest.approx(sel.base_fare_inr.median())
    peak = pc[(pc.route_id == "IC06") & (pc.day_type == "weekday") & (pc.band == "peak")].iloc[0]
    sel = comp[(comp.route_pair == "Rajkot-Ahmedabad") & (comp.day_type == "weekday") & (comp.bus_type == "AC_seater")]
    assert peak.private_comparator_inr == pytest.approx(sel.surge_fare_inr.median())  # peak -> surge fare
    # express maps to private ordinary; missing comparator stays NaN
    assert (pc[pc.bus_class == "express"].private_bus_type == "ordinary").all()
    no_comp = d["competitors"][~((d["competitors"].route_pair == "Rajkot-Somnath") & (d["competitors"].bus_type == "AC_seater"))]
    e2 = fa.private_comparison(pc[pc.route_id == "IC02"].iloc[:, :-7] if False else pc[pc.route_id == "IC02"][[c for c in pc.columns if not c.startswith("private_") and c not in ("fare_index_vs_private", "fare_gap_vs_private_inr")]], no_comp)
    assert e2.private_comparator_inr.isna().all() and e2.fare_index_vs_private.isna().all()
    assert e2.private_note.str.contains("missing").all()


def test_differential_zero_change_equals_baseline(pc):
    s = fa.differential_fares(pc, peak_change_pct=0.0, normal_change_pct=0.0)
    ok = s.dropna(subset=["revenue_per_day_inr"])
    assert np.allclose(ok.revenue_per_day_inr, ok.baseline_revenue_per_day_inr, rtol=1e-9)
    assert np.allclose(ok.passengers_per_day, ok.baseline_passengers_per_day, rtol=1e-9)
    assert np.allclose(ok.load_factor, ok.baseline_load_factor, rtol=1e-9)
    assert np.allclose(ok.contribution_per_day_inr, ok.baseline_contribution_per_day_inr, rtol=1e-9)
    assert np.allclose(ok.full_cost_margin_per_day_inr, ok.baseline_full_cost_margin_per_day_inr, rtol=1e-9)
    tot = fa.differential_totals(s, by=None)
    assert tot.revenue_change_per_day_inr.abs().iloc[0] < 1e-6


def test_differential_fares_directions_and_cap(pc):
    s = fa.differential_fares(pc, peak_change_pct=10.0, normal_change_pct=-10.0)
    ok = s.dropna(subset=["revenue_per_day_inr"])
    pk, nm = ok[ok.band == "peak"], ok[ok.band == "normal"]
    assert (pk.passengers_per_day <= pk.baseline_passengers_per_day + 1e-9).all()   # price up -> demand down
    assert (nm.passengers_per_day >= nm.baseline_passengers_per_day - 1e-9).all() or (nm.load_factor <= 1 + 1e-9).all()
    assert (ok.passengers_per_day <= ok.capacity_passengers_per_day + 1e-9).all()    # seat cap respected
    # private cap: a huge increase is limited to ratio x comparator (never above), never cuts
    cap = fa.differential_fares(pc, peak_change_pct=100.0, normal_change_pct=100.0, private_cap_ratio=1.0)
    has = cap.merge(pc[["route_id", "day_type", "band", "private_comparator_inr", "state_fare_full_length_inr"]],
                    on=["route_id", "day_type", "band"])
    has = has[has.private_comparator_inr.notna()]
    new_full = has.state_fare_full_length_inr * (1 + has.fare_change_pct_applied / 100)
    assert (new_full <= np.maximum(has.state_fare_full_length_inr, has.private_comparator_inr) + 1e-6).all()
    assert has.capped.any() and (has.fare_change_pct_applied >= 0).all()
    with pytest.raises(ValueError):
        fa.differential_fares(pc, peak_elasticity=0.5)


def _row(pc, **kw):
    r = pc.iloc[[0]].copy()
    for k, v in kw.items():
        r[k] = v
    return r


def test_recommended_band_rule_and_not_viable_flag(pc):
    base = dict(state_fare_full_length_inr=250.0, be_adult_fare_target_full_inr=300.0, private_n_services=3)
    # viable: floor = max(current, BE) = 300 <= cap = 0.85 x 400 = 340
    r = fa.recommend_fare_band(_row(pc, **base, private_comparator_inr=400.0)).iloc[0]
    assert r.status == "viable" and r.viable
    assert r.floor_inr == 300.0 and r.band_low_inr == 300.0 and r.band_high_inr == pytest.approx(0.85 * 400.0)
    # not viable: BE 300 > cap 0.85 x 300 = 255 -> no band invented
    r = fa.recommend_fare_band(_row(pc, **base, private_comparator_inr=300.0)).iloc[0]
    assert "not viable" in r.status and not r.viable
    assert math.isnan(r.band_low_inr) and math.isnan(r.band_high_inr)
    # missing comparator: floor only, shown as missing
    r = fa.recommend_fare_band(_row(pc, **base, private_comparator_inr=np.nan)).iloc[0]
    assert r.status == "no private comparator - floor only" and math.isnan(r.band_high_inr) and r.band_low_inr == 300.0
    # current fare above cap but break-even below it
    r = fa.recommend_fare_band(_row(pc, state_fare_full_length_inr=400.0, be_adult_fare_target_full_inr=200.0,
                                    private_comparator_inr=400.0)).iloc[0]
    assert r.band_low_inr == 200.0 and r.band_high_inr == pytest.approx(340.0) and r.viable
    # floor never below the current fare
    r = fa.recommend_fare_band(_row(pc, state_fare_full_length_inr=250.0, be_adult_fare_target_full_inr=100.0,
                                    private_comparator_inr=400.0)).iloc[0]
    assert r.floor_inr == 250.0
    # whole table: every row carries evidence and assumptions
    full = fa.recommend_fare_band(pc)
    assert full.evidence.str.len().gt(0).all() and full.assumptions.str.len().gt(0).all()
    assert full.status.str.contains("not viable").any()


@pytest.mark.parametrize("corridor,route_id,band", [("Rajkot-Junagadh", "IC04", "peak"), ("Rajkot-Ahmedabad", "IC06", "normal"),
                                                    ("Rajkot-Jamnagar", "IC05", "normal")])
def test_whatif_incumbent_reproduces_baseline(d, econ, corridor, route_id, band):
    inc = d["model"].class_params and econ[(econ.route_id == route_id) & (econ.day_type == "weekday") & (econ.band == band)].iloc[0]
    w = fa.new_class_whatif(d["tm"], d["model"], corridor=corridor, day_type="weekday", band=band, bus_class=inc.bus_class,
                            trips_per_day=inc.trips_per_day).iloc[0]
    assert w.revenue_per_day_inr == pytest.approx(inc.revenue_inr / inc.n_days, rel=1e-9)
    assert w.served_passengers_per_day == pytest.approx(inc.passengers_per_day, rel=1e-9)
    assert w.load_factor == pytest.approx(inc.load_factor, rel=1e-9)
    assert w.trip_operating_cost_per_day_inr == pytest.approx(inc.trip_operating_cost_per_trip_inr * inc.trips_per_day, rel=1e-9)
    assert w.full_cost_per_day_inr == pytest.approx(inc.full_cost_per_trip_inr * inc.trips_per_day, rel=1e-9)
    assert w.contribution_per_day_inr == pytest.approx(w.baseline_contribution_per_day_inr, rel=1e-9)
    assert w.full_cost_margin_per_day_inr == pytest.approx(w.baseline_full_cost_margin_per_day_inr, rel=1e-9)
    assert w.fare_ratio_vs_incumbent == pytest.approx(1.0)
    assert "WHAT-IF" in w.label


def test_whatif_new_classes_and_elasticity(d):
    kw = dict(corridor="Rajkot-Junagadh", day_type="weekday", band="normal")
    rows = pd.concat([fa.new_class_whatif(d["tm"], d["model"], bus_class=c, **kw) for c in cm.ALL_CLASSES], ignore_index=True)
    assert len(rows) == 7 and (rows.trips_needed_per_day >= 1).all()
    assert (rows.load_factor <= 1 + 1e-9).all()
    assert rows.set_index("bus_class").loc["e_bus", "seats"] == 40
    # target-load trips: served demand fits within trips x seats x L x target
    assert (rows.load_factor <= config.SERVICE_TARGET_LOAD_FACTOR + 1e-9).all()
    # a fare rise with elasticity -> fewer passengers
    base = fa.new_class_whatif(d["tm"], d["model"], bus_class="volvo_ac", **kw).iloc[0]
    up = fa.new_class_whatif(d["tm"], d["model"], bus_class="volvo_ac", fare_change_pct=20.0, **kw).iloc[0]
    assert up.demand_passengers_per_day < base.demand_passengers_per_day
    with pytest.raises(ValueError):
        fa.new_class_whatif(d["tm"], d["model"], bus_class="nonexistent", **kw)
    with pytest.raises(ValueError):
        fa.new_class_whatif(d["tm"], d["model"], bus_class="e_bus", corridor="Rajkot-Junagadh", day_type="weekday", band="bogus")
