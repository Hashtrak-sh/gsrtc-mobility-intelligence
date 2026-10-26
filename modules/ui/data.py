"""Cached data access for the dashboard.

Pages never regenerate data and never touch the network: they only read parquet tables written by
``python -m modules.data_gen.generate`` and ``python -m modules.analytics.run``.

Cache invalidation: ``st.cache_data`` entries are keyed on (layer, table name, resolved file path, file mtime in ns).
Re-running the generator/analytics rewrites the file, the mtime changes, and the next page run reads the new table with
no restart. A missing table raises :class:`DataUnavailable` (never an empty frame that looks like real data).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from modules.data import io


class DataUnavailable(Exception):
    """One or more required tables have not been generated."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("Missing tables: " + ", ".join(missing))


def _stamp(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


@st.cache_data(show_spinner=False)
def _read(layer: str, name: str, path: str, mtime_ns: int) -> pd.DataFrame:  # noqa: ARG001 - mtime_ns is the cache key
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _read_json(path: str, mtime_ns: int) -> dict:  # noqa: ARG001
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(name: str, layer: str) -> pd.DataFrame:
    """Return a table (a cached copy) or raise :class:`DataUnavailable`."""
    p = io.table_path(name, layer)
    stamp = _stamp(p)
    if stamp is None:
        raise DataUnavailable([f"{layer}/{name}"])
    return _read(layer, name, str(p), stamp)


def try_load(name: str, layer: str) -> pd.DataFrame | None:
    try:
        return load(name, layer)
    except DataUnavailable:
        return None


def load_many(required: Iterable[tuple[str, str]]) -> dict[str, pd.DataFrame]:
    """Load ``(layer, name)`` pairs keyed by table name; raise one :class:`DataUnavailable` listing all missing."""
    req = list(required)
    missing = [f"{layer}/{name}" for layer, name in req if _stamp(io.table_path(name, layer)) is None]
    if missing:
        raise DataUnavailable(missing)
    return {name: load(name, layer) for layer, name in req}


def provenance(name: str, layer: str) -> dict | None:
    """Provenance sidecar as a dict, or None if absent/unreadable."""
    p = io.provenance_path(name, layer)
    stamp = _stamp(p)
    if stamp is None:
        return None
    try:
        return _read_json(str(p), stamp)
    except (OSError, ValueError):
        return None


def zone_names() -> dict[str, str]:
    z = try_load("zones", "synthetic")
    return {} if z is None else dict(zip(z["zone_id"], z["name"]))


def stop_names() -> dict[str, str]:
    s = try_load("stops", "synthetic")
    return {} if s is None else dict(zip(s["stop_id"], s["name"]))
