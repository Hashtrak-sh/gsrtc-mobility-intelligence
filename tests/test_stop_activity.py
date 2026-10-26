"""Stop-level activity (geographic demand heatmap): formula, reconciliation, filters, figure and page."""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.analytics import stop_activity as SA
from modules.routing import maps as M

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (config.PROCESSED_DIR / "stop_occupancy.parquet").is_file(),
                                reason="processed data not generated (python -m modules.analytics.run)")


@pytest.fixture(scope="module")
def tabs() -> dict[str, pd.DataFrame]:
    p = config.PROCESSED_DIR
    return {"so": pd.read_parquet(p / "stop_occupancy.parquet"), "rs": pd.read_parquet(p / "route_summary.parquet"),
            "stops": pd.read_parquet(config.SYNTHETIC_DIR / "stops.parquet")}


def test_formula_on_small_frame():
    so = pd.DataFrame({"route_id": ["A", "A", "B"], "day_type": ["weekday"] * 3, "hour": [7, 8, 7], "stop_id": ["S1", "S1", "S2"],
                       "avg_boardings": [10.0, 4.0, 3.0], "avg_alightings": [1.0, 2.0, 5.0], "trips_per_day": [2.0, 1.0, 4.0]})
    stops = pd.DataFrame({"stop_id": ["S1", "S2"], "name": ["One", "Two"], "lat": [22.3, 22.4], "lon": [70.8, 70.9],
                          "coord_source": ["openstreetmap", "openstreetmap_offset"]})
    a = SA.stop_activity(so, stops, day_type="weekday").set_index("stop_id")
    assert a.loc["S1", "boardings_per_day"] == 10 * 2 + 4 * 1 and a.loc["S1", "alightings_per_day"] == 1 * 2 + 2 * 1
    assert a.loc["S2", "net_per_day"] == 3 * 4 - 5 * 4
    assert SA.stop_activity(so, stops, day_type="weekday", hour_lo=8, hour_hi=24).set_index("stop_id").loc["S1", "boardings_per_day"] == 4
    assert SA.stop_activity(so, stops, day_type="weekday", route_ids=["B"])["stop_id"].tolist() == ["S2"]


@pytest.mark.parametrize("day", ["weekday", "weekend", "festival"])
def test_reconciles_with_route_summary(tabs, day):
    a = SA.stop_activity(tabs["so"], tabs["stops"], day_type=day)
    want = tabs["rs"][f"boardings_per_day_{day}"].sum()
    assert a["boardings_per_day"].sum() == pytest.approx(want, rel=1e-6)          # exact up to float rounding
    for corridor in config.INTERCITY_CORRIDORS:
        ids = tabs["rs"].loc[tabs["rs"]["corridor"] == corridor, "route_id"]
        c = SA.stop_activity(tabs["so"], tabs["stops"], day_type=day, route_ids=ids)
        assert c["boardings_per_day"].sum() == pytest.approx(tabs["rs"].loc[ids.index, f"boardings_per_day_{day}"].sum(), rel=1e-6)


def test_non_negative_and_filters(tabs):
    full = SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekday")
    assert (full[["boardings_per_day", "alightings_per_day"]] >= 0).all().all()
    assert (full["net_per_day"] == full["boardings_per_day"] - full["alightings_per_day"]).all()
    am = SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekday", hour_lo=7, hour_hi=10)
    rest = SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekday", hour_lo=0, hour_hi=7)
    pm = SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekday", hour_lo=10, hour_hi=24)
    assert 0 < am["boardings_per_day"].sum() < full["boardings_per_day"].sum()
    assert rest["boardings_per_day"].sum() + am["boardings_per_day"].sum() + pm["boardings_per_day"].sum() == pytest.approx(full["boardings_per_day"].sum())
    assert SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekend")["boardings_per_day"].sum() != full["boardings_per_day"].sum()


def test_city_split_and_takeaway(tabs):
    a = SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekday")
    m = SA.in_city(a)
    assert 0 < m.sum() < len(a)
    t = SA.takeaway(a)
    assert a.iloc[0]["name"] in t and "simulated" in t
    assert "No stop activity" in SA.takeaway(a.iloc[0:0])
    assert "imbalance" in SA.takeaway(a, "net")


@pytest.mark.parametrize("city", [True, False])
def test_figure_traces(tabs, city):
    a = SA.stop_activity(tabs["so"], tabs["stops"], day_type="weekday")
    a = a[SA.in_city(a)] if city else a
    for metric in SA.METRICS:
        fig = M.demand_heatmap(a, SA.metric_column(metric), label=metric, city=city)
        assert [type(x) for x in fig.data] == [go.Densitymap, go.Scattermap]
        assert fig.layout.map.style == "open-street-map"
    assert len(M.demand_heatmap(a.iloc[0:0], "boardings_per_day", label="x").data) == 0


def test_page_has_heatmap_section():
    at = AppTest.from_file(str(ROOT / "pages/4_Passenger_Flow_OD.py"), default_timeout=90)
    at.session_state["flt_corridor"] = "All"
    at.session_state["flt_day_type"] = "weekday"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Where demand concentrates: stop-level heatmap" in [s.value for s in at.subheader]
    assert any(r.label == "Metric" for r in at.radio) and any(r.label == "Map view" for r in at.radio)
    assert any("simulated" in c.value and "OpenStreetMap" in c.value for c in at.caption)
    assert any("most boardings" in m.value for m in at.markdown)
    next(r for r in at.radio if r.label == "Metric").set_value("net").run()
    assert not at.exception
    next(r for r in at.radio if r.label == "Map view").set_value("Whole network").run()
    assert not at.exception
    at.session_state["flt_corridor"] = "Rajkot-Somnath"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "no map is shown" not in " ".join(m.value for m in at.markdown).lower()
