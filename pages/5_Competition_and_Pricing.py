"""Competition & Pricing: departure slots, fares by bus type, and a fare what-if."""
import math

import pandas as pd
import streamlit as st

import config
from modules.analytics import scenarios as SC
from modules.competition import analysis as CA
from modules.ui import charts, fmt, narrative as N
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("competition", show_filters=("corridor", "day_type"))
t = L.require_tables(spec)
rs, kpis, routes, trips, comp = t["route_summary"], t["route_kpis"], t["routes"], t["trips"], t["competitor_services"]

corridor = f.corridor if f.corridor in config.INTERCITY_CORRIDORS else config.PRIMARY_CORRIDOR
if corridor != f.corridor:
    st.info(f"Competition is analysed on intercity corridors, where synthetic private operators exist. Showing {corridor}; choose another corridor in the sidebar.")
day_type = f.day_type

slots = CA.slot_comparison(trips, comp, routes, corridor, day_type)
fares = CA.fare_comparison(comp, routes, corridor, day_type)
gap_hours = [int(x) for x in slots.loc[slots["state_gap"], "hour"]]
private_in_gap = float(slots.loc[slots["state_gap"], "private_departures"].sum())

both = fares.dropna(subset=["fare_index"])
fare_row = None
if len(both):
    pref = both[both["bus_type"] == "AC_seater"]
    fare_row = (pref if len(pref) else both).iloc[0]

if slots.empty and fares.empty:
    L.empty_state("No service data for this corridor", f"No state trips or private services were found for {corridor} on a {day_type}.")
    st.stop()

L.kpi_row([
    {"label": "State departures per day", "value": fmt.number(slots["state_departures"].sum(), 1),
     "help": f"Average outbound GSRTC (demo) departures from Rajkot on {corridor} for a {day_type}."},
    {"label": "Private departures per day", "value": fmt.number(slots["private_departures"].sum()),
     "help": "Synthetic private-operator departures from Rajkot on the same corridor and day type."},
    {"label": "Hours with private but no state departure", "value": fmt.number(len(gap_hours)),
     "help": "Clock hours in which a private operator departs and the state timetable has none."},
    {"label": f"State fare vs private ({str(fare_row['bus_type']).replace('_', ' ')})" if fare_row is not None else "State fare vs private",
     "value": fmt.ratio_pct(fare_row["fare_index"]) if fare_row is not None else fmt.NA,
     "help": "Illustrative state full-route fare divided by the median private base fare for the same bus type."},
])

st.subheader("Departure slots: state vs private")
L.show_chart(charts.slot_chart(slots, corridor, day_type), key="cp_slots")
L.note("Departures from the Rajkot terminal per average day, by clock hour. Orange shading marks hours where private operators depart and the state timetable does not.")

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

# ---- Pricing what-if
st.subheader("Fare what-if")
ids = CA.corridor_route_ids(routes, corridor)
labels = {r: f"{r} {rs.loc[rs['route_id'] == r, 'name'].iloc[0]}" for r in ids}
default_rid = next((r for r in ids if rs.loc[rs["route_id"] == r, "bus_type"].iloc[0] == "AC_seater"), ids[0])
rid = st.selectbox("State service", ids, index=ids.index(default_rid), format_func=labels.get, key=f"cp_route_{corridor}")
rrow = rs[rs["route_id"] == rid].iloc[0]
res = sens = None
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
            ("Contribution per day (not profit)", f"{fmt.inr(res['baseline_contribution_inr'])} → {fmt.inr(res['contribution_inr'])}"),
            ("Demand turned away by the seat cap", fmt.number(res["spilled_demand"], 1)),
        ], columns=["Outcome", "Baseline → scenario"])
        st.dataframe(out, hide_index=True, width="stretch")
        st.markdown("**Sensitivity to the elasticity assumption**")
        L.show_chart(charts.sensitivity_chart(sens), key="cp_sens")
        sdisp = sens.assign(**{"Elasticity": sens["elasticity"].map(lambda e: f"{e:+.1f}"), "Revenue change per day": sens["revenue_change_inr"].map(fmt.inr),
                               "Occupancy": sens["occupancy"].map(fmt.ratio_pct), "Contribution per day": sens["contribution_inr"].map(fmt.inr)})
        st.dataframe(sdisp[["Elasticity", "Revenue change per day", "Occupancy", "Contribution per day"]], hide_index=True, width="stretch")
        L.note("Illustrative pricing scenario: " + SC.PRICING_LABEL + ".")

L.what_this_means(N.competition_meaning(corridor, day_type, gap_hours, private_in_gap, fare_row, res))
L.evidence_expander(
    sources=["trips (state outbound departures)", "competitor_services (synthetic private departures and fares)", "routes (corridor, length, bus type)",
             "route_kpis (day-type baseline for the what-if)", "route_summary (route names)"],
    formulas=["Departures per day = trips (or services) of the day type in each clock hour / number of dates of that day type.",
              "State fare = illustrative full-route fare from the demo tariff for the bus type and route length.",
              "Demand after = baseline demand x (new fare / baseline fare) ^ elasticity, capped at seats offered; revenue = served x new fare.",
              "Baseline demand = passenger-km / route km (full-journey equivalents); occupancy = served / seats offered, which equals the route load factor at the baseline.",
              "Contribution = ticket revenue - operating cost (not profit)."],
    assumptions=[f"Elasticity defaults to {config.PRICING_ELASTICITY_DEFAULT} and is an assumption; sensitivity runs {', '.join(str(e) for e in config.PRICING_ELASTICITY_SENSITIVITY)}.",
                 "Competitor services, operators and fares are synthetic; they are not verified competitor data.",
                 "The state tariff is an illustrative demo tariff, not an actual GSRTC fare.",
                 "The what-if keeps seats and operating cost fixed and ignores competitor reactions and cross-route effects.",
                 config.SIMULATION_BADGE_TEXT + "."],
    filters=f"Corridor: {corridor} | Day type: {day_type}")
