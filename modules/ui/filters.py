"""Shared dashboard filters: corridor, day type, hour range.

Semantics (identical on every page that shows the filter):

* **Corridor** - ``All`` (every route), ``Rajkot local network`` (local routes L01-L10) or one intercity corridor
  (routes whose ``routes.corridor`` equals it). Route-level tables are filtered by route. Corridor-level rows of
  ``hourly_demand_supply`` are filtered by ``corridor`` (and dropped for the local network). ``od_flows`` has no route
  column, so an O-D pair belongs to a scope when both zones are served by the scope's routes and, for an intercity
  corridor, the pair is not entirely inside the zones served by local routes. Consequence: a pair served by several
  corridors (e.g. Rajkot-Junagadh, on the Somnath and Junagadh corridors) appears under each, so corridor O-D totals can exceed that
  corridor's route boardings; the local network and All scopes reconcile with route_summary.
* **Day type** - ``weekday`` / ``weekend`` / ``festival``. Applies to tables built per day type (``hourly_demand_supply``,
  ``stop_occupancy``, ``od_flows``, ``cctv_hourly_profile``). Route-level KPIs (``route_summary``, ``route_scores``)
  always span the whole 42-day synthetic period, so every KPI agrees across pages; recommendations are pre-computed for
  the day types stated on each card and are filtered by corridor only.
* **Hours** - a half-open clock window ``[start, end)`` in 24-hour time (e.g. 07:00-10:00 = hours 7, 8, 9). It applies
  to hour-level tables (departure hour for supply/occupancy, boarding hour for O-D, clock hour for CCTV).

The selection lives in ``st.session_state`` under stable keys (``flt_corridor``, ``flt_day_type``, ``flt_hours``) so it
persists across pages. The sidebar widgets use separate keys and are re-synchronised from these canonical keys on every
run, which also keeps the selection when a page that hides a widget is visited in between.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

import config
from modules.ui import fmt

ALL = "All"
LOCAL = "Rajkot local network"
DAY_TYPES: tuple[str, ...] = ("weekday", "weekend", "festival")
CORRIDOR_OPTIONS: tuple[str, ...] = (ALL, LOCAL, *config.INTERCITY_CORRIDORS)

OD_CORRIDOR_NOTE = ("O-D flows are not tagged by route. For an intercity corridor, any pair whose two zones both lie on that corridor's routes is included, "
                    "so pairs that other corridors also serve (for example Rajkot to Junagadh) appear under each of them and the total can exceed "
                    "the corridor's route boardings.")

KEY_CORRIDOR = "flt_corridor"
KEY_DAY = "flt_day_type"
KEY_HOURS = "flt_hours"


@dataclass(frozen=True)
class Filters:
    corridor: str = ALL
    day_type: str = config.PEAK_DAY_TYPE
    hour_lo: int = 0
    hour_hi: int = 24  # exclusive

    def __post_init__(self) -> None:
        if self.corridor not in CORRIDOR_OPTIONS:
            raise ValueError(f"Unknown corridor {self.corridor!r}")
        if self.day_type not in DAY_TYPES:
            raise ValueError(f"Unknown day type {self.day_type!r}")
        if not (0 <= self.hour_lo < self.hour_hi <= 24):
            raise ValueError(f"Invalid hour window [{self.hour_lo}, {self.hour_hi})")

    @property
    def hours_label(self) -> str:
        return fmt.hour_window(self.hour_lo, self.hour_hi)

    def describe(self, *, corridor: bool = True, day_type: bool = True, hours: bool = True) -> str:
        parts = []
        if corridor:
            parts.append(f"Corridor: {self.corridor}")
        if day_type:
            parts.append(f"Day type: {self.day_type}")
        if hours:
            parts.append(f"Hours: {self.hours_label}")
        return " | ".join(parts)

    def as_dict(self) -> dict:
        return {"corridor": self.corridor, "day_type": self.day_type, "hours": self.hours_label}


# ---------------------------------------------------------------------------
# Pure filter functions
# ---------------------------------------------------------------------------
def scope_routes(routes: pd.DataFrame, corridor: str) -> pd.DataFrame:
    """Rows of a route-level frame (needs ``route_type`` and ``corridor`` columns) inside the corridor scope."""
    if corridor == ALL:
        return routes
    if corridor == LOCAL:
        return routes[routes["route_type"] == "local"]
    return routes[routes["corridor"] == corridor]


def route_ids(routes: pd.DataFrame, corridor: str) -> list[str]:
    return sorted(scope_routes(routes, corridor)["route_id"].tolist())


def filter_by_routes(df: pd.DataFrame, routes: pd.DataFrame, corridor: str) -> pd.DataFrame:
    """Keep rows of a table with a ``route_id`` column whose route is in the scope."""
    if corridor == ALL:
        return df
    return df[df["route_id"].isin(route_ids(routes, corridor))]


def _hours(df: pd.DataFrame, f: Filters, col: str = "hour") -> pd.Series:
    return (df[col] >= f.hour_lo) & (df[col] < f.hour_hi)


def filter_hourly(hourly: pd.DataFrame, f: Filters, routes: pd.DataFrame, *, hours: bool = True) -> pd.DataFrame:
    """Apply corridor + day type (+ hours) to ``hourly_demand_supply`` (both row levels)."""
    h = hourly[hourly["day_type"] == f.day_type]
    if hours:
        h = h[_hours(h, f)]
    if f.corridor == ALL:
        return h
    if f.corridor == LOCAL:
        return h[(h["level"] == "route_direction") & h["route_id"].isin(route_ids(routes, LOCAL))]
    keep = ((h["level"] == "route_direction") & h["route_id"].isin(route_ids(routes, f.corridor))) | (
        (h["level"] == "corridor") & (h["corridor"] == f.corridor))
    return h[keep]


def filter_stop_occupancy(so: pd.DataFrame, f: Filters, routes: pd.DataFrame) -> pd.DataFrame:
    s = filter_by_routes(so, routes, f.corridor)
    s = s[s["day_type"] == f.day_type]
    return s[_hours(s, f)]


def zones_for_routes(route_stops: pd.DataFrame, stops: pd.DataFrame, ids: list[str]) -> set[str]:
    sid = route_stops.loc[route_stops["route_id"].isin(ids), "stop_id"].unique()
    return set(stops.loc[stops["stop_id"].isin(sid), "zone_id"])


def filter_od(od: pd.DataFrame, f: Filters, routes: pd.DataFrame, route_stops: pd.DataFrame, stops: pd.DataFrame,
              *, hours: bool = True) -> pd.DataFrame:
    """Apply day type, hours and corridor scope (zone membership; see module docstring) to ``od_flows``."""
    o = od[od["day_type"] == f.day_type]
    if hours:
        o = o[_hours(o, f)]
    if f.corridor == ALL:
        return o
    zs = zones_for_routes(route_stops, stops, route_ids(routes, f.corridor))
    inside = o["origin_zone_id"].isin(zs) & o["dest_zone_id"].isin(zs)
    if f.corridor == LOCAL:
        return o[inside]
    local_zs = zones_for_routes(route_stops, stops, route_ids(routes, LOCAL))
    both_local = o["origin_zone_id"].isin(local_zs) & o["dest_zone_id"].isin(local_zs)
    return o[inside & ~both_local]


def filter_cctv(prof: pd.DataFrame, f: Filters) -> pd.DataFrame:
    p = prof[prof["day_type"] == f.day_type]
    return p[_hours(p, f)]


def filter_recommendations(recs: pd.DataFrame, f: Filters, routes: pd.DataFrame) -> pd.DataFrame:
    """Recommendations whose route is in the corridor scope (day type/hours are stated on each recommendation)."""
    if f.corridor == ALL:
        return recs
    return recs[recs["route_id"].isin(route_ids(routes, f.corridor))]


# ---------------------------------------------------------------------------
# Session state and sidebar
# ---------------------------------------------------------------------------
def _init_state() -> None:
    st.session_state.setdefault(KEY_CORRIDOR, ALL)
    st.session_state.setdefault(KEY_DAY, config.PEAK_DAY_TYPE)
    st.session_state.setdefault(KEY_HOURS, (0, 24))


def current() -> Filters:
    """The active filters from session state (invalid stored values fall back to defaults)."""
    _init_state()
    lo, hi = st.session_state[KEY_HOURS]
    try:
        return Filters(st.session_state[KEY_CORRIDOR], st.session_state[KEY_DAY], int(lo), int(hi))
    except ValueError:
        return Filters()


def _store(canon: str, widget: str) -> None:
    st.session_state[canon] = st.session_state[widget]


def sidebar(show: tuple[str, ...] = ("corridor", "day_type", "hours")) -> Filters:
    """Render the shared filters in the sidebar (only those named in ``show``) and return the active selection."""
    _init_state()
    cur = current()
    st.session_state[KEY_CORRIDOR], st.session_state[KEY_DAY] = cur.corridor, cur.day_type
    st.session_state[KEY_HOURS] = (cur.hour_lo, cur.hour_hi)
    with st.sidebar:
        st.markdown("**Filters**")
        if "corridor" in show:
            st.session_state["w_corridor"] = cur.corridor
            st.selectbox("Corridor", CORRIDOR_OPTIONS, key="w_corridor", on_change=_store, args=(KEY_CORRIDOR, "w_corridor"),
                         help="All routes, the Rajkot local network, or one intercity corridor.")
        if "day_type" in show:
            st.session_state["w_day_type"] = cur.day_type
            st.selectbox("Day type", DAY_TYPES, key="w_day_type", on_change=_store, args=(KEY_DAY, "w_day_type"),
                         help="Applies to hourly, stop-level, O-D and CCTV views. Route KPIs always cover all 42 days.")
        if "hours" in show:
            st.session_state["w_hours"] = (cur.hour_lo, cur.hour_hi)
            st.slider("Hours of day (24-hour clock)", 0, 24, key="w_hours", on_change=_store, args=(KEY_HOURS, "w_hours"),
                      format="%02d:00", help="Half-open window: start included, end excluded.")
    return current()
