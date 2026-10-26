"""Figures and small assembly helpers for the Cost-Benefit & Fares page and its PDF section.

No Streamlit, no file I/O. Every builder takes frames already computed by ``modules.analytics.cost_model``,
``fare_analysis`` and ``socio_economic`` and returns a ``go.Figure``; the assembly helpers only aggregate those frames
(ratios of sums) or fill ``full_cost_per_day_inr`` for the socio-economic inputs. All cost parameters are illustrative.
Missing values are shown as the em dash, never as ``nan``.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from modules.analytics import cost_model as cm
from modules.analytics import socio_economic as SE
from modules.ui import charts as ch
from modules.ui import fmt

DASH = "—"

# Trip-operating layer = blue/teal family; fixed + overhead layer = orange/brown family (visibly a different layer).
COMPONENT_COLOURS: dict[str, str] = {
    "energy": "#1f4e79", "tyres": "#5b87b3", "maintenance_and_other_running": "#9dbbd8", "crew": "#2a8a8a",
    "dead_km_uplift": "#7a3410", "depreciation_or_lease": "#c4551b", "insurance_tax_permits": "#e08a55",
    "tolls": "#f0b48a", "overhead": "#8a949e",
}
BAND_COLOURS = {"peak": ch.WARN, "normal": ch.ACCENT}
GOOD = "#3a8f5c"


def ok(x: Any) -> bool:
    try:
        return x is not None and not isinstance(x, bool) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def d_inr(x: Any, decimals: int = 0) -> str:
    return fmt.inr(x, decimals) if ok(x) else DASH


def d_num(x: Any, decimals: int = 0) -> str:
    return fmt.number(x, decimals) if ok(x) else DASH


def d_pct(x: Any, decimals: int = 0) -> str:
    """A 0-1 ratio as a percentage."""
    return fmt.ratio_pct(x, decimals) if ok(x) else DASH


def d_x(x: Any, decimals: int = 2) -> str:
    return f"{float(x):.{decimals}f}" if ok(x) else DASH


def route_label(row: Any) -> str:
    return f"{row['route_id']} {cm.CLASS_LABELS.get(row['bus_class'], row['bus_class'])}"


# ---------------------------------------------------------------------------------------------------------------- assembly
def corridor_length(econ_sel: pd.DataFrame) -> float:
    """Trip-weighted mean route length (km) of a corridor's rows (used for the per-km toll)."""
    w = econ_sel["trips"].astype(float)
    return float((econ_sel["length_km"] * w).sum() / w.sum()) if w.sum() > 0 else float("nan")


def full_cost_per_day_by_route(econ: pd.DataFrame, n_days_total: float) -> pd.Series:
    """Full cost per average service day per route: ``sum(full_cost_inr)`` over ALL day types and bands / all service dates.

    Same basis as ``socio_economic.build_default_inputs(route_summary, by="route")`` (42-day totals / number of service dates).
    """
    return econ.groupby("route_id")["full_cost_inr"].sum() / float(n_days_total)


def cba_inputs(route_summary: pd.DataFrame, econ: pd.DataFrame, n_days_total: float) -> pd.DataFrame:
    """Route-level CBA inputs with ``full_cost_per_day_inr`` filled from the cost model (NaN where a route has no cost row)."""
    inp = SE.build_default_inputs(route_summary, by="route")
    fc = full_cost_per_day_by_route(econ, n_days_total)
    inp["full_cost_per_day_inr"] = inp["route_id"].map(fc).astype(float)
    return inp


def _ratio(a: float, b: float) -> float:
    return float(a) / float(b) if ok(a) and ok(b) and float(b) != 0 else float("nan")


def headline(econ_sel: pd.DataFrame) -> dict[str, float]:
    """Corridor x day-type headline numbers (ratios of sums over the selected rows, per average day of the day type)."""
    if econ_sel.empty:
        return {}
    nd = float(econ_sel["n_days"].iloc[0])
    vkm = econ_sel["vehicle_km"].sum()
    out = {
        "full_cost_per_km": _ratio(econ_sel["full_cost_inr"].sum(), vkm),
        "trip_cost_per_km": _ratio(econ_sel["trip_operating_cost_inr"].sum(), vkm),
        "revenue_per_km": _ratio(econ_sel["revenue_inr"].sum(), vkm),
        "contribution_per_day": (econ_sel["revenue_inr"].sum() - econ_sel["trip_operating_cost_inr"].sum()) / nd,
        "full_margin_per_day": (econ_sel["revenue_inr"].sum() - econ_sel["full_cost_inr"].sum()) / nd,
        "revenue_per_day": econ_sel["revenue_inr"].sum() / nd,
        "full_cost_per_day": econ_sel["full_cost_inr"].sum() / nd,
    }
    for b in ("peak", "normal"):
        g = econ_sel[econ_sel["band"] == b]
        out[f"lf_{b}"] = _ratio(g["passenger_km"].sum(), g["seat_km"].sum()) if len(g) else float("nan")
        out[f"trips_{b}"] = float(g["trips"].sum()) / nd if len(g) else 0.0
    return out


def band_summary(econ_sel: pd.DataFrame) -> pd.DataFrame:
    """Per band over the selection: load factor, revenue / contribution / full-cost margin per trip (ratios of sums)."""
    rows = []
    for b, g in econ_sel.groupby("band", sort=False):
        trips = g["trips"].sum()
        rows.append({"band": b, "trips": trips, "load_factor": _ratio(g["passenger_km"].sum(), g["seat_km"].sum()),
                     "revenue_per_trip_inr": _ratio(g["revenue_inr"].sum(), trips),
                     "full_cost_per_trip_inr": _ratio(g["full_cost_inr"].sum(), trips),
                     "contribution_per_trip_inr": _ratio(g["revenue_inr"].sum() - g["trip_operating_cost_inr"].sum(), trips),
                     "full_margin_per_trip_inr": _ratio(g["revenue_inr"].sum() - g["full_cost_inr"].sum(), trips)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------------- cost stack
def cost_stack_chart(ct: pd.DataFrame, title: str | None = None) -> go.Figure:
    """Horizontal stacked bar of ``cost_model.component_table``: one bar per class, one segment per component.

    Trip-operating components use blue/teal, fixed and overhead components orange/brown; what-if classes are hatched and
    carry "(what-if)" in their label.
    """
    if ct.empty:
        return ch.empty_figure("No cost components to show")
    labels = list(dict.fromkeys(ct["bus_class_label"]))
    what_if = {cm.CLASS_LABELS[c] for c in cm.WHAT_IF_CLASSES}
    fig = go.Figure()
    for comp in (*cm.TRIP_COMPONENTS, *cm.FIXED_COMPONENTS):
        g = ct[ct["component"] == comp].set_index("bus_class_label")
        if g.empty:
            continue
        vals = [float(g["inr_per_km"].get(lb, 0.0)) for lb in labels]
        layer = "trip operating" if comp in cm.TRIP_COMPONENTS else "fixed and overhead"
        fig.add_bar(
            y=labels, x=vals, orientation="h", name=f"{cm.COMPONENT_LABELS[comp]} ({layer})",
            marker=dict(color=COMPONENT_COLOURS[comp], line=dict(color="white", width=0.5),
                        pattern=dict(shape=["/" if lb in what_if else "" for lb in labels], size=6, solidity=0.35, fgcolor="white")),
            hovertemplate="%{y}<br>" + cm.COMPONENT_LABELS[comp] + f" ({layer}): " + "₹%{x:.1f} per bus-km<extra></extra>")
    fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=11)))
    fig.update_yaxes(autorange="reversed", title_text=None)
    fig.update_xaxes(title_text="Cost per bus-km (₹, illustrative)")
    return ch.style(fig, height=430, title=title)


# ---------------------------------------------------------------------------------------------------------------- bands
def band_hours_chart(bands_sel: pd.DataFrame) -> go.Figure:
    """Departure-hour load factor of the corridor with peak hours highlighted (``classify_time_bands`` output, one corridor x day type)."""
    if bands_sel.empty:
        return ch.empty_figure("No served hours for this corridor and day type")
    b = bands_sel.sort_values("dep_hour")
    colours = [BAND_COLOURS["peak"] if x == "peak" else ch.ACCENT_LIGHT for x in b["band"]]
    fig = go.Figure(go.Bar(x=b["dep_hour"], y=b["load_factor"] * 100, marker_color=colours,
                           customdata=np.stack([b["trips"], b["band"]], axis=-1),
                           hovertemplate="%{x:02d}:00<br>load factor %{y:.0f}%<br>%{customdata[0]} trips, %{customdata[1]}<extra></extra>"))
    thr = float(b["threshold"].iloc[0])
    fig.add_hline(y=thr * 100, line_dash="dash", line_color=ch.GREY,
                  annotation_text=f"peak threshold {thr * 100:.0f}%", annotation_position="top left")
    ch._hour_ticks(fig, [int(h) for h in b["dep_hour"]])
    fig.update_yaxes(title_text="Load factor (%)", rangemode="tozero")
    return ch.style(fig, height=300, title="Load factor by departure hour (peak hours in orange)")


BAND_METRICS: dict[str, tuple[str, str]] = {
    "load_factor_pct": ("Load factor (%)", "pct"),
    "revenue_per_trip_inr": ("Revenue per trip (₹)", "inr"),
    "full_cost_per_trip_inr": ("Full cost per trip (₹)", "inr"),
    "contribution_per_trip_inr": ("Contribution per trip (₹, not profit)", "inr"),
    "full_cost_margin_per_trip_inr": ("Full-cost margin per trip (₹)", "inr"),
    "contribution_per_seat_km_inr": ("Contribution per seat-km (₹)", "seat"),
    "full_cost_margin_per_seat_km_inr": ("Full-cost margin per seat-km (₹)", "seat"),
}


def band_compare_chart(econ_sel: pd.DataFrame, metric: str) -> go.Figure:
    """Grouped bar: peak vs normal by route/class for one ``band_economics`` metric."""
    if econ_sel.empty or metric not in BAND_METRICS:
        return ch.empty_figure("No band economics for this selection")
    label, _ = BAND_METRICS[metric]
    e = econ_sel.copy()
    e["label"] = e.apply(route_label, axis=1)
    fig = go.Figure()
    for b in ("peak", "normal"):
        g = e[e["band"] == b]
        if g.empty:
            continue
        fig.add_bar(x=g["label"], y=g[metric], name=b.capitalize(), marker_color=BAND_COLOURS[b],
                    hovertemplate="%{x}<br>" + b + ": %{y:,.2f}<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text=label, zeroline=True)
    fig.update_xaxes(title_text=None)
    return ch.style(fig, height=340)


# ---------------------------------------------------------------------------------------------------------------- fares
def fare_range_chart(rec_sel: pd.DataFrame) -> go.Figure:
    """Dumbbell/range chart per route-class x band: current fare, break-even fare, private comparator and recommended band."""
    if rec_sel.empty:
        return ch.empty_figure("No fare analysis for this selection")
    r = rec_sel.copy()
    r["y"] = r.apply(lambda x: f"{route_label(x)} · {x['band']}", axis=1)
    ys = list(r["y"])
    fig = go.Figure()
    shown = {"band": False, "floor": False}
    for row in r.itertuples():
        if ok(row.band_low_inr) and ok(row.band_high_inr):
            fig.add_trace(go.Scatter(x=[row.band_low_inr, row.band_high_inr], y=[row.y, row.y], mode="lines",
                                     line=dict(color=GOOD, width=12), opacity=0.55, name="Recommended band",
                                     legendgroup="band", showlegend=not shown["band"],
                                     hovertemplate=f"{row.y}<br>recommended band ₹{row.band_low_inr:,.0f} to ₹{row.band_high_inr:,.0f}<extra></extra>"))
            shown["band"] = True
        elif ok(row.band_low_inr):
            fig.add_trace(go.Scatter(x=[row.band_low_inr], y=[row.y], mode="markers", marker=dict(symbol="triangle-right", size=14, color=GOOD),
                                     name="Floor only (no private comparator)", legendgroup="floor", showlegend=not shown["floor"],
                                     hovertemplate=f"{row.y}<br>floor ₹{row.band_low_inr:,.0f}, no cap<extra></extra>"))
            shown["floor"] = True
    for col, name, sym, colour in (("current_fare_inr", "Current fare (adult, full route)", "diamond", ch.ACCENT),
                                   ("break_even_fare_inr", "Break-even fare (full cost at target load)", "x", ch.WARN),
                                   ("private_comparator_inr", "Private comparator (median)", "circle-open", ch.GREY)):
        g = r[r[col].map(ok)]
        if g.empty:
            continue
        fig.add_trace(go.Scatter(x=g[col], y=g["y"], mode="markers", name=name,
                                 marker=dict(symbol=sym, size=11, color=colour, line=dict(width=2, color=colour)),
                                 hovertemplate="%{y}<br>" + name + ": ₹%{x:,.0f}<extra></extra>"))
    xmax = float(np.nanmax(r[["current_fare_inr", "break_even_fare_inr", "private_comparator_inr", "band_high_inr"]].to_numpy(dtype=float)))
    for row in r.itertuples():
        if not row.viable:
            fig.add_annotation(x=xmax * 1.02, y=row.y, text="no band: not viable on fare alone", showarrow=False, xanchor="left",
                               font=dict(size=11, color=ch.WARN))
    fig.update_xaxes(title_text="Full-route adult fare (₹)", range=[0, xmax * 1.45])
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=ys, title_text=None)
    fig.update_layout(legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=11)))
    return ch.style(fig, height=max(300, 70 * len(ys) + 140))


# ---------------------------------------------------------------------------------------------------------------- CBA
def cba_summary_chart(corr: pd.DataFrame) -> go.Figure:
    """Left: BCR per corridor with the BCR = 1 line. Right: net social benefit per day. Missing values are left out."""
    c = corr.dropna(subset=["bcr"])
    if c.empty:
        return ch.empty_figure("BCR not available (full cost missing)")
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Benefit-cost ratio (1.0 = benefits just cover cost)", "Net social benefit per day (₹)"),
                        horizontal_spacing=0.14)
    fig.add_bar(x=c["corridor"], y=c["bcr"], marker_color=ch.ACCENT, name="BCR", showlegend=False,
                hovertemplate="%{x}<br>BCR %{y:.2f}<extra></extra>", row=1, col=1)
    fig.add_hline(y=1.0, line_dash="dash", line_color=ch.WARN, row=1, col=1)
    net = c["net_social_benefit_per_day_inr"]
    fig.add_bar(x=c["corridor"], y=net, marker_color=[ch.ACCENT if v >= 0 else ch.WARN for v in net], name="Net social benefit",
                showlegend=False, hovertemplate="%{x}<br>₹%{y:,.0f} per day<extra></extra>", row=1, col=2)
    fig.update_yaxes(rangemode="tozero", row=1, col=1)
    return ch.style(fig, height=340)


WATERFALL_LABELS: dict[str, str] = {
    "private_travel_cost_saved": "Vehicle cost saved", "fare_paid_diverted_users": "Fare paid (users)",
    "induced_traveller_surplus": "New-traveller surplus", "travel_time": "Travel time",
    "co2_private_avoided": "CO2 avoided", "co2_bus_emissions": "CO2 of bus", "accidents_avoided": "Accidents avoided",
    "accidents_bus": "Bus accidents", "congestion_avoided": "Congestion avoided", "congestion_bus": "Bus congestion",
    "ticket_revenue": "Ticket revenue", "full_cost": "Full cost",
}


def cba_waterfall(comp: pd.DataFrame, corridor: str) -> go.Figure:
    """Waterfall of ``socio_economic.component_table`` for one corridor; negative components go down. Ends in the net social benefit."""
    c = comp[comp["INR_per_day"].map(ok)]
    if c.empty or len(c) < len(comp):
        return ch.empty_figure("Components not available (full cost missing)")
    x = [WATERFALL_LABELS.get(k, k) for k in c["component"]] + ["Net social benefit"]
    y = list(c["INR_per_day"].astype(float)) + [float(c["INR_per_day"].sum())]
    fig = go.Figure(go.Waterfall(
        x=x, y=y, measure=["relative"] * len(c) + ["total"], connector=dict(line=dict(color=ch.GREY_LIGHT)),
        increasing=dict(marker=dict(color=ch.ACCENT)), decreasing=dict(marker=dict(color=ch.WARN)),
        totals=dict(marker=dict(color="#2a8a8a")), hovertemplate="%{x}<br>₹%{y:,.0f} per day<extra></extra>"))
    fig.update_yaxes(title_text="₹ per average day")
    fig.update_xaxes(tickangle=-35)
    return ch.style(fig, height=420, title=f"{corridor}: where the net social benefit comes from (₹ per day)")


TORNADO_LABELS: dict[str, str] = {
    "value_of_time_inr_per_hour": "Value of time (₹/hour)", "share_car": "Share of passengers who would drive a car",
    "carbon_price_inr_per_tonne": "Carbon price (₹/tonne)",
}


def tornado_chart(tor: pd.DataFrame, corridor: str) -> go.Figure:
    """Tornado of the BCR for one corridor: bar from the low to the high setting of each assumption around the base case."""
    t = tor[(tor["corridor"] == corridor)].dropna(subset=["bcr_low", "bcr_high", "bcr_central"])
    if t.empty:
        return ch.empty_figure("Sensitivity not available (full cost missing)")
    t = t.sort_values("bcr_swing", ascending=True)
    base = float(t["bcr_central"].iloc[0])
    names = [TORNADO_LABELS.get(p, p) for p in t["parameter"]]
    fig = go.Figure()
    for col, name, colour in (("bcr_low", "Low setting", ch.ACCENT_MID), ("bcr_high", "High setting", ch.WARN)):
        fig.add_bar(y=names, x=t[col] - base, base=base, orientation="h", name=name, marker_color=colour,
                    customdata=t[col], hovertemplate="%{y}<br>" + name + ": BCR %{customdata:.2f}<extra></extra>")
    fig.add_vline(x=base, line_color=ch.TEXT, line_width=1)
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title_text=f"Benefit-cost ratio (base case {base:.2f})")
    return ch.style(fig, height=260, title=f"{corridor}: how much each assumption moves the BCR")


# ---------------------------------------------------------------------------------------------------------------- PDF payload
def default_report_payload(inputs: dict, route_summary: pd.DataFrame, corridor: str, day_type: str) -> dict[str, Any]:
    """Everything the PDF section needs at DEFAULT parameters (same computations as the page, no Streamlit)."""
    from modules.analytics import fare_analysis as FA

    model, routes = inputs["model"], inputs["routes"]
    econ = FA.band_economics(inputs["tm"], model, routes)
    pc = FA.private_comparison(econ, inputs["competitors"])
    rec = FA.recommend_fare_band(pc)
    sel = econ[(econ["corridor"] == corridor) & (econ["day_type"] == day_type)]
    length = corridor_length(sel) if len(sel) else None
    summary = cm.cost_summary(model, corridor=corridor if length else None, length_km=length)
    bands = inputs["bands"]
    bsel = bands[(bands["corridor"] == corridor) & (bands["day_type"] == day_type)]
    n_total = float(inputs["tm"]["service_date"].nunique())
    cinp = cba_inputs(route_summary, econ, n_total)
    res = SE.compute_cba(cinp)
    corr = SE.aggregate_to_corridor(res)
    return {"summary": summary, "sel": sel, "bands": bsel, "rec": rec[(rec["corridor"] == corridor) & (rec["day_type"] == day_type)],
            "corr": corr, "length_km": length, "target_load_factor": float(econ["target_load_factor"].iloc[0])}
