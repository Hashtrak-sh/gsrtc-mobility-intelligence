"""Figures for the Operations Replay page (frames in, go.Figure out). Simulated data for demonstration."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from modules.analytics.replay import clock_label
from modules.routing import maps
from modules.ui import charts


def replay_map(stops: pd.DataFrame, boardings: pd.Series, buses: pd.DataFrame, *, height: int = 460) -> go.Figure:
    """Stops sized by boardings in the last hour, plus estimated bus positions (not GPS)."""
    s = stops.copy()
    s["b"] = s["stop_id"].map(boardings).fillna(0)
    top = max(float(s["b"].max()), 1.0)
    fig = go.Figure()
    fig.add_trace(go.Scattermap(
        lon=s["lon"], lat=s["lat"], mode="markers", name="Stops (size = boardings in last hour)",
        marker=dict(size=8 + 30 * np.sqrt(s["b"] / top), color=charts.ACCENT, opacity=0.55),
        customdata=np.stack([s["name"], s["b"]], axis=1),
        hovertemplate="%{customdata[0]}<br>Boardings in last hour: %{customdata[1]:,.0f}<extra></extra>"))
    if len(buses):
        fig.add_trace(go.Scattermap(
            lon=buses["lon"], lat=buses["lat"], mode="markers", name="Buses in service (estimated position)",
            marker=dict(size=9, color=charts.WARN), customdata=buses[["route_id", "progress"]].to_numpy(),
            hovertemplate="Route %{customdata[0]}<br>Trip progress (time-based estimate): %{customdata[1]:.0%}<extra></extra>"))
    centre, zoom = maps._fit(list(s["lon"]), list(s["lat"]))
    fig.update_layout(map=dict(style="open-street-map", center=centre, zoom=zoom), height=height, margin=dict(l=0, r=0, t=0, b=0),
                      paper_bgcolor="white", legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01,
                                                         bgcolor="rgba(255,255,255,0.85)", font=dict(size=11)))
    return fig


def cumulative_fig(curve: pd.DataFrame, t: float) -> go.Figure:
    fig = go.Figure(go.Scatter(x=curve["t_min"], y=curve["cumulative"], mode="lines", line=dict(color=charts.ACCENT, width=3),
                               name="Cumulative boardings", hovertemplate="%{customdata}: %{y:,.0f}<extra></extra>",
                               customdata=[clock_label(x) for x in curve["t_min"]]))
    now = curve.iloc[(curve["t_min"] - t).abs().argmin()]
    fig.add_trace(go.Scatter(x=[t], y=[now["cumulative"]], mode="markers", name="Now", marker=dict(size=13, color=charts.WARN),
                             hovertemplate=f"Now {clock_label(t)}: %{{y:,.0f}}<extra></extra>"))
    hrs = list(range(int(curve["t_min"].min() // 60 * 60), int(curve["t_min"].max()) + 1, 180))
    fig.update_xaxes(tickvals=hrs, ticktext=[clock_label(h) for h in hrs], title="Clock (simulated service day)")
    fig.update_yaxes(title="Passengers boarded so far")
    return charts.style(fig, height=320)
