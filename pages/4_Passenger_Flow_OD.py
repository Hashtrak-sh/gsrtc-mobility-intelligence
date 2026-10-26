"""Passenger Flow & O-D: busiest zone pairs, the zone matrix and the hourly commute direction."""
import streamlit as st

from modules.analytics import queries as Q
from modules.analytics import stop_activity as SA
from modules.routing import maps as M
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("flow")
t = L.require_tables(spec, extra=[("processed", "stop_occupancy")])
od, rs, zones = t["od_flows"], t["route_summary"], t["zones"]
names = D.zone_names()
ztype = dict(zip(zones["zone_id"], zones["zone_type"]))

o = F.filter_od(od, f, rs, t["route_stops"], t["stops"])
if o.empty:
    L.empty_state("No passenger flows", f"No O-D flows match {f.describe()}. Widen the hours, or pick another day type or corridor.")
    st.stop()

intra = st.checkbox("Include trips within a single zone", value=True, key="od_intra",
                    help="Intra-zone trips board and alight in the same zone (short local hops).")
pairs = Q.od_pairs(o, top=10, include_intra_zone=intra)
pairs = pairs.assign(label=[f"{names.get(a, a)} → {names.get(b, b)}" for a, b in zip(pairs["origin_zone_id"], pairs["dest_zone_id"])])
total = float(o["passenger_count"].sum())
by_hour = o.groupby("hour")["passenger_count"].sum()
peak_hour = int(by_hour.idxmax())
intra_share = float(o.loc[o["is_intra_zone"], "passenger_count"].sum() / total * 100) if total else 0.0
top = pairs.iloc[0] if len(pairs) else None
top_share = float(top["passengers_per_day"] / total * 100) if top is not None and total else float("nan")

L.kpi_row([
    {"label": f"Boardings per average {f.day_type}", "value": fmt.number(total),
     "help": "Passengers in the selected corridor and hours, per average service day (od_flows)."},
    {"label": "Busiest zone pair", "value": f"{fmt.number(top['passengers_per_day'])} / day" if top is not None else fmt.NA,
     "help": top["label"] if top is not None else "No pair in the current filters."},
    {"label": "Peak boarding hour", "value": fmt.hhmm(peak_hour), "help": f"Clock hour with {fmt.number(by_hour.max())} boardings per average day."},
    {"label": "Trips within one zone", "value": fmt.pct(intra_share, 0), "help": "Share of passengers whose origin and destination zones are the same."},
])


st.subheader("Busiest origin-destination pairs")
tab_p, tab_m = st.tabs(["Top pairs", "Zone matrix"])
with tab_p:
    L.show_chart(charts.od_bar(pairs), key="od_bar")
    L.note("Zone names are used throughout; flows are average passengers per service day of the selected day type, in the selected boarding hours.")
with tab_m:
    L.show_chart(charts.od_matrix_fig(Q.od_matrix(o if intra else o[~o["is_intra_zone"]]), names), key="od_matrix")
    L.note("Rows are origin zones and columns are destination zones, sorted by total flow; empty cells have no recorded passengers. The matrix is the readable fallback to arcs on a map.")

st.subheader("Commute direction by hour")
L.show_chart(charts.directional_fig(Q.directional_profile(o, ztype)), key="od_dir")
L.note("Flows grouped by the zone type of their destination and origin: 'towards employment zones' (morning commute pattern) versus 'from employment zones' (return pattern).")

st.subheader("Where demand concentrates: stop-level heatmap")
act = SA.stop_activity(t["stop_occupancy"], t["stops"], day_type=f.day_type, hour_lo=f.hour_lo, hour_hi=f.hour_hi,
                       route_ids=None if f.corridor == F.ALL else F.route_ids(rs, f.corridor))
city_mask = SA.in_city(act)
hc1, hc2 = st.columns([2, 3])
metric = hc1.radio("Metric", list(SA.METRICS), format_func=SA.METRICS.get, horizontal=True, key="hm_metric")
default_city = int(f.corridor in (F.ALL, F.LOCAL)) if city_mask.any() else 0
view = hc2.radio("Map view", ["Rajkot city", "Whole network"], index=0 if default_city else 1, horizontal=True,
                 key=f"hm_view_{f.corridor}", help="The intercity corridors are about 200 km from Rajkot, so the city view zooms in "
                 "to keep the city readable; the network view shows every stop.")
shown = act[city_mask] if view == "Rajkot city" else act
col = SA.metric_column(metric)
missing_xy = int(act[["lat", "lon"]].isna().any(axis=1).sum())
if shown.dropna(subset=["lat", "lon"]).empty:
    L.empty_state("No stops to map", f"No stop activity with coordinates matches {f.describe()} in this view. Try the whole network.")
else:
    L.show_chart(M.demand_heatmap(shown, col, label=SA.METRICS[metric] + " per day", city=view == "Rajkot city"), key="od_heatmap")
    st.markdown(f"**{SA.takeaway(shown.dropna(subset=['lat', 'lon']), metric)}**")
L.note("Basemap and stop positions: (c) OpenStreetMap contributors; stop positions are real OpenStreetMap points or offsets from them "
       "(coordinate source shown on hover). All passenger values are simulated data for demonstration. Density colour and bubble size "
       "show the chosen metric per average service day in the selected hours"
       + (f"; {missing_xy} stop(s) without coordinates are not drawn." if missing_xy else ".")
       + (" Net bubbles in orange are stops where more passengers alight than board." if metric == "net" else ""))

L.what_this_means(N.flow_meaning(total, top, names, peak_hour, intra_share, f.day_type))
L.evidence_expander(
    sources=["od_flows (zone pair x route x boarding hour x day type)", "zones (names and zone types)", "route_summary (route to corridor membership)",
             "stop_occupancy (average bus boardings/alightings per stop, route, direction, day type and departure hour)",
             "stops (stop names and coordinates; coord_source = openstreetmap, openstreetmap_offset or manual_demo_input)"],
    formulas=["Passengers per day = total passengers of the day type / number of service dates of that day type.",
              "Hour = clock hour of the ticket's boarding timestamp.",
              "Stop heatmap: boardings per day at a stop = sum over routes, directions and hours in the window of average boardings per trip x trips per day "
              "(alightings likewise; net = boardings - alightings). Network total equals the route_summary boardings per day of the same routes.",
              "Corridor scope: every O-D row carries the route that carried the passengers, so a corridor shows exactly the passengers of its routes "
              "(a zone pair served by two corridors is split between them, never counted twice)."],
    assumptions=["Flows come from simulated tickets; they exclude people who could not board because buses were full.",
                 "Zone types (residential, employment, ...) are synthetic labels used only to describe commute direction.",
                 "Zones are synthetic demo areas near real Rajkot place names; their coordinates may come from OpenStreetMap but all passenger values are simulated.",
                 "The heatmap shows stop-level activity, not O-D arcs (arcs would not be readable); the matrix and ranked pairs carry the O-D information.",
                 "Stop positions are real OpenStreetMap points or offsets from them; the hour window uses the trip's departure hour, so a stop's later hours reflect trips that departed in the window.",
                 "Heatmap density is drawn in screen pixels, so its blur radius changes with zoom; use the bubbles and hover for exact values."],
    filters=f.describe())
