"""M5 page tests (AppTest) for Demand & Surveys, Passenger Flow & O-D and Competition & Pricing, plus the end-to-end
analytics command (deterministic, including the model outputs)."""
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.data import io
from modules.survey import mode_choice as MC
from modules.survey import themes as TH
from modules.ui import fmt

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (config.PROCESSED_DIR / "competition_analysis.parquet").is_file(),
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


def proc(name: str) -> pd.DataFrame:
    return pd.read_parquet(config.PROCESSED_DIR / f"{name}.parquet")


# ------------------------------------------------------------------------------------------ page 5
def test_competition_page_kpis_come_from_tables():
    at = run("pages/5_Competition_and_Pricing.py", flt_corridor="Rajkot-Somnath", flt_day_type="weekday")
    assert not at.exception, [e.value for e in at.exception]
    assert config.SIMULATION_BADGE_TEXT in md(at) and "What this means" in md(at) and "Data and assumptions" in [e.label for e in at.expander]
    c = proc("competition_analysis")
    c = c[(c["route_pair"] == "Rajkot-Somnath") & (c["day_type"] == "weekday")]
    m = metrics(at)
    assert len(at.metric) == 4
    assert m["Highest competitive gap score"] == f"{c['competitive_gap_score'].max():.0f} / 100"
    assert m["Private departures per day"] == fmt.number(c["private_departures"].sum())
    assert m["Hours with private but no state departure"] == "5"
    assert [t.label for t in at.tabs] == ["Departure slots and gap score", "Fares and fare index", "Review themes", "Fare what-if"]
    text = md(at)
    assert "demo-comp-v1" in text or "Weights (demo-comp-v1" in " ".join(c.value for c in at.caption)
    assert any("mirror" in x.value for x in at.caption)                      # Rajkot-only / mirrored competitor timetable is stated
    assert "Fare index by hour: normal vs illustrative surge" in text


def test_competition_page_theme_methods_and_provenance():
    at = run("pages/5_Competition_and_Pricing.py", flt_corridor="Rajkot-Somnath")
    radio = next(r for r in at.radio if r.label == "Theme method")
    assert set(radio.options) == set(TH.METHOD_LABELS.values())
    cap = " ".join(c.value for c in at.caption)
    assert "tagged when the synthetic reviews were generated" in cap.lower()
    radio.set_value(TH.METHOD_KEYWORD).run()
    assert not at.exception
    assert "deterministic keyword tagger applied to the review text" in " ".join(c.value for c in at.caption).lower()
    assert "How reliable is the keyword tagger?" in [e.label for e in at.expander]
    assert "LLM" not in md(at)                       # LLM theme analysis is a later milestone and is not advertised


def test_competition_page_other_corridors_and_surge_view():
    for corridor in config.INTERCITY_CORRIDORS:
        at = run("pages/5_Competition_and_Pricing.py", flt_corridor=corridor, flt_day_type="festival")
        assert not at.exception, (corridor, [e.value for e in at.exception])
        assert not [m for m in at.metric if "nan" in m.value.lower()]


def test_pricing_what_if_is_bounded_and_complete():
    at = run("pages/5_Competition_and_Pricing.py", flt_corridor="Rajkot-Somnath")
    fare = next(s for s in at.slider if s.label.startswith("New fare"))
    el = next(s for s in at.slider if s.label.startswith("Assumed price elasticity"))
    base = float(proc("route_kpis").pipe(lambda k: k[(k["route_id"] == "IC02") & (k["day_type"] == "weekday")]["ticket_revenue_inr"].sum()))
    assert fare.min < fare.value < fare.max and el.min == config.PRICING_ELASTICITY_RANGE[0] and el.max == config.PRICING_ELASTICITY_RANGE[1]
    assert base > 0
    fare.set_value(fare.min).run()
    assert not at.exception and not at.error
    out = next(d.value for d in at.dataframe if "Outcome" in d.value.columns)
    assert {"Operating cost per day (included, fixed)", "Contribution per day (not profit)", "Occupancy (served / seats)",
            "Passengers per day (full-journey equivalents)"} <= set(out["Outcome"])
    assert any("Included cost" in c.value for c in at.caption)
    sens = next(d.value for d in at.dataframe if "Elasticity" in d.value.columns)
    assert len(sens) == len(config.PRICING_ELASTICITY_SENSITIVITY)
    # a lower fare at the same elasticity cannot lower demand
    el.set_value(-1.0).run()
    assert not at.exception


# ------------------------------------------------------------------------------------------ page 1
def test_survey_page_separates_descriptive_findings_from_model():
    at = run("pages/1_Demand_and_Surveys.py")
    assert not at.exception, [e.value for e in at.exception]
    text = md(at)
    assert config.SIMULATION_BADGE_TEXT in text and "What this means" in text
    heads = [s.value for s in at.subheader]
    assert heads.index("Survey evidence: what respondents said (descriptive)") < heads.index("Switching probability: illustrative model")
    warn = " ".join(w.value for w in at.warning)
    assert "Model-based" in warn and "not a forecast of real behaviour" in warn and "illustrative" in warn.lower()
    assert len(at.metric) == 4 and metrics(at)["Survey responses"] == "800"
    notes = " ".join(c.value for c in at.caption)
    assert "Illustrative, conditional on the synthetic training setup. Not a forecast of real behaviour" in notes
    m = proc("survey_model_metrics").set_index("metric")
    perf = next(d.value for d in at.dataframe if "Naive baseline" in d.value.columns)
    assert perf.loc[perf["Metric"] == "ROC-AUC", "Model"].iloc[0] == f"{m.loc['roc_auc', 'model']:.3f}"
    assert set(perf["Beats baseline"]) == {"yes"}
    assert [t.label for t in at.tabs][:3] == ["Trip purpose and mode", "Why people use a private vehicle", "What would make them switch"]
    assert "By mode, purpose and income" in [t.label for t in at.tabs]


def test_survey_scenario_widget_matches_model_and_responds():
    at = run("pages/1_Demand_and_Surveys.py")
    coef = proc("survey_model_coefficients")
    scn = next(d.value for d in at.dataframe if "Model switching probability" in d.value.columns)
    want = MC.scenario_table(coef, mode="car", purpose="work", income_band="middle", met=["reliability", "ac_comfort"])
    assert list(scn["Model switching probability"]) == [fmt.pct(p * 100, 0) for p in want["model_probability"]]
    assert list(scn["True generator probability"]) == [fmt.pct(p * 100, 0) for p in want["true_generator_probability"]]
    ms = next(w for w in at.multiselect if w.label == "Conditions met")
    ms.set_value([]).run()
    assert not at.exception
    scn2 = next(d.value for d in at.dataframe if "Model switching probability" in d.value.columns)
    assert scn2["Model switching probability"].iloc[0] == scn2["Model switching probability"].iloc[1]     # nothing met -> no uplift
    ms.set_value(["reliability", "ac_comfort", "frequency"]).run()
    scn3 = next(d.value for d in at.dataframe if "Model switching probability" in d.value.columns)
    p3 = float(scn3["Model switching probability"].iloc[1].rstrip("%"))
    assert p3 > float(scn3["Model switching probability"].iloc[0].rstrip("%"))


def test_survey_crosstab_tab_controls():
    at = run("pages/1_Demand_and_Surveys.py")
    what = next(r for r in at.radio if r.label == "Show")
    by = next(r for r in at.radio if r.label == "Split by")
    by.set_value("income_band").run()
    assert not at.exception
    what.set_value("Trip purpose by current mode").run()
    assert not at.exception and next(r for r in at.radio if r.label == "Split by").disabled
    what.set_value("Reasons for using a private vehicle").run()
    assert not at.exception


def test_survey_page_without_model_tables_or_sklearn(monkeypatch, tmp_path):
    for layer in ("raw", "synthetic", "processed"):
        shutil.copytree(config.LAYER_DIRS[layer], tmp_path / layer, ignore=shutil.ignore_patterns("survey_model_*"))
    monkeypatch.setattr(config, "LAYER_DIRS", {k: tmp_path / k for k in ("raw", "synthetic", "processed")})
    monkeypatch.setitem(sys.modules, "sklearn.linear_model", None)          # simulate scikit-learn not being installed
    at = run("pages/1_Demand_and_Surveys.py")
    assert not at.exception, [e.value for e in at.exception]
    text = md(at)
    assert "Switch-intent model not available" in text and "needs scikit-learn" in text
    assert any("python -m modules.survey.mode_choice" in c.value for c in at.code)
    assert "Survey evidence: what respondents said (descriptive)" in [s.value for s in at.subheader]      # descriptive part still renders
    assert len(at.metric) == 4


# ------------------------------------------------------------------------------------------ page 4
def test_flow_page_corridor_total_equals_route_boardings():
    rs = proc("route_summary")
    for corridor in ("Rajkot-Somnath", "Rajkot-Junagadh", "Rajkot-Jamnagar", "Rajkot-Ahmedabad"):
        at = run("pages/4_Passenger_Flow_OD.py", flt_corridor=corridor, flt_day_type="weekday", flt_hours=(0, 24))
        assert not at.exception, [e.value for e in at.exception]
        want = rs.loc[rs["corridor"] == corridor, "boardings_per_day_weekday"].sum()
        assert metrics(at)["Boardings per average weekday"] == fmt.number(want), corridor
    assert not any("can exceed" in c.value for c in at.caption)               # the old double-counting caveat is gone


# ------------------------------------------------------------------------------------------ end to end
def test_analytics_run_twice_is_deterministic_including_model(tables, tmp_path):
    pytest.importorskip("sklearn")
    from modules.analytics import run as RUN

    for name, df in tables.items():
        io.write_table(df, name, "synthetic", base_dir=tmp_path)
    assert RUN.main(["--base-dir", str(tmp_path)]) == 0
    first = {n: io.read_table(n, "processed", tmp_path) for n in (*RUN.OUTPUT_TABLES, MC.TABLE_COEF, MC.TABLE_METRICS)}
    assert RUN.main(["--base-dir", str(tmp_path)]) == 0
    for n, df in first.items():
        pd.testing.assert_frame_equal(df, io.read_table(n, "processed", tmp_path), obj=n)
    assert len(first["competition_analysis"]) > 100 and "route_id" in first["od_flows"].columns
    assert (tmp_path / "processed" / "competition_analysis.provenance.json").is_file()
    assert io.read_provenance(MC.TABLE_METRICS, "processed", tmp_path).source_type.value == "model_output"
