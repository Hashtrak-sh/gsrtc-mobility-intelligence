"""Competition & Pricing: departure slots and competitive gap score, fares (normal vs surge), review themes, and a fare what-if."""
import math

import pandas as pd
import streamlit as st

import config
from modules.analytics import scenarios as SC
from modules.competition import analysis as CA
from modules.competition import gap_score as CG
from modules.survey import themes as TH
from modules.ui import charts, fmt, narrative as N
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("competition", show_filters=("corridor", "day_type"))
t = L.require_tables(spec)
rs, kpis, routes, trips, comp = t["route_summary"], t["route_kpis"], t["routes"], t["trips"], t["competitor_services"]
cga, reviews = t["competition_analysis"], t["reviews"]

corridor = f.corridor if f.corridor in config.INTERCITY_CORRIDORS else config.PRIMARY_CORRIDOR
if corridor != f.corridor:
    st.info(f"Competition is analysed on intercity corridors, where synthetic private operators exist. Showing {corridor}; choose another corridor in the sidebar.")
day_type = f.day_type

slots = CA.slot_comparison(trips, comp, routes, corridor, day_type)
fares = CA.fare_comparison(comp, routes, corridor, day_type)
cg_rows = cga[(cga["route_pair"] == corridor) & (cga["day_type"] == day_type)]
gap_hours = [int(x) for x in slots.loc[slots["state_gap"], "hour"]]
private_in_gap = float(slots.loc[slots["state_gap"], "private_departures"].sum())
top_gap = CG.top_gap_slots(cga, corridor, day_type, top=1)
top_gap_row = top_gap.iloc[0] if len(top_gap) else None

both = fares.dropna(subset=["fare_index"])
fare_row = None
if len(both):
    pref = both[both["bus_type"] == "AC_seater"]
    fare_row = (pref if len(pref) else both).iloc[0]

if slots.empty and fares.empty:
    L.empty_state("No service data for this corridor", f"No state trips or private services were found for {corridor} on a {day_type}.")
    st.stop()

L.kpi_row([
    {"label": "Private departures per day", "value": fmt.number(slots["private_departures"].sum()),
     "help": "Synthetic private-operator departures from Rajkot on the same corridor and day type (the opposite direction is assumed to mirror them)."},
    {"label": "Hours with private but no state departure", "value": fmt.number(len(gap_hours)),
     "help": "Clock hours in which a private operator departs and the state timetable has none."},
    {"label": "Highest competitive gap score",
     "value": f"{top_gap_row['competitive_gap_score']:.0f} / 100" if top_gap_row is not None else fmt.NA,
     "help": (f"Peak slot {fmt.hhmm(top_gap_row['hour'])}. " if top_gap_row is not None else "") +
             f"Weighted index of five visible components (weights {config.COMPETITIVE_GAP_WEIGHTS.weight_version}); not a forecast."},
    {"label": f"State fare vs private ({str(fare_row['bus_type']).replace('_', ' ')})" if fare_row is not None else "State fare vs private",
     "value": fmt.ratio_pct(fare_row["fare_index"]) if fare_row is not None else fmt.NA,
     "help": "Illustrative state full-route fare divided by the median private base fare for the same bus type."},
])

tab_slots, tab_fares, tab_reviews, tab_price = st.tabs(["Departure slots and gap score", "Fares and fare index", "Review themes", "Fare what-if"])

# ---------------------------------------------------------------- slots + gap score
with tab_slots:
    st.subheader("Departure slots: state vs private")
    L.show_chart(charts.slot_chart(slots, corridor, day_type), key="cp_slots")
    L.note("Departures from the Rajkot terminal per average day, by clock hour. Orange shading marks hours where private operators depart and the state timetable does not. "
           "Competitor departure times are from Rajkot only; the opposite direction is assumed to mirror them.")
    st.markdown("**Competitive gap score by hour** (0-100; bar height = score, segments = weighted components)")
    w = config.COMPETITIVE_GAP_WEIGHTS.components()
    L.show_chart(charts.gap_score_chart(cg_rows[cg_rows["private_departures"] > 0], w, CG.COMPONENT_LABELS, CG.COMPONENT_COLUMNS), key="cp_gapscore")
    L.note(f"Weights ({config.COMPETITIVE_GAP_WEIGHTS.weight_version}, demo values, not validated policy): "
           + "; ".join(f"{CG.COMPONENT_LABELS[k].lower()} {v:.0%}" for k, v in w.items())
           + ". Hours without any private departure score 0. A component that cannot be computed (for example the fare component when the state has no "
             "like-for-like bus type) is left out and the remaining weights are rescaled.")
    top5 = CG.top_gap_slots(cga, day_type=day_type, top=5)
    if len(top5):
        st.markdown(f"**Five highest competitive gap scores across all corridors ({day_type})**")
        st.dataframe(pd.DataFrame({
            "Corridor": top5["route_pair"], "Departure hour": top5["hour"].map(fmt.hhmm), "Score": top5["competitive_gap_score"].round(0).astype(int),
            "State departures": top5["state_departures"].round(1), "Private departures": top5["private_departures"].astype(int),
            "Premium services with no state equivalent": top5["premium_bus_gap"].astype(int)}), hide_index=True, width="stretch")

# ---------------------------------------------------------------- fares + fare index
with tab_fares:
    st.subheader("Fares and bus types")
    L.show_chart(charts.fare_chart(fares), key="cp_fares")
    if len(fares):
        tbl = pd.DataFrame({
            "Bus type": fares["bus_type"].str.replace("_", " "),
            "State fare (illustrative)": fares["state_fare_inr"].map(lambda v: fmt.inr(v)),
            "Private services": fares["private_services"].fillna(0).astype(int),
            "Private base fare (median)": fares["private_base_fare_inr"].map(lambda v: fmt.inr(v)),
            f"Private fare on a {day_type} (median)": fares["private_surge_fare_inr"].map(lambda v: fmt.inr(v)),
            "State / private base": fares["fare_index"].map(lambda v: fmt.ratio_pct(v)),
        })
        st.dataframe(tbl, hide_index=True, width="stretch")
        L.note("n/a means the bus type exists on only one side (for example state express has no private equivalent).")
    st.markdown("**Fare index by hour: normal vs illustrative surge**")
    view = CG.fare_index_view(cga, corridor, day_type)
    L.show_chart(charts.fare_index_chart(view), key="cp_fareindex")
    L.note("Fare index = state tariff for the same bus class / median private fare in that clock hour. Normal uses the private base fare; surge uses the illustrative "
           "private peak fare of the day type while the state tariff stays fixed. Below 1.0 the state is cheaper. Hours where the state runs no like-for-like bus class are left out.")

# ---------------------------------------------------------------- review themes
with tab_reviews:
    st.subheader("Review themes: state vs private")
    method = st.radio("Theme method", [TH.METHOD_GENERATOR, TH.METHOD_KEYWORD], format_func=TH.METHOD_LABELS.get, horizontal=True, key="cp_theme_method",
                      help="Both methods are deterministic. 'Tagged when generated' reads the stored tags; the keyword tagger re-derives themes from the review text.")
    tc = TH.theme_comparison(reviews, method, corridor)
    n_state, n_private = int(tc["state_n_reviews"].iloc[0]), int(tc["private_n_reviews"].iloc[0])
    if n_state == 0 or n_private == 0:
        L.empty_state("Not enough reviews", f"{corridor} has {n_state} state and {n_private} private synthetic reviews; a comparison needs both.")
    else:
        L.show_chart(charts.theme_negative_chart(tc), key="cp_themes")
        L.note(f"Share of reviews that mention the theme negatively, {corridor}: {n_state} state and {n_private} private synthetic reviews. "
               f"Method: {TH.METHOD_LABELS[method].lower()}.")
        agree = TH.agreement_report(reviews)
        with st.expander("How reliable is the keyword tagger?"):
            st.markdown(
                f"On all {agree['n_reviews']} synthetic reviews the keyword tagger ({TH.TAGGER_VERSION}) reproduces the stored tags exactly for "
                f"{fmt.pct(agree['exact_match_share'] * 100, 1)} of reviews (theme precision {fmt.pct(agree['theme_precision'] * 100, 1)}, recall "
                f"{fmt.pct(agree['theme_recall'] * 100, 1)}, polarity accuracy {fmt.pct(agree['polarity_accuracy'] * 100, 1)}). "
                "The review texts are assembled from template sentences and the keyword list was written for that vocabulary, so this high agreement shows the tagger "
                "works on the synthetic texts, not that it would work on real reviews.")
            per = pd.DataFrame(agree["per_theme"])
            st.dataframe(pd.DataFrame({"Theme": per["theme"].map(TH.THEME_LABELS), "Precision": per["precision"].map(lambda v: fmt.pct(v * 100, 0)),
                                       "Recall": per["recall"].map(lambda v: fmt.pct(v * 100, 0)), "Reviews matched": per["tp"]}),
                         hide_index=True, width="stretch")

# ---------------------------------------------------------------- pricing what-if
res = sens = None
with tab_price:
    st.subheader("Fare what-if")
    ids = CA.corridor_route_ids(routes, corridor)
    labels = {r: f"{r} {rs.loc[rs['route_id'] == r, 'name'].iloc[0]}" for r in ids}
    default_rid = next((r for r in ids if rs.loc[rs["route_id"] == r, "bus_type"].iloc[0] == "AC_seater"), ids[0])
    rid = st.selectbox("State service", ids, index=ids.index(default_rid), format_func=labels.get, key=f"cp_route_{corridor}")
    rrow = rs[rs["route_id"] == rid].iloc[0]
    try:
        base = CA.pricing_baseline(kpis, rrow, day_type)
    except ValueError as exc:
        L.empty_state("Nothing to price", str(exc))
        base = None
    if base is not None:
        lo = base["baseline_fare"] * config.PRICING_FARE_BOUNDS_FACTOR[0]
        hi = base["baseline_fare"] * config.PRICING_FARE_BOUNDS_FACTOR[1]
        lo_i, hi_i = math.ceil(lo), math.floor(hi)
        default_fare = min(max(round(base["baseline_fare"]), lo_i), hi_i)
        st.caption(f"Baseline from {corridor} {rid}, average {day_type}: {fmt.number(base['baseline_demand'], 1)} full-journey passengers per day, "
                   f"{fmt.inr(base['baseline_fare'], 1)} average ticket revenue per passenger, {fmt.number(base['seats_offered'])} seats offered, "
                   f"load factor {fmt.pct(base['load_factor_pct'])}.")
        c1, c2 = st.columns(2)
        with c1:
            new_fare = st.slider("New fare per full-journey passenger (₹)", lo_i, hi_i, default_fare, 1, key=f"cp_fare_{rid}_{day_type}",
                                 help=f"Allowed range is {fmt.ratio_pct(config.PRICING_FARE_BOUNDS_FACTOR[0])} to {fmt.ratio_pct(config.PRICING_FARE_BOUNDS_FACTOR[1])} of the baseline fare.")
        with c2:
            lo_e, hi_e = config.PRICING_ELASTICITY_RANGE
            elasticity = st.slider("Assumed price elasticity of demand", float(lo_e), float(hi_e), float(config.PRICING_ELASTICITY_DEFAULT), 0.1,
                                   key=f"cp_elast_{rid}", help="Percentage change in demand for a 1% change in fare. An assumption, not a fitted value; -0.4 means demand is fairly insensitive to price.")
        try:
            res = SC.pricing_scenario(base["baseline_demand"], base["baseline_fare"], float(new_fare), float(elasticity), base["seats_offered"], base["operating_cost"])
            sens = SC.pricing_sensitivity(base["baseline_demand"], base["baseline_fare"], float(new_fare), base["seats_offered"], base["operating_cost"])
        except ValueError as exc:
            L.error_state(f"This fare cannot be evaluated: {exc}")
        if res is not None:
            L.show_chart(charts.pricing_outcomes(res), key="cp_outcomes")
            out = pd.DataFrame([
                ("Baseline fare per full-journey passenger", fmt.inr(base["baseline_fare"], 1)),
                ("New fare", f"{fmt.inr(res['new_fare_inr'], 0)} ({res['fare_change_pct']:+.0f}%)"),
                ("Passengers per day (full-journey equivalents)", f"{fmt.number(base['baseline_demand'], 1)} → {fmt.number(res['served_demand'], 1)}"),
                ("Occupancy (served / seats)", f"{fmt.ratio_pct(res['baseline_occupancy'])} → {fmt.ratio_pct(res['occupancy'])}"),
                ("Ticket revenue per day", f"{fmt.inr(res['baseline_revenue_inr'])} → {fmt.inr(res['revenue_inr'])} ({fmt.inr(res['revenue_change_inr'])})"),
                ("Operating cost per day (included, fixed)", fmt.inr(res["operating_cost_inr"])),
                ("Contribution per day (not profit)", f"{fmt.inr(res['baseline_contribution_inr'])} → {fmt.inr(res['contribution_inr'])}"),
                ("Demand turned away by the seat cap", fmt.number(res["spilled_demand"], 1)),
            ], columns=["Outcome", "Baseline → scenario"])
            st.dataframe(out, hide_index=True, width="stretch")
            L.note("Included cost: the route's operating cost (illustrative cost per vehicle-km x vehicle-km of the day's trips). Not included: depot overheads, staff "
                   "outside the trip cost, depreciation, taxes and subsidy, so contribution is not profit.")
            st.markdown("**Sensitivity to the elasticity assumption**")
            L.show_chart(charts.sensitivity_chart(sens), key="cp_sens")
            sdisp = sens.assign(**{"Elasticity": sens["elasticity"].map(lambda e: f"{e:+.1f}"), "Revenue change per day": sens["revenue_change_inr"].map(fmt.inr),
                                   "Occupancy": sens["occupancy"].map(fmt.ratio_pct), "Contribution per day": sens["contribution_inr"].map(fmt.inr)})
            st.dataframe(sdisp[["Elasticity", "Revenue change per day", "Occupancy", "Contribution per day"]], hide_index=True, width="stretch")
            L.note("Illustrative pricing scenario: " + SC.PRICING_LABEL + ".")

theme_row = None
tcm = TH.theme_comparison(reviews, TH.METHOD_GENERATOR, corridor)
if int(tcm["state_n_reviews"].iloc[0]) and int(tcm["private_n_reviews"].iloc[0]):
    theme_row = tcm.sort_values("deficit", ascending=False).iloc[0]
L.what_this_means(N.competition_meaning(corridor, day_type, gap_hours, private_in_gap, fare_row, res, top_gap_row, theme_row))
L.evidence_expander(
    sources=["trips (state outbound departures)", "competitor_services (synthetic private departures and fares)", "routes (corridor, length, bus type)",
             "competition_analysis (derived: corridor x hour x day type, gap score, fare index)", "reviews (synthetic, tagged themes and review text)",
             "route_kpis (day-type baseline for the what-if)", "route_summary (route names)"],
    formulas=["Departures per day = trips (or services) of the day type in each clock hour / number of dates of that day type.",
              "State fare = illustrative full-route fare from the demo tariff for the bus type and route length. Fare index = state fare / median private fare "
              "(base fare for normal, illustrative peak fare for surge) for the same bus class.",
              "Competitive gap score = 100 x sum(weight x component), components scaled 0-1: departure-slot gap, seat-share gap, premium-bus gap, fare disadvantage "
              "(state fare above private), review-theme deficit (state minus private negative share).",
              "Demand after = baseline demand x (new fare / baseline fare) ^ elasticity, capped at seats offered; revenue = served x new fare.",
              "Baseline demand = passenger-km / route km (full-journey equivalents); occupancy = served / seats offered, which equals the route load factor at the baseline.",
              "Contribution = ticket revenue - operating cost (not profit)."],
    assumptions=[f"Elasticity defaults to {config.PRICING_ELASTICITY_DEFAULT} and is an assumption; sensitivity runs {', '.join(str(e) for e in config.PRICING_ELASTICITY_SENSITIVITY)}.",
                 f"Gap-score weights ({config.COMPETITIVE_GAP_WEIGHTS.weight_version}) are demo values, shown with the score, not validated policy.",
                 "Competitor services, operators, fares and reviews are synthetic; they are not verified competitor data and nothing here is live.",
                 "Competitor departure times are from Rajkot only; the opposite direction is assumed to mirror them and is not modelled separately.",
                 "The state tariff is an illustrative demo tariff, not an actual GSRTC fare; the fare index compares tariffs, not what passengers actually paid.",
                 "Review themes are tagged in the synthetic generation or by a deterministic keyword tagger written for the synthetic review vocabulary.",
                 "The what-if keeps seats and operating cost fixed and ignores competitor reactions and cross-route effects.",
                 config.SIMULATION_BADGE_TEXT + "."],
    filters=f"Corridor: {corridor} | Day type: {day_type}")
