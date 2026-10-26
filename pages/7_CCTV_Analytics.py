"""CCTV Analytics: the SYNTHETIC footfall stream, and the honest status of the real-video detector."""
import pandas as pd
import streamlit as st

import config
from modules import diagnostics
from modules.analytics import cctv as CC
from modules.ui import charts, fmt, narrative as N
from modules.ui import data as D
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("cctv", show_filters=("day_type", "hours"))
t = L.require_tables(spec)
prof = t["cctv_hourly_profile"]
names = D.stop_names()

try:
    diag = diagnostics.run_diagnostics()
    deps = {s.module: s.available for s in diag["optional_deps"]}
    clips = list(diag["video_clips"])
except Exception:  # diagnostics must never take the page down
    deps, clips = {}, []
status = CC.detector_status(deps)

p = F.filter_cctv(prof, f)
if p.empty:
    peak = None
else:
    peak = p.sort_values(["mean_inbound_persons", "location_id", "hour"], ascending=[False, True, True]).iloc[0]

st.subheader("Synthetic footfall stream")
st.warning("This stream is SYNTHETIC footfall generated for the demonstration. It is not video, not detector output and not a real count.")
L.kpi_row([
    {"label": "Camera locations", "value": fmt.number(p["location_id"].nunique()) if len(p) else "0",
     "help": "Locations in the synthetic stream (bus stands). Location ids are stop ids, not person identifiers."},
    {"label": "Peak hour", "value": fmt.hhmm(peak["hour"]) if peak is not None else fmt.NA, "help": f"Busiest clock hour in {f.hours_label} for a {f.day_type}."},
    {"label": "Peak inbound persons per hour", "value": fmt.number(peak["mean_inbound_persons"]) if peak is not None else fmt.NA,
     "help": "Mean synthetic inbound persons in the peak hour, per day of the selected day type."},
    {"label": "Inbound persons per day (selected hours)",
     "value": fmt.number(p.groupby("location_id")["mean_inbound_persons"].sum().max()) if len(p) else fmt.NA,
     "help": "Synthetic inbound persons per day at the busiest location in the selected hours."},
])
L.show_chart(charts.cctv_profile(p, names), key="cc_profile")
L.note("Mean inbound persons per clock hour at each synthetic camera location, for the selected day type and hours. Aggregate counts only; no individuals are identified.")

locs = sorted(prof["location_id"].unique())
loc = st.selectbox("Location", locs, format_func=lambda x: f"{names.get(x, x)} ({x})", key="cc_loc")
dt_prof = prof[(prof["location_id"] == loc) & (prof["hour"] >= f.hour_lo) & (prof["hour"] < f.hour_hi)]
L.show_chart(charts.day_type_profile(dt_prof), key="cc_daytype")
L.note("The same synthetic profile by day type for the chosen location.")

st.subheader("Real-video detector status")
if status["state"] == "unavailable":
    st.error(status["message"])
else:
    st.info(status["message"])
st.markdown(
    f"- **Permitted clip files found:** {', '.join(clips) if clips else 'none'}. Whether a clip may be processed must be confirmed by the developer; "
    f"no clip is processed or shown here.\n"
    f"- **Model used:** none (no detector has run).\n"
    f"- **Privacy:** counts are aggregate people/vehicle movements only; no face or identity recognition and no person-level identifiers are kept.")
st.markdown("**Expected output schema** (what real detector output would contain; no values are shown because none exist)")
st.dataframe(pd.DataFrame(CC.EXPECTED_OUTPUT_SCHEMA, columns=["Column", "Type", "Meaning"]), hide_index=True, width="stretch")

L.what_this_means(N.cctv_meaning(names.get(peak["location_id"], peak["location_id"]) if peak is not None else None,
                                 int(peak["hour"]) if peak is not None else None, float(peak["mean_inbound_persons"]) if peak is not None else 0.0,
                                 status["state"] == "no_output"))
L.evidence_expander(
    sources=["cctv_hourly_profile (mean inbound persons per hour, from the synthetic `cctv_counts` stream)",
             "Environment diagnostics (installed detector packages, video files present)"],
    formulas=["Mean inbound persons per hour = sum of 5-minute inbound person counts in the hour, averaged over service dates of the day type."],
    assumptions=["The footfall profile is generated (measurement_method = synthetic) with a morning-peak pattern; it is not derived from video.",
                 "Counts from a real detector would need a manual spot-check against the clip before any accuracy claim.",
                 "Nothing on this page is live: it is a static, pre-generated demonstration stream.",
                 config.SIMULATION_BADGE_TEXT + "."],
    filters=f.describe(corridor=False))
