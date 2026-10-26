"""``competition_analysis`` (M5): corridor x clock hour x day type comparison of state and synthetic private services, the
fare index (normal and illustrative surge) and the competitive gap score with visible, versioned component weights.

Illustrative only: competitor services, fares and reviews are synthetic demonstration values, not verified operator data.

Competitor timetable convention (documented in M1, `docs/DATA_SCHEMA.md`): ``competitor_services.departure_time`` is the
departure from the corridor origin (Rajkot) ONLY; the opposite direction is assumed to mirror the same slots and is NOT
modelled separately. ``competition_analysis`` therefore compares OUTBOUND state departures from Rajkot with the private
departures from Rajkot.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import config
from modules.analytics.common import SOURCE_TYPE, dep_hour, jdump, n_days_by_day_type
from modules.analytics.recommendations import full_route_fare_inr
from modules.competition.analysis import corridor_route_ids
from modules.survey import themes as TH

COMPETITION_COLUMNS = [
    "route_pair", "hour", "day_type", "state_departures", "private_departures", "state_seats", "private_seats",
    "state_fare_inr", "median_private_fare_inr", "fare_index", "median_private_surge_fare_inr", "fare_index_surge",
    "premium_bus_gap", "review_theme_summary", "competitive_gap_score",
    "departure_slot_gap", "seat_share_gap", "premium_gap_component", "fare_disadvantage", "review_theme_deficit",
    "missing_components", "weight_version", "weights_json", "assumptions_json", "source_type"]
# component name (config weight key) -> column in competition_analysis
COMPONENT_COLUMNS = {"departure_slot_gap": "departure_slot_gap", "seat_share_gap": "seat_share_gap",
                     "premium_gap": "premium_gap_component", "fare_disadvantage": "fare_disadvantage",
                     "review_theme_deficit": "review_theme_deficit"}
COMPONENT_LABELS = {"departure_slot_gap": "Departure-slot gap", "seat_share_gap": "Seat-share gap",
                    "premium_gap": "Premium-bus gap", "fare_disadvantage": "Fare disadvantage",
                    "review_theme_deficit": "Review-theme deficit"}


def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def score_components(*, state_deps: float, private_deps: float, state_seats: float, private_seats: float, premium_gap: float,
                     fare_index: float, review_deficit: float) -> dict[str, float]:
    """The five 0-1 components of the competitive gap score for one corridor-hour (NaN = not available).

    * ``departure_slot_gap`` = 1 if private services depart and the state has none, else ``max(0, p - s) / p``.
    * ``seat_share_gap`` = ``max(0, ps - ss) / (ps + ss)`` (private seats beyond state seats).
    * ``premium_gap`` = ``premium_bus_gap / PREMIUM_GAP_SATURATION`` capped at 1.
    * ``fare_disadvantage`` = ``(fare_index - 1) / FARE_DISADVANTAGE_SATURATION`` clipped to 0-1: only a state tariff ABOVE the
      private median counts (0 when the state is cheaper); NaN when no private fare exists in the slot.
    * ``review_theme_deficit`` = corridor mean per-theme excess of state over private negative-mention share, over its
      saturation (NaN when the corridor has too few reviews).
    All components are 0 where no private operator departs in the hour (no competitive pressure to measure).
    """
    if private_deps <= 0:
        return {"departure_slot_gap": 0.0, "seat_share_gap": 0.0, "premium_gap": 0.0, "fare_disadvantage": 0.0,
                "review_theme_deficit": 0.0}
    dep = 1.0 if state_deps <= 0 else _clip01((private_deps - state_deps) / private_deps)
    tot = private_seats + state_seats
    seat = _clip01((private_seats - state_seats) / tot) if tot > 0 else 0.0
    prem = _clip01(premium_gap / config.PREMIUM_GAP_SATURATION)
    fare = float("nan") if pd.isna(fare_index) else _clip01((fare_index - 1.0) / config.FARE_DISADVANTAGE_SATURATION)
    rev = float("nan") if pd.isna(review_deficit) else _clip01(review_deficit / config.REVIEW_DEFICIT_SATURATION)
    return {"departure_slot_gap": dep, "seat_share_gap": seat, "premium_gap": prem, "fare_disadvantage": fare,
            "review_theme_deficit": rev}


def combine_score(components: dict[str, float], weights: dict[str, float] | None = None) -> tuple[float, list[str]]:
    """0-100 weighted score over the available components (missing ones dropped, the rest re-weighted);
    returns ``(score, missing_component_names)``. All components missing -> NaN."""
    w = config.COMPETITIVE_GAP_WEIGHTS.components() if weights is None else weights
    avail = {k: v for k, v in components.items() if not pd.isna(v)}
    missing = sorted(k for k in w if k not in avail)
    tw = sum(w[k] for k in avail)
    if tw <= 0:
        return float("nan"), missing
    return 100.0 * sum(w[k] * avail[k] for k in avail) / tw, missing


def state_tariffs(routes: pd.DataFrame, corridor: str) -> dict[str, float]:
    """Illustrative state full-route fare per bus type on a corridor (mean over that bus type's routes)."""
    r = routes[routes["corridor"] == corridor]
    return {str(b): float(np.mean([full_route_fare_inr(b, float(k)) for k in g["length_km"]])) for b, g in r.groupby("bus_type")}


def _equivalent_state_fare(bus_type: str, tariffs: dict[str, float]) -> float:
    """State tariff of the same bus class; ``premium`` maps to the state AC_sleeper; no equivalent -> NaN (never invented)."""
    return tariffs.get("AC_sleeper" if bus_type == "premium" else bus_type, float("nan"))


def competition_analysis(trips: pd.DataFrame, competitors: pd.DataFrame, routes: pd.DataFrame, reviews: pd.DataFrame,
                         method: str = TH.METHOD_GENERATOR) -> pd.DataFrame:
    """Derived table ``competition_analysis``: intercity corridor x clock hour x day type (hours with any departure).

    * Departures and seats: state = outbound trips of the corridor's routes / number of dates of the day type (average day);
      private = competitor services of that corridor and day type (departure from Rajkot; both directions assumed to mirror).
    * ``state_fare_inr`` = median over the hour's private services of the illustrative state tariff for the SAME bus class
      (``premium`` -> state AC_sleeper; no state class -> not counted); with no private service it is the mean tariff of the
      state routes departing that hour. ``fare_index = state_fare / median private base fare``; ``fare_index_surge`` uses the
      median private ``surge_fare_inr`` of the day type (illustrative peak fare; the state tariff does not surge).
    * ``premium_bus_gap`` = private premium / AC-sleeper services in the hour when no state AC_sleeper departs that hour.
    * ``review_theme_summary`` = JSON of per-operator theme counts and polarity for the corridor (``method`` says whose tags).
    * ``competitive_gap_score`` = 0-100 weighted sum of :func:`score_components` (``config.COMPETITIVE_GAP_WEIGHTS``,
      visible in ``weights_json``; weight version in ``weight_version``).
    """
    rows: list[dict[str, Any]] = []
    nd = n_days_by_day_type(trips)
    w = config.COMPETITIVE_GAP_WEIGHTS
    wj = jdump({**w.components(), "weight_version": w.weight_version})
    rb = routes.set_index("route_id")
    for corridor in sorted(routes["corridor"].dropna().unique()):
        ids = corridor_route_ids(routes, corridor)
        tariffs = state_tariffs(routes, corridor)
        summary = jdump(TH.review_theme_summary(reviews, corridor, method))
        deficit = TH.review_theme_deficit(reviews, corridor, method, min_reviews=config.REVIEW_MIN_PER_OPERATOR)
        for day_type in sorted(competitors["day_type"].unique()):
            days = int(nd.get(day_type, 0))
            t = trips[trips["route_id"].isin(ids) & (trips["direction"] == "outbound") & (trips["day_type"] == day_type)].copy()
            t["hour"] = dep_hour(t["departure_time"])
            c = competitors[(competitors["route_pair"] == corridor) & (competitors["day_type"] == day_type)].copy()
            c["hour"] = dep_hour(c["departure_time"])
            hours = sorted(set(t["hour"].dropna().astype(int)) | set(c["hour"].dropna().astype(int)))
            for h in hours:
                th, ch = t[t["hour"] == h], c[c["hour"] == h]
                sdep = len(th) / days if days else 0.0
                sseat = float(th["seats"].sum()) / days if days else 0.0
                pdep, pseat = float(len(ch)), float(ch["seats"].sum())
                if len(ch):
                    st_fares = [_equivalent_state_fare(b, tariffs) for b in ch["bus_type"]]
                    state_fare = float("nan") if np.all(np.isnan(st_fares)) else float(np.nanmedian(st_fares))
                    med, med_s = float(ch["base_fare_inr"].median()), float(ch["surge_fare_inr"].median())
                else:
                    f = [full_route_fare_inr(rb.loc[r, "bus_type"], float(rb.loc[r, "length_km"])) for r in th["route_id"]]
                    state_fare = float(np.mean(f)) if f else float("nan")
                    med = med_s = float("nan")
                prem_private = int(ch["bus_type"].isin(config.PREMIUM_BUS_TYPES).sum())
                state_equiv = int(th["route_id"].map(rb["bus_type"]).isin(config.STATE_PREMIUM_EQUIVALENT).sum())
                prem_gap = float(prem_private) if state_equiv == 0 else 0.0
                fi = state_fare / med if med == med and med > 0 else float("nan")
                fis = state_fare / med_s if med_s == med_s and med_s > 0 else float("nan")
                comps = score_components(state_deps=sdep, private_deps=pdep, state_seats=sseat, private_seats=pseat,
                                         premium_gap=prem_gap, fare_index=fi, review_deficit=deficit)
                score, missing = combine_score(comps)
                rows.append({
                    "route_pair": corridor, "hour": h, "day_type": day_type, "state_departures": sdep, "private_departures": pdep,
                    "state_seats": sseat, "private_seats": pseat, "state_fare_inr": state_fare, "median_private_fare_inr": med,
                    "fare_index": fi, "median_private_surge_fare_inr": med_s, "fare_index_surge": fis, "premium_bus_gap": prem_gap,
                    "review_theme_summary": summary, "competitive_gap_score": score,
                    "departure_slot_gap": comps["departure_slot_gap"], "seat_share_gap": comps["seat_share_gap"],
                    "premium_gap_component": comps["premium_gap"], "fare_disadvantage": comps["fare_disadvantage"],
                    "review_theme_deficit": comps["review_theme_deficit"], "missing_components": ",".join(missing),
                    "weight_version": w.weight_version, "weights_json": wj,
                    "assumptions_json": jdump({
                        "departures": "outbound from Rajkot; private departures are the competitor timetable (both directions assumed to mirror)",
                        "state_fare": "illustrative demo tariff for the same bus class (premium -> AC_sleeper)",
                        "surge": "illustrative competitor peak fare; the state tariff is held constant",
                        "review_method": method, "review_min_per_operator": config.REVIEW_MIN_PER_OPERATOR,
                        "no_private_service_means_score_0": True, "note": config.SIMULATION_BADGE_TEXT}),
                    "source_type": SOURCE_TYPE})
    if not rows:
        return pd.DataFrame(columns=COMPETITION_COLUMNS)
    return pd.DataFrame(rows)[COMPETITION_COLUMNS].sort_values(["route_pair", "day_type", "hour"], kind="mergesort").reset_index(drop=True)


def top_gap_slots(comp: pd.DataFrame, corridor: str | None = None, day_type: str | None = None, top: int = 5) -> pd.DataFrame:
    """Highest competitive gap scores (optionally one corridor / day type); ties broken by corridor, day type, hour."""
    c = comp
    if corridor is not None:
        c = c[c["route_pair"] == corridor]
    if day_type is not None:
        c = c[c["day_type"] == day_type]
    return c.sort_values(["competitive_gap_score", "route_pair", "day_type", "hour"], ascending=[False, True, True, True],
                         kind="mergesort").head(top).reset_index(drop=True)


def fare_index_view(comp: pd.DataFrame, corridor: str, day_type: str) -> pd.DataFrame:
    """Hours of one corridor/day type with a private fare: normal vs illustrative surge fare index."""
    c = comp[(comp["route_pair"] == corridor) & (comp["day_type"] == day_type) & comp["fare_index"].notna()]
    return c[["hour", "state_fare_inr", "median_private_fare_inr", "median_private_surge_fare_inr", "fare_index",
              "fare_index_surge"]].reset_index(drop=True)
