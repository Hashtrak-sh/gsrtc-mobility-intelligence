"""M5 survey intelligence: theme tagger and aggregation, survey schema alignment with docs/survey_questions.md,
descriptive cross-tabs, and the illustrative logistic switch-intent model (metrics, coefficients, sklearn-missing path)."""
import re
import sys

import numpy as np
import pandas as pd
import pytest

import config
from modules.data import io
from modules.data_gen import constants as C
from modules.data_gen import surveys as GEN
from modules.survey import mode_choice as MC
from modules.survey import summaries as SV
from modules.survey import themes as TH



# ------------------------------------------------------------------------------------------ theme tagger
@pytest.mark.parametrize("text,expected", [
    ("The bus left late and reached well after the scheduled time.", {("punctuality", "negative")}),
    ("Left on time and arrived as scheduled.", {("punctuality", "positive")}),
    ("No working AC and the seats were uncomfortable.", {("comfort_ac", "negative")}),
    ("Very comfortable ride with good air conditioning.", {("comfort_ac", "positive")}),
    ("Did not feel safe during the late-evening trip.", {("safety", "negative")}),
    ("Online booking failed twice.", {("booking_ease", "negative")}),
    ("The fare felt too high for what was offered.", {("value", "negative")}),
    ("Good value for the fare. Courteous staff.", {("value", "positive"), ("staff_behaviour", "positive")}),
    ("Reasonable price for the comfort.", {("value", "positive")}),
])
def test_tagger_known_sentences(text, expected):
    assert {(d["theme"], d["polarity"]) for d in TH.tag_review_text(text)} == expected


def test_tagger_edge_cases():
    assert TH.tag_review_text("") == [] and TH.tag_review_text(None) == [] and TH.tag_review_text(float("nan")) == []
    assert TH.tag_review_text("Nothing relevant here at all.") == []
    assert TH.parse_themes("not json") == [] and TH.parse_themes(None) == []
    assert TH.parse_themes('[{"theme": "value", "polarity": "negative"}, {"theme": "bogus", "polarity": "negative"}]') == [{"theme": "value", "polarity": "negative"}]


def test_tagger_agrees_with_generator_tags(tables):
    rep = TH.agreement_report(tables["reviews"])
    assert rep["n_reviews"] == len(tables["reviews"]) and {p["theme"] for p in rep["per_theme"]} == set(C.REVIEW_THEMES)
    assert rep["exact_match_share"] >= 0.95 and rep["polarity_accuracy"] >= 0.95
    assert rep["theme_precision"] >= 0.95 and rep["theme_recall"] >= 0.95
    assert TH.agreement_report(tables["reviews"].iloc[0:0])["n_reviews"] == 0


def test_open_text_tagger_agrees_with_structured_answers(tables):
    ag = TH.open_text_agreement(tables["survey_responses"])
    assert ag["condition_precision"] >= 0.95 and ag["no_condition_agreement"] >= 0.95 and ag["reason_precision"] >= 0.95
    t = TH.tag_open_text("I travel by my car because the bus has no air conditioning in the heat. I would consider the bus if the fare was lower.")
    assert t == {"reasons": ["no_ac_on_bus"], "switch_conditions": ["lower_fare"]}
    assert TH.tag_open_text(None) == {"reasons": [], "switch_conditions": []}


# ------------------------------------------------------------------------------------------ theme aggregation
def _mini_reviews():
    rows = [
        ("state", "A", [{"theme": "punctuality", "polarity": "negative"}, {"theme": "value", "polarity": "positive"}]),
        ("state", "A", [{"theme": "punctuality", "polarity": "negative"}]),
        ("state", "A", [{"theme": "punctuality", "polarity": "positive"}]),
        ("state", "A", [{"theme": "value", "polarity": "negative"}]),
        ("private", "A", [{"theme": "punctuality", "polarity": "positive"}]),
        ("private", "A", [{"theme": "value", "polarity": "negative"}, {"theme": "value", "polarity": "negative"}]),  # duplicate counted once
        ("private", "B", [{"theme": "value", "polarity": "negative"}]),
    ]
    import json

    return pd.DataFrame({"review_id": [f"R{i}" for i in range(len(rows))], "operator_type": [r[0] for r in rows], "route_pair": [r[1] for r in rows],
                         "themes": [json.dumps(r[2]) for r in rows], "text": ""})


def test_theme_counts_and_comparison_hand_computed():
    r = _mini_reviews()
    c = TH.theme_counts(r, TH.METHOD_GENERATOR).set_index(["operator_type", "theme"])
    assert c.loc[("state", "punctuality"), "negative"] == 2 and c.loc[("state", "punctuality"), "positive"] == 1
    assert c.loc[("state", "punctuality"), "n_reviews"] == 4 and c.loc[("state", "punctuality"), "negative_share"] == pytest.approx(0.5)
    assert c.loc[("private", "value"), "negative"] == 2 and c.loc[("private", "value"), "n_reviews"] == 3   # duplicate in one review counted once -> A:1 + B:1
    assert (c["positive"] + c["negative"] == c["mentions"]).all()
    cmp_ = TH.theme_comparison(r, TH.METHOD_GENERATOR, "A").set_index("theme")
    assert cmp_.loc["punctuality", "deficit"] == pytest.approx(0.5 - 0.0)          # state 2/4 vs private 0/2
    assert cmp_.loc["value", "deficit"] == pytest.approx(1 / 4 - 1 / 2)
    assert cmp_.loc["punctuality", "state_n_reviews"] == 4 and cmp_.loc["punctuality", "private_n_reviews"] == 2
    assert TH.review_theme_deficit(r, "A", min_reviews=1) == pytest.approx((0.5 + 0.0) / 7)          # only positive deficits (punctuality) count
    assert np.isnan(TH.review_theme_deficit(r, "A", min_reviews=5))                                   # too few reviews -> missing, not 0
    assert np.isnan(TH.theme_comparison(r[r["operator_type"] == "state"], TH.METHOD_GENERATOR)["private_negative_share"]).all()


def test_review_theme_summary_json_and_planted_state_private_difference(tables):
    s = TH.review_theme_summary(tables["reviews"], "Rajkot-Somnath")
    assert s["method"] == TH.METHOD_GENERATOR and s["state"]["n_reviews"] > 0 and s["private"]["n_reviews"] > 0
    assert set(s["state"]["themes"]) == set(C.REVIEW_THEMES)
    for method in (TH.METHOD_GENERATOR, TH.METHOD_KEYWORD):
        t = TH.theme_comparison(tables["reviews"], method).set_index("theme")
        assert t.loc["punctuality", "deficit"] > 0.15 and t.loc["comfort_ac", "deficit"] > 0.15      # state worse on punctuality and AC (planted)
        assert t.loc["value", "deficit"] < 0                                                          # private worse on value (planted)
    a = TH.theme_comparison(tables["reviews"], TH.METHOD_GENERATOR)
    b = TH.theme_comparison(tables["reviews"], TH.METHOD_KEYWORD)
    assert np.allclose(a["state_negative_share"], b["state_negative_share"])                         # both methods give the same aggregate on this data
    with pytest.raises(ValueError):
        TH.theme_counts(tables["reviews"], "llm")


# ------------------------------------------------------------------------------------------ survey schema alignment
def _parse_questions():
    text = (config.ROOT_DIR / "docs" / "survey_questions.md").read_text(encoding="utf-8")
    blocks = re.split(r"^### ", text, flags=re.M)[1:]
    out = {}
    for b in blocks:
        m = re.search(r"^Field: `(\w+)`", b, flags=re.M)
        if m:
            out.setdefault(m.group(1), []).append(set(re.findall(r"^- `([^`]+)` - ", b, flags=re.M)))
    return text, blocks, out


def test_survey_questions_match_schema_enums_exactly(tables):
    text, blocks, q = _parse_questions()
    assert 1 <= len([b for b in blocks if re.match(r"Q\d+\.", b)]) <= 12
    assert q["current_mode"] == [set(C.MODES)] and q["trip_purpose"] == [set(C.PURPOSES)]
    assert q["income_band"] == [set(C.SURVEY_INCOME_BANDS)] and q["switch_conditions"] == [set(C.SWITCH_CONDITIONS)]
    (both_lists,) = q["reasons"]                                       # Q5 shows a private-mode list and a bus/rail list
    private, transit = set(C.PRIVATE_USE_REASONS), set(GEN._TRANSIT_REASONS)
    assert both_lists == private | transit
    head, tail = text.split("Bus and rail list:")
    assert set(re.findall(r"^- `([^`]+)` - ", head.split("Private-mode list:")[1].split("### Q6")[0], flags=re.M)) == private
    assert set(re.findall(r"^- `([^`]+)` - ", tail.split("### Q6")[0], flags=re.M)) == transit
    assert q["switch_intent"] == [{"1", "0"}]
    cols = set(tables["survey_responses"].columns)
    assert set(q) <= cols and {"origin_zone_id", "dest_zone_id", "open_text"} <= set(q)
    # the synthetic data only uses codes the question set offers
    s = tables["survey_responses"]
    assert set(s["current_mode"]) <= set(C.MODES) and set(s["income_band"]) <= set(C.SURVEY_INCOME_BANDS)
    used = {x for cell in s["reasons"] for x in SV._parse(cell)}
    assert used <= private | transit


def test_survey_questions_state_no_live_endpoint_and_data_minimisation():
    text, _, _ = _parse_questions()
    low = text.lower()
    assert "no live response endpoint" in low and "simulated" in low
    assert "no name, phone number" in low and "live_demo_response" in text


# ------------------------------------------------------------------------------------------ descriptive cross-tabs
def test_descriptive_crosstabs(tables):
    s = tables["survey_responses"]
    m = SV.mode_by_purpose(s)
    assert np.allclose(m.sum(axis=0), 100.0)                                       # each mode column is 100% of its respondents
    for by in SV.GROUP_COLUMNS:
        w = SV.multi_select_by_group(s, "switch_conditions", by)
        assert w.shape[0] <= 8 and ((w >= 0) & (w <= 100)).all().all()
    w = SV.multi_select_by_group(s, "switch_conditions", "income_band")
    sizes = SV.group_sizes(SV.private_mode_users(s), "income_band")
    assert list(w.columns) == [SV.label(g) for g in SV.INCOME_ORDER if sizes.get(g, 0) >= 10]
    # hand check: reliability share among low-income private users
    low = SV.private_mode_users(s)
    low = low[low["income_band"] == "low"]
    want = np.mean(["reliability" in SV._parse(c) for c in low["switch_conditions"]]) * 100
    assert w.loc["Reliable timings", "Low income"] == pytest.approx(want)
    assert SV.multi_select_by_group(s.iloc[0:0], "reasons", "trip_purpose").empty


# ------------------------------------------------------------------------------------------ logistic model
@pytest.fixture(scope="module")
def sk():
    return pytest.importorskip("sklearn")   # model tests need it; the sklearn-missing path is tested via monkeypatch below


@pytest.fixture(scope="module")
def fit(sk, tables):
    return MC.fit_switch_model(tables["survey_responses"])


def test_design_matrix_matches_documented_population(tables):
    X, y = MC.design_matrix(tables["survey_responses"])
    s = tables["survey_responses"]
    assert list(X.columns) == list(MC.FEATURES) and len(X) == len(y) == int(s["switch_intent"].notna().sum())
    assert set(s.loc[X.index, "current_mode"]) <= set(MC.PRIVATE_MODEL_MODES) and set(np.unique(y)) == {0, 1}
    assert set(np.unique(X.to_numpy())) <= {0, 1}


def test_metrics_beat_naive_baseline(fit):
    m = fit["metrics"].set_index("metric")
    assert m.loc["roc_auc", "model"] > 0.6 and m.loc["roc_auc", "baseline"] == 0.5
    assert m.loc["brier_score", "model"] < m.loc["brier_score", "baseline"]
    assert m.loc["accuracy", "model"] > m.loc["accuracy", "baseline"]
    assert m["beats_baseline"].all() and fit["metrics"]["n_test"].iloc[0] == fit["meta"]["n_test"]
    meta = fit["meta"]
    assert meta["n_train"] + meta["n_test"] == meta["n_labelled"] and meta["seed"] == config.SEED
    assert meta["n_test"] == pytest.approx(meta["n_labelled"] * config.SURVEY_MODEL_TEST_SIZE, abs=1)
    assert "not a forecast" in meta["label"]


def test_stratified_split_keeps_base_rate(sk, tables):
    from sklearn.model_selection import train_test_split

    X, y = MC.design_matrix(tables["survey_responses"])
    _, _, ytr, yte = train_test_split(X, y, test_size=config.SURVEY_MODEL_TEST_SIZE, random_state=config.SEED, stratify=y)
    assert abs(ytr.mean() - yte.mean()) < 0.01 and ytr.mean() == pytest.approx(y.mean(), abs=0.01)


def test_coefficients_recover_planted_mechanism(fit):
    c = fit["coefficients"].set_index("feature")
    for f in ("cond_reliability", "cond_ac_comfort", "cond_frequency"):
        assert c.loc[f, "coef_full_fit"] > 0 and c.loc[f, "coef_train_fit"] > 0           # signs as planted
        assert abs(c.loc[f, "coef_full_fit"] - c.loc[f, "true_coefficient"]) < 0.4          # and near the true value
    assert c.loc["mode_car", "coef_full_fit"] < 0 and c.loc["income_high", "coef_full_fit"] < 0
    # the three planted conditions are the three largest fitted condition effects
    cond = c[c.index.str.startswith("cond_")]["coef_full_fit"].sort_values(ascending=False)
    assert set(cond.index[:3]) == {"cond_reliability", "cond_ac_comfort", "cond_frequency"}
    assert c.loc["cond_safety", "true_coefficient"] == 0 and abs(c.loc["cond_safety", "coef_full_fit"]) < 0.5   # distractors stay near 0
    assert (c.loc[[f for f in c.index if c.loc[f, "true_coefficient"] == 0], "sign_matches_truth"].isna()).all()
    assert c.loc["intercept", "true_coefficient"] == C.INTENT_INTERCEPT
    assert (fit["coefficients"]["source_type"] == "model_output").all()


def test_model_is_deterministic(sk, tables):
    a, b = MC.fit_switch_model(tables["survey_responses"]), MC.fit_switch_model(tables["survey_responses"])
    pd.testing.assert_frame_equal(a["coefficients"], b["coefficients"])
    pd.testing.assert_frame_equal(a["metrics"], b["metrics"])


def test_scenario_probabilities(fit):
    coef = fit["coefficients"]
    persona = dict(mode="car", purpose="work", income_band="middle")
    none = MC.predict_probability(coef, MC.persona_features(conditions=[], **persona))
    two = MC.predict_probability(coef, MC.persona_features(conditions=["reliability", "ac_comfort"], **persona))
    three = MC.predict_probability(coef, MC.persona_features(conditions=["reliability", "ac_comfort", "frequency"], **persona))
    assert 0 < none < two < three < 1
    # true generator probability, hand computed from constants.py
    z = C.INTENT_INTERCEPT + C.INTENT_COEF["cond_reliability"] + C.INTENT_COEF["cond_ac_comfort"] + C.INTENT_COEF["mode_car"] + C.INTENT_COEF["purpose_work"]
    assert MC.predict_probability(coef, MC.persona_features(conditions=["reliability", "ac_comfort"], **persona), "true_coefficient") == pytest.approx(1 / (1 + np.exp(-z)))
    tab = MC.scenario_table(coef, met=["reliability", "ac_comfort"], **persona)
    assert list(tab["scenario"]) == ["No switch condition met", "Selected conditions met"] and tab["model_probability"].iloc[1] == pytest.approx(two)
    assert abs(tab["model_probability"] - tab["true_generator_probability"]).max() < 0.15


def test_numpy_prediction_equals_sklearn(sk, tables):
    full = MC._fit(*MC.design_matrix(tables["survey_responses"]))
    fit_ = MC.fit_switch_model(tables["survey_responses"])
    row = MC.persona_features(conditions=["frequency"], mode="two_wheeler", purpose="leisure", income_band="high")
    p_sk = float(full.predict_proba(pd.DataFrame([row])[list(MC.FEATURES)])[0, 1])
    assert MC.predict_probability(fit_["coefficients"], row) == pytest.approx(p_sk, abs=1e-9)


def test_degenerate_samples_are_rejected(sk, tables):
    s = tables["survey_responses"]
    with pytest.raises(ValueError):
        MC.fit_switch_model(s.head(20))
    one_class = s.copy()
    one_class["switch_intent"] = one_class["switch_intent"].where(one_class["switch_intent"].isna(), 1)
    with pytest.raises(ValueError):
        MC.fit_switch_model(one_class)


def test_persisted_outputs_round_trip(fit, tmp_path):
    MC.write_outputs(fit, tmp_path)
    coef, mets = MC.read_outputs(tmp_path)
    pd.testing.assert_frame_equal(coef.reset_index(drop=True), fit["coefficients"].reset_index(drop=True), check_dtype=False)
    assert set(mets["metric"]) == {"accuracy", "roc_auc", "brier_score"}
    prov = io.read_provenance(MC.TABLE_COEF, "processed", tmp_path)
    assert prov.source_type.value == "model_output" and "not a forecast" in prov.description
    assert MC.read_outputs(tmp_path / "nowhere") is None


# ------------------------------------------------------------------------------------------ sklearn missing
def test_graceful_skip_when_sklearn_missing(monkeypatch, tables, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "sklearn.linear_model", None)     # makes `import sklearn.linear_model` raise ImportError
    assert MC.sklearn_available() is False
    with pytest.raises(RuntimeError, match="scikit-learn"):
        MC.fit_switch_model(tables["survey_responses"])
    assert MC.run_and_write(tables["survey_responses"], tmp_path) is None
    assert "skipped" in capsys.readouterr().err
    assert MC.read_outputs(tmp_path) is None                              # nothing written
    # numpy-only scenario maths still works from previously persisted coefficients
    assert MC.UNAVAILABLE_MESSAGE.startswith("The illustrative switch-intent model needs scikit-learn")
    coef = pd.DataFrame({"feature": ["intercept", "cond_reliability"], "coef_full_fit": [-1.0, 1.0], "true_coefficient": [-2.0, 1.1]})
    assert MC.predict_probability(coef, {"cond_reliability": 1}) == pytest.approx(0.5)       # no sklearn needed to use persisted coefficients
