"""Operations Replay: pure snapshot functions, registry placement and a paused AppTest run."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.analytics import replay as R
from modules.analytics.reliability import reliability_pct
from modules.ui.pages_registry import PAGES

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-03"


def _toy():
    trips = pd.DataFrame({
        "trip_id": ["A", "B", "C"], "route_id": ["R1", "R1", "R2"], "service_date": [DATE] * 3,
        "departure_time": ["08:00", "09:00", "23:30"], "actual_departure_time": ["08:10", "08:59", "23:45"],
        "scheduled_minutes": [60.0, 30.0, 60.0], "departure_delay_min": [10.0, -1.0, 15.0], "direction": ["outbound"] * 3,
    })
    tickets = pd.DataFrame({
        "trip_id": ["A", "A", "B", "C"], "origin_stop_id": ["S1", "S2", "S1", "S1"], "passenger_count": [2, 1, 4, 3],
        "timestamp": pd.to_datetime([f"{DATE} 08:20", f"{DATE} 08:50", f"{DATE} 09:10", "2026-08-04 00:10"]),
    })
    return R.prepare_day(trips, tickets, DATE)


def test_buses_in_service_hand_checked():
    td, _ = _toy()
    # A runs 08:10-09:10, B 08:59-09:29, C 23:45-00:45 (+1 day)
    assert R.buses_in_service(td, 8 * 60) == 0
    assert R.buses_in_service(td, 8 * 60 + 30) == 1
    assert R.buses_in_service(td, 9 * 60) == 2          # A and B
    assert R.buses_in_service(td, 9 * 60 + 10) == 1     # A ended exactly (end exclusive), B running
    assert R.buses_in_service(td, 24 * 60 + 10) == 1    # C after midnight


def test_boardings_and_departures_hand_checked():
    td, tk = _toy()
    assert R.boardings_so_far(tk, 8 * 60 + 30) == 2
    assert R.boardings_last_hour(tk, 9 * 60 + 30) == 5  # 08:50 (1) and 09:10 (4); 08:20 is outside
    assert R.boardings_so_far(tk, 25 * 60) == 10        # after-midnight ticket stays on the service date
    d = R.departures_status(td, 9 * 60)                 # A (+10) and B (-1) departed
    assert (d["departed"], d["on_time"], d["late"], d["early"]) == (2, 1, 1, 0)
    assert d["on_time_pct"] == pytest.approx(50.0)


def test_on_time_uses_shared_definition():
    td, _ = _toy()
    d = R.departures_status(td, 26 * 60)
    assert d["on_time_pct"] == reliability_pct(td["departure_delay_min"])


def test_clock_labels_and_bounds():
    td, tk = _toy()
    assert R.clock_label(8 * 60 + 5) == "08:05" and R.clock_label(24 * 60 + 30) == "00:30 (+1 day)"
    lo, hi = R.clock_bounds(td, tk, 15)
    assert lo == 8 * 60 and hi % 15 == 0 and hi >= 24 * 60 + 45


@pytest.fixture(scope="module")
def real():
    S = config.LAYER_DIRS["synthetic"]
    if not (S / "tickets.parquet").is_file():
        pytest.skip("synthetic data not generated")
    trips = pd.read_parquet(S / "trips.parquet")
    tickets = pd.read_parquet(S / "tickets.parquet")
    return trips, tickets


def test_cumulative_monotonic_and_equals_day_total(real):
    trips, tickets = real
    td, tk = R.prepare_day(trips, tickets, DATE)
    lo, hi = R.clock_bounds(td, tk, 15)
    curve = R.cumulative_curve(tk, np.arange(lo, hi + 1, 15))
    assert (np.diff(curve["cumulative"]) >= 0).all()
    expected = tickets[tickets["trip_id"].isin(trips.loc[trips["service_date"].astype(str) == DATE, "trip_id"])]["passenger_count"].sum()
    assert curve["cumulative"].iloc[-1] == expected == R.boardings_so_far(tk, hi)


def test_bus_positions_lie_between_stops(real):
    S = config.LAYER_DIRS["synthetic"]
    trips, tickets = real
    td, _ = R.prepare_day(trips, tickets, DATE)
    stops, rs = pd.read_parquet(S / "stops.parquet"), pd.read_parquet(S / "route_stops.parquet")
    pos = R.bus_positions(td, rs, stops, 10 * 60)
    assert len(pos) == R.buses_in_service(td, 10 * 60) > 0
    assert pos["lat"].between(stops["lat"].min(), stops["lat"].max()).all()
    assert pos["progress"].between(0, 1).all()


def test_registry_second_and_file_exists():
    assert [p.key for p in PAGES][:2] == ["overview", "replay"]
    spec = PAGES[1]
    assert spec.title == "Operations Replay" and spec.milestone == "M8" and (ROOT / spec.file).is_file()


def test_page_paused_run_has_banner_and_four_kpis():
    if not (config.LAYER_DIRS["synthetic"] / "tickets.parquet").is_file():
        pytest.skip("synthetic data not generated")
    at = AppTest.from_file(str(ROOT / "pages/9_Operations_Replay.py"), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["rp_playing"] is False
    assert any("not live" in w.value for w in at.warning)
    assert len(at.metric) == 4
    html = " ".join(m.value for m in at.markdown)
    assert config.SIMULATION_BADGE_TEXT in html and "What this means" in html
    assert "Data and assumptions" in [e.label for e in at.expander]


def test_page_play_advances_then_stops_at_end():
    if not (config.LAYER_DIRS["synthetic"] / "tickets.parquet").is_file():
        pytest.skip("synthetic data not generated")
    at = AppTest.from_file(str(ROOT / "pages/9_Operations_Replay.py"), default_timeout=90).run()
    key = "rp_clock_2026-08-03_15"
    before = at.session_state[key]
    at.session_state["rp_playing"] = True
    at.run()  # one fragment/app run while playing advances one step (no timer thread in AppTest)
    assert at.session_state[key] > before
    S = config.LAYER_DIRS["synthetic"]
    td, tk = R.prepare_day(pd.read_parquet(S / "trips.parquet"), pd.read_parquet(S / "tickets.parquet"), DATE)
    last = R.clock_bounds(td, tk, 15)[1]
    at.session_state[key] = last - 15
    at.session_state["rp_last_tick"] = 0.0
    at.run()
    at.session_state["rp_last_tick"] = 0.0
    at.run()
    assert at.session_state["rp_playing"] is False and not at.exception
