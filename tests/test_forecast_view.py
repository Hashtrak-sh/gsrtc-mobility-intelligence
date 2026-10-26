"""Next-7-days baseline view: helpers, chart, and the Route Intelligence page."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.analytics import forecast_view as FV
from modules.ui import charts

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (config.PROCESSED_DIR / "baseline_forecast.parquet").is_file(),
                                reason="baseline_forecast not generated (python -m modules.analytics.run)")
RID = "IC01"


def _data():
    fc = pd.read_parquet(config.PROCESSED_DIR / "baseline_forecast.parquet")
    k = pd.read_parquet(config.PROCESSED_DIR / "route_kpis.parquet")
    return fc, k


def _route():
    fc, k = _data()
    return FV.forecast_rows(fc, RID), FV.history_tail(k[k["route_id"] == RID], 21)


def test_dates_follow_history_and_band_order():
    fcr, hist = _route()
    assert len(fcr) == 7 and len(hist) == 21
    assert FV.dates_follow_history(fcr, hist)
    assert ((fcr["lower_bound"] <= fcr["forecast_boardings"]) & (fcr["forecast_boardings"] <= fcr["upper_bound"])).all()
    assert not FV.dates_follow_history(fcr.iloc[1:], hist)


def test_summary_matches_table():
    fcr, hist = _route()
    s = FV.summarize(fcr, hist)
    assert s["total"] == pytest.approx(fcr["forecast_boardings"].sum())
    assert s["peak_value"] == pytest.approx(fcr["forecast_boardings"].max())
    assert s["prev_week_total"] == pytest.approx(hist.tail(7)["boardings"].sum())
    tbl = FV.forecast_table(fcr)
    assert len(tbl) == 7 and list(tbl["Weekday"])[0] == fcr["service_date"].iloc[0].strftime("%A")
    txt = FV.takeaway(RID, s)
    assert f"{s['total']:,.0f}" in txt and s["peak_weekday"] in txt and "not a prediction" in txt


def test_chart_traces():
    fcr, hist = _route()
    fig = charts.forecast_next_days(hist, fcr)
    names = [t.name for t in fig.data]
    assert "Observed (synthetic)" in names and "Baseline estimate" in names and "Approx. 80 % band" in names
    assert any(a.text == "Forecast starts" for a in fig.layout.annotations)
    assert len(fig.layout.shapes) == 1


def test_page_shows_next_7_days():
    at = AppTest.from_file(str(ROOT / "pages" / "2_Route_Intelligence.py"), default_timeout=90)
    at.session_state["sel_route"] = RID
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " " + " ".join(m.value for m in at.warning) + " " + " ".join(m.value for m in at.info)
    assert "Next 7 days (baseline estimate)" in text
    assert "Baseline estimate (seasonal average)" in text
    assert "not a prediction of real GSRTC ridership" in text
