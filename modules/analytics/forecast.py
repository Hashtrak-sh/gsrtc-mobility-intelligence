"""Deterministic baseline forecast of next-week route-day boardings (Milestone 6). NOT a model.

Method ("seasonal average"): for every route and every day of the next 7 calendar days, the estimate is the mean boardings of
the same weekday over the last ``config.FORECAST_HISTORY_WEEKS`` weeks of history, leaving out festival days (the calendar
of the forecast week is assumed festival-free: no festival calendar is available for the future). The band is the estimate
+/- 1.2816 x the pooled relative spread (coefficient of variation) of the same-weekday history, i.e. an approximate 80 %
band under a normal assumption. With 6 synthetic weeks this is a plain rule-of-thumb baseline - labelled "baseline
estimate", never "prediction" - and Prophet / seasonal decomposition are deliberately not used (too little history).
Needs only pandas; no scikit-learn.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

TABLE = "baseline_forecast"
Z80 = 1.2816  # standard-normal 90th percentile: +/- Z80 x sigma is a nominal 80 % band


def baseline_forecast(route_kpis: pd.DataFrame, weeks: int = config.FORECAST_HISTORY_WEEKS,
                      horizon_days: int = config.FORECAST_HORIZON_DAYS) -> pd.DataFrame:
    """Next-``horizon_days`` route-day baseline estimate with a simple band (see module docstring)."""
    k = route_kpis[["route_id", "service_date", "day_type", "boardings"]].copy()
    k["date"] = pd.to_datetime(k["service_date"])
    last = k["date"].max()
    start = last - pd.Timedelta(days=7 * weeks - 1)
    hist = k[(k["date"] >= start) & (k["day_type"] != "festival")].copy()
    hist["dow"] = hist["date"].dt.dayofweek
    g = hist.groupby(["route_id", "dow"])["boardings"]
    stats = g.agg(mean="mean", std="std", n="count").reset_index()
    stats["cv"] = stats["std"].fillna(0.0) / stats["mean"].replace(0, np.nan)
    pooled_cv = float(np.sqrt(np.nanmean(stats.loc[stats["n"] >= 2, "cv"] ** 2))) if (stats["n"] >= 2).any() else 0.0
    rows = []
    for i in range(1, horizon_days + 1):
        d = last + pd.Timedelta(days=i)
        dow = d.dayofweek
        s = stats[stats["dow"] == dow]
        for r in s.itertuples():
            est = float(r.mean)
            half = Z80 * pooled_cv * est
            rows.append({"route_id": r.route_id, "service_date": d.strftime("%Y-%m-%d"),
                         "day_type": "weekend" if dow >= 5 else "weekday", "forecast_boardings": est,
                         "lower_bound": max(0.0, est - half), "upper_bound": est + half,
                         "history_days_used": int(r.n), "history_weeks": int(weeks),
                         "pooled_relative_spread": pooled_cv,
                         "method": "same-weekday mean of the last %d weeks, festival days excluded" % weeks,
                         "label": "Baseline estimate (seasonal average) - not a model; synthetic history of 6 weeks only; "
                                  "assumes no festival in the forecast week",
                         "source_type": "model_output"})
    out = pd.DataFrame(rows).sort_values(["route_id", "service_date"]).reset_index(drop=True)
    return out
