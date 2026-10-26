"""Parquet table I/O with layered directories (raw / synthetic / processed).

``base_dir`` overrides the data root (used by tests); by default the paths in
``config.LAYER_DIRS`` are used. Pages and analytics should go through these
helpers rather than building paths by hand.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

import config
from modules.data.provenance import Provenance

LAYERS: tuple[str, ...] = ("raw", "synthetic", "processed")

# Table names from docs/DATA_SCHEMA.md.
SOURCE_TABLES: tuple[str, ...] = (
    "zones", "stops", "routes", "route_stops", "trips", "tickets", "cctv_counts",
    "survey_responses", "competitor_services", "reviews",
    "assets_assessment", "digital_assessment",
)
DERIVED_TABLES: tuple[str, ...] = (
    "route_kpis", "route_summary", "hourly_demand_supply", "stop_occupancy", "od_flows", "route_scores",
    "cctv_hourly_profile", "route_paths", "route_candidates", "predictions", "recommendations", "competition_analysis",
    "ridership_model_metrics", "ridership_feature_importance", "baseline_forecast",  # M6-ML
)
EXPECTED_TABLES: dict[str, tuple[str, ...]] = {
    "synthetic": SOURCE_TABLES,
    "processed": DERIVED_TABLES,
}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def layer_dir(layer: str, base_dir: Path | str | None = None) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Unknown layer {layer!r}; expected one of {LAYERS}")
    if base_dir is None:
        return config.LAYER_DIRS[layer]
    return Path(base_dir) / layer


def table_path(name: str, layer: str, base_dir: Path | str | None = None) -> Path:
    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid table name {name!r}; use lowercase letters, digits, underscores")
    return layer_dir(layer, base_dir) / f"{name}.parquet"


def provenance_path(name: str, layer: str, base_dir: Path | str | None = None) -> Path:
    p = table_path(name, layer, base_dir)
    return p.with_name(f"{name}.provenance.json")


def table_exists(name: str, layer: str, base_dir: Path | str | None = None) -> bool:
    return table_path(name, layer, base_dir).is_file()


def read_table(name: str, layer: str, base_dir: Path | str | None = None) -> pd.DataFrame:
    """Read a parquet table. Raises FileNotFoundError if it has not been generated."""
    p = table_path(name, layer, base_dir)
    if not p.is_file():
        raise FileNotFoundError(
            f"Table '{name}' not found in layer '{layer}' ({p}). Generate the data first."
        )
    return pd.read_parquet(p)


def write_table(
    df: pd.DataFrame,
    name: str,
    layer: str,
    base_dir: Path | str | None = None,
    provenance: Provenance | None = None,
) -> Path:
    """Write ``df`` as parquet (plus optional provenance JSON sidecar). Returns the path."""
    p = table_path(name, layer, base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    if provenance is not None:
        provenance_path(name, layer, base_dir).write_text(provenance.to_json(), encoding="utf-8")
    return p


def read_provenance(name: str, layer: str, base_dir: Path | str | None = None) -> Provenance | None:
    p = provenance_path(name, layer, base_dir)
    return Provenance.from_json(p.read_text(encoding="utf-8")) if p.is_file() else None


def missing_tables(layer: str, base_dir: Path | str | None = None) -> list[str]:
    """Expected tables (per DATA_SCHEMA.md) not yet present in a layer."""
    return [t for t in EXPECTED_TABLES.get(layer, ()) if not table_exists(t, layer, base_dir)]
