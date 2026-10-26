"""Plain (non-Streamlit) table and provenance loading for the PDF report, the LLM summary and the CLI tools.

Reads the same parquet files the dashboard reads (``modules.data.io``), so numbers agree. Missing tables are simply absent
from the returned dict (never replaced by plausible values); callers state "not available" for them.
"""
from __future__ import annotations

import json

import pandas as pd

from modules.data import io

# (layer, name). Everything the report/LLM summary may use; each is optional except where a section needs it.
REPORT_TABLES: tuple[tuple[str, str], ...] = (
    ("processed", "route_summary"), ("processed", "route_scores"), ("processed", "route_kpis"),
    ("processed", "recommendations"), ("processed", "hourly_demand_supply"), ("processed", "od_flows"),
    ("processed", "stop_occupancy"), ("processed", "competition_analysis"), ("processed", "ridership_model_metrics"),
    ("processed", "survey_model_metrics"), ("processed", "survey_model_coefficients"), ("processed", "route_candidates"),
    ("processed", "route_paths"), ("processed", "predictions"), ("processed", "cctv_hourly_profile"),
    ("synthetic", "routes"), ("synthetic", "stops"), ("synthetic", "zones"), ("synthetic", "route_stops"),
    ("synthetic", "survey_responses"), ("synthetic", "competitor_services"), ("synthetic", "reviews"),
    ("synthetic", "assets_assessment"), ("synthetic", "digital_assessment"),
)

LAYER_OF: dict[str, str] = {name: layer for layer, name in REPORT_TABLES}


def load_tables(base_dir=None) -> dict[str, pd.DataFrame]:
    """Every available table in :data:`REPORT_TABLES`, keyed by name."""
    out: dict[str, pd.DataFrame] = {}
    for layer, name in REPORT_TABLES:
        if io.table_exists(name, layer, base_dir):
            out[name] = io.read_table(name, layer, base_dir)
    return out


def provenance(name: str, layer: str | None = None, base_dir=None) -> dict | None:
    """Provenance sidecar as a dict (None if absent or unreadable)."""
    layer = layer or LAYER_OF.get(name, "processed")
    p = io.provenance_path(name, layer, base_dir)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def data_generated_at(tables: dict[str, pd.DataFrame] | None = None) -> str:
    """Generation time of the processed data (``route_summary`` sidecar) or ``unknown``."""
    p = provenance("route_summary", "processed") or {}
    return str(p.get("generated_at") or p.get("generated_at_utc") or "unknown")


def data_seed() -> object:
    p = provenance("route_summary", "processed") or {}
    return p.get("seed", "unknown")
