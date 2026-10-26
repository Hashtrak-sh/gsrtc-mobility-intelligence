"""Route-day ridership baseline model on the SYNTHETIC data (scikit-learn), with naive baselines, intervals and importances.

**Target** - ``route_kpis.boardings``: passengers boarding a route on a service date (16 routes x 42 days = 672 rows). Route-hour
demand is not modelled (daily level is enough for a baseline and the hourly table is censored by capacity).

**Features (no same-day outcome information)**
* route attributes: ``is_intercity``, ``length_km``, bus type (one-hot), ``minimum_service``, ``n_stops``, catchment
  population / jobs / points of interest of the zones the route's stops sit in (``zones``; each zone counted once);
* planned service supply: ``sched_trips`` and ``sched_seats`` per day, counted from the timetable (``trips``). Supply is
  PLANNED before the day happens, so it is not an outcome of the day's demand (it does reflect past planning decisions,
  which is why importance is not causal);
* calendar: ``dow`` (0 = Monday), ``is_weekend``, ``is_festival``;
* ``private_services``: synthetic competitor services of the route's corridor for the day type (0 for local routes).
Never used: tickets, revenue, passenger-km, load factor, boardings per seat, peak load, delay or anything else derived from the
same day's tickets (:data:`FORBIDDEN_FEATURES`). Lagged boardings appear only in the separately labelled forecasting baseline
``seasonal_naive_lag7``.

**Split** - time-based holdout: the first ``config.RIDERSHIP_TRAIN_DAYS`` (28) service dates train, the remaining 14 test.
For the shipped data: train 2026-08-03..2026-08-30, test 2026-08-31..2026-09-13. The same 16 routes are in both windows, so this
is a temporal forecast, not cross-route generalisation (a leave-one-route-out diagnostic is reported separately).
CAVEAT: both festival days (2026-09-04/05) fall in the TEST window, so no model can learn a festival effect from the training
window; per-day-type metrics show how much that costs.

**Models** - baselines ``route_daytype_mean`` (training mean of the route x day type; the route's overall mean for an unseen
day type), ``seasonal_naive_lag7`` (boardings of the same route 7 days earlier, a 7-day-ahead forecasting baseline); models
``hgb`` (HistGradientBoostingRegressor, the point model whose output is stored) and ``ridge`` (standardised ridge regression).
Seed 42, deterministic. Interval: quantile HGB at 0.1 / 0.9 (nominal 80 %), empirical coverage reported on the test window.
Explainability: permutation importance of ``hgb`` on the test window (increase in MAE when a feature is shuffled). SHAP is not
used. Importance is a statement about the fitted model, not about causes.

scikit-learn is optional (``requirements-optional.txt``, group ``ml``). Command: ``python -m modules.ml.ridership`` (also called
by ``python -m modules.analytics.run`` when scikit-learn is installed; skipped with a note otherwise).
"""
from __future__ import annotations

import importlib
import json
import sys
from typing import Any

import numpy as np
import pandas as pd

import config
from modules.data import io
from modules.data.provenance import make_provenance

TABLE_PRED = "predictions"
TABLE_METRICS = "ridership_model_metrics"
TABLE_IMPORTANCE = "ridership_feature_importance"
MODEL_NAME = "hgb_route_day_boardings"
LIMITATIONS = ("Synthetic data, 6 weeks, 16 routes; same routes in train and test; festival days only in the test window. "
               + config.RIDERSHIP_LABEL + ".")
UNAVAILABLE_MESSAGE = ("The ridership model needs scikit-learn, which is not installed. "
                       "Install it with `pip install scikit-learn` and run `python -m modules.ml.ridership`.")

BUS_TYPES = ("ordinary", "express", "AC_seater", "AC_sleeper")
FEATURES: tuple[str, ...] = ("is_intercity", "length_km", *[f"bus_{b}" for b in BUS_TYPES], "minimum_service", "n_stops",
                             "catchment_population", "catchment_jobs", "catchment_pois", "sched_trips", "sched_seats",
                             "dow", "is_weekend", "is_festival", "private_services")
FEATURE_LABELS = {
    "is_intercity": "Intercity route", "length_km": "Route length (km)", "bus_ordinary": "Bus type: ordinary", "bus_express": "Bus type: express",
    "bus_AC_seater": "Bus type: AC seater", "bus_AC_sleeper": "Bus type: AC sleeper", "minimum_service": "Protected minimum-service route",
    "n_stops": "Number of stops", "catchment_population": "Catchment population (served zones)", "catchment_jobs": "Catchment jobs (served zones)",
    "catchment_pois": "Catchment points of interest (served zones)", "sched_trips": "Scheduled trips per day", "sched_seats": "Scheduled seats per day",
    "dow": "Day of week", "is_weekend": "Weekend", "is_festival": "Festival day", "private_services": "Private competitor services on the corridor",
}
# Columns that carry same-day ticket outcomes (or the target itself) and must never be features.
FORBIDDEN_FEATURES: tuple[str, ...] = (
    "boardings", "ticket_revenue_inr", "estimated_passenger_km", "passenger_km", "load_factor_pct", "epkm_inr", "revenue_per_passenger_inr",
    "contribution_inr", "boardings_per_seat", "peak_load_factor_max", "reliability_pct", "mean_delay_min", "operating_cost_inr", "lag7", "lag_7")
BASELINES = ("route_daytype_mean", "seasonal_naive_lag7")
MODELS = ("hgb", "ridge")
MODEL_LABELS = {
    "hgb": "Gradient boosting (HistGradientBoostingRegressor)", "ridge": "Ridge regression (standardised)",
    "route_daytype_mean": "Baseline: route x day-type mean of the training window",
    "seasonal_naive_lag7": "Forecasting baseline: same weekday previous week (lagged boardings)",
    "route_type_daytype_mean_other_routes": "Baseline (leave-route-out): route-type x day-type mean of the other routes",
    "hgb_leave_route_out": "Gradient boosting, route held out of training",
}
SOURCE_TABLES = ("routes", "route_stops", "stops", "zones", "trips", "competitor_services")


def sklearn_available() -> bool:
    """True if scikit-learn can be imported (checked at call time so tests can simulate its absence)."""
    try:
        importlib.import_module("sklearn.ensemble")
        importlib.import_module("sklearn.inspection")
        return True
    except Exception:  # noqa: BLE001 - any import failure means "unavailable"
        return False


# ---------------------------------------------------------------------------------------------- dataset
def build_dataset(route_kpis: pd.DataFrame, t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per route x service date: identifiers, ``day_type``, target ``boardings`` and the :data:`FEATURES`."""
    routes = t["routes"].set_index("route_id")
    rs = t["route_stops"].merge(t["stops"][["stop_id", "zone_id"]], on="stop_id", how="left")
    n_stops = rs.groupby("route_id")["stop_id"].nunique()
    zones = t["zones"].copy()
    zones["pois"] = zones["poi_counts"].map(lambda v: float(sum(json.loads(v).values())) if isinstance(v, str) and v else 0.0)
    zr = rs[["route_id", "zone_id"]].drop_duplicates().merge(zones[["zone_id", "population", "jobs", "pois"]], on="zone_id", how="left")
    catch = zr.groupby("route_id").agg(catchment_population=("population", "sum"), catchment_jobs=("jobs", "sum"), catchment_pois=("pois", "sum"))
    tr = t["trips"].groupby(["route_id", "service_date"]).agg(sched_trips=("trip_id", "count"), sched_seats=("seats", "sum")).reset_index()
    comp = t["competitor_services"].groupby(["route_pair", "day_type"]).size().rename("private_services").reset_index()

    d = route_kpis[["route_id", "service_date", "day_type", "boardings"]].copy()
    d["service_date"] = d["service_date"].astype(str)
    d = d.merge(tr.assign(service_date=tr["service_date"].astype(str)), on=["route_id", "service_date"], how="left")
    r = routes.loc[d["route_id"]]
    d["is_intercity"] = (r["route_type"].to_numpy() == "intercity").astype(int)
    d["length_km"] = r["length_km"].to_numpy(dtype=float)
    for b in BUS_TYPES:
        d[f"bus_{b}"] = (r["bus_type"].to_numpy() == b).astype(int)
    d["minimum_service"] = r["minimum_service"].astype(int).to_numpy()
    d["n_stops"] = d["route_id"].map(n_stops).astype(float)
    for c in ("catchment_population", "catchment_jobs", "catchment_pois"):
        d[c] = d["route_id"].map(catch[c]).astype(float)
    dt = pd.to_datetime(d["service_date"])
    d["dow"] = dt.dt.dayofweek
    d["is_weekend"] = (d["day_type"] == "weekend").astype(int)
    d["is_festival"] = (d["day_type"] == "festival").astype(int)
    d["corridor"] = r["corridor"].to_numpy()
    d = d.merge(comp, left_on=["corridor", "day_type"], right_on=["route_pair", "day_type"], how="left").drop(columns=["route_pair", "corridor"])
    d["private_services"] = d["private_services"].fillna(0).astype(float)
    d["route_type"] = r["route_type"].to_numpy()
    d[["sched_trips", "sched_seats"]] = d[["sched_trips", "sched_seats"]].fillna(0).astype(float)
    return d.sort_values(["service_date", "route_id"]).reset_index(drop=True)


def time_split(dates, train_days: int = config.RIDERSHIP_TRAIN_DAYS) -> tuple[list[str], list[str]]:
    """First ``train_days`` distinct dates -> train, the rest -> test (strictly later, no overlap)."""
    u = sorted({str(x) for x in dates})
    if len(u) <= train_days + 1:
        raise ValueError(f"Need more than {train_days + 1} service dates for a time split, got {len(u)}")
    return u[:train_days], u[train_days:]


# ---------------------------------------------------------------------------------------------- metrics
def regression_metrics(actual, pred) -> dict[str, float]:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    ok = ~np.isnan(p)
    a, p = a[ok], p[ok]
    if len(a) == 0:
        return {"mae": np.nan, "rmse": np.nan, "mape_pct": np.nan, "n": 0}
    e = p - a
    nz = a > 0  # MAPE guard: zero-actual rows are skipped
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))),
            "mape_pct": float(np.mean(np.abs(e[nz]) / a[nz]) * 100) if nz.any() else np.nan, "n": int(len(a))}


GROUPS = {"all": lambda d: np.ones(len(d), bool), "local": lambda d: (d["route_type"] == "local").to_numpy(),
          "intercity": lambda d: (d["route_type"] == "intercity").to_numpy(), "weekday": lambda d: (d["day_type"] == "weekday").to_numpy(),
          "weekend": lambda d: (d["day_type"] == "weekend").to_numpy(), "festival": lambda d: (d["day_type"] == "festival").to_numpy()}


def metric_rows(df: pd.DataFrame, preds: dict[str, np.ndarray], split: str, kinds: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for name, p in preds.items():
        for g, fn in GROUPS.items():
            m = fn(df)
            res = regression_metrics(df["boardings"].to_numpy()[m], np.asarray(p)[m])
            for k in ("mae", "rmse", "mape_pct"):
                rows.append({"model": name, "model_kind": kinds[name], "split": split, "group": g, "metric": k, "value": res[k], "n": res["n"]})
    return rows


# ---------------------------------------------------------------------------------------------- baselines
def route_daytype_mean(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    m = train.groupby(["route_id", "day_type"])["boardings"].mean()
    overall = train.groupby("route_id")["boardings"].mean()
    out = [m.get((r, d), overall.get(r, np.nan)) for r, d in zip(test["route_id"], test["day_type"])]
    return np.asarray(out, float)


def seasonal_naive_lag7(full: pd.DataFrame, target: pd.DataFrame) -> np.ndarray:
    """Boardings of the same route 7 days earlier (NaN where that day is outside the data)."""
    key = {(r, d): b for r, d, b in zip(full["route_id"], full["service_date"], full["boardings"])}
    prev = (pd.to_datetime(target["service_date"]) - pd.DateOffset(days=7)).dt.strftime("%Y-%m-%d")
    return np.asarray([key.get((r, d), np.nan) for r, d in zip(target["route_id"], prev)], float)


# ---------------------------------------------------------------------------------------------- models
def _hgb(**kw):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=10, l2_regularization=1.0,
                                         early_stopping=False, random_state=config.SEED, **kw)


def _ridge():
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


def fit_ridership_model(route_kpis: pd.DataFrame, t: dict[str, pd.DataFrame], seed: int = config.SEED) -> dict[str, Any]:
    """Fit, evaluate and explain. Returns ``{"predictions", "metrics", "importance", "meta"}``.

    Raises ``RuntimeError(UNAVAILABLE_MESSAGE)`` without scikit-learn and ``ValueError`` for too short a history."""
    if not sklearn_available():
        raise RuntimeError(UNAVAILABLE_MESSAGE)
    from sklearn.inspection import permutation_importance

    data = build_dataset(route_kpis, t)
    train_dates, test_dates = time_split(data["service_date"])
    tr, te = data[data["service_date"].isin(train_dates)].reset_index(drop=True), data[data["service_date"].isin(test_dates)].reset_index(drop=True)
    X_tr, X_te = tr[list(FEATURES)], te[list(FEATURES)]
    y_tr = tr["boardings"].to_numpy(float)

    hgb = _hgb().fit(X_tr, y_tr)
    ridge = _ridge().fit(X_tr, y_tr)
    q_lo, q_hi = config.RIDERSHIP_INTERVAL_QUANTILES
    lo_m, hi_m = _hgb(loss="quantile", quantile=q_lo).fit(X_tr, y_tr), _hgb(loss="quantile", quantile=q_hi).fit(X_tr, y_tr)

    def clip(p):
        return np.clip(np.asarray(p, float), 0.0, None)

    preds_te = {"hgb": clip(hgb.predict(X_te)), "ridge": clip(ridge.predict(X_te)),
                "route_daytype_mean": route_daytype_mean(tr, te), "seasonal_naive_lag7": seasonal_naive_lag7(data, te)}
    preds_tr = {"hgb": clip(hgb.predict(X_tr)), "ridge": clip(ridge.predict(X_tr)),
                "route_daytype_mean": route_daytype_mean(tr, tr), "seasonal_naive_lag7": seasonal_naive_lag7(data, tr)}
    kinds = {"hgb": "model", "ridge": "model", "route_daytype_mean": "baseline", "seasonal_naive_lag7": "forecasting_baseline"}
    rows = metric_rows(te, preds_te, "test", kinds) + metric_rows(tr, preds_tr, "train", kinds)

    # interval (post-processed so that lower <= point <= upper, lower >= 0) and its empirical coverage
    point = preds_te["hgb"]
    lower = np.minimum(clip(lo_m.predict(X_te)), point)
    upper = np.maximum(clip(hi_m.predict(X_te)), point)
    inside = (te["boardings"].to_numpy() >= lower) & (te["boardings"].to_numpy() <= upper)
    nominal = q_hi - q_lo
    for g, fn in GROUPS.items():
        m = fn(te)
        if m.any():
            rows.append({"model": "hgb_interval", "model_kind": "interval", "split": "test", "group": g, "metric": "interval_coverage",
                         "value": float(inside[m].mean()), "n": int(m.sum())})
            rows.append({"model": "hgb_interval", "model_kind": "interval", "split": "test", "group": g, "metric": "interval_mean_width",
                         "value": float((upper - lower)[m].mean()), "n": int(m.sum())})
    rows.append({"model": "hgb_interval", "model_kind": "interval", "split": "test", "group": "all", "metric": "interval_nominal_coverage",
                 "value": float(nominal), "n": int(len(te))})

    # secondary diagnostic: leave-one-route-out (can the model transfer to a route it has not seen?) on the same test dates
    lo_pred, lo_base = np.full(len(te), np.nan), np.full(len(te), np.nan)
    for r in sorted(data["route_id"].unique()):
        m_tr, m_te = (tr["route_id"] != r).to_numpy(), (te["route_id"] == r).to_numpy()
        lo_pred[m_te] = clip(_hgb().fit(X_tr[m_tr], y_tr[m_tr]).predict(X_te[m_te]))
        other = tr[m_tr]
        by = other.groupby(["route_type", "day_type"])["boardings"].mean()
        by_t = other.groupby("route_type")["boardings"].mean()
        lo_base[m_te] = [by.get((a, b), by_t[a]) for a, b in zip(te.loc[m_te, "route_type"], te.loc[m_te, "day_type"])]
    kinds_lo = {"hgb_leave_route_out": "diagnostic", "route_type_daytype_mean_other_routes": "diagnostic_baseline"}
    rows += metric_rows(te, {"hgb_leave_route_out": lo_pred, "route_type_daytype_mean_other_routes": lo_base}, "test_leave_route_out", kinds_lo)
    metrics = pd.DataFrame(rows)
    metrics["source_type"] = "model_output"
    metrics["model_label"] = metrics["model"].map(lambda m: MODEL_LABELS.get(m, "Gradient boosting 10-90 % quantile interval"))

    # permutation importance on the test window
    pi = permutation_importance(hgb, X_te, te["boardings"].to_numpy(float), scoring="neg_mean_absolute_error",
                                n_repeats=config.RIDERSHIP_PERMUTATION_REPEATS, random_state=seed)
    imp = pd.DataFrame({"feature": list(FEATURES), "label": [FEATURE_LABELS[f] for f in FEATURES],
                        "importance_mae_increase": pi.importances_mean, "importance_std": pi.importances_std})
    imp = imp.sort_values("importance_mae_increase", ascending=False).reset_index(drop=True)
    imp.insert(0, "rank", np.arange(1, len(imp) + 1))
    imp["method"] = "permutation importance on the test window (increase in MAE, passengers/day, when the feature is shuffled)"
    imp["note"] = "Describes the fitted model, not causes; correlated features (route attributes) share importance. SHAP not used."
    imp["model_name"], imp["model_version"], imp["source_type"] = MODEL_NAME, config.RIDERSHIP_MODEL_VERSION, "model_output"

    pred = pd.DataFrame({
        "entity_type": "route", "entity_id": te["route_id"], "service_date": te["service_date"], "hour": pd.array([pd.NA] * len(te), dtype="Int64"),
        "actual_demand": te["boardings"].astype(float), "predicted_demand": point, "lower_bound": lower, "upper_bound": upper,
        "model_name": MODEL_NAME, "model_version": config.RIDERSHIP_MODEL_VERSION, "source_type": "model_output", "limitations": LIMITATIONS,
        "split": "test", "day_type": te["day_type"], "route_type": te["route_type"],
        "baseline_route_daytype_mean": preds_te["route_daytype_mean"], "baseline_seasonal_naive_lag7": preds_te["seasonal_naive_lag7"]})
    pred = pred.sort_values(["entity_id", "service_date"]).reset_index(drop=True)
    meta = {"target": "route_kpis.boardings (route x service date)", "features": list(FEATURES), "forbidden_features": list(FORBIDDEN_FEATURES),
            "train_dates": [train_dates[0], train_dates[-1]], "test_dates": [test_dates[0], test_dates[-1]], "n_train": int(len(tr)),
            "n_test": int(len(te)), "seed": seed, "interval_quantiles": list(config.RIDERSHIP_INTERVAL_QUANTILES),
            "model": "HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=10, l2=1.0)",
            "shap": "not used; permutation importance shown", "prophet": "not used: only 6 weeks of synthetic history",
            "h3": "not used; zones are the spatial unit", "label": config.RIDERSHIP_LABEL, "limitations": LIMITATIONS}
    return {"predictions": pred, "metrics": metrics, "importance": imp, "meta": meta}


# ---------------------------------------------------------------------------------------------- persistence
def write_outputs(result: dict[str, Any], base_dir=None) -> None:
    prov = make_provenance("model_output", assumptions=result["meta"],
                           description="Ridership baseline model on SYNTHETIC route-day boardings: " + config.RIDERSHIP_LABEL)
    io.write_table(result["predictions"], TABLE_PRED, "processed", base_dir=base_dir, provenance=prov)
    io.write_table(result["metrics"], TABLE_METRICS, "processed", base_dir=base_dir, provenance=prov)
    io.write_table(result["importance"], TABLE_IMPORTANCE, "processed", base_dir=base_dir, provenance=prov)


def run_and_write(route_kpis: pd.DataFrame, t: dict[str, pd.DataFrame], base_dir=None) -> dict[str, Any] | None:
    """Fit and persist; returns the result or None (logged note on stderr) when scikit-learn is missing / history too short."""
    try:
        res = fit_ridership_model(route_kpis, t)
    except (RuntimeError, ValueError) as exc:
        print(f"NOTE: ridership model skipped: {exc}", file=sys.stderr)
        return None
    write_outputs(res, base_dir)
    return res


def read_outputs(base_dir=None) -> dict[str, pd.DataFrame] | None:
    """Persisted ``{"predictions", "metrics", "importance"}`` or None if the model has not been run."""
    names = {"predictions": TABLE_PRED, "metrics": TABLE_METRICS, "importance": TABLE_IMPORTANCE}
    if not all(io.table_exists(n, "processed", base_dir) for n in names.values()):
        return None
    return {k: io.read_table(n, "processed", base_dir) for k, n in names.items()}


def summary_lines(res: dict[str, Any]) -> list[str]:
    m = res["metrics"]
    te = m[(m["split"] == "test") & (m["group"] == "all") & (m["metric"] == "mae")].set_index("model")["value"]
    cov = m[(m["metric"] == "interval_coverage") & (m["group"] == "all")]["value"].iloc[0]
    return [f"test MAE (passengers/day): " + ", ".join(f"{k} {v:.1f}" for k, v in te.items()),
            f"80% interval empirical coverage on the test window: {cov:.0%}", config.RIDERSHIP_LABEL]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Fit the ridership baseline model and write predictions, metrics and importances.")
    ap.add_argument("--base-dir", default=None)
    args = ap.parse_args(argv)
    try:
        t = {n: io.read_table(n, "synthetic", args.base_dir) for n in SOURCE_TABLES}
        kpis = io.read_table("route_kpis", "processed", args.base_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}\nRun: python -m modules.data_gen.generate ; python -m modules.analytics.run", file=sys.stderr)
        return 1
    res = run_and_write(kpis, t, args.base_dir)
    if res is None:
        return 0 if not sklearn_available() else 1
    print(f"{config.SIMULATION_BADGE_TEXT}. Ridership model written ({TABLE_PRED}, {TABLE_METRICS}, {TABLE_IMPORTANCE}).")
    for line in summary_lines(res):
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
