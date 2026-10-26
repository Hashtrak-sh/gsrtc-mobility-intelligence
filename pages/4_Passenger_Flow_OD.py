"""Passenger Flow & O-D: busiest zone pairs, the zone matrix and the hourly commute direction."""
import streamlit as st

from modules.analytics import queries as Q
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("flow")
t = L.require_tables(spec)
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

if f.corridor not in (F.ALL, F.LOCAL):
    L.note(F.OD_CORRIDOR_NOTE)

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

L.what_this_means(N.flow_meaning(total, top, names, peak_hour, intra_share, f.day_type))
L.evidence_expander(
    sources=["od_flows (zone pair x boarding hour x day type)", "zones (names and zone types)", "route_stops and stops (corridor scope)"],
    formulas=["Passengers per day = total passengers of the day type / number of service dates of that day type.",
              "Hour = clock hour of the ticket's boarding timestamp.",
              "Corridor scope: a pair is included when both zones are served by the scope's routes (for an intercity corridor, not entirely inside local-route zones)."],
    assumptions=["Flows come from simulated tickets; they exclude people who could not board because buses were full.",
                 "Zone types (residential, employment, ...) are synthetic labels used only to describe commute direction.",
                 "Zones are synthetic demo areas near real Rajkot place names; their coordinates may come from OpenStreetMap but all passenger values are simulated.",
                 "A map of arcs is not shown because it would not be readable; the matrix and ranked pairs carry the same information."],
    filters=f.describe())
