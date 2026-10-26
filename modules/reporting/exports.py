"""CSV exports of processed tables filtered by the active dashboard filters, with a provenance header.

Each CSV starts with ``#``-prefixed comment lines (source, seed, generation time, filters, limitations, row count) followed
by the data; load with ``pandas.read_csv(path, comment="#")``. A combined provenance JSON is also available. Filtering reuses
``modules.ui.filters`` so the exported rows equal what the dashboard shows. Generation timestamps come from the provenance
sidecars (never invented here).
"""
from __future__ import annotations

import io as _io
import json
from typing import Any, Callable

import pandas as pd

import config
from modules.ui import filters as F

# name -> (layer, description, scope note)
EXPORTS: dict[str, tuple[str, str, str]] = {
    "route_summary": ("processed", "Route KPIs over all 42 synthetic days (single source of truth for route KPIs)", "corridor"),
    "route_scores": ("processed", "Transparent rule-based route potential scores with weights (demo-v1)", "corridor"),
    "recommendations": ("processed", "Rule-generated recommendations with evidence, assumptions, impact and constraints", "corridor"),
    "hourly_demand_supply": ("processed", "Average-day demand vs seats by route-direction/corridor and hour", "corridor, day type, hours"),
    "od_flows": ("processed", "Zone-to-zone passenger flows per average day and hour", "corridor, day type, hours"),
    "stop_occupancy": ("processed", "Average-bus occupancy progression by stop", "corridor, day type, hours"),
    "cctv_hourly_profile": ("processed", "Mean inbound persons per hour from the SYNTHETIC CCTV stream", "day type, hours"),
}

LIMITATIONS = [
    f"{config.SIMULATION_BADGE_TEXT}: not real GSRTC measurements, schedules, fares or competitor data.",
    "Contribution = ticket revenue - operating cost; it is not profit.",
    "Demand from tickets is censored at capacity, so gaps are lower bounds; private-market demand is an assumption.",
]


def filter_table(name: str, df: pd.DataFrame, f: F.Filters, ctx: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Apply the dashboard filters to one exportable table. ``ctx`` needs ``route_summary``, ``route_stops``, ``stops``."""
    rs = ctx["route_summary"]
    if name in ("route_summary",):
        return F.scope_routes(df, f.corridor)
    if name == "route_scores":
        return F.filter_by_routes(df, rs, f.corridor)
    if name == "recommendations":
        return F.filter_recommendations(df, f, rs)
    if name == "hourly_demand_supply":
        return F.filter_hourly(df, f, rs)
    if name == "od_flows":
        return F.filter_od(df, f, rs, ctx["route_stops"], ctx["stops"])
    if name == "stop_occupancy":
        return F.filter_stop_occupancy(df, f, rs)
    if name == "cctv_hourly_profile":
        return F.filter_cctv(df, f)
    raise KeyError(f"No export filter defined for {name!r}")


def provenance_header(name: str, rows: int, f: F.Filters, prov: dict | None) -> list[str]:
    p = prov or {}
    lines = [
        f"# GSRTC Mobility Intelligence export: {name}",
        f"# {config.SIMULATION_BADGE_TEXT}",
        f"# source_type: {p.get('source_type', 'unknown')}",
        f"# seed: {p.get('seed', 'unknown')}",
        f"# generated_at: {p.get('generated_at', 'unknown')}",
        f"# filters: {f.describe()}",
        f"# rows: {rows}",
    ]
    lines += [f"# limitation: {x}" for x in LIMITATIONS]
    return lines


def to_csv_bytes(name: str, df: pd.DataFrame, f: F.Filters, prov: dict | None) -> bytes:
    buf = _io.StringIO()
    for line in provenance_header(name, len(df), f, prov):
        buf.write(line + "\n")
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def provenance_bundle(f: F.Filters, provs: dict[str, dict | None], row_counts: dict[str, int]) -> bytes:
    doc: dict[str, Any] = {"label": config.SIMULATION_BADGE_TEXT, "filters": f.as_dict(), "limitations": LIMITATIONS,
                           "tables": {n: {"rows": row_counts.get(n), "provenance": provs.get(n)} for n in row_counts}}
    return json.dumps(doc, indent=2, sort_keys=True, default=str).encode("utf-8")


def build_exports(tables: dict[str, pd.DataFrame], f: F.Filters, ctx: dict[str, pd.DataFrame],
                  prov_loader: Callable[[str], dict | None]) -> dict[str, tuple[pd.DataFrame, bytes]]:
    """Filtered frame and CSV bytes per available table (tables that are missing are simply absent)."""
    out = {}
    for name, df in tables.items():
        fdf = filter_table(name, df, f, ctx)
        out[name] = (fdf, to_csv_bytes(name, fdf, f, prov_loader(name)))
    return out
