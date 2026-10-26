"""Plotly map builders for route paths and candidates (pure functions: frames in, ``go.Figure`` out).

Lines are drawn with ``Scattermap`` on the ``open-street-map`` style. If the tile server is unreachable the tiles stay blank
but the lines and stop markers still render. Real OSM road geometry is a solid line; a straight-line fallback is dashed-looking
(dotted marker line) and in the warning colour, so the two are never confused.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go

ATTRIBUTION = "Map and roads (c) OpenStreetMap contributors (ODbL); routes, stops and demand are simulated"
OSM_COLOUR = "#1f4e79"
FALLBACK_COLOUR = "#c4551b"
EXISTING_COLOUR = "#8a949e"
CANDIDATE_COLOURS = ["#1f4e79", "#2a8a8a", "#b5a36a", "#7a4b9a", "#5b87b3", "#c4551b", "#3b7d3b", "#8a949e"]


def _fit(lons: Sequence[float], lats: Sequence[float]) -> tuple[dict, float]:
    lo, hi, la, lb = min(lons), max(lons), min(lats), max(lats)
    span = max(hi - lo, (lb - la) * 1.3, 0.01)
    zoom = max(4.0, min(13.0, math.log2(360.0 / span) - 0.6))
    return {"lon": (lo + hi) / 2, "lat": (la + lb) / 2}, zoom


def _line(fig: go.Figure, coords: list[list[float]], name: str, source: str, colour: str, width: float, hover: str) -> None:
    fallback = source != "openstreetmap"
    fig.add_trace(go.Scattermap(
        lon=[c[0] for c in coords], lat=[c[1] for c in coords], mode="lines", name=name, hovertemplate=hover + "<extra></extra>",
        line=dict(width=width, color=FALLBACK_COLOUR if fallback else colour),
        legendgroup=name, showlegend=True))


def route_map(paths: Sequence[dict], stops: pd.DataFrame | None = None, *, height: int = 460, selected: str | None = None) -> go.Figure:
    """``paths``: dicts with ``name``, ``coords`` ([[lon, lat], ...]), ``source``, optional ``colour``/``role`` ('existing').

    ``stops``: columns stop_id, name, lat, lon, seq (marker labelled with the sequence number).
    """
    fig = go.Figure()
    lons: list[float] = []
    lats: list[float] = []
    for i, p in enumerate(paths):
        existing = p.get("role") == "existing"
        colour = EXISTING_COLOUR if existing else p.get("colour") or CANDIDATE_COLOURS[i % len(CANDIDATE_COLOURS)]
        width = 3 if existing else (6 if p["name"] == selected else 4)
        label = p["name"] + (" (road path: OpenStreetMap)" if p["source"] == "openstreetmap" else " (STRAIGHT-LINE FALLBACK, not road geometry)")
        _line(fig, p["coords"], label, p["source"], colour, width, p["name"])
        lons += [c[0] for c in p["coords"]]
        lats += [c[1] for c in p["coords"]]
    if stops is not None and len(stops):
        fig.add_trace(go.Scattermap(
            lon=stops["lon"], lat=stops["lat"], mode="markers+text", text=stops["seq"].astype(str), textposition="top right",
            marker=dict(size=11, color="#ffffff", opacity=1.0), name="Stops (synthetic, numbered in order)",
            customdata=stops[["stop_id", "name"]].to_numpy(), hovertemplate="%{text}. %{customdata[1]} (%{customdata[0]})<extra></extra>"))
        fig.add_trace(go.Scattermap(lon=stops["lon"], lat=stops["lat"], mode="markers", marker=dict(size=7, color="#1c2833"),
                                    hoverinfo="skip", showlegend=False))
        lons += list(stops["lon"])
        lats += list(stops["lat"])
    if lons:
        centre, zoom = _fit(lons, lats)
    else:
        centre, zoom = {"lon": 70.8, "lat": 22.3}, 9.0
    fig.update_layout(map=dict(style="open-street-map", center=centre, zoom=zoom), height=height,
                      margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="white",
                      legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01, bgcolor="rgba(255,255,255,0.85)",
                                  font=dict(size=11)))
    return fig


def demand_heatmap(act: pd.DataFrame, metric_col: str, *, label: str, city: bool = True, height: int = 520) -> go.Figure:
    """Geographic demand heatmap: ``go.Densitymap`` (weighted by ``metric_col``) plus ``go.Scattermap`` bubbles with hover.

    ``act``: columns stop_id, name, lat, lon, coord_source, boardings_per_day, alightings_per_day and ``metric_col``
    (passengers/day). Stops with missing coordinates are dropped. The density uses the absolute value of ``metric_col``
    (net can be negative); net bubbles are coloured by sign. ``city=True`` uses a tight density radius and caps the zoom
    (callers pass the Rajkot city subset); ``city=False`` fits the whole network with a smaller radius.
    """
    d = act.dropna(subset=["lat", "lon", metric_col]).copy()
    fig = go.Figure()
    if d.empty:
        fig.update_layout(map=dict(style="open-street-map", center={"lon": 70.8, "lat": 22.3}, zoom=9.0), height=height,
                          margin=dict(l=0, r=0, t=0, b=0))
        return fig
    mag = d[metric_col].abs()
    top = float(mag.max()) or 1.0
    fig.add_trace(go.Densitymap(
        lon=d["lon"], lat=d["lat"], z=mag, radius=38 if city else 26, opacity=0.65, colorscale="YlOrRd", zmin=0,
        name="Density", showscale=True, hoverinfo="skip",
        colorbar=dict(title=dict(text=f"{label}<br>(simulated)", font=dict(size=11)), thickness=12, len=0.6)))
    sizes = ((mag / top).pow(0.5) * (38 if city else 30)).clip(lower=6)
    colours = d[metric_col].map(lambda v: "#c4551b" if v < 0 else "#1f4e79") if metric_col == "net_per_day" else "#1f4e79"
    fig.add_trace(go.Scattermap(
        lon=d["lon"], lat=d["lat"], mode="markers", name="Stops (size = value)", showlegend=False,
        marker=dict(size=sizes, color=colours, opacity=0.55),
        customdata=d[["name", "boardings_per_day", "alightings_per_day", "coord_source", "stop_id"]].to_numpy(),
        hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[4]})<br>Boardings: %{customdata[1]:,.0f} / day (simulated)"
                       "<br>Alightings: %{customdata[2]:,.0f} / day (simulated)"
                       "<br>Stop position source: %{customdata[3]}<extra></extra>")))
    centre, zoom = _fit(list(d["lon"]), list(d["lat"]))
    if city:
        zoom = min(zoom, 12.0)
    fig.update_layout(map=dict(style="open-street-map", center=centre, zoom=zoom), height=height,
                      margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="white")
    return fig
