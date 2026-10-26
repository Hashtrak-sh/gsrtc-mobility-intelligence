"""Demand & Surveys: demand by hour and day type, and descriptive survey evidence."""
from dataclasses import replace

import pandas as pd
import streamlit as st

import config
from modules.analytics import queries as Q
from modules.llm import ui as llm_ui
from modules.survey import mode_choice as MC
from modules.survey import summaries as SV
from modules.survey import themes as TH
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("demand")
t = L.require_tables(spec)
rs, od, survey = t["route_summary"], t["od_flows"], t["survey_responses"]

# Demand by hour for every day type (corridor and hour filters apply; the selected day type is highlighted)
frames = []
for dt in F.DAY_TYPES:
    o = F.filter_od(od, replace(f, day_type=dt), rs, t["route_stops"], t["stops"])
    g = o.groupby("hour")["passenger_count"].sum().reset_index().rename(columns={"passenger_count": "passengers"})
    frames.append(g.assign(day_type=dt))
by_hour = pd.concat(frames, ignore_index=True)
sel = by_hour[by_hour["day_type"] == f.day_type]
total = float(sel["passengers"].sum())
if len(sel) and total > 0:
    peak = sel.sort_values(["passengers", "hour"], ascending=[False, True]).iloc[0]
    peak_hour, peak_pax = int(peak["hour"]), float(peak["passengers"])
else:
    peak_hour, peak_pax = None, 0.0

meta = SV.survey_meta(survey)
intent = SV.stated_switch_intent(survey)
reasons = SV.private_use_reasons(survey)
conds = SV.switch_conditions(survey)

L.kpi_row([
    {"label": f"Boardings per average {f.day_type}", "value": fmt.number(total),
     "help": "Passengers boarding in the selected corridor and hours, per average service day of the selected day type (od_flows)."},
    {"label": "Peak boarding hour", "value": fmt.hhmm(peak_hour) if peak_hour is not None else fmt.NA,
     "help": "Clock hour with the most boardings for the selected day type, corridor and hours."},
    {"label": "Survey responses", "value": fmt.number(meta["n"]),
     "help": "Synthetic survey responses (not a real sample). The survey is not filtered by corridor or day type."},
    {"label": "Private-vehicle users who would switch", "value": fmt.pct(intent["share_pct"], 0),
     "help": f"Share of the {intent['n_private']} car and two-wheeler respondents whose recorded switch intent is yes (descriptive, synthetic)."},
])

st.subheader("Passenger demand by hour")
L.show_chart(charts.demand_by_hour(by_hour, f.day_type), key="dm_hour")
L.note("Boardings per average service day by clock hour of boarding. The selected day type is drawn thicker; other day types are shown for comparison.")

st.subheader("Survey evidence: what respondents said (descriptive)")
if meta["n"] == 0:
    L.empty_state("No survey responses", "The survey table is empty.")
else:
    tab_a, tab_b, tab_c, tab_d, tab_e = st.tabs(["Trip purpose and mode", "Why people use a private vehicle", "What would make them switch",
                                                 "By mode, purpose and income", "Open-text check"])
    with tab_a:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Trip purpose**")
            L.show_chart(charts.share_bars(SV.purpose_summary(survey), xtitle="Share of all respondents (%)"), key="sv_purpose")
        with c2:
            st.markdown("**Current mode**")
            L.show_chart(charts.share_bars(SV.mode_summary(survey), colour=charts.ACCENT_MID, xtitle="Share of all respondents (%)"), key="sv_mode")
    with tab_b:
        L.show_chart(charts.share_bars(reasons.head(10), xtitle=f"Share of the {meta['n_private']} private-vehicle users (%)"), key="sv_reasons")
        L.note("Respondents can name several reasons, so shares add up to more than 100%.")
    with tab_c:
        L.show_chart(charts.share_bars(conds.head(10), colour=charts.GREY, xtitle=f"Share of the {meta['n_private']} private-vehicle users (%)"), key="sv_conds")
        ip = SV.intent_by_purpose(survey)
        if len(ip):
            st.markdown("**Stated willingness to switch, by trip purpose** (private-vehicle users)")
            show = ip[["label", "respondents", "share_pct"]].rename(columns={"label": "Trip purpose", "respondents": "Respondents", "share_pct": "Would switch (%)"})
            st.dataframe(show, hide_index=True, width="stretch",
                         column_config={"Would switch (%)": st.column_config.NumberColumn(format="%.0f%%")})
    with tab_d:
        what = st.radio("Show", ["Switch conditions", "Reasons for using a private vehicle", "Trip purpose by current mode"], horizontal=True, key="sv_xtab_what")
        by = st.radio("Split by", list(SV.GROUP_COLUMNS), format_func=SV.GROUP_COLUMNS.get, horizontal=True, key="sv_xtab_by",
                      disabled=(what == "Trip purpose by current mode"))
        if what == "Trip purpose by current mode":
            xt = SV.mode_by_purpose(survey)
            note = "Each column is 100% of that mode's respondents. Columns with few respondents (see n) are unstable."
        else:
            col = "switch_conditions" if what == "Switch conditions" else "reasons"
            xt = SV.multi_select_by_group(survey, col, by)
            note = ("Share of car and two-wheeler respondents in each group naming the item (top 8; groups under 10 respondents are left out). "
                    "Group sizes: " + ", ".join(f"{SV.label(g)} {n}" for g, n in SV.group_sizes(SV.private_mode_users(survey), by).items()) + ".")
        L.show_chart(charts.share_heatmap(xt), key="sv_xtab")
        L.note(note + " Descriptive shares of the synthetic sample.")
    with tab_e:
        ag = TH.open_text_agreement(survey)
        st.markdown("The structured answers (reasons, switch conditions) were also re-derived from each respondent's free-text answer by a deterministic keyword tagger.")
        st.dataframe(pd.DataFrame([
            ("Stated switch condition is among the recorded conditions", fmt.pct(ag["condition_precision"] * 100, 1), ag["n_condition_texts"]),
            ("Stated switch condition equals the first recorded condition", fmt.pct(ag["condition_first_match"] * 100, 1), ag["n_condition_texts"]),
            ("Texts saying 'not likely to switch' have no recorded condition", fmt.pct(ag["no_condition_agreement"] * 100, 1), None),
            ("Stated reason is among the recorded reasons", fmt.pct(ag["reason_precision"] * 100, 1), ag["n_reason_texts"]),
        ], columns=["Check", "Agreement", "Texts checked"]).astype({"Texts checked": "Int64"}), hide_index=True, width="stretch")
        L.note("The texts are template sentences and the keyword list was written for them, so high agreement shows the tagger works on this synthetic vocabulary, not on real free text.")

L.what_this_means(N.demand_meaning(peak_hour, peak_pax, (peak_pax / total * 100) if total else 0.0, intent,
                                   reasons["label"].iloc[0] if len(reasons) else None, conds["label"].iloc[0] if len(conds) else None))

# ---------------------------------------------------------------- illustrative model (visually separate from the descriptive findings above)
st.divider()
st.subheader("Switching probability: illustrative model")
st.warning("Model-based, not descriptive. " + MC.ILLUSTRATIVE_LABEL.capitalize() + ". The model is fitted to a synthetic survey whose answers were generated by a "
           "known formula, so it can only recover that formula.")
model_out = (D.try_load(MC.TABLE_COEF, "processed"), D.try_load(MC.TABLE_METRICS, "processed"))
if model_out[0] is None or model_out[1] is None:
    msg = "Model outputs have not been generated yet."
    if not MC.sklearn_available():
        msg += " " + MC.UNAVAILABLE_MESSAGE
    L.empty_state("Switch-intent model not available", msg, "python -m modules.survey.mode_choice")
else:
    coef, mets = model_out
    mt = mets.set_index("metric")
    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("**Fitted vs true coefficients** (log-odds of switching; true = the synthetic generator's formula)")
            L.show_chart(charts.coefficient_chart(coef), key="sv_coef")
        with c2:
            st.markdown("**Held-out test performance**")
            st.dataframe(pd.DataFrame({
                "Metric": ["Accuracy", "ROC-AUC", "Brier score (lower is better)"],
                "Model": [fmt.pct(mt.loc["accuracy", "model"] * 100, 1), f"{mt.loc['roc_auc', 'model']:.3f}", f"{mt.loc['brier_score', 'model']:.3f}"],
                "Naive baseline": [fmt.pct(mt.loc["accuracy", "baseline"] * 100, 1), f"{mt.loc['roc_auc', 'baseline']:.3f}", f"{mt.loc['brier_score', 'baseline']:.3f}"],
                "Beats baseline": ["yes" if mt.loc[m, "beats_baseline"] else "no" for m in ("accuracy", "roc_auc", "brier_score")]}),
                hide_index=True, width="stretch")
            L.note(f"Stratified {int(mets['n_train'].iloc[0])} train / {int(mets['n_test'].iloc[0])} test split (seed {config.SEED}). Baseline = always predict the "
                   "majority class (accuracy) or the training base rate (Brier); chance AUC is 0.5. Gains are modest: the labels are noisy by design.")
        st.markdown("**Scenario: what if these conditions were met?**")
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            mode = st.selectbox("Current mode", ["car", "two_wheeler"], format_func=SV.label, key="sv_p_mode")
        with sc2:
            purpose = st.selectbox("Trip purpose", ["work", "education", "shopping", "health", "leisure", "other"], format_func=SV.label, key="sv_p_purpose")
        with sc3:
            income = st.selectbox("Income band", list(SV.INCOME_ORDER), index=2, format_func=SV.label, key="sv_p_income")
        met = st.multiselect("Conditions met", list(MC.C.SWITCH_CONDITIONS), default=["reliability", "ac_comfort"], format_func=SV.label, key="sv_p_conds")
        scn = MC.scenario_table(coef, mode=mode, purpose=purpose, income_band=income, met=met)
        st.dataframe(pd.DataFrame({
            "Scenario": scn["scenario"],
            "Conditions": scn["conditions"].map(lambda c: ", ".join(SV.label(x) for x in c) or "no condition"),
            "Model switching probability": scn["model_probability"].map(lambda p: fmt.pct(p * 100, 0)),
            "True generator probability": scn["true_generator_probability"].map(lambda p: fmt.pct(p * 100, 0))}), hide_index=True, width="stretch")
        st.markdown(N.survey_model_note(scn, mets, f"a {SV.label(mode).lower()} user travelling for {SV.label(purpose).lower()} ({SV.label(income).lower()})"))
        L.note("Illustrative, conditional on the synthetic training setup. Not a forecast of real behaviour or of GSRTC ridership.")

# M7 (optional): machine-generated theme summary of the open-text answers; button-triggered, cached, hidden behind a note without an LLM key.
llm_ui.theme_summary_panel(survey["open_text"].dropna().astype(str).tolist() if meta["n"] else [])

prov = D.provenance("survey_responses", "synthetic") or {}
L.evidence_expander(
    sources=["od_flows (boardings by hour and day type, scoped by route)", "survey_responses (synthetic survey)",
             "survey_model_coefficients and survey_model_metrics (model output, optional; needs scikit-learn to regenerate)"],
    formulas=["Boardings = sum of passengers per average service day over zone pairs, by boarding hour.",
              "Survey shares = respondents naming an item / respondents in the group (items are not mutually exclusive).",
              "Private-vehicle users = respondents whose current mode is car or two-wheeler (descriptive views); the model also includes shared-taxi and other private modes, "
              "the respondents for whom switch intent is defined.",
              "Switching probability = 1 / (1 + exp(-(intercept + sum of coefficient x feature))) from the fitted logistic regression."],
    assumptions=[f"Survey: {meta['n']} synthetic responses, {meta['first']} to {meta['last']} (source type: {', '.join(meta['source_types']) or 'unknown'}; "
                 f"seed {prov.get('seed', 'unknown')}; generated {str(prov.get('generated_at', 'unknown'))[:19]}).",
                 "Survey responses are simulated and not weighted to any real population; shares describe this synthetic sample only.",
                 "Switching model: logistic regression (scikit-learn, effectively unregularised) of switch intent on the nine switch conditions, car use, work trip and high "
                 "income, fitted to car, two-wheeler, shared-taxi and other-private respondents; stratified train/test split, seed 42. It is compared with the generator's true "
                 "coefficients, which exist only because the data are synthetic. Probabilities are illustrative and conditional on this synthetic setup.",
                 "Switch intent is a recorded yes/no in the synthetic data, not a measured behaviour change.",
                 "Passenger demand comes from simulated tickets, so it excludes people who could not board (ticketed demand is censored at capacity)."],
    filters=f.describe() + ". Survey views are not filtered.")
