"""Illustrative switch-intent model on the SYNTHETIC survey (scikit-learn ``LogisticRegression``).

Everything here is a demonstration of method and honesty, not a forecast:

* **Target** - ``survey_responses.switch_intent`` (0/1), defined only for respondents whose current mode is a private mode
  (car, two_wheeler, shared_taxi, other); bus and rail users have a null target and are excluded.
* **Features** (documented, 12 + intercept) - the nine ``cond_*`` indicators (1 if the condition is in ``switch_conditions``),
  ``mode_car``, ``purpose_work`` and ``income_high`` (income band upper_middle or high). These are exactly the quantities the
  synthetic generator uses (``modules/data_gen/constants.py: INTENT_INTERCEPT, INTENT_COEF``); five conditions
  (safety, cleanliness, real_time_info, parking_cost_or_hassle, direct_route) have a TRUE coefficient of 0.
* **Validation** - stratified train/test split (``config.SURVEY_MODEL_TEST_SIZE``, seed ``config.SEED``); metrics on the test
  set (accuracy, ROC-AUC, Brier score) against a naive baseline that always predicts the training base rate
  (accuracy of the majority class, Brier of the constant base rate, AUC 0.5).
* **Coefficients** - fitted on the training split (for the metrics) and refitted on all labelled rows (used by the scenario
  widget), next to the TRUE generating coefficients: the model recovers the planted mechanism because the labels were
  produced by it. On real survey data no such check exists.
* **Regularisation** - ``C = config.SURVEY_MODEL_C`` (effectively none) so the coefficients are comparable with the truth.

The scenario probability is *conditional on this synthetic training setup* and is not a forecast of real behaviour.
scikit-learn is an optional dependency (``requirements-optional.txt``, group ``ml``): fitting needs it, but reading the persisted
outputs and computing scenario probabilities (:func:`predict_probability`) only needs numpy.

Command: ``python -m modules.survey.mode_choice`` writes ``survey_model_coefficients`` and ``survey_model_metrics`` to
``data/processed/`` (also called by ``python -m modules.analytics.run`` when scikit-learn is installed).
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
from modules.data_gen import constants as C
from modules.survey.summaries import _parse

PRIVATE_MODEL_MODES: tuple[str, ...] = ("car", "two_wheeler", "shared_taxi", "other")
COND_FEATURES: tuple[str, ...] = tuple(f"cond_{c}" for c in C.SWITCH_CONDITIONS)
FEATURES: tuple[str, ...] = (*COND_FEATURES, "mode_car", "purpose_work", "income_high")
INTERCEPT = "intercept"
FEATURE_LABELS = {
    "cond_reliability": "Condition: reliable timings", "cond_ac_comfort": "Condition: AC and comfort",
    "cond_frequency": "Condition: more frequent service", "cond_lower_fare": "Condition: lower fare",
    "cond_safety": "Condition: safety", "cond_cleanliness": "Condition: cleanliness",
    "cond_real_time_info": "Condition: real-time information", "cond_parking_cost_or_hassle": "Condition: parking cost or hassle",
    "cond_direct_route": "Condition: direct route", "mode_car": "Uses a car (vs other private modes)",
    "purpose_work": "Trip purpose is work", "income_high": "Income upper-middle or high", INTERCEPT: "Intercept",
}
TABLE_COEF = "survey_model_coefficients"
TABLE_METRICS = "survey_model_metrics"
UNAVAILABLE_MESSAGE = ("The illustrative switch-intent model needs scikit-learn, which is not installed. "
                       "Install it with `pip install scikit-learn` and run `python -m modules.survey.mode_choice`.")
ILLUSTRATIVE_LABEL = config.SURVEY_MODEL_LABEL


def sklearn_available() -> bool:
    """True if scikit-learn can be imported (checked at call time so tests can simulate its absence)."""
    try:
        importlib.import_module("sklearn.linear_model")
        return True
    except Exception:  # noqa: BLE001 - any import failure means "unavailable" (missing package, blocked DLL, ...)
        return False


def true_coefficients() -> dict[str, float]:
    """The generator's TRUE coefficients by model feature name (0 for conditions that do not enter the mechanism)."""
    t = {f: 0.0 for f in FEATURES}
    t.update({k: float(v) for k, v in C.INTENT_COEF.items()})
    t[INTERCEPT] = float(C.INTENT_INTERCEPT)
    return t


def design_matrix(survey: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Features (:data:`FEATURES`) and target for private-mode respondents with a recorded ``switch_intent``."""
    s = survey[survey["current_mode"].isin(PRIVATE_MODEL_MODES) & survey["switch_intent"].notna()]
    conds = s["switch_conditions"].map(lambda c: set(_parse(c)))
    X = pd.DataFrame({f"cond_{c}": conds.map(lambda cs, c=c: int(c in cs)) for c in C.SWITCH_CONDITIONS}, index=s.index)
    X["mode_car"] = (s["current_mode"] == "car").astype(int)
    X["purpose_work"] = (s["trip_purpose"] == "work").astype(int)
    X["income_high"] = s["income_band"].isin(["upper_middle", "high"]).astype(int)
    return X[list(FEATURES)], s["switch_intent"].astype(int)


def _fit(X: pd.DataFrame, y: pd.Series):
    from sklearn.linear_model import LogisticRegression

    m = LogisticRegression(C=config.SURVEY_MODEL_C, solver="lbfgs", max_iter=5000)
    m.fit(X, y)
    return m


def fit_switch_model(survey: pd.DataFrame, seed: int = config.SEED) -> dict[str, Any]:
    """Fit the illustrative model. Returns ``{"coefficients": DataFrame, "metrics": DataFrame, "meta": dict}``.

    Raises ``RuntimeError(UNAVAILABLE_MESSAGE)`` when scikit-learn is missing and ``ValueError`` for a degenerate sample
    (too few rows or a single class).
    """
    if not sklearn_available():
        raise RuntimeError(UNAVAILABLE_MESSAGE)
    from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
    from sklearn.model_selection import train_test_split

    X, y = design_matrix(survey)
    if len(y) < 50 or y.nunique() < 2 or int(y.value_counts().min()) < 10:
        raise ValueError(f"Not enough labelled private-mode respondents to fit a model (n={len(y)}, classes={y.value_counts().to_dict()})")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=config.SURVEY_MODEL_TEST_SIZE, random_state=seed, stratify=y)
    m = _fit(Xtr, ytr)
    full = _fit(X, y)
    p = m.predict_proba(Xte)[:, 1]
    base_rate = float(ytr.mean())
    majority = int(base_rate >= 0.5)
    acc = float(accuracy_score(yte, (p >= 0.5).astype(int)))
    brier = float(brier_score_loss(yte, p))
    auc = float(roc_auc_score(yte, p))
    b_acc = float(accuracy_score(yte, np.full(len(yte), majority)))
    b_brier = float(brier_score_loss(yte, np.full(len(yte), base_rate)))
    true = true_coefficients()
    rows = [{"feature": INTERCEPT, "label": FEATURE_LABELS[INTERCEPT], "true_coefficient": true[INTERCEPT],
             "coef_train_fit": float(m.intercept_[0]), "coef_full_fit": float(full.intercept_[0])}]
    for i, f in enumerate(FEATURES):
        rows.append({"feature": f, "label": FEATURE_LABELS[f], "true_coefficient": true[f],
                     "coef_train_fit": float(m.coef_[0][i]), "coef_full_fit": float(full.coef_[0][i])})
    coef = pd.DataFrame(rows)
    coef["abs_error_full_fit"] = (coef["coef_full_fit"] - coef["true_coefficient"]).abs()
    # None where the true coefficient is 0 (sign undefined)
    coef["sign_matches_truth"] = pd.Series([None if t == 0 else bool(np.sign(c) == np.sign(t))
                                            for c, t in zip(coef["coef_full_fit"], coef["true_coefficient"])], dtype="object")
    coef["source_type"] = "model_output"
    metrics = pd.DataFrame([
        {"metric": "accuracy", "model": acc, "baseline": b_acc, "higher_is_better": True,
         "baseline_definition": "always predict the majority class of the training split"},
        {"metric": "roc_auc", "model": auc, "baseline": 0.5, "higher_is_better": True,
         "baseline_definition": "no discrimination (chance)"},
        {"metric": "brier_score", "model": brier, "baseline": b_brier, "higher_is_better": False,
         "baseline_definition": "always predict the training base rate"},
    ])
    metrics["beats_baseline"] = [acc > b_acc, auc > 0.5, brier < b_brier]
    metrics["n_train"], metrics["n_test"], metrics["source_type"] = int(len(ytr)), int(len(yte)), "model_output"
    meta = {"n_labelled": int(len(y)), "n_train": int(len(ytr)), "n_test": int(len(yte)), "base_rate_train": base_rate,
            "base_rate_all": float(y.mean()), "seed": seed, "test_size": config.SURVEY_MODEL_TEST_SIZE, "C": config.SURVEY_MODEL_C,
            "features": list(FEATURES), "modes_included": list(PRIVATE_MODEL_MODES), "label": ILLUSTRATIVE_LABEL}
    return {"coefficients": coef, "metrics": metrics, "meta": meta}


# --------------------------------------------------------------------------------------------- scenario (numpy only)
def persona_features(*, conditions: set[str] | list[str], mode: str, purpose: str, income_band: str) -> dict[str, int]:
    """Feature vector for a persona (conditions that are met, current mode, trip purpose, income band)."""
    cs = set(conditions)
    f = {f"cond_{c}": int(c in cs) for c in C.SWITCH_CONDITIONS}
    f["mode_car"] = int(mode == "car")
    f["purpose_work"] = int(purpose == "work")
    f["income_high"] = int(income_band in ("upper_middle", "high"))
    return f


def predict_probability(coefficients: pd.DataFrame, features: dict[str, int], column: str = "coef_full_fit") -> float:
    """Logistic probability ``1 / (1 + exp(-(intercept + sum coef x feature)))`` from a coefficient table (no sklearn needed).
    Use ``column="true_coefficient"`` for the synthetic generator's TRUE probability."""
    c = coefficients.set_index("feature")[column]
    z = float(c[INTERCEPT]) + sum(float(c[k]) * float(v) for k, v in features.items() if k in c.index)
    return float(1.0 / (1.0 + np.exp(-z)))


def scenario_table(coefficients: pd.DataFrame, *, mode: str, purpose: str, income_band: str, met: set[str] | list[str]) -> pd.DataFrame:
    """Probability for the persona with no conditions met vs with ``met`` conditions met, fitted vs true."""
    rows = []
    for name, conds in (("No switch condition met", set()), ("Selected conditions met", set(met))):
        feats = persona_features(conditions=conds, mode=mode, purpose=purpose, income_band=income_band)
        rows.append({"scenario": name, "conditions": sorted(conds),
                     "model_probability": predict_probability(coefficients, feats, "coef_full_fit"),
                     "true_generator_probability": predict_probability(coefficients, feats, "true_coefficient")})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------- persistence
def write_outputs(result: dict[str, Any], base_dir=None) -> None:
    prov = make_provenance("model_output", assumptions={**result["meta"], "illustrative": True,
                                                        "true_coefficients_source": "modules/data_gen/constants.py"},
                           description="Illustrative logistic switch-intent model on the SYNTHETIC survey: " + ILLUSTRATIVE_LABEL)
    io.write_table(result["coefficients"], TABLE_COEF, "processed", base_dir=base_dir, provenance=prov)
    io.write_table(result["metrics"], TABLE_METRICS, "processed", base_dir=base_dir, provenance=prov)


def run_and_write(survey: pd.DataFrame, base_dir=None) -> dict[str, Any] | None:
    """Fit and persist; returns the result, or None (with a logged note on stderr) when scikit-learn is unavailable or the
    sample is unusable. Never raises for those two conditions."""
    try:
        res = fit_switch_model(survey)
    except RuntimeError as exc:
        print(f"NOTE: survey switch-intent model skipped: {exc}", file=sys.stderr)
        return None
    except ValueError as exc:
        print(f"NOTE: survey switch-intent model skipped: {exc}", file=sys.stderr)
        return None
    write_outputs(res, base_dir)
    return res


def read_outputs(base_dir=None) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Persisted (coefficients, metrics) or None if the model has not been run."""
    if not (io.table_exists(TABLE_COEF, "processed", base_dir) and io.table_exists(TABLE_METRICS, "processed", base_dir)):
        return None
    return io.read_table(TABLE_COEF, "processed", base_dir), io.read_table(TABLE_METRICS, "processed", base_dir)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Fit the illustrative survey switch-intent model and write its outputs.")
    ap.add_argument("--base-dir", default=None)
    args = ap.parse_args(argv)
    try:
        survey = io.read_table("survey_responses", "synthetic", args.base_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}\nRun: python -m modules.data_gen.generate", file=sys.stderr)
        return 1
    res = run_and_write(survey, args.base_dir)
    if res is None:
        return 0 if not sklearn_available() else 1
    print(f"{config.SIMULATION_BADGE_TEXT}. Survey switch-intent model ({ILLUSTRATIVE_LABEL}).")
    print(res["metrics"][["metric", "model", "baseline", "beats_baseline"]].to_string(index=False))
    print(res["coefficients"][["feature", "true_coefficient", "coef_full_fit"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

