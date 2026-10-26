"""Demand-Supply Gaps: where and when demand exceeds the seats offered, and an 'add service' scenario."""
import pandas as pd
import streamlit as st

import config
from modules.analytics import queries as Q
from modules.analytics.recommendations import full_route_fare_inr
from modules.analytics.scenarios import service_frequency_scenario
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("gaps")
t = L.require_tables(spec)
hourly, rs, recs = t["hourly_demand_supply"], t["route_summary"], t["recommendations"]
route_name = dict(zip(rs["route_id"], rs["name"]))
stop_name = D.stop_names()

h = F.filter_hourly(hourly, f, rs)
s = Q.gap_summary(h)
unc = Q.uncovered_windows(h)

L.kpi_row([
    {"label": "Crowded route-hours", "value": fmt.number(s["crowded_route_hours"]),
     "help": f"Route-direction hours where demand / seats exceeds {fmt.times(config.CROWDING_GAP_INDEX_THRESHOLD, 1)} (local) or intercity buses are at seat capacity."},
    {"label": "Highest demand / seats", "value": fmt.times(s["max_gap_index"]),
     "help": "Worst crowded route-hour: critical-link load as a multiple of seats offered. A lower bound, because tickets cannot exceed capacity."},
    {"label": "Corridor hours with no state seats", "value": fmt.number(s["uncovered_corridor_hours"]),
     "help": "Hours when private operators depart from the origin terminal but the state timetable offers no seats."},
    {"label": "Private-market passengers in those hours", "value": fmt.number(s["uncovered_proxy_demand"]) + " / day",
     "help": f"Assumption-based proxy: synthetic competitor seats x {fmt.ratio_pct(config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION)} assumed occupancy."},
])

st.subheader("Where and when demand exceeds seats")
grid = Q.hour_grid(h, stop_name, route_name)
L.show_chart(charts.gap_heatmap(grid), key="gp_heat")
L.note("Colour = estimated demand divided by seats offered (1.0 = every seat full, above 1.2 = crowded). Grey crosses mean no capacity is scheduled in that hour; "
       "that is not zero demand. Blank cells are hours outside the route's service span.")

# ---- Supporting view: corridor supply vs private market
corridors = sorted(set(Q.corridor_rows(h)["corridor"].dropna()))
st.subheader("Corridor view: state seats vs the private market")
if corridors:
    default = corridors.index(config.PRIMARY_CORRIDOR) if config.PRIMARY_CORRIDOR in corridors else 0
    corridor = st.selectbox("Corridor", corridors, index=default, key="gp_corridor")
    L.show_chart(charts.corridor_supply(Q.corridor_hour_frame(h, corridor), corridor), key="gp_corr")
    L.note("Hours shaded orange have no scheduled state seats. The private-market line is a proxy built from synthetic competitor departures, not observed passengers.")
else:
    corridor = None
    L.empty_state("No intercity corridor in this view", "The corridor comparison needs an intercity corridor; choose All or an intercity corridor in the sidebar.")

# ---- Lists
st.subheader("Crowded route-hours")
crowded = Q.crowded_route_hours(h)
if crowded.empty:
    L.empty_state("No crowded route-hours", "No route-hour exceeds the crowding threshold or reaches seat capacity under the current filters.")
else:
    def rec_for(r):
        m = Q.matching_recommendation(recs, route_id=r["route_id"], direction=r["direction"], start_hour=int(r["hour"]), end_hour=int(r["hour"]) + 1)
        return m["recommendation_id"] if m is not None else ""
    lst = pd.DataFrame({
        "Route": crowded["route_id"], "Name": crowded["route_id"].map(route_name), "Direction": crowded["direction"],
        "Departure hour": crowded["hour"].map(fmt.hhmm), "Demand (passengers/day)": crowded["demand_estimate"].round(1),
        "Seats offered": crowded["seats_offered"].round(0), "Demand / seats": crowded["gap_index"].round(2),
        "Status": crowded["status"].map({"crowded": "Crowded", "at_capacity": "At seat capacity"}),
        "Fullest stop": crowded["location_id"].map(stop_name), "Recommendation": crowded.apply(rec_for, axis=1)})
    st.dataframe(lst, hide_index=True, width="stretch")

st.subheader("Recommended service windows")
svc = F.filter_recommendations(recs, f, rs)
svc = svc[svc["category"].isin(["add_service_peak", "add_service_corridor_slot", "add_capacity_weekend"])].sort_values("priority_rank")
if svc.empty:
    L.empty_state("No service recommendations in this scope", "No add-service recommendation applies to the selected corridor.")
else:
    st.dataframe(pd.DataFrame({
        "ID": svc["recommendation_id"], "Priority": svc["priority"], "Route / corridor": svc["route_id"].where(svc["category"] != "add_service_corridor_slot", svc["corridor"]),
        "Direction": svc["direction"], "Day type": svc["day_type"].str.replace("+", " and "), "Time window": svc["time_window"], "Action": svc["title"]}),
        hide_index=True, width="stretch")
    L.note("Each time window is the hours of the gap rows that triggered the recommendation, so it matches the heat map and the lists above.")

# ---- Scenario
st.subheader("Add service: scenario")
wins = Q.gap_windows(h)
options: list[dict] = []
for _, w in wins.iterrows():
    options.append({"id": f"R-{w['route_id']}-{w['direction']}-{int(w['start_hour'])}", "kind": "route", "row": w,
                    "label": f"{w['route_id']} {w['direction']} {fmt.hhmm(w['start_hour'])}–{fmt.hhmm(w['end_hour'])} "
                             f"({'crowded' if w['status'] == 'crowded' else 'at seat capacity'}, {fmt.times(w['max_gap_index'])} seats)"})
for _, w in unc.iterrows():
    options.append({"id": f"C-{w['corridor']}-{int(w['start_hour'])}", "kind": "corridor", "row": w,
                    "label": f"{w['corridor']} {fmt.hhmm(w['start_hour'])}–{fmt.hhmm(w['end_hour'])} (no state seats; private proxy {fmt.number(w['proxy_demand'])} passengers/day)"})
def _rec_rank(o: dict) -> int:
    w = o["row"]
    m = (Q.matching_recommendation(recs, route_id=w["route_id"], direction=w["direction"], start_hour=int(w["start_hour"]), end_hour=int(w["end_hour"]))
         if o["kind"] == "route" else
         Q.matching_recommendation(recs, corridor=w["corridor"], start_hour=int(w["start_hour"]), end_hour=int(w["end_hour"])))
    return int(m["priority_rank"]) if m is not None else 999


options.sort(key=_rec_rank)  # gaps that have a recommendation first, in priority order (stable for the rest)
if not options:
    L.empty_state("Nothing to simulate", "No crowded route-hours or uncovered corridor windows under the current filters. Change the day type, hours or corridor.")
else:
    by_id = {o["id"]: o for o in options}  # plain string ids as widget options (rows hold pandas objects)
    choice = by_id[st.selectbox("Gap to size", list(by_id), format_func=lambda i: by_id[i]["label"], key="gp_choice")]
    w, oid = choice["row"], choice["id"]
    if choice["kind"] == "route":
        rid = w["route_id"]
        rrow = rs[rs["route_id"] == rid].iloc[0]
        rec = Q.matching_recommendation(recs, route_id=rid, direction=w["direction"], start_hour=int(w["start_hour"]), end_hour=int(w["end_hour"]))
        projected, existing = float(w["demand"]), int(round(w["existing_departures"]))
        rec_fare = N.json_dict(rec["assumptions_json"]).get("fare_per_passenger_inr") if rec is not None else None
        fare_default = float(rec_fare) if rec_fare else float(rrow["revenue_per_passenger_inr"])
        fare_basis = "recommendation assumption" if rec_fare else "route revenue per passenger (route_summary)"
        capture = None
    else:
        ids = F.route_ids(rs, w["corridor"])
        rec = Q.matching_recommendation(recs, corridor=w["corridor"], start_hour=int(w["start_hour"]), end_hour=int(w["end_hour"]))
        default_rid = rec["route_id"] if rec is not None and rec["route_id"] in ids else ids[0]
        rid = st.selectbox("Bus service to add", ids, index=ids.index(default_rid), key=f"sc_{oid}_route",
                           format_func=lambda r: f"{r} {route_name[r]}")
        rrow = rs[rs["route_id"] == rid].iloc[0]
        capture = st.slider("Share of the private-market demand the state captures (assumption)", 0.05, 1.0, float(config.STATE_CAPTURE_SHARE), 0.05,
                            key=f"sc_{oid}_capture", format="%.2f")
        projected, existing = float(w["proxy_demand"]) * capture, 0
        fare_default = full_route_fare_inr(rrow["bus_type"], float(rrow["length_km"]))
        fare_basis = "illustrative full-route fare for the bus type"

    seats_default = float(rrow["available_seats"]) / float(rrow["trips"]) if rrow["trips"] else 40.0
    cost_default = float(rrow["operating_cost_inr"]) / float(rrow["vehicle_km"]) if rrow["vehicle_km"] else 0.0
    st.caption(f"Defaults come from the selected gap and {rid} in route_summary; fare basis: {fare_basis}. Edit any assumption.")
    c1, c2, c3 = st.columns(3)
    with c1:
        proj = st.number_input("Projected passengers (per day, this window)", min_value=0.0, value=round(projected, 1), step=5.0, key=f"sc_{oid}_{rid}_{capture}_proj")
        existing_in = st.number_input("Existing departures in the window", min_value=0, value=existing, step=1, key=f"sc_{oid}_{rid}_{capture}_exist")
    with c2:
        seats = st.number_input("Seats per bus", min_value=1.0, value=round(seats_default, 0), step=1.0, key=f"sc_{oid}_{rid}_seats")
        target = st.number_input("Target load factor", min_value=0.1, max_value=1.5, value=float(config.SERVICE_TARGET_LOAD_FACTOR), step=0.05, key=f"sc_{oid}_{rid}_tlf")
    with c3:
        cpk = st.number_input("Operating cost per km (₹)", min_value=0.0, value=round(cost_default, 1), step=1.0, key=f"sc_{oid}_{rid}_cpk")
        fare = st.number_input("Fare per passenger (₹)", min_value=0.0, value=round(fare_default, 1), step=5.0, key=f"sc_{oid}_{rid}_fare")
    trip_km = float(rrow["length_km"])
    try:
        res = service_frequency_scenario(proj, seats, target, existing_in, trip_km, cpk, fare_per_passenger=fare)
    except ValueError as exc:
        L.error_state(f"These assumptions cannot be evaluated: {exc}")
        res = None
    if res is not None:
        out = pd.DataFrame([
            ("Additional departures needed", f"{res['additional_departures']} (total {res['total_departures_after']} instead of {res['existing_departures']})"),
            ("Projected load factor after", fmt.ratio_pct(res["projected_load_factor_after"])),
            ("Extra vehicle-km per day", fmt.km(res["incremental_vehicle_km"])),
            ("Extra operating cost per day", fmt.inr(res["incremental_operating_cost_inr"])),
            ("Extra ticket revenue per day", fmt.inr(res["incremental_revenue_inr"])),
            ("Incremental contribution per day (not profit)", fmt.inr(res["incremental_contribution_inr"])),
        ], columns=["Result", "Value"])
        st.dataframe(out, hide_index=True, width="stretch")
        st.caption("Illustrative service scenario. " + " ".join(c.capitalize() + "." for c in res["constraints"]))
        if choice["kind"] == "route" and w["status"] == "at_capacity":
            st.caption("This gap is at the seat cap: demand above the seats is never ticketed, so extra revenue from added capacity cannot be observed here.")
    if rec is not None:
        e = N.json_dict(rec["expected_impact_json"])
        st.success(f"Matching recommendation {rec['recommendation_id']} ({rec['priority']} priority, window {rec['time_window']}): {rec['title']}. "
                   f"Its scenario adds {e.get('additional_departures', fmt.NA)} departure(s). {N.impact_summary(rec)}")
    else:
        st.info("No recommendation was generated for this gap (it may be below the recommendation thresholds).")

L.what_this_means(N.gaps_meaning(s, f.day_type, unc.iloc[0] if len(unc) else None))
L.evidence_expander(
    sources=["hourly_demand_supply (route_direction and corridor rows, average service day of the selected day type)", "route_summary (seats per bus, cost per km, fares)",
             "recommendations (windows, assumptions, expected impact)"],
    formulas=["Gap index = demand estimate / seats offered; crowded when above " + fmt.times(config.CROWDING_GAP_INDEX_THRESHOLD, 1) + ".",
              "Required departures = ceil(projected passengers / (seats per bus x target load factor)); additional = max(0, required - existing).",
              "Incremental contribution = incremental passengers x fare - extra vehicle-km x cost per km (not profit)."],
    assumptions=["Route-level demand is the critical-link load of ticketed passengers, censored at capacity, so gaps are lower bounds.",
                 f"Corridor demand adds a private-market proxy: competitor seats x {fmt.ratio_pct(config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION)} assumed occupancy.",
                 f"Corridor slots assume the state captures {fmt.ratio_pct(config.STATE_CAPTURE_SHARE)} of that market unless changed above.",
                 "Fleet availability, driver duty hours, depot capacity and bus turnaround are not modelled.",
                 config.SIMULATION_BADGE_TEXT + "."],
    filters=f.describe())
