"""Demand & Surveys: demand by hour and day type, and descriptive survey evidence."""
from dataclasses import replace

import pandas as pd
import streamlit as st

from modules.analytics import queries as Q
from modules.survey import summaries as SV
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
if f.corridor not in (F.ALL, F.LOCAL):
    L.note(F.OD_CORRIDOR_NOTE)
L.note("Boardings per average service day by clock hour of boarding. The selected day type is drawn thicker; other day types are shown for comparison.")

st.subheader("Survey evidence")
if meta["n"] == 0:
    L.empty_state("No survey responses", "The survey table is empty.")
else:
    tab_a, tab_b, tab_c = st.tabs(["Trip purpose and mode", "Why people use a private vehicle", "What would make them switch"])
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

L.what_this_means(N.demand_meaning(peak_hour, peak_pax, (peak_pax / total * 100) if total else 0.0, intent,
                                   reasons["label"].iloc[0] if len(reasons) else None, conds["label"].iloc[0] if len(conds) else None))

prov = D.provenance("survey_responses", "synthetic") or {}
L.evidence_expander(
    sources=["od_flows (boardings by hour and day type)", "survey_responses (synthetic survey)", "route_stops and stops (corridor scope for O-D rows)"],
    formulas=["Boardings = sum of passengers per average service day over zone pairs, by boarding hour.",
              "Survey shares = respondents naming an item / respondents in the group (items are not mutually exclusive).",
              "Private-vehicle users = respondents whose current mode is car or two-wheeler."],
    assumptions=[f"Survey: {meta['n']} synthetic responses, {meta['first']} to {meta['last']} (source type: {', '.join(meta['source_types']) or 'unknown'}; "
                 f"seed {prov.get('seed', 'unknown')}; generated {str(prov.get('generated_at', 'unknown'))[:19]}).",
                 "Survey responses are simulated and not weighted to any real population; shares describe this synthetic sample only.",
                 "Switch intent is a recorded yes/no in the synthetic data, not a measured behaviour change.",
                 "Passenger demand comes from simulated tickets, so it excludes people who could not board (ticketed demand is censored at capacity)."],
    filters=f.describe() + ". Survey views are not filtered.")
