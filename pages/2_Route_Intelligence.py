"""Route Intelligence: ranked routes with a transparent score, and a drill-down for one route."""
import pandas as pd
import streamlit as st

import config
from modules.analytics import queries as Q
from modules.data_gen import constants as C
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("routes")
t = L.require_tables(spec)
rs, scores, kpis, so, hourly = t["route_summary"], t["route_scores"], t["route_kpis"], t["stop_occupancy"], t["hourly_demand_supply"]

scope = F.scope_routes(rs, f.corridor)
types = [rt for rt in ("local", "intercity") if rt in set(scope["route_type"])]
if not types:
    L.empty_state("No routes in this scope", "The selected corridor has no routes in the generated data. Choose another corridor in the sidebar.")
    st.stop()

# Selected route persists across pages under 'sel_route'; the type switch follows it on first display.
sel = st.session_state.get("sel_route")
if st.session_state.get("ri_type") not in types:
    sel_type = rs.loc[rs["route_id"] == sel, "route_type"]
    st.session_state["ri_type"] = sel_type.iloc[0] if len(sel_type) and sel_type.iloc[0] in types else types[0]

st.subheader("Route ranking")
route_type = st.radio("Route type", types, key="ri_type", horizontal=True,
                      format_func=lambda x: {"local": "Local routes (Rajkot city)", "intercity": "Intercity routes"}[x],
                      help="Scores are normalised within a route type, so local and intercity routes are ranked separately.")
ranked = Q.ranked_scores(scores, rs, route_type, F.route_ids(rs, f.corridor))
n_in_type = int((rs["route_type"] == route_type).sum())
weights = Q.score_weights(scores)
labels = {r: Q.chart_label(r, n) for r, n in zip(rs["route_id"], rs["name"])}

order = ranked.sort_values("total_score", ascending=False)["route_id"].tolist()
L.show_chart(charts.score_stack(Q.weighted_components(ranked, weights), order, labels), key="ri_stack")
L.note("Each bar is the route's potential score (0-100). Segment length = component score x weight, so the bar shows what drives the rank. "
       "This is a rule-based index, not an AI prediction.")

col_names = {Q.COMPONENT_COLUMNS[c]: f"{Q.COMPONENT_LABELS[c]} ({weights[c] * 100:.0f}%)" for c in Q.COMPONENT_COLUMNS}
table = ranked.assign(Route=ranked["route_id"], Name=ranked["name"].map(lambda n: n),
                      Protection=ranked["protected_minimum_service"].map({True: "Minimum service (protected)", False: ""}))
table = table.rename(columns={"rank_within_type": f"Rank in {route_type}", "total_score": "Total score (0-100)", **col_names})
show_cols = [f"Rank in {route_type}", "Route", "Name", "Total score (0-100)", *col_names.values(), "Protection"]
st.dataframe(table[show_cols], hide_index=True, width="stretch",
             column_config={"Total score (0-100)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                            f"Rank in {route_type}": st.column_config.NumberColumn(format="%d"),
                            **{v: st.column_config.NumberColumn(format="%.0f") for v in col_names.values()}})
if ranked["protected_minimum_service"].any():
    L.note("Minimum-service routes are protected: a low commercial score never makes a route a removal candidate; the recommendation is to retain and review the timetable.")

# ---- Route detail
st.subheader("Route detail")
opts = ranked["route_id"].tolist()
cur = st.session_state.get("sel_route")
st.session_state["w_route"] = cur if cur in opts else opts[0]
route_id = st.selectbox("Select a route", opts, key="w_route", format_func=lambda r: Q.route_label(r, dict(zip(rs["route_id"], rs["name"]))[r]),
                        on_change=lambda: st.session_state.__setitem__("sel_route", st.session_state["w_route"]))
st.session_state["sel_route"] = route_id
p = Q.route_profile(rs, route_id)
srow = ranked[ranked["route_id"] == route_id].iloc[0]

if p["minimum_service"]:
    st.info("Protected minimum-service route: it serves an essential social need, so a low load factor or negative contribution is not a reason to withdraw it.")

L.kpi_row([
    {"label": "Load factor", "value": fmt.pct(p["load_factor_pct"]), "help": "Passenger-km / seat-km over all 42 days (route_summary)."},
    {"label": "Earnings per vehicle-km (EPKM)", "value": fmt.inr(p["epkm_inr"], 1) + " / km",
     "help": "Ticket revenue per vehicle-km. Excludes subsidy, advertising and other income."},
    {"label": "On-time departures", "value": fmt.pct(p["reliability_pct"]),
     "help": "Share of trips departing between 1 minute early and 5 minutes late."},
    {"label": "Revenue per passenger", "value": fmt.inr(p["revenue_per_passenger_inr"], 1), "help": "Ticket revenue divided by passengers carried."},
])
st.caption(f"{p['name']} | {fmt.km(p['length_km'])} | {p['bus_type'].replace('_', ' ')} | Average boardings per day: {fmt.number(p['avg_boardings_per_day'])} | "
           f"Contribution per day (not profit): {fmt.inr(p['contribution_per_day_inr'])} | Busiest hour: {p['peak_hour_window']}")
L.note("Observed synthetic demand derived from simulated tickets; no forecasting model is used on this page. All 42 days; day type and hours filters apply to the stop and hourly views.")

direction = st.radio("Direction", ["outbound", "inbound"], horizontal=True, key="ri_dir",
                     help="Outbound follows the stop order of the route definition; inbound is the reverse.")
tab_a, tab_b, tab_c = st.tabs(["Daily ridership", "Load along the route", "Hourly profile"])
with tab_a:
    L.show_chart(charts.daily_trend(kpis[kpis["route_id"] == route_id]), key="ri_trend")
    L.note("Passengers per service day, coloured by day type (weekday, weekend, festival).")
with tab_b:
    so_f = F.filter_stop_occupancy(so, f, rs)
    so_r = so_f[(so_f["route_id"] == route_id) & (so_f["direction"] == direction)]
    hrs = sorted(int(x) for x in so_r["hour"].dropna().unique())
    pick = st.selectbox("Departure hour", ["All hours in the filter window", *[fmt.hhmm(h) for h in hrs]], key="ri_hour") if hrs else None
    hour = None if pick in (None, "All hours in the filter window") else int(pick[:2])
    prog = Q.occupancy_progression(so_f, route_id, direction, hour)
    crush = C.LOCAL_CRUSH_FACTOR if p["route_type"] == "local" else None
    if prog.empty:
        L.empty_state("No trips in this window", f"{route_id} has no {direction} departures on a {f.day_type} in {f.hours_label}. Widen the hour or day-type filter.")
    else:
        L.show_chart(charts.occupancy_chart(prog, D.stop_names(), crush), key="ri_occ")
        L.note("Average passengers on board after each stop for the selected departures, against seats"
               + (" and the crush load (standing allowed on local buses)." if crush else " (intercity buses carry seated passengers only)."))
with tab_c:
    hr = Q.route_rows(F.filter_hourly(hourly, f, rs))
    hr = hr[(hr["route_id"] == route_id) & (hr["direction"] == direction)]
    prof = hr.rename(columns={"demand_estimate": "demand", "seats_offered": "seats"})[["hour", "demand", "seats", "status"]]
    L.show_chart(charts.route_hourly_profile(prof), key="ri_hourly")
    L.note("Estimated demand is the critical-link load of ticketed passengers (a lower bound where buses are full). X marks hours inside the service span with no scheduled departure.")
# M4 extension point: route map and candidate-route inspection attach here (after the tabs), reading route_paths / route_candidates.

L.what_this_means(N.route_meaning(p, int(srow["rank_within_type"]), n_in_type, route_type, float(srow["total_score"])))
w_lines = [f"{Q.COMPONENT_LABELS[c]}: weight {weights[c] * 100:.0f}%" for c in Q.COMPONENT_COLUMNS]
L.evidence_expander(
    sources=["route_summary (KPIs: single source of truth)", "route_scores (components, weights, explanation)", "route_kpis (daily trend)",
             "stop_occupancy (load along the route)", "hourly_demand_supply (hourly profile)"],
    formulas=["Total score = sum of weight x component score (each component min-max normalised to 0-100 within route type).",
              "Weights (" + str(srow["weight_version"]) + "): " + "; ".join(w_lines) + ".",
              "Load factor = passenger-km / seat-km; EPKM = ticket revenue / vehicle-km; contribution = revenue - operating cost.",
              f"Why this route scores {fmt.number(srow['total_score'], 1)}: {srow['explanation']}"],
    assumptions=["Weights are demonstration values, not validated policy.",
                 f"Social importance is rule-based and gives minimum-service routes the maximum; {int(ranked['protected_minimum_service'].sum())} route(s) here are protected.",
                 "Feasibility is a proxy, not an engineering assessment.",
                 config.SIMULATION_BADGE_TEXT + ": routes are demonstration routes with synthetic tickets, not real GSRTC or RMTS routes."],
    filters=f.describe() + ". The ranking and KPIs cover all 42 days; the stop and hourly views use the day type and hours.")
