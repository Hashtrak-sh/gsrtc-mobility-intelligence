"""Overview: what is happening, where the problem is, what action is recommended."""
import pandas as pd
import streamlit as st

import config
from modules.analytics import queries as Q
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L
from modules.ui.health import render_health_panel

spec, f = L.page_setup("overview")
t = L.require_tables(spec)
rs, hourly, od, recs = t["route_summary"], t["hourly_demand_supply"], t["od_flows"], t["recommendations"]

scope = F.scope_routes(rs, f.corridor)
if scope.empty:
    L.empty_state("No routes in this scope", "The selected corridor has no routes in the generated data. Choose another corridor in the sidebar.")
    st.stop()

route_name = dict(zip(rs["route_id"], rs["name"]))
h = F.filter_hourly(hourly, f, rs)
o = F.filter_od(od, f, rs, t["route_stops"], t["stops"])
pairs = Q.od_pairs(o, top=10)
kp = Q.scope_kpis(scope)
findings = N.key_findings(h, pairs, route_name, D.stop_names(), D.zone_names(), f.day_type, float(o["passenger_count"].sum()))
scoped_recs = F.filter_recommendations(recs, f, rs).sort_values("priority_rank")

# 1. Decision first: three findings
st.subheader("Key findings")
for col, fd in zip(st.columns(3), findings):
    with col:
        L.card(fd["title"], fd["text"], meta=f"Source: {fd['source']}")

# 2. KPIs (route_summary is the single source of truth for route KPIs)
st.subheader("Network at a glance")
L.kpi_row([
    {"label": "Average boardings per day", "value": fmt.number(kp["avg_boardings_per_day"]),
     "help": "Passengers boarding per average service day over all 42 synthetic days (route_summary)."},
    {"label": "Load factor", "value": fmt.pct(kp["load_factor_pct"]),
     "help": "Passenger-km divided by seat-km over all trips in scope (ratio of sums)."},
    {"label": "On-time departures", "value": fmt.pct(kp["reliability_pct"]),
     "help": "Share of trips departing between 1 minute early and 5 minutes late (trip-weighted)."},
    {"label": "Contribution per day (not profit)", "value": fmt.inr(kp["contribution_per_day_inr"]),
     "help": "Ticket revenue minus operating cost per average day. Overheads, staff, depreciation and subsidy are not modelled."},
])
st.caption(f"{kp['n_routes']} route(s) in scope; route KPIs cover all 42 synthetic days regardless of the day-type filter.")

# 3. Recommended actions
st.subheader("Recommended actions")
if scoped_recs.empty:
    L.empty_state("No recommendations for this scope", "No rule-generated recommendation applies to the selected corridor.")
else:
    top = scoped_recs.head(4)
    for i in range(0, len(top), 2):
        for col, (_, r) in zip(st.columns(2), top.iloc[i:i + 2].iterrows()):
            with col:
                with st.container(border=True):
                    pill_cls = "high" if r["priority"] == "High" else ""
                    st.markdown(f'<span class="gsrtc-pill {pill_cls}">{r["priority"]} priority</span> **{r["title"]}**', unsafe_allow_html=True)
                    st.write(r["action"])
                    st.markdown(f"**Time window:** {r['time_window']}  \n**Day type:** {str(r['day_type']).replace('+', ' and ')}  \n"
                                f"**Expected impact:** {N.impact_summary(r)}")
                    cons = N.json_list(r["constraints_json"])
                    if cons:
                        st.markdown("**Constraints:** " + "; ".join(cons[:2]) + ".")
                    with st.expander("See evidence"):
                        ev = N.json_dict(r["evidence_json"])
                        st.markdown("**Evidence** (from `hourly_demand_supply`, `route_summary`, `route_scores`)")
                        for k, v in ev.get("figures", {}).items():
                            line = N.describe_value(k, v)
                            if line:
                                st.markdown(f"- {line}")
                        for line in N.capture_sensitivity_lines(r):
                            st.markdown(f"- {line}")
                        st.markdown("**Assumptions**")
                        for k, v in N.json_dict(r["assumptions_json"]).items():
                            line = N.describe_value(k, v)
                            if line:
                                st.markdown(f"- {line}")
                        if cons:
                            st.markdown("**All constraints**")
                            for c in cons:
                                st.markdown(f"- {c}")
                        st.caption(f"{r['recommendation_id']} | {r['confidence_label']}")
    if len(scoped_recs) > len(top):
        with st.expander(f"All {len(scoped_recs)} recommendations in this scope"):
            st.dataframe(scoped_recs[["recommendation_id", "priority", "title", "time_window", "day_type"]].rename(columns={
                "recommendation_id": "ID", "priority": "Priority", "title": "Action", "time_window": "Time window", "day_type": "Day type"}),
                hide_index=True, width="stretch")

# 4. Primary and supporting visual
st.subheader("Where the pressure is")
left, right = st.columns(2)
with left:
    bars = scope.assign(label=[Q.chart_label(a, b) for a, b in zip(scope["route_id"], scope["name"])])
    L.show_chart(charts.peak_load_bars(bars), key="ov_peak")
    L.note("Peak-hour load by route over all days: the bus load in the route's busiest hour as a multiple of its seats.")
with right:
    L.show_chart(charts.demand_vs_seats(Q.demand_vs_seats_by_hour(h), title=f"Demand vs seats by hour ({f.day_type})"), key="ov_hours")
    L.note("Seats offered vs estimated demand for scheduled departures. Hours without any scheduled departure are not drawn.")

L.what_this_means(N.overview_meaning(kp, findings, len(scoped_recs), f.corridor))
L.evidence_expander(
    sources=["route_summary (route KPIs)", "hourly_demand_supply (findings, hourly chart)", "od_flows (busiest pair)",
             "recommendations (actions, evidence, assumptions)", "Provenance sidecars (`*.provenance.json`) for source type, seed and time"],
    formulas=["Load factor = passenger-km / seat-km x 100.", "Crowded when demand / seats exceeds " + fmt.times(config.CROWDING_GAP_INDEX_THRESHOLD, 1) + ".",
              "Contribution = ticket revenue - operating cost (not profit)."],
    assumptions=["Ticketed demand is censored at capacity, so crowding gaps are lower bounds.",
                 f"Private-market demand is an assumption ({fmt.ratio_pct(config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION)} occupancy of synthetic competitor seats).",
                 f"Service scenarios target {fmt.ratio_pct(config.SERVICE_TARGET_LOAD_FACTOR)} load factor; fleet and crew limits are not modelled.",
                 config.SIMULATION_BADGE_TEXT + ": nothing here is a real GSRTC measurement."],
    filters=f.describe() + ". Recommendations are filtered by corridor only; each states its own day type.")

# 5. Provenance panel
st.subheader("Data provenance")
rows = []
for layer, names in (("synthetic", ["routes", "stops", "zones", "trips", "tickets", "survey_responses", "competitor_services", "reviews",
                                    "cctv_counts", "assets_assessment", "digital_assessment"]),
                     ("processed", ["route_summary", "route_kpis", "hourly_demand_supply", "od_flows", "stop_occupancy", "route_scores",
                                    "recommendations", "cctv_hourly_profile"])):
    for n in names:
        p = D.provenance(n, layer)
        if p:
            rows.append({"Table": n, "Layer": layer, "Source type": p.get("source_type"), "Seed": p.get("seed"),
                         "Generated (UTC)": str(p.get("generated_at", ""))[:19].replace("T", " ")})
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=250)
else:
    L.note("No provenance sidecars were found.")
stops = t["stops"]
cs = stops["coord_source"].value_counts()
st.markdown(
    f"**Real geography vs simulated mobility.** Of {len(stops)} stops, {int(cs.get('openstreetmap', 0))} use coordinates taken from OpenStreetMap, "
    f"{int(cs.get('openstreetmap_offset', 0))} are synthetic points placed near a real OpenStreetMap place, and "
    f"{int(cs.get('manual_demo_input', 0))} are hand-entered approximations. Everything about passengers, tickets, fares, surveys, "
    f"competitors and routes is synthetic; the routes are demonstration routes, not real GSRTC or RMTS routes.")

with st.expander("System health and diagnostics"):
    render_health_panel()
