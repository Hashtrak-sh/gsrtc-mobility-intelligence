"""M6-ML: ridership baseline model (time split, leakage guard, baselines, interval coverage, importance, determinism,
sklearn-missing path, FK to routes), baseline forecast, and the Route Intelligence 'Observed vs model estimate' tab."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.analytics import forecast as FC
from modules.data import io
from modules.ml import ridership as RM

pytest.importorskip("sklearn")
ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "pages" / "2_Route_Intelligence.py")


@pytest.fixture(scope="module")
def result(tables, analytics):
    return RM.fit_ridership_model(analytics["route_kpis"], tables)


def test_time_split_no_overlap_and_ordered(tables, analytics):
    d = RM.build_dataset(analytics["route_kpis"], tables)
    tr, te = RM.time_split(d["service_date"])
    assert not set(tr) & set(te) and max(tr) < min(te)
    assert len(tr) == config.RIDERSHIP_TRAIN_DAYS and len(te) == 14
    with pytest.raises(ValueError):
        RM.time_split(sorted(d["service_date"].unique())[:10])


def test_no_leakage_features(tables, analytics):
    assert not set(RM.FEATURES) & set(RM.FORBIDDEN_FEATURES)
    assert not any("lag" in f or "revenue" in f or "km" in f.replace("length_km", "") or "load" in f for f in RM.FEATURES)
    d = RM.build_dataset(analytics["route_kpis"], tables)
    assert set(RM.FEATURES) <= set(d.columns) and "boardings" not in RM.FEATURES
    assert d[list(RM.FEATURES)].notna().all().all() and len(d) == 16 * 42


def test_metrics_contain_models_and_baselines(result):
    m = result["metrics"]
    t = m[(m["split"] == "test") & (m["group"] == "all")]
    for name in ("hgb", "ridge", "route_daytype_mean", "seasonal_naive_lag7"):
        assert {"mae", "rmse", "mape_pct"} <= set(t[t["model"] == name]["metric"])
    assert {"local", "intercity", "weekday", "weekend", "festival"} <= set(m["group"])
    assert (m[m["metric"].isin(["mae", "rmse"])]["value"].dropna() >= 0).all()
    assert "test_leave_route_out" in set(m["split"])
    assert (m["source_type"] == "model_output").all()


def test_mape_guards_zero_actuals():
    r = RM.regression_metrics([0, 10, 20], [1, 12, 18])
    assert np.isfinite(r["mape_pct"]) and r["n"] == 3 and r["mae"] == pytest.approx(5 / 3)
    assert np.isnan(RM.regression_metrics([0, 0], [1, 1])["mape_pct"])


def test_interval_coverage_and_bounds(result):
    m = result["metrics"]
    cov = m[(m["metric"] == "interval_coverage") & (m["group"] == "all")]["value"].iloc[0]
    assert 0.0 <= cov <= 1.0
    p = result["predictions"]
    assert (p["lower_bound"] <= p["predicted_demand"]).all() and (p["predicted_demand"] <= p["upper_bound"]).all() and (p["lower_bound"] >= 0).all()
    assert cov == pytest.approx(((p["actual_demand"] >= p["lower_bound"]) & (p["actual_demand"] <= p["upper_bound"])).mean())


def test_importance_table(result):
    imp = result["importance"]
    assert len(imp) == len(RM.FEATURES) and set(imp["feature"]) == set(RM.FEATURES)
    assert imp["rank"].tolist() == list(range(1, len(imp) + 1)) and imp["importance_mae_increase"].is_monotonic_decreasing


def test_predictions_schema_and_fk(result, tables):
    p = result["predictions"]
    for c in ("entity_type", "entity_id", "service_date", "hour", "actual_demand", "predicted_demand", "lower_bound", "upper_bound",
              "model_name", "model_version", "source_type", "limitations"):
        assert c in p.columns
    assert set(p["entity_id"]) <= set(tables["routes"]["route_id"]) and (p["entity_type"] == "route").all() and p["hour"].isna().all()
    assert p["service_date"].min() > result["meta"]["train_dates"][1] and len(p) == 16 * 14
    assert "not evidence of real-world accuracy" in p["limitations"].iloc[0]


def test_deterministic(tables, analytics, result):
    again = RM.fit_ridership_model(analytics["route_kpis"], tables)
    for k in ("predictions", "metrics", "importance"):
        pd.testing.assert_frame_equal(result[k], again[k])


def test_graceful_skip_without_sklearn(monkeypatch, tables, analytics, tmp_path, capsys):
    monkeypatch.setattr(RM, "sklearn_available", lambda: False)
    with pytest.raises(RuntimeError):
        RM.fit_ridership_model(analytics["route_kpis"], tables)
    assert RM.run_and_write(analytics["route_kpis"], tables, tmp_path) is None
    assert "skipped" in capsys.readouterr().err and not io.table_exists("predictions", "processed", tmp_path)


def test_write_and_read_roundtrip(result, tmp_path):
    RM.write_outputs(result, tmp_path)
    back = RM.read_outputs(tmp_path)
    assert set(back) == {"predictions", "metrics", "importance"} and len(back["predictions"]) == len(result["predictions"])
    assert io.read_provenance("predictions", "processed", tmp_path).source_type.value == "model_output"
    assert RM.read_outputs(tmp_path / "nowhere") is None


# ------------------------------------------------------------------ baseline forecast
def test_baseline_forecast(analytics):
    k = analytics["route_kpis"]
    fc = FC.baseline_forecast(k)
    assert len(fc) == 16 * 7 and fc.groupby("route_id").size().eq(7).all()
    assert pd.to_datetime(fc["service_date"]).min() == pd.to_datetime(k["service_date"]).max() + pd.Timedelta(days=1)
    assert (fc["lower_bound"] <= fc["forecast_boardings"]).all() and (fc["forecast_boardings"] <= fc["upper_bound"]).all()
    assert fc["label"].str.contains("not a model").all()
    # IC02 weekend estimate exceeds its weekday estimate (planted weekend lift)
    ic = fc[fc["route_id"] == "IC02"].set_index("day_type")["forecast_boardings"]
    assert ic.loc["weekend"].min() > ic.loc["weekday"].max()
    pd.testing.assert_frame_equal(fc, FC.baseline_forecast(k))


# ------------------------------------------------------------------ page
def _tab_text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(w.value for w in at.warning) + " " + " ".join(c.value for c in at.code)


@pytest.mark.skipif(not all((config.PROCESSED_DIR / f"{t}.parquet").is_file() for t in ("route_summary", "predictions", "ridership_model_metrics",
                                                                                      "ridership_feature_importance")), reason="model outputs not generated")
def test_page_with_predictions():
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Observed vs model estimate" in [t.label for t in at.tabs]
    assert "not evidence of real-world accuracy" in _tab_text(at)
    assert len(at.metric) <= 4


def test_page_without_predictions(monkeypatch):
    from modules.ui import data as D

    real = D.try_load
    monkeypatch.setattr(D, "try_load", lambda n, layer: None if n in ("predictions", "ridership_model_metrics", "ridership_feature_importance") else real(n, layer))
    if not (config.PROCESSED_DIR / "route_summary.parquet").is_file():
        pytest.skip("processed data not generated")
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Model outputs not available" in _tab_text(at) and "python -m modules.analytics.run" in _tab_text(at)
