"""Route potential score (``route_scores``): a transparent, rule-based 0-100 index. NOT an AI prediction.

Seven components with weights from ``config.ROUTE_SCORE_WEIGHTS`` (version ``demo-v1``; demo weights, not policy):

1. ``demand_score``            mean of min-max(avg boardings/day) and min-max(catchment = population + jobs of the distinct
                               zones the route serves).
2. ``unmet_demand_score``      min-max(sum of weekday ``gap_count`` over the route's route-direction hours; intercity routes
                               also receive an equal share of their corridor's no-state-capacity market gap). A lower bound
                               because ticketed demand is censored at capacity.
3. ``load_factor_score``       min-max(peak-hour peak load factor = max-link onboard / seats at the route's busiest weekday hour).
4. ``reliability_gap_score``   min-max(100 - reliability_pct): higher = more room to improve punctuality.
5. ``revenue_potential_score`` mean of min-max(ticket revenue/day) and min-max(EPKM).
6. ``social_importance_score`` rule-based, NOT min-max: 50 if ``minimum_service`` + 50 x share of the distinct zones served that
                               are residential, education or religious.
7. ``feasibility_score``       PROXY (no fleet/driver/depot data exists): mean of (100 - min-max(mean scheduled minutes), i.e.
                               shorter routes turn buses round faster) and min-max(weekday trips/day = existing frequency).

Min-max normalisation (components 1-5, 7) is done WITHIN ``route_type`` (local routes vs intercity routes), because
a 190 km AC intercity bus and a 10 km city shuttle are not comparable on volume or revenue. A group whose inputs are all
identical (or that has a single route) gets a neutral 50. A missing input gives a NaN component; ``total_score`` then
re-weights the remaining components (weights divided by the sum of available weights) and the explanation says so.
Routes with ``minimum_service`` are flagged ``protected_minimum_service``: the score never leads to a removal action.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from modules.analytics.common import SOURCE_TYPE, jdump
from modules.analytics.gaps import STATUS_NO_CAPACITY

COMPONENTS = ["demand_score", "unmet_demand_score", "load_factor_score", "reliability_gap_score",
              "revenue_potential_score", "social_importance_score", "feasibility_score"]
_WEIGHT_KEY = dict(zip(COMPONENTS, ["demand_potential", "unmet_demand", "load_factor", "reliability_gap",
                                    "revenue_potential", "social_importance", "feasibility"]))
_LABEL = {"demand_score": "demand potential", "unmet_demand_score": "unmet demand", "load_factor_score": "peak crowding",
          "reliability_gap_score": "punctuality improvement room", "revenue_potential_score": "revenue potential",
          "social_importance_score": "social importance", "feasibility_score": "operational feasibility (proxy)"}
SOCIAL_ZONE_TYPES = ("residential", "education", "religious")


def minmax_within(values: pd.Series, groups: pd.Series, invert: bool = False) -> pd.Series:
    """Min-max to 0-100 within each group. NaN stays NaN; identical values (or one route) -> 50. ``invert`` flips."""
    v = pd.to_numeric(values, errors="coerce")
    out = pd.Series(np.nan, index=v.index, dtype=float)
    for _, idx in v.groupby(groups).groups.items():
        s = v.loc[idx]
        ok = s.dropna()
        if ok.empty:
            continue
        lo, hi = ok.min(), ok.max()
        scaled = pd.Series(50.0, index=ok.index) if hi == lo else (ok - lo) / (hi - lo) * 100.0
        if invert:
            scaled = 100.0 - scaled
        out.loc[ok.index] = scaled
    return out


def _nanmean_cols(*cols: pd.Series) -> pd.Series:
    return pd.concat(cols, axis=1).mean(axis=1, skipna=False)


def served_zone_table(routes: pd.DataFrame, route_stops: pd.DataFrame, stops: pd.DataFrame, zones: pd.DataFrame) -> pd.DataFrame:
    """Per route: distinct zones served, catchment (population + jobs) and the share of residential/education/religious zones."""
    rz = route_stops[["route_id", "stop_id"]].merge(stops[["stop_id", "zone_id"]], on="stop_id", how="left").drop_duplicates(["route_id", "zone_id"])
    rz = rz.merge(zones[["zone_id", "population", "jobs", "zone_type"]], on="zone_id", how="left")
    g = rz.groupby("route_id").agg(
        zones_served=("zone_id", "nunique"), catchment=("population", "sum"), jobs=("jobs", "sum"),
        social_zones=("zone_type", lambda s: int(s.isin(SOCIAL_ZONE_TYPES).sum())),
    ).reset_index()
    g["catchment"] = g["catchment"] + g["jobs"]
    g["social_zone_share"] = g["social_zones"] / g["zones_served"].where(g["zones_served"] > 0)
    return g.drop(columns="jobs")


def unmet_demand_by_route(hourly: pd.DataFrame, routes: pd.DataFrame, day_type: str | None = None) -> pd.Series:
    """Sum of weekday gap_count per route (+ equal share of the corridor's no-state-capacity market gap for intercity routes)."""
    day_type = day_type or config.PEAK_DAY_TYPE
    if hourly.empty:
        return pd.Series(np.nan, index=routes["route_id"], dtype=float)
    h = hourly[hourly["day_type"] == day_type]
    rd = h[h["level"] == "route_direction"].groupby("route_id")["gap_count"].sum(min_count=1)
    out = pd.Series(0.0, index=routes["route_id"], dtype=float)
    out.loc[rd.index.intersection(out.index)] = rd
    cor = h[(h["level"] == "corridor") & (h["status"] == STATUS_NO_CAPACITY)].groupby("corridor")["gap_count"].sum(min_count=1)
    n_routes = routes[routes["corridor"].notna()].groupby("corridor")["route_id"].count()
    for c, gap in cor.items():
        share = gap / n_routes[c]
        for rid in routes.loc[routes["corridor"] == c, "route_id"]:
            out[rid] += share
    return out


def route_scores(summary: pd.DataFrame, hourly: pd.DataFrame, routes: pd.DataFrame, route_stops: pd.DataFrame,
                 stops: pd.DataFrame, zones: pd.DataFrame, trips: pd.DataFrame,
                 weights: config.RouteScoreWeights | None = None) -> pd.DataFrame:
    w = weights or config.ROUTE_SCORE_WEIGHTS
    wd = w.components()
    df = summary[["route_id", "route_type", "minimum_service", "avg_boardings_per_day", "revenue_per_day_inr", "epkm_inr",
                  "peak_hour_load_factor", "reliability_pct", "trips_per_day_weekday"]].copy()
    sz = served_zone_table(routes, route_stops, stops, zones)
    df = df.merge(sz, on="route_id", how="left")
    sched = trips.groupby("route_id")["scheduled_minutes"].mean().rename("scheduled_minutes")
    df = df.join(sched, on="route_id")
    df["unmet_raw"] = df["route_id"].map(unmet_demand_by_route(hourly, routes))
    grp = df["route_type"]
    c = pd.DataFrame({"route_id": df["route_id"]})
    c["demand_score"] = _nanmean_cols(minmax_within(df["avg_boardings_per_day"], grp), minmax_within(df["catchment"], grp))
    c["unmet_demand_score"] = minmax_within(df["unmet_raw"], grp)
    c["load_factor_score"] = minmax_within(df["peak_hour_load_factor"], grp)
    c["reliability_gap_score"] = minmax_within(100.0 - df["reliability_pct"], grp)
    c["revenue_potential_score"] = _nanmean_cols(minmax_within(df["revenue_per_day_inr"], grp), minmax_within(df["epkm_inr"], grp))
    c["social_importance_score"] = 50.0 * df["minimum_service"].astype(float) + 50.0 * df["social_zone_share"]
    c["feasibility_score"] = _nanmean_cols(minmax_within(df["scheduled_minutes"], grp, invert=True),
                                           minmax_within(df["trips_per_day_weekday"], grp))
    wts = pd.Series({k: wd[_WEIGHT_KEY[k]] for k in COMPONENTS})
    avail = c[COMPONENTS].notna()
    wsum = avail.mul(wts, axis=1).sum(axis=1)
    contrib = c[COMPONENTS].fillna(0.0).mul(wts, axis=1).div(wsum.where(wsum > 0), axis=0)
    c["total_score"] = contrib.sum(axis=1).where(wsum > 0)
    c["weight_version"] = w.weight_version
    c["route_type"] = df["route_type"].to_numpy()
    c["minimum_service"] = df["minimum_service"].astype(bool).to_numpy()
    c["protected_minimum_service"] = c["minimum_service"]
    c["missing_components"] = [",".join(k for k in COMPONENTS if not avail.loc[i, k]) for i in c.index]
    c["weights_json"] = jdump({**{k: wd[_WEIGHT_KEY[k]] for k in COMPONENTS}, "weight_version": w.weight_version})
    c["normalisation"] = ("min-max within route_type (local vs intercity); social importance is rule-based; "
                          "missing components are re-weighted")
    inputs = df[["avg_boardings_per_day", "catchment", "unmet_raw", "peak_hour_load_factor", "reliability_pct",
                 "revenue_per_day_inr", "epkm_inr", "social_zone_share", "scheduled_minutes", "trips_per_day_weekday"]]
    c["inputs_json"] = [jdump(r) for r in inputs.to_dict("records")]
    c["explanation"] = [_explain(c.loc[i], contrib.loc[i], avail.loc[i], wsum.loc[i], wts) for i in c.index]
    c["rank"] = c["total_score"].rank(ascending=False, method="min")
    c["rank_within_type"] = c.groupby("route_type")["total_score"].rank(ascending=False, method="min")
    c["source_type"] = SOURCE_TYPE
    cols = ["route_id", "demand_score", "unmet_demand_score", "load_factor_score", "reliability_gap_score",
            "revenue_potential_score", "social_importance_score", "feasibility_score", "total_score", "weight_version",
            "explanation", "source_type", "route_type", "rank", "rank_within_type", "minimum_service",
            "protected_minimum_service", "missing_components", "weights_json", "normalisation", "inputs_json"]
    return c[cols].sort_values(["total_score", "route_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def _explain(row: pd.Series, contrib: pd.Series, avail: pd.Series, wsum: float, wts: pd.Series) -> str:
    if not avail.any():
        return "No score: every component input is missing. Rule-based index, not a prediction."
    top = contrib[avail].sort_values(ascending=False).head(2)
    drivers = "; ".join(f"{_LABEL[k]} ({row[k]:.0f}/100, weight {wts[k] * 100:.0f}%)" for k in top.index)
    parts = [f"Top score drivers: {drivers}."]
    low = contrib[avail].sort_values().head(1)
    if len(low):
        k = low.index[0]
        parts.append(f"Weakest component: {_LABEL[k]} ({row[k]:.0f}/100).")
    miss = [k for k in COMPONENTS if not avail[k]]
    if miss:
        parts.append(f"Missing inputs for {', '.join(_LABEL[k] for k in miss)}; remaining components re-weighted (sum of weights {wsum:.2f}).")
    if bool(row["minimum_service"]):
        parts.append("Minimum-service route: retain and review the timetable regardless of commercial score; never a removal candidate.")
    parts.append(f"Rule-based demo score (weights {row['weight_version']}), not an AI prediction.")
    return " ".join(parts)
