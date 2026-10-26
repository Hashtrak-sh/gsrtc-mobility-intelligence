"""Route Intelligence: ranked routes with a transparent score, and a drill-down for one route."""
import json

import pandas as pd
import streamlit as st

import config
from modules.analytics import queries as Q
from modules.data_gen import constants as C
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L
from modules.routing import maps as RM

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

# ---- M4: route map, candidate routes, recommendations (all read cached tables; nothing is downloaded or recomputed here)
ROUTING_CMD = "python -m modules.routing.run"
rp, cands = D.try_load("route_paths", "processed"), D.try_load("route_candidates", "processed")
recs, rstops, stops_t = D.try_load("recommendations", "processed"), D.try_load("route_stops", "synthetic"), D.try_load("stops", "synthetic")

st.subheader("Route map")
prow = rp[rp["route_id"] == route_id] if rp is not None else None
if prow is None or prow.empty or rstops is None or stops_t is None:
    L.empty_state("Route paths not built yet", "The road paths are produced from the cached OpenStreetMap graphs. Run the command below, then reload.", ROUTING_CMD)
else:
    prow = prow.iloc[0]
    seq = rstops[rstops["route_id"] == route_id].sort_values("stop_seq").merge(stops_t[["stop_id", "name", "lat", "lon"]], on="stop_id", how="left")
    seq_disp = seq if direction == "outbound" else seq.iloc[::-1].reset_index(drop=True)
    seq_disp = seq_disp.assign(seq=range(1, len(seq_disp) + 1))
    is_osm = prow["path_source"] == "openstreetmap"
    coords = json.loads(prow["path_geojson"])["coordinates"]
    st.markdown(f"**Path source: {'real OpenStreetMap roads' if is_osm else 'straight-line fallback (estimate, not road geometry)'}**"
                + ("" if is_osm else f" - reason: {prow['note']}"))
    L.show_chart(RM.route_map([{"name": route_id, "coords": coords, "source": prow["path_source"]}], seq_disp), key="ri_map")
    L.note(RM.ATTRIBUTION + ". Stops are numbered in the " + direction + " direction; the path always follows the outbound stop order.")
    fig_tbl = pd.DataFrame({"Measure": ["Road path length (km)" if is_osm else "Straight-line estimate x 1.3 (km)", "Route length in the synthetic data (km)",
                                        "Ratio (path / synthetic)", "Illustrative travel time (min)"],
                            "Value": [f"{prow['osm_length_km']:.1f}", f"{prow['synthetic_length_km']:.1f}", f"{prow['length_ratio']:.2f}", f"{prow['travel_time_min']:.0f}"]})
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Stop sequence (from route_stops)**")
        st.dataframe(seq_disp[["seq", "stop_id", "name", "cum_km"]].rename(columns={"seq": "#", "stop_id": "Stop ID", "name": "Stop", "cum_km": "Cum. km (outbound frame)"}),
                     hide_index=True, width="stretch")
    with c2:
        st.markdown("**Path versus the synthetic route length**")
        st.dataframe(fig_tbl, hide_index=True, width="stretch")
        L.note("Travel time uses OSM-derived speeds scaled by a bus factor plus dwell per stop; it is illustrative, not a timetable.")

st.subheader("Candidate routes (illustrative)")
if cands is None or cands.empty:
    L.empty_state("Candidate routes not built yet", "Candidates are generated from the cached road graphs. Run the command below, then reload.", ROUTING_CMD)
else:
    groups = list(dict.fromkeys(cands["corridor"]))
    default_group = next((g for g in groups if (route_type == "intercity") == g.startswith("Rajkot-")), groups[0])
    group = st.selectbox("Candidate corridor", groups, index=groups.index(default_group), key="ri_cand_group",
                         help="A bounded, hand-specified set of candidates for two demo corridors. This is not a network-wide optimisation.")
    cg = cands[cands["corridor"] == group].copy()
    n_fb = int((cg["rank_flag"] != "ranked").sum())
    wv = next((json.loads(b).get("weight_version", "") for b in cg["score_breakdown_json"].dropna()), "")
    st.warning(f"{cg['label'].iloc[0]}. Scores use simulated population and jobs and demonstration weights ({wv}).")
    if n_fb:
        st.info(f"{n_fb} candidate(s) have no OpenStreetMap road path (straight-line fallback). They are shown but NOT scored or ranked, because their overlap, penalty and coverage are not comparable.")
    show = cg.assign(Score=cg["score"], Rank=cg["rank_in_corridor"].astype("Int64"),
                     Comparable=cg["rank_flag"].map({"ranked": "yes", "not_comparable_fallback": "no (straight-line fallback)"}),
                     Path=cg["path_source"].map({"openstreetmap": "OpenStreetMap", "straight_line_fallback": "fallback"}))
    st.dataframe(show[["candidate_id", "name", "Rank", "Score", "travel_time_min", "population_covered", "jobs_covered", "travel_time_penalty_pct",
                       "existing_route_overlap_pct", "Comparable", "Path"]].sort_values("Rank", na_position="last").rename(columns={
        "candidate_id": "ID", "name": "Candidate", "travel_time_min": "Travel time (min)", "population_covered": "Population within 800 m",
        "jobs_covered": "Jobs within 800 m", "travel_time_penalty_pct": "Time penalty vs fastest (%)", "existing_route_overlap_pct": "Overlap with existing routes (%)"}),
        hide_index=True, width="stretch",
        column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                       "Population within 800 m": st.column_config.NumberColumn(format="%d"), "Jobs within 800 m": st.column_config.NumberColumn(format="%d"),
                       "Travel time (min)": st.column_config.NumberColumn(format="%.0f"),
                       "Time penalty vs fastest (%)": st.column_config.NumberColumn(format="%.0f"),
                       "Overlap with existing routes (%)": st.column_config.NumberColumn(format="%.0f")})
    pick_c = st.selectbox("Inspect a candidate", cg["candidate_id"].tolist(), key="ri_cand_pick",
                          format_func=lambda c: f"{c} - {cg.loc[cg['candidate_id'] == c, 'name'].iloc[0]}")
    crow = cg[cg["candidate_id"] == pick_c].iloc[0]
    L.show_chart(RM.route_map([{"name": r["candidate_id"], "coords": json.loads(r["path_geojson"])["coordinates"], "source": r["path_source"]}
                               for _, r in cg.iterrows()], None, selected=pick_c, height=420), key="ri_cand_map")
    L.note(RM.ATTRIBUTION + ". Candidates are illustrative; orange lines (if any) are straight-line fallbacks.")
    with st.expander(f"Score breakdown for {pick_c}"):
        bd = json.loads(crow["score_breakdown_json"])
        if "components_0_1" in bd:
            st.dataframe(pd.DataFrame({"Component": list(bd["components_0_1"]), "Value (0-1)": list(bd["components_0_1"].values()),
                                       "Weight": [bd["weights"][k] for k in bd["components_0_1"]],
                                       "Weighted contribution": [bd["weighted_contribution"][k] for k in bd["components_0_1"]]}),
                         hide_index=True, width="stretch")
            st.caption(f"Score = 100 x sum of weighted contributions = {crow['score']:.1f}. Weights {bd['weight_version']} are demonstration values. {bd['scaling']}.")
        else:
            st.write(bd.get("not_comparable", "Not scored."))
    st.markdown("**Bounds of this analysis.** Candidates cover only the demo corridors above (a handful of hand-specified paths), not the whole GSRTC network. "
                "Not modelled: fleet size, driver duty and rest rules, depot capacity and turnaround times. Minimum-service routes (L09, L10) stay protected: "
                "no candidate or score implies withdrawing them.")

st.subheader("Recommendations for this route")
if recs is None:
    L.empty_state("Recommendations not generated", "Run the analytics command to create the rule-generated recommendations.", "python -m modules.analytics.run")
else:
    rr = recs[recs["route_id"] == route_id].sort_values("priority_rank")
    if rr.empty:
        L.note("No rule-generated recommendation applies to this route. Recommendations come from the gap analysis and are not created on this page.")
    else:
        st.dataframe(rr[["recommendation_id", "priority", "title", "time_window", "day_type", "confidence_label"]].rename(columns={
            "recommendation_id": "ID", "priority": "Priority", "title": "Action", "time_window": "Time window", "day_type": "Day type",
            "confidence_label": "Confidence"}), hide_index=True, width="stretch")
        L.note("These are the existing recommendation rows; the time window is the demand-supply gap window of the Demand-Supply Gaps page.")


L.what_this_means(N.route_meaning(p, int(srow["rank_within_type"]), n_in_type, route_type, float(srow["total_score"])))
w_lines = [f"{Q.COMPONENT_LABELS[c]}: weight {weights[c] * 100:.0f}%" for c in Q.COMPONENT_COLUMNS]
L.evidence_expander(
    sources=["route_summary (KPIs: single source of truth)", "route_scores (components, weights, explanation)", "route_kpis (daily trend)",
             "stop_occupancy (load along the route)", "hourly_demand_supply (hourly profile)",
             "route_paths, route_candidates (M4: OpenStreetMap road paths and illustrative candidates; built from cached graphs)",
             "recommendations (existing rows, unchanged)", "route_stops, stops (stop sequence)"],
    formulas=["Total score = sum of weight x component score (each component min-max normalised to 0-100 within route type).",
              "Weights (" + str(srow["weight_version"]) + "): " + "; ".join(w_lines) + ".",
              "Load factor = passenger-km / seat-km; EPKM = ticket revenue / vehicle-km; contribution = revenue - operating cost.",
              f"Why this route scores {fmt.number(srow['total_score'], 1)}: {srow['explanation']}"],
    assumptions=["Weights are demonstration values, not validated policy.",
                 f"Social importance is rule-based and gives minimum-service routes the maximum; {int(ranked['protected_minimum_service'].sum())} route(s) here are protected.",
                 "Feasibility is a proxy, not an engineering assessment.",
                 "Road geometry is real OpenStreetMap data (c) OpenStreetMap contributors; routes, stops, demand and candidates are simulated and illustrative. Path travel times use assumed speeds.",
                 config.SIMULATION_BADGE_TEXT + ": routes are demonstration routes with synthetic tickets, not real GSRTC or RMTS routes."],
    filters=f.describe() + ". The ranking and KPIs cover all 42 days; the stop and hourly views use the day type and hours.")
