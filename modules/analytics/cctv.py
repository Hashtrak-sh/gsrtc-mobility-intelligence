"""Small CCTV summary: mean inbound person count per hour per average day, by location and day type.

Works on the SYNTHETIC ``cctv_counts`` stream only (``measurement_method = synthetic``). Aggregate counts, no identities.
"""
from __future__ import annotations

import json

import pandas as pd

import config
from modules.analytics.common import SOURCE_TYPE
from modules.data import io

COLUMNS = ["location_id", "day_type", "hour", "mean_inbound_persons", "n_days", "measurement_method", "source_type"]


def cctv_hourly_profile(cctv: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Mean inbound person count per hour per day (rows: location x day_type x hour)."""
    if cctv.empty or trips.empty:
        return pd.DataFrame(columns=COLUMNS)
    c = cctv[(cctv["class"] == "person") & (cctv["direction"] == "inbound")].copy()
    cal = trips[["service_date", "day_type"]].drop_duplicates()
    cal = cal.assign(date=pd.to_datetime(cal["service_date"]))[["date", "day_type"]]
    c["date"] = c["timestamp_min"].dt.normalize()
    c["hour"] = c["timestamp_min"].dt.hour
    c = c.merge(cal, on="date", how="inner")
    per = c.groupby(["location_id", "day_type", "date", "hour"])["count"].sum().reset_index()
    g = per.groupby(["location_id", "day_type", "hour"]).agg(mean_inbound_persons=("count", "mean"), n_days=("date", "nunique")).reset_index()
    methods = "|".join(sorted(cctv["measurement_method"].dropna().unique()))
    g["measurement_method"] = methods
    g["source_type"] = SOURCE_TYPE
    return g[COLUMNS]


# ---------------------------------------------------------------------------
# Detector status (presentation support; no detection happens here)
# ---------------------------------------------------------------------------
DETECTOR_PACKAGES = ("ultralytics", "supervision", "cv2")

# Expected columns of real detector output (docs/DATA_SCHEMA.md `cctv_counts`); shown as a schema, never with invented counts.
EXPECTED_OUTPUT_SCHEMA = [
    ("location_id", "string", "Camera or location label (not a person identifier)"),
    ("timestamp_min", "datetime", "Start of the minute bucket"),
    ("direction", "string", "inbound / outbound / unknown"),
    ("class", "string", "person / car / two_wheeler / auto / bus / truck / other"),
    ("count", "integer", "Aggregate count in the bucket (>= 0)"),
    ("measurement_method", "string", "actual_detector for real inference (this prototype's synthetic stream uses synthetic)"),
    ("source_type", "string", "Provenance of the counts"),
]


def detector_status(available: dict[str, bool]) -> dict:
    """Detector availability from a package -> installed map. ``state`` is ``unavailable`` or ``no_output``.

    Even with every dependency installed, no counts exist until a detector run has produced output, so the dashboard never
    reports a detector result from this function.
    """
    missing = [p for p in DETECTOR_PACKAGES if not available.get(p, False)]
    if missing:
        return {"state": "unavailable", "missing": missing,
                "message": "Detector unavailable: required package(s) not installed: " + ", ".join(missing) + "."}
    return {"state": "no_output", "missing": [],
            "message": "Detector packages are installed, but no detector output has been produced, so no real counts are shown."}


# ---------------------------------------------------------------------------
# M6-CCTV: real detector output on the permitted pre-recorded clip (separate stream, never merged with synthetic cctv_counts)
# ---------------------------------------------------------------------------
DETECTOR_TABLE = "cctv_detector_counts"
SPOT_CHECK_FILE = "cctv_spot_check.json"
CV_RUN_COMMAND = (".venv-cv/Scripts/python.exe -m modules.cv.count_video --video data/raw/video/a-morning-on-route-r014.mp4 "
                  "--config modules/cv/configs/a-morning-on-route-r014.lines.json --stride 3 --annotate")


def cv_env_exists() -> bool:
    """Whether a separate CV virtualenv (``.venv-cv``) exists. Checked by path only; nothing is imported."""
    return any((config.ROOT_DIR / ".venv-cv" / sub).exists() for sub in ("Scripts/python.exe", "bin/python"))


def detector_output_status() -> dict:
    """``available`` if the detector output table AND its provenance sidecar exist, else ``no_output``. Never imports heavy libs."""
    table_ok = io.table_exists(DETECTOR_TABLE, "processed")
    prov_path = io.provenance_path(DETECTOR_TABLE, "processed")
    prov = None
    if prov_path.is_file():
        try:
            prov = json.loads(prov_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prov = None
    state = "available" if table_ok and prov is not None else "no_output"
    spot = None
    sp = io.layer_dir("processed") / SPOT_CHECK_FILE
    if sp.is_file():
        try:
            spot = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            spot = None
    return {"state": state, "provenance": prov, "spot_check": spot, "cv_env_exists": cv_env_exists(),
            "command": CV_RUN_COMMAND}
