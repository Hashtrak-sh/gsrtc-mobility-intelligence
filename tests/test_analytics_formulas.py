"""Formula and edge-case tests for the M2 analytics engine on tiny hand-built tables."""
import numpy as np
import pandas as pd
import pytest

import config
from modules.analytics import gaps, occupancy, od, reliability, route_kpis
from modules.analytics.common import contiguous_runs, hour_window, safe_div

D1 = pd.Timestamp("2026-08-03").date()
D2 = pd.Timestamp("2026-08-04").date()


# ----------------------------------------------------------------------------- mini network
def mini(extra_tickets=None, extra_trips=None):
    routes = pd.DataFrame([{"route_id": "R1", "name": "R1", "route_type": "local", "origin_stop_id": "A", "destination_stop_id": "C",
                            "length_km": 10.0, "bus_type": "ordinary", "minimum_service": False, "corridor": None}])
    rs = pd.DataFrame({"route_id": "R1", "stop_seq": [1, 2, 3], "stop_id": ["A", "B", "C"], "cum_km": [0.0, 4.0, 10.0], "cum_minutes": [0, 5, 12]})
    stops = pd.DataFrame({"stop_id": ["A", "B", "C"], "zone_id": ["Z1", "Z2", "Z3"]})
    trips = pd.DataFrame([
        {"trip_id": "T1", "route_id": "R1", "service_date": D1, "departure_time": "07:00", "day_type": "weekday", "seats": 10,
         "direction": "outbound", "operating_cost_inr": 520.0, "departure_delay_min": 2.0},
        {"trip_id": "T2", "route_id": "R1", "service_date": D1, "departure_time": "08:00", "day_type": "weekday", "seats": 10,
         "direction": "inbound", "operating_cost_inr": 520.0, "departure_delay_min": 7.0},
        {"trip_id": "T3", "route_id": "R1", "service_date": D2, "departure_time": "07:00", "day_type": "weekday", "seats": 10,
         "direction": "outbound", "operating_cost_inr": 520.0, "departure_delay_min": np.nan},
    ])
    if extra_trips is not None:
        trips = pd.concat([trips, extra_trips], ignore_index=True)
    rows = [("K1", "T1", "A", "C", 50.0, 5), ("K2", "T1", "B", "C", 30.0, 3), ("K3", "T2", "C", "A", 20.0, 2), ("K4", "T2", "C", "B", 10.0, 1)]
    if extra_tickets:
        rows += extra_tickets
    tickets = pd.DataFrame(rows, columns=["ticket_id", "trip_id", "origin_stop_id", "dest_stop_id", "fare_inr", "passenger_count"])
    tickets["timestamp"] = pd.Timestamp("2026-08-03 07:05")
    return routes, rs, stops, trips, tickets


def pipeline(extra_tickets=None, extra_trips=None):
    routes, rs, stops, trips, tickets = mini(extra_tickets, extra_trips)
    legs = occupancy.ticket_legs(trips, tickets, rs)
    prof = occupancy.trip_stop_profile(trips, legs, rs)
    ts = occupancy.trip_summary(trips, tickets, prof, routes)
    return routes, rs, stops, trips, tickets, legs, prof, ts


# ----------------------------------------------------------------------------- occupancy progression
def test_occupancy_progression_outbound_and_inbound():
    *_, prof, ts = pipeline()
    t1 = prof[prof["trip_id"] == "T1"].set_index("stop_id")
    assert t1["boardings"].tolist() == [5, 3, 0] and t1["alightings"].tolist() == [0, 0, 8]
    assert t1["onboard_after"].tolist() == [5, 8, 0]            # previous + boardings - alightings
    t2 = prof[prof["trip_id"] == "T2"].sort_values("position")
    assert t2["stop_id"].tolist() == ["C", "B", "A"]            # inbound = reversed order
    assert t2["onboard_after"].tolist() == [3, 2, 0]
    r = ts.set_index("trip_id")
    assert r.loc["T1", "peak_onboard"] == 8 and r.loc["T1", "peak_stop_id"] == "B"
    assert not r["negative_flag"].any() and not r["over_capacity_flag"].any() and not r["not_empty_at_end_flag"].any()


def test_load_factor_variants():
    routes, rs, stops, trips, tickets, legs, prof, ts = pipeline()
    t1 = ts.set_index("trip_id").loc["T1"]
    assert t1["peak_load_factor"] == pytest.approx(8 / 10)        # max link onboard / seats
    assert t1["boardings_per_seat"] == pytest.approx(8 / 10)      # passenger turnover (separately named)
    tm = route_kpis.trip_metrics(ts, legs)
    k = route_kpis.aggregate_kpis(tm, ["route_id"]).iloc[0]
    # pax-km: T1 5*10 + 3*6 = 68 ; T2 2*10 + 1*6 = 26 ; seat-km = 3 trips * 10 seats * 10 km = 300
    assert k["estimated_passenger_km"] == pytest.approx(94.0)
    assert k["seat_km"] == pytest.approx(300.0)
    assert k["load_factor_pct"] == pytest.approx(94.0 / 300.0 * 100)
    assert occupancy.load_factor_pct(94, 300) == pytest.approx(31.333, abs=1e-3)
    assert np.isnan(occupancy.load_factor_pct(10, 0)) and np.isnan(occupancy.load_factor_pct(np.nan, 10))


def test_turnover_can_exceed_peak_load_factor():
    # 6 pax A->B, they alight, then 6 pax B->C: boardings/seat = 1.2 but at most 6 onboard (peak LF 0.6)
    *_, ts = pipeline(extra_tickets=[("K5", "T3", "A", "B", 10.0, 6), ("K6", "T3", "B", "C", 10.0, 6)])
    r = ts.set_index("trip_id").loc["T3"]
    assert r["boardings_per_seat"] == pytest.approx(1.2) and r["peak_load_factor"] == pytest.approx(0.6)


def test_negative_and_over_capacity_are_flagged_not_clamped():
    # outbound ticket B->A (alights before boarding): onboard goes negative at stop A; 20 pax A->C exceeds the local cap 16
    _, _, _, _, _, legs, prof, ts = pipeline(extra_tickets=[("K7", "T3", "B", "A", 5.0, 2), ("K8", "T1", "A", "C", 1.0, 12)])
    r = ts.set_index("trip_id")
    assert r.loc["T3", "min_onboard"] == -2 and bool(r.loc["T3", "negative_flag"])
    lg = legs.set_index("ticket_id")
    assert not bool(lg.loc["K7", "leg_valid"]) and np.isnan(lg.loc["K7", "pax_km"])
    assert r.loc["T1", "peak_onboard"] == 20 and r.loc["T1", "onboard_cap"] == 16 and bool(r.loc["T1", "over_capacity_flag"])
    occ = occupancy.stop_occupancy(ts, prof)
    assert occ["negative_flag"].any() and occ["over_capacity_flag"].any()
    assert prof["onboard_after"].min() == -2                      # raw impossible value kept in the progression (no clamp)


def test_stop_occupancy_table_basic():
    *_, prof, ts = pipeline()
    occ = occupancy.stop_occupancy(ts, prof)
    row = occ[(occ["direction"] == "outbound") & (occ["hour"] == 7) & (occ["stop_id"] == "B")].iloc[0]
    assert row["n_trips"] == 2                                    # T1 and T3 depart in hour 7
    assert row["avg_onboard"] == pytest.approx(4.0)               # (8 + 0) / 2 trips
    assert row["onboard_pct"] == pytest.approx(40.0) and row["trips_per_day"] == pytest.approx(1.0)  # 2 trips / 2 dates


# ----------------------------------------------------------------------------- KPIs
def test_epkm_revenue_per_passenger_contribution():
    routes, rs, stops, trips, tickets, legs, prof, ts = pipeline()
    tm = route_kpis.trip_metrics(ts, legs)
    k = route_kpis.aggregate_kpis(tm, ["route_id"]).iloc[0]
    assert k["ticket_revenue_inr"] == pytest.approx(110.0) and k["vehicle_km"] == pytest.approx(30.0)
    assert k["epkm_inr"] == pytest.approx(110 / 30)
    assert k["boardings"] == 11 and k["revenue_per_passenger_inr"] == pytest.approx(10.0)
    assert k["contribution_inr"] == pytest.approx(110 - 1560)     # revenue - trip operating cost; not profit
    day = route_kpis.route_kpis(tm).set_index("service_date")
    d2 = day.loc[D2]
    assert d2["boardings"] == 0 and d2["ticket_revenue_inr"] == 0 and np.isnan(d2["revenue_per_passenger_inr"])  # zero passengers
    assert d2["epkm_inr"] == 0 and d2["load_factor_pct"] == 0


def test_zero_denominators_and_empty_tables_do_not_crash():
    empty_tm = route_kpis.aggregate_kpis(pd.DataFrame(), ["route_id"])
    assert empty_tm.empty and "epkm_inr" in empty_tm.columns
    assert np.isnan(safe_div(5, 0)) and np.isnan(safe_div(np.nan, 5)) and np.isnan(safe_div(None, 5))
    s = safe_div(pd.Series([1.0, 2.0]), pd.Series([0.0, 4.0]))
    assert np.isnan(s.iloc[0]) and s.iloc[1] == 0.5
    routes, rs, stops, trips, tickets = mini()
    et, ek = trips.iloc[0:0], tickets.iloc[0:0]
    legs = occupancy.ticket_legs(et, ek, rs)
    prof = occupancy.trip_stop_profile(et, legs, rs)
    ts = occupancy.trip_summary(et, ek, prof, routes)
    assert legs.empty and prof.empty and ts.empty
    assert occupancy.stop_occupancy(ts, prof).empty
    assert od.od_flows(legs, et, stops).empty
    assert gaps.hourly_demand_supply(ts, prof, routes, stops, pd.DataFrame()).empty


def test_trips_without_tickets_are_not_dropped():
    routes, rs, stops, trips, tickets = mini()
    legs = occupancy.ticket_legs(trips, tickets.iloc[0:0], rs)
    prof = occupancy.trip_stop_profile(trips, legs, rs)
    ts = occupancy.trip_summary(trips, tickets.iloc[0:0], prof, routes)
    assert len(ts) == 3 and (ts["boardings"] == 0).all() and (ts["peak_load_factor"] == 0).all()


# ----------------------------------------------------------------------------- reliability
@pytest.mark.parametrize("delay,expected", [(-1.0, True), (-1.01, False), (0.0, True), (5.0, True), (5.01, False), (30.0, False)])
def test_reliability_band_edges(delay, expected):
    assert bool(reliability.on_time_flag(pd.Series([delay])).iloc[0]) is expected


def test_reliability_pct_and_missing():
    d = pd.Series([-1.0, 5.0, 5.1, -2.0, np.nan])
    assert reliability.reliability_pct(d) == pytest.approx(50.0)          # NaN excluded from the denominator
    assert np.isnan(reliability.reliability_pct(pd.Series([np.nan, np.nan])))
    assert np.isnan(reliability.reliability_pct(pd.Series([], dtype=float)))
    assert reliability.mean_delay_min(d) == pytest.approx(1.775)
    assert config.RELIABILITY_ON_TIME_BAND_MIN == (-1.0, 5.0)


def test_route_reliability_excludes_missing_delay_trips():
    routes, rs, stops, trips, tickets, legs, prof, ts = pipeline()
    k = route_kpis.aggregate_kpis(route_kpis.trip_metrics(ts, legs), ["route_id"]).iloc[0]
    assert k["reliability_pct"] == pytest.approx(50.0)                    # T1 (2 min) on time, T2 (7 min) late, T3 unknown
    assert k["mean_delay_min"] == pytest.approx(4.5)


# ----------------------------------------------------------------------------- gaps
def test_gap_metrics_formulas():
    g = gaps.gap_metrics(pd.Series([12.0, 13.0, 5.0, 8.0, np.nan]), pd.Series([10.0, 10.0, 10.0, 0.0, 10.0]))
    assert g["gap_count"].iloc[:4].tolist() == [2.0, 3.0, 0.0, 8.0] and np.isnan(g["gap_count"].iloc[4])
    assert g["gap_index"].iloc[0] == pytest.approx(1.2) and g["gap_index"].iloc[1] == pytest.approx(1.3)
    assert np.isnan(g["gap_index"].iloc[3]) and not np.isinf(g["gap_index"]).any()      # zero seats -> no division
    assert g["crowding_flag"].tolist() == [False, True, False, False, False]            # strictly greater than 1.2
    assert gaps.gap_metrics(pd.Series([11.0]), pd.Series([10.0]), threshold=1.0)["crowding_flag"].iloc[0]


def test_no_service_hour_inside_span_is_null_with_status():
    extra = pd.DataFrame([{"trip_id": "T9", "route_id": "R1", "service_date": D1, "departure_time": "10:00", "day_type": "weekday",
                           "seats": 10, "direction": "outbound", "operating_cost_inr": 520.0, "departure_delay_min": 1.0}])
    routes, rs, stops, trips, tickets, legs, prof, ts = pipeline(extra_trips=extra)
    h = gaps.route_direction_rows(ts, prof, stops)
    out = h[(h["direction"] == "outbound") & (h["day_type"] == "weekday")].set_index("hour")
    assert set(out.index) == {7, 8, 9, 10}                      # span 07..10, hours 08/09 have no outbound departure
    for hr in (8, 9):
        assert out.loc[hr, "status"] == "no_scheduled_capacity" and out.loc[hr, "seats_offered"] == 0
        assert pd.isna(out.loc[hr, "demand_estimate"]) and pd.isna(out.loc[hr, "gap_index"]) and pd.isna(out.loc[hr, "gap_count"])
    assert out.loc[7, "status"] == "ok" and out.loc[7, "seats_offered"] == pytest.approx(10.0)   # T1+T3 -> 20 seats / 2 dates
    assert out.loc[7, "demand_estimate"] == pytest.approx(4.0)   # peak loads 8 and 0, over 2 dates
    assert h["service_date"].isna().all()


def test_corridor_rows_private_proxy_and_zero_state_capacity():
    routes, rs, stops, trips, tickets, legs, prof, ts = pipeline()
    routes = routes.assign(route_type="intercity", corridor="C-1", bus_type="express")
    comp = pd.DataFrame({"route_pair": "C-1", "day_type": "weekday", "departure_time": ["07:30", "09:15"], "seats": [40, 30]})
    h = gaps.corridor_rows(ts, prof, routes, stops, comp, private_occupancy=0.5).set_index("hour")
    assert h.loc[9, "status"] == "no_scheduled_capacity" and h.loc[9, "seats_offered"] == 0
    assert h.loc[9, "demand_estimate"] == pytest.approx(15.0) and h.loc[9, "private_demand_proxy"] == pytest.approx(15.0)
    assert pd.isna(h.loc[9, "gap_index"]) and h.loc[9, "gap_count"] == pytest.approx(15.0)
    assert h.loc[7, "demand_estimate"] == pytest.approx(h.loc[7, "state_demand"] + 20.0)   # 40 seats x 0.5
    assert pd.isna(h.loc[8, "demand_estimate"]) and h.loc[8, "status"] == "no_scheduled_capacity"  # nothing offered, nothing observable
    with pytest.raises(ValueError):
        gaps.corridor_rows(ts, prof, routes, stops, comp, private_occupancy=1.5)


# ----------------------------------------------------------------------------- misc helpers
def test_helpers():
    assert contiguous_runs([8, 7, 17, 18, 20]) == [(7, 8), (17, 18), (20, 20)]
    assert hour_window(7, 8) == "07:00-09:00" and hour_window(18, 21) == "18:00-22:00"


def test_od_flows_average_per_day_and_passenger_km():
    routes, rs, stops, trips, tickets, legs, prof, ts = pipeline()
    f = od.od_flows(legs, trips, stops)
    r = f[(f["origin_zone_id"] == "Z1") & (f["dest_zone_id"] == "Z3")].iloc[0]
    assert r["passengers_total"] == 5 and r["n_days"] == 2 and r["passenger_count"] == pytest.approx(2.5)
    assert r["estimated_passenger_km"] == pytest.approx(5 * 10 / 2) and r["hour"] == 7 and r["day_type"] == "weekday"
    top = od.top_od_pairs(f, "weekday", (7, 8), top=1)
    assert (top.iloc[0]["origin_zone_id"], top.iloc[0]["dest_zone_id"]) == ("Z1", "Z3")
