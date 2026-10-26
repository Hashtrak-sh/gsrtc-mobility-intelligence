"""CCTV Analytics: the SYNTHETIC footfall stream, and the honest status of the real-video detector."""
import json

import pandas as pd
import streamlit as st

import config
from modules import diagnostics
from modules.analytics import cctv as CC
from modules.data import io
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

st.subheader("Recorded clip: detector output")
st.caption("A separate evidence stream: counts from a pre-recorded clip, produced by an object detector, recorded at a different time and "
           "place from the synthetic ticket and footfall data above. The two are never combined. Nothing on this page is a live camera feed.")
out = CC.detector_output_status()
if out["state"] == "available":
    prov = out["provenance"]
    try:
        det = io.read_table(CC.DETECTOR_TABLE, "processed")
    except Exception:  # unreadable table must not take the page down
        det = pd.DataFrame()
else:
    prov, det = None, pd.DataFrame()

if not det.empty:
    seg = prov.get("segment", {})
    st.info("Real detector output on a pre-recorded clip (measurement_method = actual_detector). It is not synthetic and not a live feed. "
            "The clip is a public sample road-traffic video, location not in the pilot area; it is used only to demonstrate the counting method.")
    tot = det.groupby(["direction", "class"])["count"].sum().reset_index()
    inb = int(det[det["direction"] == "inbound"]["count"].sum())
    outb = int(det[det["direction"] == "outbound"]["count"].sum())
    # cards, not st.metric: the page contract allows at most four KPI metrics and section 1 already uses them
    c1, c2, c3 = st.columns(3)
    with c1:
        L.card("Inbound crossings (clip)", fmt.number(inb), meta="All counted classes, across the processed segment")
    with c2:
        L.card("Outbound crossings (clip)", fmt.number(outb), meta="All counted classes, across the processed segment")
    with c3:
        L.card("Segment processed", f"{seg.get('processed_s', 0):.0f} s", meta=f"{fmt.number(prov.get('frames_processed'))} frames passed to the detector")
    L.show_chart(charts.cctv_detector_minutes(det[det["count"] > 0] if det["count"].sum() else det), key="cc_det")
    if int(det["count"].sum()) == 0:
        st.warning("The detector recorded zero line crossings in this clip. That is a measured zero; see the method note on what the clip contains.")
    L.note("Per-minute line-crossing counts by class and direction. Minutes are clip-relative (minute 0 = start of the clip), not clock times.")
    st.dataframe(tot.rename(columns={"direction": "Direction", "class": "Class", "count": "Crossings"}), hide_index=True, width="stretch")
    m = prov.get("model", {})
    th = prov.get("thresholds", {})
    clip = prov.get("clip", {})
    v = prov.get("versions", {})
    st.markdown(
        f"**Method.** Model `{m.get('name')}` ({m.get('family')}); ultralytics {v.get('ultralytics')}, supervision {v.get('supervision')}; "
        f"confidence {th.get('conf')}, IoU {th.get('iou')}, image size {th.get('imgsz')}; every {prov.get('stride')}th frame, CPU.  \n"
        f"**Clip.** `{clip.get('filename')}` ({clip.get('duration_s', 0):.0f} s, {clip.get('width')}x{clip.get('height')}); processed "
        f"{seg.get('processed_s', 0):.0f} s from {seg.get('start_s', 0):.0f} s ({'full clip' if seg.get('full_clip') else 'partial segment'}) "
        f"in {prov.get('processing_seconds')} s.  \n"
        f"**Processed on.** {str(prov.get('generated_at_utc', ''))[:10]} (UTC). The clip's own recording time is unknown, so timestamps are clip-relative.  \n"
        f"**Counting line.** {prov.get('line_config', {}).get('description', 'see provenance')}")
    sc = out["spot_check"]
    st.markdown("**Spot check**")
    if sc:
        st.markdown(f"{sc.get('label', '')} Segment: {sc.get('segment', 'n/a')}. Detector count {sc.get('detector_count')}, "
                    f"reference count {sc.get('reference_count')}; {sc.get('result_text', '')}")
        for lim in sc.get("limitations", []):
            st.markdown(f"- {lim}")
    else:
        st.warning("No spot check has been recorded, so these counts are not validated and no accuracy is claimed.")
    video = config.PROCESSED_DIR / "cctv" / str(prov.get("annotated_video") or "")
    # Hosted deployments ship only a short browser-playable excerpt (described by a JSON sidecar), not the full annotated clip.
    excerpt = video.with_name(f"{video.stem}_excerpt.mp4")
    excerpt_meta = excerpt.with_suffix(".json")
    if prov.get("annotated_video") and (video.is_file() or excerpt.is_file()):
        excerpt_note = ""
        if not video.is_file():
            video = excerpt
            try:
                em = json.loads(excerpt_meta.read_text(encoding="utf-8"))
                lo, hi = int(em["start_s"]), int(em["start_s"] + em["duration_s"])
                excerpt_note = (f" Excerpt only: clip time {lo // 60:02d}:{lo % 60:02d}-{hi // 60:02d}:{hi % 60:02d} "
                                "(covers the spot-check window); the counts above are for the full clip.")
            except Exception:  # noqa: BLE001 - a missing sidecar only drops the excerpt note
                excerpt_note = " Excerpt only; the counts above are for the full clip."
        st.video(str(video))
        st.caption("Pre-recorded clip, not live. Detector boxes and counting line are drawn; no track identifiers are shown. The upper part of "
                   "person boxes is blurred, which is not reliable face anonymisation (missed detections are not blurred)." + excerpt_note)
else:
    if CC.detector_status(deps)["state"] == "unavailable" and not out["cv_env_exists"]:
        st.error("Detector output not available. " + status["message"])
    else:
        st.info("Detector output not available. No detector run has produced output yet, so no real counts are shown.")
    st.markdown(f"- **Permitted clip files found:** {', '.join(clips) if clips else 'none'}.\n"
                f"- **CV environment (`.venv-cv`):** {'present' if out['cv_env_exists'] else 'not found (create it; see README)'}.\n"
                f"- **Privacy:** aggregate people/vehicle crossings only; no face or identity recognition and no person-level identifiers are kept.")
    st.markdown("Run the detector in the separate CV environment, then reload this page:")
    st.code(out["command"], language="bash")
    st.markdown("**Expected output schema** (no values are shown because none exist)")
    st.dataframe(pd.DataFrame(CC.EXPECTED_OUTPUT_SCHEMA, columns=["Column", "Type", "Meaning"]), hide_index=True, width="stretch")

meaning = N.cctv_meaning(names.get(peak["location_id"], peak["location_id"]) if peak is not None else None,
                         int(peak["hour"]) if peak is not None else None, float(peak["mean_inbound_persons"]) if peak is not None else 0.0,
                         status["state"] == "no_output")
if not det.empty:
    meaning = meaning.split(" The real-video detector")[0] + (" Separately, a real detector was run on one pre-recorded clip; its counts are a different "
                                                              "evidence stream and are not comparable with the synthetic profile.")
L.what_this_means(meaning)
L.evidence_expander(
    sources=["cctv_hourly_profile (mean inbound persons per hour, from the synthetic `cctv_counts` stream)",
             "Environment diagnostics (installed detector packages, video files present)",
             "cctv_detector_counts and its provenance file (real detector output on a pre-recorded clip, when present)"],
    formulas=["Mean inbound persons per hour = sum of 5-minute inbound person counts in the hour, averaged over service dates of the day type."],
    assumptions=["The footfall profile is generated (measurement_method = synthetic) with a morning-peak pattern; it is not derived from video.",
                 "Counts from a real detector would need a manual spot-check against the clip before any accuracy claim.",
                 "Nothing on this page is live: it is a static, pre-generated demonstration stream.",
                 config.SIMULATION_BADGE_TEXT + "."],
    filters=f.describe(corridor=False))
