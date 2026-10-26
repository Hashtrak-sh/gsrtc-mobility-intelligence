"""Gantt-style plotly timeline for the digital roadmap."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from modules.analytics.roadmap import CAPABILITIES, HORIZON_MONTHS, PHASES
from modules.ui import charts

_PHASE_FILL = ["rgba(183,205,227,0.25)", "rgba(213,219,225,0.30)", "rgba(244,214,194,0.25)"]


def roadmap_figure(rm: pd.DataFrame) -> go.Figure:
    sched = rm[rm["status"] == "scheduled"].copy()
    if sched.empty:
        return charts.empty_figure("No initiatives to schedule: all capabilities meet their targets.")
    sched = sched.sort_values(["start_month", "id"], ascending=[False, False], kind="mergesort")
    x_max = max(HORIZON_MONTHS, float(sched["end_month"].max()))
    fig = go.Figure()
    for (num, name, lo, hi), fill in zip(PHASES, _PHASE_FILL):
        hi_plot = x_max if num == PHASES[-1][0] else hi
        fig.add_vrect(x0=lo, x1=hi_plot, fillcolor=fill, line_width=0, layer="below")
        fig.add_annotation(x=(lo + hi_plot) / 2, y=1.0, yref="paper", yanchor="bottom", showarrow=False,
                           text=f"Phase {num}: {name}", font=dict(size=12, color=charts.TEXT))
    colour = {c: charts.SERIES[i % len(charts.SERIES)] for i, c in enumerate(CAPABILITIES)}
    labels = sched["id"] + "  " + sched["initiative"].str.slice(0, 48)
    for cap in CAPABILITIES:
        m = sched["capability"] == cap
        if not m.any():
            continue
        s = sched[m]
        fig.add_trace(go.Bar(
            y=labels[m], x=s["end_month"] - s["start_month"], base=s["start_month"],
            orientation="h", name=cap.capitalize(), marker_color=colour[cap],
            customdata=list(zip(s["start_month"], s["end_month"], s["current"], s["target_maturity"], s["phase_name"])),
            hovertemplate="%{y}<br>Months %{customdata[0]:.0f} to %{customdata[1]:.0f} (%{customdata[4]})<br>"
                          "Maturity %{customdata[2]:.1f} to %{customdata[3]:.1f}<extra></extra>"))
    fig.update_xaxes(range=[0, x_max], dtick=6, title_text="Months from start (illustrative plan)")
    fig.update_yaxes(automargin=True, categoryorder="array", categoryarray=list(labels))
    fig.update_layout(barmode="overlay", legend=dict(y=1.12))
    return charts.style(fig, height=140 + 38 * len(sched))
