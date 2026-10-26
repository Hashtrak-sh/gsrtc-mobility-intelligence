"""Plotly chart builders with one shared visual template.

Visual system: a single deep-blue accent, neutral greys, one warning colour (burnt orange) for gaps/crowding, and a
distinct grey cross-hatch marker for "no scheduled capacity" (never drawn as zero). Every builder takes already-computed
frames and returns a ``go.Figure``; none read files. Hover text uses INR (Indian grouping), km, % and 24-hour times.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from modules.ui import fmt

ACCENT = "#1f4e79"
ACCENT_MID = "#5b87b3"
ACCENT_LIGHT = "#b7cde3"
GREY = "#8a949e"
GREY_LIGHT = "#d5dbe1"
GRID = "#e6eaee"
WARN = "#c4551b"
WARN_LIGHT = "#f4d6c2"
TEXT = "#1c2833"
FONT = "Source Sans Pro, Segoe UI, Helvetica, Arial, sans-serif"

# Components / categories: ordered, muted, distinguishable (accent family first, then neutral and teal).
SERIES = ["#1f4e79", "#5b87b3", "#9dbbd8", "#2a8a8a", "#7fc1b8", "#b5a36a", "#8a949e"]
DAY_COLOURS = {"weekday": ACCENT, "weekend": GREY, "festival": WARN}

# 0 -> light neutral, ~1 -> amber tint, >=1.2 -> warning colour (demand / seats)
GAP_SCALE = [[0.0, "#eef3f8"], [0.35, "#c9dcec"], [0.55, "#f6e4d3"], [0.7, "#eba57a"], [1.0, WARN]]
SEQ_SCALE = [[0.0, "#f3f6fa"], [1.0, ACCENT]]

TEMPLATE = go.layout.Template(layout=dict(
    font=dict(family=FONT, size=13, color=TEXT),
    colorway=SERIES,
    paper_bgcolor="white", plot_bgcolor="white",
    margin=dict(l=10, r=10, t=36, b=10),
    xaxis=dict(gridcolor=GRID, linecolor=GREY_LIGHT, zerolinecolor=GREY_LIGHT, ticks="outside", tickcolor=GREY_LIGHT),
    yaxis=dict(gridcolor=GRID, linecolor=GREY_LIGHT, zerolinecolor=GREY_LIGHT),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=12)),
    title=dict(font=dict(size=15), x=0, xanchor="left"),
    hoverlabel=dict(font=dict(family=FONT, size=12)),
))
pio.templates["gsrtc"] = TEMPLATE


def style(fig: go.Figure, *, height: int = 380, title: str | None = None) -> go.Figure:
    fig.update_layout(template="gsrtc", height=height)
    if title is not None:
        fig.update_layout(title_text=title)
    return fig


def _hour_ticks(fig: go.Figure, hours: list[int], axis: str = "x") -> None:
    upd = dict(tickmode="array", tickvals=hours, ticktext=[f"{h:02d}" for h in hours], title_text="Hour of day (24-hour clock)")
    fig.update_xaxes(**upd) if axis == "x" else fig.update_yaxes(**upd)


def empty_figure(message: str, height: int = 240) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=14, color=GREY), xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, height=height)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
def peak_load_bars(df: pd.DataFrame) -> go.Figure:
    """Horizontal bars of each route's peak-hour load (x seats). ``df``: route_id, label, peak_hour_load_factor, peak_hour_window."""
    d = df.dropna(subset=["peak_hour_load_factor"]).sort_values("peak_hour_load_factor")
    if d.empty:
        return empty_figure("No peak-hour load data for the current filters")
    colours = [WARN if v > 1.0 else ACCENT for v in d["peak_hour_load_factor"]]
    fig = go.Figure(go.Bar(
        x=d["peak_hour_load_factor"], y=d["label"], orientation="h", marker_color=colours,
        customdata=np.stack([d["peak_hour_window"].astype(str)], axis=-1),
        hovertemplate="%{y}<br>Peak-hour load: %{x:.2f}x seats<br>Peak hour: %{customdata[0]}<extra></extra>"))
    fig.add_vline(x=1.0, line_dash="dash", line_color=GREY, annotation_text="all seats full", annotation_position="top")
    fig.update_xaxes(title_text="Peak-hour load (multiple of seats; above 1.0 means standing passengers)", rangemode="tozero")
    fig.update_yaxes(title_text=None, automargin=True)
    return style(fig, height=max(300, 26 * len(d) + 90))


def demand_vs_seats(df: pd.DataFrame, title: str | None = None) -> go.Figure:
    """Seats offered (bars) vs estimated demand (line) by hour. ``df``: hour, demand, seats."""
    if df.empty:
        return empty_figure("No hourly demand data for the current filters")
    fig = go.Figure()
    fig.add_bar(x=df["hour"], y=df["seats"], name="Seats offered", marker_color=GREY_LIGHT,
                hovertemplate="%{x:02d}:00 seats offered: %{y:,.0f}<extra></extra>")
    fig.add_scatter(x=df["hour"], y=df["demand"], name="Estimated demand (critical-link load)", mode="lines+markers",
                    line=dict(color=ACCENT, width=3), hovertemplate="%{x:02d}:00 demand: %{y:,.0f}<extra></extra>")
    _hour_ticks(fig, sorted(df["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Passengers / seats per average day")
    return style(fig, height=340, title=title)


# ---------------------------------------------------------------------------
# Demand & surveys
# ---------------------------------------------------------------------------
def demand_by_hour(df: pd.DataFrame, selected_day_type: str | None = None) -> go.Figure:
    """Boardings per average day by boarding hour, one line per day type. ``df``: hour, day_type, passengers."""
    if df.empty:
        return empty_figure("No passenger flow data for the current filters")
    fig = go.Figure()
    for dt in ["weekday", "weekend", "festival"]:
        d = df[df["day_type"] == dt].sort_values("hour")
        if d.empty:
            continue
        sel = selected_day_type in (None, dt)
        fig.add_scatter(x=d["hour"], y=d["passengers"], name=dt, mode="lines+markers",
                        line=dict(color=DAY_COLOURS[dt], width=3.5 if dt == selected_day_type else 2, dash="solid" if sel else "dot"),
                        opacity=1.0 if sel else 0.75,
                        hovertemplate=dt + " %{x:02d}:00: %{y:,.0f} boardings<extra></extra>")
    _hour_ticks(fig, sorted(df["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Boardings per average day")
    return style(fig, height=360)


def share_bars(df: pd.DataFrame, *, colour: str = ACCENT, height: int | None = None, xtitle: str = "Share of respondents (%)") -> go.Figure:
    """Horizontal share bars. ``df``: label, share_pct, responses."""
    if df.empty:
        return empty_figure("No responses in this group")
    d = df.sort_values("share_pct")
    fig = go.Figure(go.Bar(
        x=d["share_pct"], y=d["label"], orientation="h", marker_color=colour,
        text=[f"{v:.0f}%" for v in d["share_pct"]], textposition="outside", cliponaxis=False,
        customdata=np.stack([d["responses"]], axis=-1),
        hovertemplate="%{y}: %{x:.1f}% (%{customdata[0]} respondents)<extra></extra>"))
    fig.update_xaxes(title_text=xtitle, range=[0, max(100.0, float(d["share_pct"].max()) * 1.15) if float(d["share_pct"].max()) > 85 else 100])
    fig.update_yaxes(title_text=None, automargin=True)
    return style(fig, height=height or max(260, 34 * len(d) + 80))


# ---------------------------------------------------------------------------
# Route intelligence
# ---------------------------------------------------------------------------
def score_stack(weighted: pd.DataFrame, order: list[str], labels: dict[str, str]) -> go.Figure:
    """Stacked horizontal bars: weight x component score, so the stack length is the total score (0-100)."""
    if weighted.empty:
        return empty_figure("No route scores for the current filters")
    fig = go.Figure()
    comps = list(dict.fromkeys(weighted["component"]))
    for i, comp in enumerate(comps):
        d = weighted[weighted["component"] == comp].set_index("route_id").reindex(order)
        fig.add_bar(y=[labels.get(r, r) for r in order], x=d["points"], orientation="h", name=f"{d['label'].dropna().iloc[0]} ({d['weight'].dropna().iloc[0] * 100:.0f}%)",
                    marker_color=SERIES[i % len(SERIES)], customdata=np.stack([d["score"], d["weight"] * 100], axis=-1),
                    hovertemplate="%{y}<br>" + str(d["label"].dropna().iloc[0]) + ": score %{customdata[0]:.0f} x weight %{customdata[1]:.0f}% = %{x:.1f} points<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_yaxes(autorange="reversed", automargin=True)
    fig.update_xaxes(title_text="Total score (0-100) = sum of weight x component score")
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.18, x=0))
    return style(fig, height=max(320, 30 * len(order) + 170))


def daily_trend(df: pd.DataFrame) -> go.Figure:
    """Daily boardings for one route. ``df``: service_date, boardings, day_type."""
    if df.empty:
        return empty_figure("No daily data for this route")
    d = df.sort_values("service_date")
    x = pd.to_datetime(d["service_date"])
    fig = go.Figure()
    fig.add_scatter(x=x, y=d["boardings"], mode="lines", line=dict(color=GREY_LIGHT, width=2), hoverinfo="skip", showlegend=False)
    for dt in ["weekday", "weekend", "festival"]:
        m = d["day_type"] == dt
        if m.any():
            fig.add_scatter(x=x[m], y=d.loc[m, "boardings"], mode="markers", name=dt,
                            marker=dict(color=DAY_COLOURS[dt], size=9), hovertemplate="%{x|%a %d %b}: %{y:,.0f} passengers (" + dt + ")<extra></extra>")
    fig.update_yaxes(title_text="Passengers per day", rangemode="tozero")
    fig.update_xaxes(title_text=None, tickformat="%d %b")
    return style(fig, height=340)


def ridership_vs_model(df: pd.DataFrame) -> go.Figure:
    """Actual vs model estimate for one route over the test window (M6-ML). ``df``: service_date, actual_demand,
    predicted_demand, lower_bound, upper_bound, baseline_route_daytype_mean."""
    if df.empty:
        return empty_figure("No model estimates for this route")
    d = df.sort_values("service_date")
    x = pd.to_datetime(d["service_date"])
    fig = go.Figure()
    fig.add_scatter(x=x, y=d["upper_bound"], mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=x, y=d["lower_bound"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(91,135,179,0.22)",
                    name="Model interval (nominal 80 %)", hoverinfo="skip")
    fig.add_scatter(x=x, y=d["baseline_route_daytype_mean"], mode="lines", line=dict(color=GREY, width=1.5, dash="dash"), name="Baseline: route x day-type mean",
                    hovertemplate="%{x|%a %d %b}: %{y:,.0f} (baseline)<extra></extra>")
    fig.add_scatter(x=x, y=d["predicted_demand"], mode="lines", line=dict(color=ACCENT_MID, width=2.5), name="Model estimate",
                    hovertemplate="%{x|%a %d %b}: %{y:,.0f} (model estimate)<extra></extra>")
    fig.add_scatter(x=x, y=d["actual_demand"], mode="markers", marker=dict(color=ACCENT, size=8), name="Observed (synthetic)",
                    hovertemplate="%{x|%a %d %b}: %{y:,.0f} (observed, synthetic)<extra></extra>")
    fig.update_yaxes(title_text="Passengers per day", rangemode="tozero")
    fig.update_xaxes(title_text=None, tickformat="%d %b")
    return style(fig, height=340)


def occupancy_chart(prog: pd.DataFrame, stop_names: dict[str, str], crush_factor: float | None) -> go.Figure:
    """Mean onboard load by stop along the route, with seat capacity (and crush load for local buses)."""
    if prog.empty:
        return empty_figure("No stop-level occupancy for the current filters")
    labels = [stop_names.get(s, s) for s in prog["stop_id"]]
    seats = float(prog["seats"].mean())
    fig = go.Figure()
    fig.add_scatter(x=labels, y=prog["avg_onboard"], mode="lines+markers", name="Average passengers on board after the stop",
                    line=dict(color=ACCENT, width=3), marker=dict(size=8),
                    customdata=np.stack([prog["n_trips"], prog["onboard_pct"]], axis=-1),
                    hovertemplate="%{x}<br>%{y:.1f} on board (%{customdata[1]:.0f}% of seats)<br>%{customdata[0]} trips<extra></extra>")
    fig.add_hline(y=seats, line_dash="dash", line_color=GREY, annotation_text=f"Seats ({seats:.0f})", annotation_position="top left")
    if crush_factor and crush_factor > 1:
        fig.add_hline(y=seats * crush_factor, line_dash="dot", line_color=WARN,
                      annotation_text=f"Crush load ({seats * crush_factor:.0f})", annotation_position="top left")
    fig.update_yaxes(title_text="Passengers on board", rangemode="tozero")
    fig.update_xaxes(title_text="Stops in direction of travel", tickangle=-30, automargin=True)
    return style(fig, height=380)


def route_hourly_profile(df: pd.DataFrame) -> go.Figure:
    """Hourly demand vs seats for one route direction. ``df``: hour, demand, seats, status."""
    if df.empty:
        return empty_figure("No hourly data for this route and filters")
    d = df.sort_values("hour")
    fig = go.Figure()
    fig.add_bar(x=d["hour"], y=d["seats"], name="Seats offered", marker_color=GREY_LIGHT,
                hovertemplate="%{x:02d}:00 seats: %{y:,.0f}<extra></extra>")
    fig.add_bar(x=d["hour"], y=d["demand"], name="Estimated demand", marker_color=ACCENT,
                hovertemplate="%{x:02d}:00 demand: %{y:,.0f}<extra></extra>")
    nc = d[d["status"] == "no_scheduled_capacity"]
    if len(nc):
        fig.add_scatter(x=nc["hour"], y=[0] * len(nc), mode="markers", name="No scheduled capacity",
                        marker=dict(symbol="x", color=GREY, size=9), hovertemplate="%{x:02d}:00 no scheduled capacity<extra></extra>")
    fig.update_layout(barmode="group")
    _hour_ticks(fig, sorted(d["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Passengers / seats per average day")
    return style(fig, height=340)


# ---------------------------------------------------------------------------
# Gaps
# ---------------------------------------------------------------------------
def gap_heatmap(grid: pd.DataFrame) -> go.Figure:
    """Hour x location heat map of demand / seats; hatched grey crosses mark 'no scheduled capacity' (not zero)."""
    if grid.empty:
        return empty_figure("No demand-supply rows for the current filters")
    hours = list(range(int(grid["hour"].min()), int(grid["hour"].max()) + 1))
    rows = list(dict.fromkeys(grid.sort_values(["order", "row_label"])["row_label"]))
    gi = grid.pivot_table(index="row_label", columns="hour", values="gap_index", aggfunc="first").reindex(index=rows, columns=hours)
    hv = grid.pivot_table(index="row_label", columns="hour", values="hover", aggfunc="first").reindex(index=rows, columns=hours)
    nc = grid[grid["status"] == "no_scheduled_capacity"].assign(v=1.0).pivot_table(
        index="row_label", columns="hour", values="v", aggfunc="first").reindex(index=rows, columns=hours)
    xs = [f"{h:02d}" for h in hours]
    fig = go.Figure()
    fig.add_trace(go.Heatmap(z=gi.values, x=xs, y=rows, zmin=0, zmax=1.8, colorscale=GAP_SCALE, xgap=2, ygap=2, hoverongaps=False,
                             customdata=hv.values, hovertemplate="%{customdata}<extra></extra>", showscale=True,
                             colorbar=dict(title=dict(text="Demand / seats", side="right"), thickness=12, len=0.8,
                                           tickvals=[0, 0.6, 1.0, 1.2, 1.8], ticktext=["0", "0.6", "1.0", "1.2 (crowded)", "1.8"])))
    fig.add_trace(go.Heatmap(z=nc.values, x=xs, y=rows, colorscale=[[0, GREY_LIGHT], [1, GREY_LIGHT]], showscale=False, xgap=2, ygap=2,
                             hoverongaps=False, customdata=hv.values, hovertemplate="%{customdata}<extra></extra>"))
    ys, xx = [], []
    for r in rows:
        for h, x in zip(hours, xs):
            if pd.notna(nc.loc[r, h]):
                ys.append(r)
                xx.append(x)
    fig.add_trace(go.Scatter(x=xx, y=ys, mode="markers", name="No scheduled capacity (not zero demand)",
                             marker=dict(symbol="x-thin", size=10, color=GREY, line=dict(width=1.5, color=GREY)), hoverinfo="skip"))
    fig.update_xaxes(title_text="Departure hour (24-hour clock)", type="category", side="bottom")
    fig.update_yaxes(autorange="reversed", automargin=True, type="category", title_text=None)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0))
    return style(fig, height=max(340, 24 * len(rows) + 130))


def corridor_supply(df: pd.DataFrame, corridor: str) -> go.Figure:
    """Corridor hours: state seats vs private seats (bars) and private-market proxy demand (line); no-state-capacity hours shaded."""
    if df.empty:
        return empty_figure("No corridor rows for the current filters")
    fig = go.Figure()
    for _, r in df[df["no_state_capacity"]].iterrows():
        fig.add_vrect(x0=r["hour"] - 0.5, x1=r["hour"] + 0.5, fillcolor=WARN_LIGHT, opacity=0.55, line_width=0, layer="below")
    fig.add_bar(x=df["hour"], y=df["state_seats"], name="State seats offered", marker_color=ACCENT,
                hovertemplate="%{x:02d}:00 state seats: %{y:,.0f}<extra></extra>")
    fig.add_bar(x=df["hour"], y=df["private_seats"], name="Private seats offered (synthetic)", marker_color=GREY,
                hovertemplate="%{x:02d}:00 private seats: %{y:,.0f}<extra></extra>")
    fig.add_scatter(x=df["hour"], y=df["private_demand_proxy"], name="Private-market demand proxy (assumed 75% occupancy)", mode="lines+markers",
                    line=dict(color=WARN, width=2.5), hovertemplate="%{x:02d}:00 proxy demand: %{y:,.0f}<extra></extra>")
    fig.add_annotation(text="Shaded = no scheduled state seats", xref="paper", yref="paper", x=1, y=1.12, showarrow=False,
                       font=dict(size=12, color=WARN), xanchor="right")
    fig.update_layout(barmode="group")
    _hour_ticks(fig, sorted(df["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Seats / passengers per average day")
    return style(fig, height=380, title=f"{corridor}: outbound departures from the origin terminal")


# ---------------------------------------------------------------------------
# O-D
# ---------------------------------------------------------------------------
def od_bar(pairs: pd.DataFrame) -> go.Figure:
    """Top O-D pairs. ``pairs``: label, passengers_per_day, passengers_total."""
    if pairs.empty:
        return empty_figure("No O-D flows for the current filters")
    d = pairs.sort_values("passengers_per_day")
    fig = go.Figure(go.Bar(x=d["passengers_per_day"], y=d["label"], orientation="h", marker_color=ACCENT,
                           text=[f"{v:,.0f}" for v in d["passengers_per_day"]], textposition="outside", cliponaxis=False,
                           customdata=np.stack([d["passengers_total"]], axis=-1),
                           hovertemplate="%{y}<br>%{x:,.1f} passengers per average day<br>%{customdata[0]:,.0f} over the period<extra></extra>"))
    fig.update_xaxes(title_text="Passengers per average day", rangemode="tozero")
    fig.update_yaxes(title_text=None, automargin=True)
    return style(fig, height=max(320, 34 * len(d) + 90))


def od_matrix_fig(m: pd.DataFrame, names: dict[str, str]) -> go.Figure:
    if m.empty:
        return empty_figure("No O-D flows for the current filters")
    lab_y = [names.get(z, z) for z in m.index]
    lab_x = [names.get(z, z) for z in m.columns]
    z = m.values.astype(float)
    zz = np.where(z > 0, z, np.nan)
    fig = go.Figure(go.Heatmap(z=zz, x=lab_x, y=lab_y, colorscale=SEQ_SCALE, xgap=1, ygap=1, hoverongaps=False,
                               hovertemplate="%{y} to %{x}<br>%{z:,.1f} passengers per average day<extra></extra>",
                               colorbar=dict(title=dict(text="Passengers / day", side="right"), thickness=12)))
    fig.update_xaxes(title_text="Destination zone", tickangle=-40, automargin=True, side="bottom")
    fig.update_yaxes(title_text="Origin zone", autorange="reversed", automargin=True)
    return style(fig, height=max(420, 22 * len(lab_y) + 160))


def directional_fig(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_figure("No O-D flows for the current filters")
    colours = {"Towards employment zones": ACCENT, "From employment zones": WARN, "Other movements": GREY}
    fig = go.Figure()
    for flow in ["Towards employment zones", "From employment zones", "Other movements"]:
        d = df[df["flow"] == flow].sort_values("hour")
        if not d.empty:
            fig.add_scatter(x=d["hour"], y=d["passenger_count"], name=flow, mode="lines+markers", line=dict(color=colours[flow], width=3),
                            hovertemplate=flow + " %{x:02d}:00: %{y:,.0f} passengers<extra></extra>")
    _hour_ticks(fig, sorted(df["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Passengers per average day", rangemode="tozero")
    return style(fig, height=340)


# ---------------------------------------------------------------------------
# Competition & pricing
# ---------------------------------------------------------------------------
def slot_chart(df: pd.DataFrame, corridor: str, day_type: str) -> go.Figure:
    if df.empty:
        return empty_figure("No state or private departures for this corridor and day type")
    fig = go.Figure()
    for _, r in df[df["state_gap"]].iterrows():
        fig.add_vrect(x0=r["hour"] - 0.5, x1=r["hour"] + 0.5, fillcolor=WARN_LIGHT, opacity=0.55, line_width=0, layer="below")
    fig.add_bar(x=df["hour"], y=df["state_departures"], name="State departures per day", marker_color=ACCENT,
                hovertemplate="%{x:02d}:00 state departures: %{y:.1f}<extra></extra>")
    fig.add_bar(x=df["hour"], y=df["private_departures"], name="Private departures per day (synthetic)", marker_color=GREY,
                hovertemplate="%{x:02d}:00 private departures: %{y:.0f}<extra></extra>")
    fig.add_annotation(text="Shaded = private service, no state departure", xref="paper", yref="paper", x=1, y=1.12, showarrow=False,
                       font=dict(size=12, color=WARN), xanchor="right")
    fig.update_layout(barmode="group")
    _hour_ticks(fig, list(range(int(df["hour"].min()), int(df["hour"].max()) + 1)))
    fig.update_yaxes(title_text="Departures from Rajkot per day", rangemode="tozero", dtick=1)
    return style(fig, height=380, title=f"{corridor}: departure slots on a {day_type}")


def fare_chart(df: pd.DataFrame) -> go.Figure:
    """Fare per passenger by bus type: state tariff vs private base and surge fares."""
    if df.empty:
        return empty_figure("No fare data for this corridor")
    labels = [b.replace("_", " ") for b in df["bus_type"]]
    fig = go.Figure()
    fig.add_bar(x=labels, y=df["state_fare_inr"], name="State full-route fare (illustrative tariff)", marker_color=ACCENT,
                hovertemplate="%{x}: ₹%{y:,.0f}<extra>State</extra>")
    fig.add_bar(x=labels, y=df["private_base_fare_inr"], name="Private base fare (median)", marker_color=GREY,
                hovertemplate="%{x}: ₹%{y:,.0f}<extra>Private base</extra>")
    fig.add_bar(x=labels, y=df["private_surge_fare_inr"], name="Private fare on this day type (median)", marker_color=WARN_LIGHT,
                hovertemplate="%{x}: ₹%{y:,.0f}<extra>Private day-type fare</extra>")
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="Fare per passenger (₹)", rangemode="tozero", tickprefix="₹")
    fig.update_xaxes(title_text="Bus type")
    return style(fig, height=340)


def pricing_outcomes(res: dict) -> go.Figure:
    """Revenue and occupancy, baseline vs scenario, side by side."""
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Ticket revenue per day", "Occupancy (served / seats)"), horizontal_spacing=0.14)
    fig.add_bar(x=["Baseline", "New fare"], y=[res["baseline_revenue_inr"], res["revenue_inr"]], marker_color=[GREY, ACCENT],
                text=[fmt.inr_compact(res["baseline_revenue_inr"]), fmt.inr_compact(res["revenue_inr"])], textposition="outside",
                cliponaxis=False, hovertemplate="%{x}: ₹%{y:,.0f}<extra></extra>", showlegend=False, row=1, col=1)
    occ = [res["baseline_occupancy"] * 100, res["occupancy"] * 100]
    fig.add_bar(x=["Baseline", "New fare"], y=occ, marker_color=[GREY, ACCENT], text=[f"{v:.0f}%" for v in occ], textposition="outside",
                cliponaxis=False, hovertemplate="%{x}: %{y:.1f}%<extra></extra>", showlegend=False, row=1, col=2)
    fig.update_yaxes(rangemode="tozero", tickprefix="₹", row=1, col=1)
    fig.update_yaxes(rangemode="tozero", ticksuffix="%", range=[0, max(100.0, max(occ) * 1.15)], row=1, col=2)
    return style(fig, height=340)


def sensitivity_chart(df: pd.DataFrame) -> go.Figure:
    """Revenue change vs baseline by assumed elasticity."""
    if df.empty:
        return empty_figure("No sensitivity results")
    colours = [ACCENT if v >= 0 else WARN for v in df["revenue_change_inr"]]
    fig = go.Figure(go.Bar(x=[f"{e:+.1f}" for e in df["elasticity"]], y=df["revenue_change_inr"], marker_color=colours,
                           text=[fmt.inr_compact(v) for v in df["revenue_change_inr"]], textposition="outside", cliponaxis=False,
                           hovertemplate="Elasticity %{x}: revenue change ₹%{y:,.0f} per day<extra></extra>"))
    fig.add_hline(y=0, line_color=GREY)
    fig.update_xaxes(title_text="Assumed price elasticity of demand")
    fig.update_yaxes(title_text="Revenue change per day (₹)", tickprefix="₹")
    return style(fig, height=320)


# ---------------------------------------------------------------------------
# Infrastructure & digital, CCTV
# ---------------------------------------------------------------------------
def score_heatmap(m: pd.DataFrame, *, xlabels: dict[str, str] | None = None, title: str | None = None, vmax: float = 5.0) -> go.Figure:
    """Annotated heat map of 0-5 scores (rows = assets, columns = dimensions/capabilities); low scores are warm."""
    if m.empty:
        return empty_figure("No assessment data")
    xl = [(xlabels or {}).get(c, str(c).capitalize()) for c in m.columns]
    fig = go.Figure(go.Heatmap(
        z=m.values, x=xl, y=list(m.index), zmin=0, zmax=vmax, xgap=2, ygap=2, hoverongaps=False,
        colorscale=[[0, WARN], [0.5, "#f6e4d3"], [0.75, ACCENT_LIGHT], [1, ACCENT]], text=np.round(m.values, 1), texttemplate="%{text}",
        textfont=dict(size=13), hovertemplate="%{y}<br>%{x}: %{z:.1f} of 5<extra></extra>",
        colorbar=dict(title=dict(text="Score (0-5)", side="right"), thickness=12)))
    fig.update_yaxes(autorange="reversed", automargin=True)
    fig.update_xaxes(side="top")
    return style(fig, height=max(280, 40 * len(m) + 110), title=title)


def cctv_profile(df: pd.DataFrame, names: dict[str, str]) -> go.Figure:
    """Synthetic mean inbound persons per hour, one line per camera location. ``df``: location_id, hour, mean_inbound_persons."""
    if df.empty:
        return empty_figure("No synthetic CCTV profile for the current filters")
    fig = go.Figure()
    for i, (loc, d) in enumerate(df.groupby("location_id")):
        d = d.sort_values("hour")
        fig.add_scatter(x=d["hour"], y=d["mean_inbound_persons"], name=names.get(loc, loc), mode="lines+markers",
                        line=dict(color=SERIES[i % len(SERIES)], width=3),
                        hovertemplate=names.get(loc, loc) + " %{x:02d}:00: %{y:,.0f} persons (synthetic)<extra></extra>")
    _hour_ticks(fig, sorted(df["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Mean inbound persons per hour (synthetic)", rangemode="tozero")
    return style(fig, height=360)


def day_type_profile(df: pd.DataFrame) -> go.Figure:
    """Mean inbound persons per hour at one location by day type. ``df``: day_type, hour, mean_inbound_persons."""
    if df.empty:
        return empty_figure("No synthetic CCTV profile for this location")
    fig = go.Figure()
    for dt in ["weekday", "weekend", "festival"]:
        d = df[df["day_type"] == dt].sort_values("hour")
        if not d.empty:
            fig.add_scatter(x=d["hour"], y=d["mean_inbound_persons"], name=dt, mode="lines", line=dict(color=DAY_COLOURS[dt], width=2.5),
                            hovertemplate=dt + " %{x:02d}:00: %{y:,.0f} persons (synthetic)<extra></extra>")
    _hour_ticks(fig, sorted(df["hour"].astype(int).unique()))
    fig.update_yaxes(title_text="Mean inbound persons per hour (synthetic)", rangemode="tozero")
    return style(fig, height=300)


# ---------------------------------------------------------------------------
# M5: competition scores, review themes, fare index, survey cross-tabs and model coefficients
# ---------------------------------------------------------------------------
def gap_score_chart(rows: pd.DataFrame, weights: dict[str, float], labels: dict[str, str], col_map: dict[str, str]) -> go.Figure:
    """Stacked bars per clock hour: weight x component (0-1) x 100, so the stack height is the competitive gap score.
    ``rows``: hour + the component columns named in ``col_map`` (weight key -> column)."""
    if rows.empty:
        return empty_figure("No competition data for this corridor and day type")
    r = rows.sort_values("hour")
    fig = go.Figure()
    for i, (k, w) in enumerate(weights.items()):
        v = r[col_map[k]].fillna(0.0) * w * 100
        fig.add_bar(x=r["hour"], y=v, name=f"{labels[k]} ({w:.0%})", marker_color=SERIES[i % len(SERIES)],
                    hovertemplate="%{x:02d}:00 " + labels[k] + ": %{y:.1f} points<extra></extra>")
    fig.update_layout(barmode="stack")
    _hour_ticks(fig, [int(h) for h in r["hour"]])
    fig.update_yaxes(title_text="Competitive gap score (0-100)", range=[0, 100])
    return style(fig, height=360)


def fare_index_chart(view: pd.DataFrame) -> go.Figure:
    """State tariff / private median fare by hour: normal (base) vs illustrative surge. ``view``: hour, fare_index, fare_index_surge."""
    if view.empty:
        return empty_figure("No hour with both a state tariff and a private fare for this corridor and day type")
    v = view.sort_values("hour")
    fig = go.Figure()
    fig.add_scatter(x=v["hour"], y=v["fare_index"], name="Normal (private base fare)", mode="lines+markers", line=dict(color=ACCENT, width=3),
                    hovertemplate="%{x:02d}:00 state / private base: %{y:.2f}<extra></extra>")
    fig.add_scatter(x=v["hour"], y=v["fare_index_surge"], name="Illustrative surge (private peak fare)", mode="lines+markers",
                    line=dict(color=WARN, width=3, dash="dot"), hovertemplate="%{x:02d}:00 state / private surge: %{y:.2f}<extra></extra>")
    fig.add_hline(y=1.0, line_color=GREY, annotation_text="1.0 = same fare", annotation_position="top left")
    _hour_ticks(fig, [int(h) for h in v["hour"]])
    fig.update_yaxes(title_text="State fare / private median fare", rangemode="tozero")
    return style(fig, height=340)


def theme_negative_chart(comp: pd.DataFrame) -> go.Figure:
    """Grouped horizontal bars: share of reviews with a negative mention of each theme, state vs private.
    ``comp``: label, state_negative_share, private_negative_share (fractions)."""
    if comp.empty or comp[["state_negative_share", "private_negative_share"]].isna().all().all():
        return empty_figure("No reviews for this selection")
    d = comp.assign(_s=comp["state_negative_share"].fillna(0)).sort_values("_s")
    fig = go.Figure()
    fig.add_bar(y=d["label"], x=d["state_negative_share"] * 100, name="State (GSRTC demo)", orientation="h", marker_color=ACCENT,
                hovertemplate="%{y}: %{x:.0f}% of state reviews negative<extra></extra>")
    fig.add_bar(y=d["label"], x=d["private_negative_share"] * 100, name="Private (synthetic)", orientation="h", marker_color=GREY,
                hovertemplate="%{y}: %{x:.0f}% of private reviews negative<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_xaxes(title_text="Reviews with a negative mention of the theme (%)", ticksuffix="%", rangemode="tozero")
    fig.update_yaxes(title_text=None, automargin=True)
    return style(fig, height=380)


def share_heatmap(m: pd.DataFrame, *, title: str | None = None) -> go.Figure:
    """Annotated heat map of shares in % (rows = items, columns = respondent groups)."""
    if m.empty:
        return empty_figure("No responses for this cross-tab")
    fig = go.Figure(go.Heatmap(
        z=m.values, x=[str(c) for c in m.columns], y=list(m.index), zmin=0, zmax=max(100.0, float(np.nanmax(m.values))), xgap=2, ygap=2,
        colorscale=SEQ_SCALE, text=np.round(m.values, 0), texttemplate="%{text:.0f}%", textfont=dict(size=12),
        hovertemplate="%{y}<br>%{x}: %{z:.1f}%<extra></extra>", colorbar=dict(title=dict(text="% of group", side="right"), thickness=12)))
    fig.update_yaxes(autorange="reversed", automargin=True)
    fig.update_xaxes(side="top")
    return style(fig, height=max(260, 34 * len(m) + 110), title=title)


def coefficient_chart(coef: pd.DataFrame) -> go.Figure:
    """True generating coefficient vs fitted coefficient (log-odds), excluding the intercept. ``coef``: label, true_coefficient, coef_full_fit."""
    c = coef[coef["feature"] != "intercept"]
    if c.empty:
        return empty_figure("No model coefficients")
    c = c.iloc[::-1]
    fig = go.Figure()
    fig.add_bar(y=c["label"], x=c["true_coefficient"], name="True generating coefficient", orientation="h", marker_color=GREY_LIGHT,
                marker_line_color=GREY, marker_line_width=1, hovertemplate="%{y}: true %{x:.2f}<extra></extra>")
    fig.add_bar(y=c["label"], x=c["coef_full_fit"], name="Fitted logistic coefficient", orientation="h", marker_color=ACCENT,
                hovertemplate="%{y}: fitted %{x:.2f}<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_xaxes(title_text="Coefficient (log-odds of switching)", zeroline=True)
    fig.update_yaxes(title_text=None, automargin=True)
    return style(fig, height=max(380, 36 * len(c) + 120))


# --- M6-CCTV: detector output on a pre-recorded clip (clip-relative minutes, aggregate counts only) ---
def cctv_detector_minutes(df: pd.DataFrame) -> go.Figure:
    """Counts per clip minute, grouped bars by class and direction. ``df``: clip_minute, direction, class, count."""
    if df.empty:
        return empty_figure("No detector rows")
    fig = go.Figure()
    for i, ((cls, d), g) in enumerate(df.groupby(["class", "direction"])):
        g = g.sort_values("clip_minute")
        fig.add_bar(x=g["clip_minute"], y=g["count"], name=f"{cls} {d}", marker_color=SERIES[i % len(SERIES)],
                    hovertemplate=f"{cls} {d}, clip minute %{{x}}: %{{y}} crossings<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_xaxes(title_text="Minute of the clip (clip-relative, not a clock time)", dtick=1)
    fig.update_yaxes(title_text="Line crossings per minute (detector)", rangemode="tozero")
    return style(fig, height=340)
