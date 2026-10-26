"""Pure helpers for the "Next 7 days (baseline estimate)" view on Route Intelligence.

Everything here is computed from two tables: ``baseline_forecast`` (the deterministic seasonal-average baseline of
:mod:`modules.analytics.forecast`, NOT the ML model) and ``route_kpis`` (observed synthetic daily boardings). No file access.
"""
from __future__ import annotations

import pandas as pd

Z80 = 1.2816  # same constant as modules.analytics.forecast.Z80

# Why the ML model is not used for the forward week (see modules/ml/ridership.py FEATURES): its inputs include planned supply
# (sched_trips / sched_seats from the timetable), is_festival and private_services for each date; the generated timetable
# (trips) covers only the 42 history dates and no festival calendar exists for the future (forecast.py docstring), so scoring
# future dates would need invented inputs. The baseline needs only past boardings.
WHY_NOT_ML = ("Why not the machine-learning model? Its inputs include the planned timetable (scheduled trips and seats) and the "
              "festival flag for each date, and the data holds no timetable or festival calendar beyond the 42 history days. "
              "Scoring future days would mean inventing those inputs, so the forward view uses a baseline that needs only past boardings.")


def history_tail(route_kpis_route: pd.DataFrame, days: int = 21) -> pd.DataFrame:
    """Last ``days`` observed days of one route: service_date (datetime), boardings, day_type."""
    h = route_kpis_route[["service_date", "boardings", "day_type"]].copy()
    h["service_date"] = pd.to_datetime(h["service_date"])
    return h.sort_values("service_date").tail(days).reset_index(drop=True)


def forecast_rows(fc: pd.DataFrame, route_id: str) -> pd.DataFrame:
    d = fc[fc["route_id"] == route_id].copy()
    d["service_date"] = pd.to_datetime(d["service_date"])
    return d.sort_values("service_date").reset_index(drop=True)


def forecast_table(fcr: pd.DataFrame) -> pd.DataFrame:
    """Display table: date, weekday, day type, estimate, band."""
    return pd.DataFrame({
        "Date": fcr["service_date"].dt.strftime("%d %b %Y"),
        "Weekday": fcr["service_date"].dt.strftime("%A"),
        "Day type": fcr["day_type"],
        "Estimate (passengers)": fcr["forecast_boardings"].round(0).astype(int),
        "Band (approx. 80 %)": [f"{lo:,.0f} - {hi:,.0f}" for lo, hi in zip(fcr["lower_bound"], fcr["upper_bound"])],
    })


def summarize(fcr: pd.DataFrame, hist: pd.DataFrame) -> dict:
    """KPIs of the forecast week for one route, plus a comparison with the last 7 observed days."""
    if fcr.empty:
        return {}
    peak = fcr.loc[fcr["forecast_boardings"].idxmax()]
    last7 = hist.tail(7)
    total = float(fcr["forecast_boardings"].sum())
    prev = float(last7["boardings"].sum()) if len(last7) == 7 else float("nan")
    return {
        "total": total, "lower_total": float(fcr["lower_bound"].sum()), "upper_total": float(fcr["upper_bound"].sum()),
        "peak_weekday": peak["service_date"].strftime("%A"), "peak_value": float(peak["forecast_boardings"]),
        "prev_week_total": prev, "change_pct": (total / prev - 1) * 100 if prev == prev and prev > 0 else float("nan"),
        "first_date": fcr["service_date"].min(), "last_date": fcr["service_date"].max(),
        "spread_pct": float(fcr["pooled_relative_spread"].iloc[0]) * 100, "weeks": int(fcr["history_weeks"].iloc[0]),
    }


def dates_follow_history(fcr: pd.DataFrame, hist: pd.DataFrame) -> bool:
    """True when the forecast dates are exactly the consecutive days after the last observed date."""
    if fcr.empty or hist.empty:
        return False
    expected = pd.date_range(hist["service_date"].max() + pd.Timedelta(days=1), periods=len(fcr))
    return list(fcr["service_date"]) == list(expected)


def takeaway(route_id: str, s: dict) -> str:
    """One 'what this means' sentence, built from the summary (never a prediction claim)."""
    if not s:
        return f"No baseline estimate is available for {route_id}."
    chg = ""
    if s["change_pct"] == s["change_pct"]:
        word = "above" if s["change_pct"] >= 0 else "below"
        chg = f", {abs(s['change_pct']):.0f}% {word} the last 7 observed days ({s['prev_week_total']:,.0f})"
    return (f"If the recent weekly pattern simply repeats, {route_id} would carry about {s['total']:,.0f} passengers over "
            f"{s['first_date']:%d %b}-{s['last_date']:%d %b}{chg}, busiest on {s['peak_weekday']} (about {s['peak_value']:,.0f}). "
            f"This is a seasonal-average baseline with an approximate 80% band of +/-{s['spread_pct'] * Z80:.0f}% per day, built from "
            f"{s['weeks']} weeks of simulated history; it is a planning reference, not a prediction of real GSRTC ridership.")
