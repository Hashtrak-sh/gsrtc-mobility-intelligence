"""M3 page tests: every page on real generated data, empty states, filters and cross-page consistency (AppTest)."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.analytics import queries as Q
from modules.ui import fmt
from modules.ui.pages_registry import PAGES

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (config.PROCESSED_DIR / "route_summary.parquet").is_file(),
                                reason="processed data not generated (python -m modules.analytics.run)")


def run(page_file: str, **state) -> AppTest:
    at = AppTest.from_file(str(ROOT / page_file), default_timeout=90)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def md(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def rsum() -> pd.DataFrame:
    return pd.read_parquet(config.PROCESSED_DIR / "route_summary.parquet")


@pytest.mark.parametrize("spec", PAGES, ids=lambda s: s.key)
def test_page_real_data_contract(spec):
    at = run(spec.file)
    assert not at.exception, [e.value for e in at.exception]
    text = md(at)
    assert config.SIMULATION_BADGE_TEXT in text and "What this means" in text
    assert "Data and assumptions" in [e.label for e in at.expander]
    assert "Data not yet generated" not in text
    assert len(at.metric) <= 4
    # numbers shown as values (metrics and table cells) must never be NaN/None placeholders
    cells = [m.value for m in at.metric] + [str(v) for d in at.dataframe for v in d.value.astype(object).to_numpy().ravel()]
    assert not [c for c in cells if c.strip().lower() in ("nan", "none", "inf", "-inf", "₹nan", "nan%")]
    assert all("nan" not in m.value.lower() for m in at.metric)
    if spec.key not in ("infrastructure",):
        assert any("Active filters" in c.value for c in at.caption)


@pytest.mark.parametrize("spec", PAGES, ids=lambda s: s.key)
def test_page_empty_state_with_no_data(spec, monkeypatch, tmp_path):
    empty = {"raw": tmp_path / "raw", "synthetic": tmp_path / "synthetic", "processed": tmp_path / "processed"}
    monkeypatch.setattr(config, "LAYER_DIRS", empty)
    at = run(spec.file)
    assert not at.exception, [e.value for e in at.exception]
    assert "Data not yet generated" in md(at)
    assert any(spec.command in c.value for c in at.code)
    assert config.SIMULATION_BADGE_TEXT in md(at)
    assert not at.metric  # no numbers are invented


def test_overview_kpis_match_route_summary():
    at = run("pages/0_Overview.py", flt_corridor="Rajkot-Ahmedabad")
    rs = rsum()
    row = rs[rs["route_id"] == "IC06"].iloc[0]
    m = metrics(at)
    assert m["Average boardings per day"] == fmt.number(row["avg_boardings_per_day"])
    assert m["Load factor"] == fmt.pct(row["load_factor_pct"])
    assert m["On-time departures"] == fmt.pct(row["reliability_pct"])
    assert m["Contribution per day (not profit)"] == fmt.inr(row["contribution_per_day_inr"])


def test_overview_has_findings_actions_provenance_and_health():
    at = run("pages/0_Overview.py")
    text = md(at)
    assert text.count('class="gsrtc-card-title"') == 3
    assert "Rajkot-Somnath" in text and "no seats" in text  # the evening gap finding is computed from the corridor rows
    assert "See evidence" in [e.label for e in at.expander]
    assert any("System health" in e.label for e in at.expander)
    assert "Real geography vs simulated mobility" in text
    recs = pd.read_parquet(config.PROCESSED_DIR / "recommendations.parquet")
    top = recs.sort_values("priority_rank").iloc[0]
    assert top["title"] in text and top["time_window"] in text


def test_route_intelligence_kpis_equal_route_summary_for_each_selected_route():
    rs = rsum()
    for rid in ("L05", "L09", "IC02"):
        at = run("pages/2_Route_Intelligence.py", sel_route=rid)
        assert not at.exception
        row = rs[rs["route_id"] == rid].iloc[0]
        m = metrics(at)
        assert m["Load factor"] == fmt.pct(row["load_factor_pct"])
        assert m["Earnings per vehicle-km (EPKM)"] == fmt.inr(row["epkm_inr"], 1) + " / km"
        assert m["On-time departures"] == fmt.pct(row["reliability_pct"])
        assert m["Revenue per passenger"] == fmt.inr(row["revenue_per_passenger_inr"], 1)
        assert at.session_state["sel_route"] == rid


def test_minimum_service_protection_is_visible():
    at = run("pages/2_Route_Intelligence.py", sel_route="L09")
    assert any("minimum-service" in i.value for i in at.info)
    table = at.dataframe[0].value
    assert "Minimum service (protected)" in set(table["Protection"])
    assert {"Demand potential (25%)", "Unmet demand (20%)"} <= set(table.columns)  # components and weights exposed


def test_cross_page_boardings_per_day_consistency():
    rs = rsum()
    row = rs[rs["route_id"] == "IC06"].iloc[0]
    want = fmt.number(row["avg_boardings_per_day"])
    over = run("pages/0_Overview.py", flt_corridor="Rajkot-Ahmedabad")
    ri = run("pages/2_Route_Intelligence.py", sel_route="IC06", flt_corridor="Rajkot-Ahmedabad")
    assert metrics(over)["Average boardings per day"] == want
    assert f"Average boardings per day: {want}" in " ".join(c.value for c in ri.caption)
    # the Reports page total for the same scope equals route_summary boardings
    rep = run("pages/8_Reports.py", flt_corridor="Rajkot-Ahmedabad")
    assert metrics(rep)["Passengers in scope (42 days)"] == fmt.number(row["boardings"])


def test_gaps_page_recommendation_windows_match_table():
    at = run("pages/3_Demand_Supply_Gaps.py")
    assert not at.exception
    recs = pd.read_parquet(config.PROCESSED_DIR / "recommendations.parquet")
    svc = recs[recs["category"].isin(["add_service_peak", "add_service_corridor_slot", "add_capacity_weekend"])]
    shown = next(d.value for d in at.dataframe if "Time window" in d.value.columns)
    assert sorted(shown["Time window"]) == sorted(svc["time_window"])
    assert sorted(shown["ID"]) == sorted(svc["recommendation_id"])
    crowded = next(d.value for d in at.dataframe if "Demand / seats" in d.value.columns and "Fullest stop" in d.value.columns)
    assert set(crowded["Recommendation"]) <= set(svc["recommendation_id"]) | {""}
    m = metrics(at)
    assert m["Crowded route-hours"] == "4" and m["Highest demand / seats"] == "1.58x"
    # the scenario defaults to the highest-priority recommended gap and shows its recommendation
    assert any(s.value.startswith("Matching recommendation REC-001") for s in at.success)


def test_gaps_scenario_edit_and_invalid_input():
    at = run("pages/3_Demand_Supply_Gaps.py")
    ni = [n for n in at.number_input if n.label.startswith("Projected passengers")][0]
    ni.set_value(400.0).run()
    assert not at.exception
    out = next(d.value for d in at.dataframe if "Result" in d.value.columns)
    added = out.loc[out["Result"] == "Additional departures needed", "Value"].iloc[0]
    assert int(added.split()[0]) >= 10  # 400 passengers need many more departures than the default scenario
    tl = [n for n in at.number_input if n.label == "Seats per bus"][0]
    assert tl.value > 0


def test_flow_page_zone_names_not_ids():
    at = run("pages/4_Passenger_Flow_OD.py")
    assert not at.exception
    text = md(at)
    assert "Kotharia" in text and "Z05" not in text.split("What this means")[1][:600]


def test_competition_page_shows_evening_gap_and_pricing_defaults():
    at = run("pages/5_Competition_and_Pricing.py", flt_corridor="Rajkot-Somnath")
    assert not at.exception
    m = metrics(at)
    assert m["Hours with private but no state departure"] == "5"
    text = md(at)
    assert "18:00-22:00" in text.replace("–", "-")
    fare = [s for s in at.slider if s.label.startswith("New fare")][0]
    el = [s for s in at.slider if s.label.startswith("Assumed price elasticity")][0]
    assert el.value == pytest.approx(config.PRICING_ELASTICITY_DEFAULT)
    assert fare.min < fare.value < fare.max
    fare.set_value(fare.max).run()
    assert not at.exception and not at.error
    out = next(d.value for d in at.dataframe if "Outcome" in d.value.columns)
    assert "Ticket revenue per day" in set(out["Outcome"])
    assert len(next(d.value for d in at.dataframe if "Elasticity" in d.value.columns)) == len(config.PRICING_ELASTICITY_SENSITIVITY)


def test_competition_defaults_to_primary_corridor_for_local_scope():
    at = run("pages/5_Competition_and_Pricing.py", flt_corridor="Rajkot local network")
    assert not at.exception and any(config.PRIMARY_CORRIDOR in i.value for i in at.info)


def test_cctv_page_is_honest_about_detector():
    at = run("pages/7_CCTV_Analytics.py")
    assert not at.exception
    assert any("SYNTHETIC" in w.value for w in at.warning)
    assert any("Detector unavailable" in e.value or "no real counts" in e.value for e in [*at.error, *at.info])
    schema = next(d.value for d in at.dataframe if "Column" in d.value.columns)
    assert "count" in set(schema["Column"])
    assert "live" not in md(at).lower().replace("nothing on this page is live", "")


def test_reports_page_provenance_and_no_pdf():
    at = run("pages/8_Reports.py")
    assert not at.exception
    assert "pdf" not in (md(at) + " ".join(c.value for c in at.caption)).lower()
    assert len(at.get("download_button")) >= 8  # 7 CSVs + provenance JSON


def test_filters_persist_and_apply_via_sidebar():
    at = run("pages/3_Demand_Supply_Gaps.py")
    at.sidebar.selectbox(key="w_corridor").select("Rajkot-Somnath").run()
    assert at.session_state["flt_corridor"] == "Rajkot-Somnath"
    assert any("Rajkot-Somnath" in c.value for c in at.caption if "Active filters" in c.value)
    at.sidebar.selectbox(key="w_day_type").select("weekend").run()
    assert at.session_state["flt_day_type"] == "weekend" and at.session_state["flt_corridor"] == "Rajkot-Somnath"
    at.sidebar.slider(key="w_hours").set_range(7, 10).run()
    assert at.session_state["flt_hours"] == (7, 10)
    assert any("07:00" in c.value and "weekend" in c.value for c in at.caption if "Active filters" in c.value)
    assert not at.exception


@pytest.mark.parametrize("corridor", ["All", "Rajkot local network", "Rajkot-Somnath", "Rajkot-Junagadh", "Rajkot-Jamnagar", "Rajkot-Ahmedabad"])
@pytest.mark.parametrize("day", ["weekday", "festival"])
def test_all_pages_survive_every_filter_combination(corridor, day):
    for spec in PAGES:
        at = run(spec.file, flt_corridor=corridor, flt_day_type=day, flt_hours=(6, 11))
        assert not at.exception, (spec.key, corridor, day, [e.value for e in at.exception])


def test_corridor_route_ids_consistent_with_queries():
    rs = rsum()
    sel = rs[rs["corridor"] == "Rajkot-Somnath"]
    k = Q.scope_kpis(sel)
    at = run("pages/0_Overview.py", flt_corridor="Rajkot-Somnath")
    assert metrics(at)["Average boardings per day"] == fmt.number(k["avg_boardings_per_day"])
