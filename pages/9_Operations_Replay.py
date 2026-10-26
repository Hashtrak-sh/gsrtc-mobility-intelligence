"""Operations Replay: a simulated control-room view of one synthetic service day. Not live, not streamed."""
import time

import pandas as pd
import streamlit as st

import config
from modules.data import io
from modules.analytics import replay as R
from modules.ui import data as D
from modules.ui import fmt
from modules.ui import layout as L
from modules.ui import replay_charts as RC

spec, _ = L.page_setup("replay", show_filters=())
st.warning(
    "**Simulated replay - not live.** This replays one synthetic service day from the stored tables to show how a real-time "
    "operations view would look once live ETM (ticketing) and AVL (GPS) feeds are connected. Nothing on this page is streamed.",
    icon=":material/info:",
)
t = L.require_tables(spec)
trips, tickets, hourly, stops, route_stops, routes = (t[k] for k in ("trips", "tickets", "hourly_demand_supply", "stops", "route_stops", "routes"))
route_name = dict(zip(routes["route_id"], routes["name"]))

SPEEDS = {"Slow (1 step every 4 s)": 4.0, "Normal (1 step every 2 s)": 2.0, "Fast (1 step every 1 s)": 1.0}
STEPS = {"15 minutes": 15, "30 minutes": 30, "60 minutes": 60}

day_types = trips.drop_duplicates("service_date").assign(service_date=lambda d: d["service_date"].astype(str)).sort_values("service_date")
date_type = dict(zip(day_types["service_date"], day_types["day_type"]))
dates = list(date_type)
default_date = next((d for d in dates if date_type[d] == config.PEAK_DAY_TYPE), dates[0])


@st.cache_data(show_spinner=False)
def day_frames(service_date: str, stamp: int) -> tuple[pd.DataFrame, pd.DataFrame]:  # noqa: ARG001 - stamp keys the cache on the data
    return R.prepare_day(trips, tickets, service_date)


st.session_state.setdefault("rp_playing", False)

c1, c2, c3, c4 = st.columns([2.2, 1.4, 1.6, 1.2])
with c1:
    service_date = st.selectbox("Service date (42 synthetic days)", dates, index=dates.index(default_date), key="rp_date",
                                format_func=lambda d: f"{d} - {date_type[d]}")
with c2:
    step_label = st.selectbox("Clock step", list(STEPS), index=0, key="rp_step")
with c3:
    speed_label = st.selectbox("Play speed", list(SPEEDS), index=1, key="rp_speed")
with c4:
    st.write("")
    playing = st.session_state["rp_playing"]
    if st.button("Pause" if playing else "Play", icon=":material/pause:" if playing else ":material/play_arrow:", width="stretch",
                 key="rp_toggle"):
        st.session_state["rp_playing"] = not playing
        st.rerun()
st.caption("Active filters: none. The global corridor, day type and hours filters do not apply here; the replay uses its own service-date and clock controls.")
st.caption(f"Day type: **{date_type[service_date]}**. Replay starts paused; press Play to advance the simulated clock automatically "
           "until the end of the day, or drag the clock.")

step = STEPS[step_label]
interval = SPEEDS[speed_label]
td, tk = day_frames(service_date, D._stamp(io.table_path("tickets", "synthetic")) or 0)
day_type = date_type[service_date]
lo, hi = R.clock_bounds(td, tk, step)
options = list(range(lo, hi + 1, step))
slider_key = f"rp_clock_{service_date}_{step}"
first_hour = next((o for o in options if o >= 10 * 60), options[0])
st.session_state.setdefault(slider_key, first_hour)
stop_xy = stops[["stop_id", "name", "lat", "lon"]]
grid = list(range(lo, hi + 1, 15))
curve = R.cumulative_curve(tk, grid)

run_every = interval if st.session_state["rp_playing"] else None


@st.fragment(run_every=run_every)
def replay_view() -> None:
    if st.session_state["rp_playing"]:
        now = time.time()
        last = st.session_state.get("rp_last_tick", 0.0)
        if now - last >= interval * 0.9:
            st.session_state["rp_last_tick"] = now
            cur = st.session_state[slider_key]
            nxt = [o for o in options if o > cur]
            if nxt:
                st.session_state[slider_key] = nxt[0]
    clock = st.select_slider("Simulated clock", options=options, key=slider_key, format_func=R.clock_label)
    if st.session_state["rp_playing"] and clock >= options[-1]:
        st.session_state["rp_playing"] = False
        st.rerun()  # full rerun so the Play/Pause button and the fragment timer reset

    snap = R.snapshot(td, tk, hourly, day_type, clock)
    d, c = snap["dep"], snap["crowd"]
    L.kpi_row([
        {"label": "Buses in service", "value": fmt.number(snap["buses"]),
         "help": "Trips whose departure (actual where recorded, else timetable) is at or before the clock and whose departure plus scheduled running time is after it."},
        {"label": "Boardings so far today", "value": fmt.number(snap["so_far"]),
         "help": "Sum of passenger_count over tickets of this service date with timestamp at or before the clock."},
        {"label": "Departures on time", "value": fmt.pct(d["on_time_pct"], 0) if d["known"] else fmt.NA,
         "help": f"Of {d['departed']} departures so far: on time means delay within {config.RELIABILITY_ON_TIME_BAND_MIN[0]:+.0f} to "
                 f"{config.RELIABILITY_ON_TIME_BAND_MIN[1]:+.0f} min (same definition as Route Intelligence); {d['late']} later than that, {d['early']} earlier."},
        {"label": f"Crowded route-hours at {c['hour']:02d}:00", "value": f"{c['crowded']} of {c['scheduled']}",
         "help": "Route-direction hours flagged crowded in hourly_demand_supply. That table is per AVERAGE service day of this day type, "
                 "not per date, so this card changes with the day type and hour, not with the chosen date."},
    ])
    st.caption(f"Clock {R.clock_label(clock)} | boardings in the last hour: {fmt.number(snap['last_hour'])} | "
               f"departures so far: {d['departed']} ({d['on_time']} on time, {d['late']} late, {d['early']} early) | "
               "Simulated data for demonstration")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Network map at this clock")
        buses = R.bus_positions(td, route_stops, stops, clock)
        L.show_chart(RC.replay_map(stop_xy, R.stop_boardings(tk, clock), buses), key="rp_map")
        L.note("Blue circles: stops sized by boardings in the last hour. Orange dots: buses in service at ESTIMATED positions "
               "(share of scheduled time elapsed along the stop sequence, straight lines between stops; not GPS). Map (c) OpenStreetMap contributors.")
    with right:
        st.subheader("Alerts")
        items = R.alerts(td, hourly, day_type, clock, route_name)
        if items:
            for a in items:
                st.markdown(f"- {a}")
        else:
            st.markdown("No alerts at this clock.")
        L.note(f"Alerts: departures more than {R.LATE_ALERT_MIN:.0f} min late in the last hour, and route-hours where average-day "
               "demand exceeds 100% of seats. Computed from the stored tables.")
    st.subheader("Cumulative boardings through the day")
    L.show_chart(RC.cumulative_fig(curve, clock), key="rp_cum")
    L.note("Running total of ticketed passengers for this service date; the orange marker is the simulated clock.")
    L.what_this_means(R.takeaway(R.clock_label(clock), snap))


replay_view()

L.evidence_expander(
    sources=[
        "synthetic/trips (departure_time, actual_departure_time, departure_delay_min, scheduled_minutes, direction), filtered to the chosen service date",
        "synthetic/tickets (timestamp, passenger_count, origin_stop_id), matched to the date through trip_id",
        "processed/hourly_demand_supply (crowding_flag, gap_index): one row per route-direction, day type and hour, per AVERAGE service day",
        "synthetic/stops and synthetic/route_stops (coordinates, stop order, cumulative minutes); map tiles (c) OpenStreetMap contributors",
    ],
    formulas=[
        "Buses in service = trips with start <= clock < start + scheduled_minutes, start = actual departure where recorded, else timetable.",
        "Boardings so far = sum of ticket passenger_count with timestamp <= clock; last hour = timestamp in (clock - 60 min, clock].",
        "On-time share = reliability_pct over departures so far, on time = delay in the configured band "
        f"({config.RELIABILITY_ON_TIME_BAND_MIN[0]:+.0f} to {config.RELIABILITY_ON_TIME_BAND_MIN[1]:+.0f} min), shared with Route Intelligence.",
        "Crowded route-hours = rows with crowding_flag for this day type and clock hour (demand / seats above the crowding threshold).",
        "Estimated bus position = elapsed share of scheduled minutes x route cum_minutes, linear between stops.",
    ],
    assumptions=[
        "Simulated replay, not live: nothing is streamed or refreshed from any feed. Play only steps a clock over stored tables.",
        "A real-time view would need ETM (ticketing) and AVL (GPS) feeds, which are not connected in this prototype.",
        "Bus positions are estimates from the timetable, not GPS; inbound trips are assumed to run the stop order in reverse.",
        "Crowding and over-100% alerts come from an average-day table, so they do not vary by the selected date.",
        "Trips running past midnight stay on their service date; the clock shows them as (+1 day).",
        "Simulated data for demonstration.",
    ],
)
