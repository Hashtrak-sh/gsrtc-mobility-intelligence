"""Cost-Benefit & Fares page: AppTest runs (default, parameter change, corridor/day-type switch, what-if classes) and the PDF section."""
import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.data import io as dio

pytestmark = pytest.mark.skipif(
    not (dio.table_exists("route_summary", "processed") and dio.table_exists("trips", "synthetic")),
    reason="data not generated (python -m modules.data_gen.generate; python -m modules.analytics.run)")

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "pages" / "10_Cost_Benefit_and_Fares.py")
HEADINGS = ["Headline", "What a bus-km costs, by class", "Peak vs normal hours", "Break-even and recommended fares",
            "Peak / off-peak fare scenario", "What if this corridor ran a different bus?", "Social cost-benefit (illustrative appraisal)"]
BAD = ("nan", "none", "inf", "-inf", "₹nan", "nan%")


def run(**state) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=120)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def kpis(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def cells(at: AppTest) -> list[str]:
    return [m.value for m in at.metric] + [str(v) for d in at.dataframe for v in d.value.astype(object).to_numpy().ravel()]


def assert_clean(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.metric) <= 4
    assert not [c for c in cells(at) if c.strip().lower() in BAD]
    assert not any("nan" in c.lower().split() for c in cells(at))


def test_default_page_clean_and_complete():
    at = run()
    assert_clean(at)
    assert [h.value for h in at.header] == HEADINGS
    assert len(at.metric) == 4
    text = " ".join(m.value for m in at.markdown)
    assert config.SIMULATION_BADGE_TEXT in text and "What this means" in text
    assert "Data and assumptions" in [e.label for e in at.expander]
    assert {"Cost assumptions (illustrative, editable)", "Appraisal assumptions (illustrative, editable)"} <= {e.label for e in at.expander}
    assert any("Active filters" in c.value for c in at.caption)
    assert any("Peak departure hours" in m.value for m in at.markdown)


def test_diesel_price_changes_full_cost_kpi():
    base = kpis(run())["Full cost per bus-km"]
    at = run()
    at.number_input(key="cb_c_diesel").set_value(120.0).run()
    assert_clean(at)
    assert kpis(at)["Full cost per bus-km"] != base


def test_trip_cost_layer_matches_base_rate_at_defaults():
    from modules.analytics import cost_model as cm
    from modules.data_gen import constants as C
    from modules.analytics import fare_analysis as FA

    inp = FA.load_inputs()
    for cls in cm.EXISTING_CLASSES:
        assert cm.trip_operating_cost_per_km(inp["model"], cls) == pytest.approx(C.OPERATING_COST_PER_KM_INR[cls])


def test_corridor_and_day_type_switch():
    at = run(flt_corridor="Rajkot-Ahmedabad", flt_day_type="weekend")
    assert_clean(at)
    assert any("Rajkot-Ahmedabad" in m.value for m in at.markdown)


def test_non_intercity_filter_falls_back_to_primary():
    at = run(flt_corridor="All")
    assert_clean(at)
    assert any(config.PRIMARY_CORRIDOR in i.value for i in at.info)


@pytest.mark.parametrize("cls", ["volvo_ac", "e_bus", "non_ac_sleeper"])
def test_whatif_classes_run_clean(cls):
    at = run()
    at.selectbox(key="cb_w_class").set_value(cls).run()
    assert_clean(at)
    assert any("WHAT-IF" in str(d.value.columns[-1]) for d in at.dataframe)


def test_class_override_and_no_peak_scenario_inputs():
    at = run()
    at.selectbox(key="cb_c_class").set_value("e_bus").run()
    at.number_input(key="cb_c_ov_e_bus_lease").set_value(0.0).run()
    assert_clean(at)
    at.slider(key="cb_scn_peak").set_value(30).run()
    at.toggle(key="cb_scn_cap").set_value(False).run()
    assert_clean(at)


def test_diversion_shares_rebalance_and_overpin_warning():
    at = run()
    at.slider(key="cb_s_share_car").set_value(60).run()
    assert_clean(at)
    at.slider(key="cb_s_share_no_travel").set_value(60).run()  # 60 + 60 > 100 -> defaults used with a warning
    assert_clean(at)
    assert any("more than 100%" in w.value for w in at.warning)


def test_cba_full_cost_basis_reconciles_with_route_summary():
    """Per-day trip operating cost from the band economics equals the route_summary basis, so the BCR basis is consistent."""
    import pandas as pd

    from modules.analytics import fare_analysis as FA
    from modules.analytics import socio_economic as SE
    from modules.ui import cost_charts as CC

    inp = FA.load_inputs()
    econ = FA.band_economics(inp["tm"], inp["model"], inp["routes"])
    rs = dio.read_table("route_summary", "processed")
    n_days = float(inp["tm"]["service_date"].nunique())
    cinp = CC.cba_inputs(rs, econ, n_days)
    assert cinp["full_cost_per_day_inr"].notna().all()
    op = econ.groupby("route_id")["trip_operating_cost_inr"].sum() / n_days
    pd.testing.assert_series_equal(cinp.set_index("route_id")["trip_operating_cost_per_day_inr"].sort_index(), op.sort_index(),
                                   check_names=False, rtol=1e-6)
    corr = SE.aggregate_to_corridor(SE.compute_cba(cinp))
    assert corr["bcr"].notna().all()


def test_pdf_contains_cost_benefit_section():
    pypdf = pytest.importorskip("pypdf")
    from modules.reporting import pdf as P
    from modules.ui import filters as F

    data = P.build_report_pdf(F.Filters("Rajkot-Somnath", "weekday"), now=datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc))
    full = " ".join(" ".join((p.extract_text() or "").split()) for p in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "Cost-benefit and fares (illustrative)" in full
    assert "not viable on fare alone" in full and "Peak departure hours derived from the data" in full
    assert "Illustrative social benefit-cost ratio per corridor" in full
