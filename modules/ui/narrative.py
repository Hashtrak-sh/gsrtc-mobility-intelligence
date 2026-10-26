"""Templated plain-language sentences for 'What this means' boxes, findings and recommendation cards.

Every number in the text is passed in from computed tables (nothing is hardcoded); every function is pure so the wording can
be tested. Wording rules (RULES.md): say 'synthetic' / 'illustrative', contribution is not profit, gaps from ticketed demand
are lower bounds, private-market demand is an assumption.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

import config
from modules.analytics import queries as Q
from modules.ui import fmt


def _short(name: str) -> str:
    """Route/stop display name without the trailing '(demo...)' marker."""
    i = name.rfind(" (demo")
    return name[:i] if i > 0 else name


# ---------------------------------------------------------------------------
# Overview findings (computed from the filtered tables)
# ---------------------------------------------------------------------------
def key_findings(h: pd.DataFrame, pairs: pd.DataFrame, route_name: dict[str, str], stop_name: dict[str, str],
                 zone_name: dict[str, str], day_type: str, total_passengers: float | None = None) -> list[dict[str, str]]:
    """Up to three findings: where it is crowded, where service is missing, who travels where."""
    out: list[dict[str, str]] = []

    crowded = Q.crowded_route_hours(h)
    if len(crowded):
        r = crowded.iloc[0]
        rname = _short(route_name.get(r["route_id"], r["route_id"]))
        where = stop_name.get(r["location_id"], "")
        if r["status"] == "crowded":
            txt = (f"{r['route_id']} {rname} ({r['direction']}) is the most crowded route-hour on a {day_type}: buses leaving around "
                   f"{fmt.hhmm(r['hour'])} carry up to {fmt.times(r['gap_index'])} their seats" + (f", fullest near {where}" if where else "") + ".")
        else:
            txt = (f"{r['route_id']} {rname} ({r['direction']}) runs at its seat capacity around {fmt.hhmm(r['hour'])} on a {day_type}; "
                   f"ticketed demand is capped at the seats, so unmet demand is not visible in tickets.")
        out.append({"title": "Where it is crowded", "text": txt, "source": "hourly_demand_supply (route_direction rows)"})
    else:
        out.append({"title": "Where it is crowded", "source": "hourly_demand_supply (route_direction rows)",
                    "text": f"No route-hour in the current filters exceeds the crowding threshold of {fmt.times(config.CROWDING_GAP_INDEX_THRESHOLD, 1)} seats."})

    unc = Q.uncovered_windows(h)
    if len(unc):
        r = unc.iloc[0]
        out.append({"title": "Where service is missing", "source": "hourly_demand_supply (corridor rows)",
                    "text": (f"On {r['corridor']} the state timetable has no seats between {fmt.hhmm(r['start_hour'])} and {fmt.hhmm(r['end_hour'])} "
                             f"while private operators run {r['private_departures']:.0f} departures; at an assumed "
                             f"{fmt.ratio_pct(config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION)} occupancy that is about {fmt.number(r['proxy_demand'])} "
                             f"passengers a day (an assumption-based proxy, not an observation).")})
    else:
        out.append({"title": "Where service is missing", "source": "hourly_demand_supply (corridor rows)",
                    "text": "No intercity corridor hour in the current filters has private service but no scheduled state seats."})

    if len(pairs):
        r = pairs.iloc[0]
        tot = total_passengers if total_passengers else pairs["passengers_per_day"].sum()
        o, d = zone_name.get(r["origin_zone_id"], r["origin_zone_id"]), zone_name.get(r["dest_zone_id"], r["dest_zone_id"])
        out.append({"title": "Who travels where", "source": "od_flows",
                    "text": (f"{o} to {d} is the busiest zone pair: about {fmt.number(r['passengers_per_day'])} passengers per average {day_type} "
                             f"in the selected hours, {fmt.pct(r['passengers_per_day'] / tot * 100, 0) if tot else fmt.NA} of all passengers boarding in the selected scope.")})
    else:
        out.append({"title": "Who travels where", "source": "od_flows", "text": "No passenger flows match the current filters."})
    return out


# ---------------------------------------------------------------------------
# Recommendation cards
# ---------------------------------------------------------------------------
def impact_summary(rec: pd.Series) -> str:
    """One sentence on the expected impact from ``expected_impact_json`` (illustrative; never profit)."""
    try:
        e = json.loads(rec["expected_impact_json"])
    except (TypeError, ValueError):
        return "Expected impact not available."
    if rec["category"] == "protect_minimum_service":
        c = e.get("contribution_per_day_inr")
        return (f"Service retained. The cost of protection is a contribution of {fmt.inr(c)} per day (revenue minus operating cost); "
                f"this is a social-service trade-off, not a commercial test.")
    add = e.get("additional_departures")
    lf = e.get("projected_load_factor_after")
    c = e.get("incremental_contribution_inr")
    parts = []
    if add is not None:
        parts.append(f"{add} additional departure{'s' if add != 1 else ''}")
    if lf is not None:
        parts.append(f"load factor about {fmt.ratio_pct(lf)} after")
    if c is not None:
        parts.append(f"incremental contribution about {fmt.inr(c)} per day (illustrative, not profit)")
    else:
        parts.append("revenue not estimated because demand above the seat cap is never ticketed")
    cost = e.get("incremental_operating_cost_inr")
    if cost is not None:
        parts.append(f"extra operating cost about {fmt.inr(cost)} per day")
    return "; ".join(parts).capitalize() + "."


def capture_sensitivity_lines(rec: pd.Series) -> list[str]:
    """Capture-share sensitivity (REC-001 style) as readable lines; empty if the recommendation has none."""
    try:
        e = json.loads(rec["expected_impact_json"])
    except (TypeError, ValueError):
        return []
    lines = []
    for s in e.get("capture_share_sensitivity", []) or []:
        lines.append(f"If the state captures {fmt.ratio_pct(s.get('capture_share'))} of the private-market demand: "
                     f"{s.get('additional_departures')} departure(s), load factor {fmt.ratio_pct(s.get('projected_load_factor_after'))}, "
                     f"contribution {fmt.inr(s.get('incremental_contribution_inr'))} per day.")
    return lines


def describe_value(key: str, v: Any) -> str | None:
    """Readable 'label: value' text for an evidence/assumption item (None for nested structures that are not summarised)."""
    label = key.replace("_", " ")
    ratio_key = "share" in key or "occupancy" in key or key == "target_load_factor"

    def one(x: Any) -> str:
        if isinstance(x, bool):
            return "yes" if x else "no"
        if isinstance(x, (int, float)):
            if key.endswith("_inr"):
                return fmt.inr(x, 0 if abs(x) >= 100 else 2)
            if ratio_key and 0 <= x <= 1.5:
                return fmt.ratio_pct(x)
            return fmt.number(x, 0 if float(x).is_integer() else 2)
        return str(x)

    if isinstance(v, dict):
        if any(isinstance(x, (dict, list)) for x in v.values()):
            return None
        return f"{label}: " + "; ".join(f"{str(k).replace('_', ' ')} {one(x)}" for k, x in v.items())
    if isinstance(v, list):
        if any(isinstance(x, (dict, list)) for x in v):
            return None
        return f"{label}: " + ", ".join(one(x) for x in v)
    return f"{label}: {one(v)}"


def json_list(cell: Any) -> list[str]:
    try:
        v = json.loads(cell)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def json_dict(cell: Any) -> dict:
    try:
        v = json.loads(cell)
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


# ---------------------------------------------------------------------------
# 'What this means' boxes
# ---------------------------------------------------------------------------
def overview_meaning(kpis: dict, findings: list[dict], n_recs: int, scope: str) -> str:
    return (f"In the selected scope ({scope}) the simulated network carries about {fmt.number(kpis['avg_boardings_per_day'])} boardings a day "
            f"at a {fmt.pct(kpis['load_factor_pct'])} load factor, and its ticket revenue does not cover operating cost "
            f"(contribution {fmt.inr(kpis['contribution_per_day_inr'])} per day; contribution is not profit). "
            f"The pressure is concentrated in a few hours and routes rather than spread evenly: {n_recs} recommended action(s) target them, "
            f"each with its evidence and assumptions below. All values are simulated and illustrative.")


def demand_meaning(peak_hour: int | None, peak_pax: float, share_peak: float, intent: dict, top_reason: str | None, top_condition: str | None) -> str:
    a = (f"Boardings peak at {fmt.hhmm(peak_hour)} with about {fmt.number(peak_pax)} passengers per average day, "
         f"{fmt.pct(share_peak, 0)} of the day's boardings in the selected hours." if peak_hour is not None else
         "No boardings match the current filters.")
    b = ""
    if intent.get("n_private"):
        b = (f" Among the {intent['n_private']} private-vehicle users in the synthetic survey, {fmt.pct(intent['share_pct'], 0)} state they would switch"
             + (f"; the most common reason for using a private vehicle is \"{top_reason.lower()}\"" if top_reason else "")
             + (f" and the most common switch condition is \"{top_condition.lower()}\"" if top_condition else "") + ".")
    return a + b + " Survey results are descriptive shares of simulated responses, not a forecast."


def route_meaning(p: dict, rank: int | None, n_in_type: int, route_type: str, total_score: float | None) -> str:
    r = (f"{p['route_id']} ranks {rank} of {n_in_type} {route_type} routes on the potential score ({fmt.number(total_score, 1)} of 100). "
         if rank is not None and total_score is not None else "")
    load = (f"It runs at a {fmt.pct(p['load_factor_pct'])} load factor with {fmt.pct(p['reliability_pct'])} of departures on time, "
            f"earning {fmt.inr(p['revenue_per_passenger_inr'], 1)} per passenger and {fmt.inr(p['epkm_inr'], 1)} per vehicle-km; "
            f"its contribution is {fmt.inr(p['contribution_per_day_inr'])} per day (not profit). ")
    prot = ("It is a protected minimum-service route: a low commercial score is never a reason to withdraw it. "
            if p.get("minimum_service") else "")
    return r + load + prot + "Values are observed synthetic demand from simulated tickets."


def gaps_meaning(s: dict, day_type: str, top_window: pd.Series | None) -> str:
    a = (f"On a {day_type}, {s['crowded_route_hours']} route-hour(s) are crowded or at seat capacity"
         + (f" (highest {fmt.times(s['max_gap_index'])} seats)" if s["crowded_route_hours"] else "") + "; these are lower bounds because tickets cannot exceed capacity. ")
    if top_window is not None and len(top_window):
        b = (f"The largest uncovered window is {top_window['corridor']} {fmt.hhmm(top_window['start_hour'])}-{fmt.hhmm(top_window['end_hour'])}: "
             f"no scheduled state seats against about {fmt.number(top_window['proxy_demand'])} passengers a day of assumed private-market demand. ")
    else:
        b = "No corridor window without scheduled state seats and with private service appears in the current filters. "
    return a + b + "Hatched cells mean no service is scheduled, which is different from zero demand."


def flow_meaning(total: float, top: pd.Series | None, names: dict[str, str], peak_hour: int | None, intra_share: float, day_type: str) -> str:
    if top is None or not total:
        return "No passenger flows match the current filters."
    o, d = names.get(top["origin_zone_id"], top["origin_zone_id"]), names.get(top["dest_zone_id"], top["dest_zone_id"])
    return (f"On an average {day_type} in the selected hours about {fmt.number(total)} passengers board; the busiest pair is {o} to {d} "
            f"({fmt.number(top['passengers_per_day'])} a day). Boardings are highest at {fmt.hhmm(peak_hour)}, and {fmt.pct(intra_share, 0)} of passengers travel "
            f"within a single zone. Flows are derived from simulated tickets.")


def competition_meaning(corridor: str, day_type: str, gap_hours: list[int], private_dep_in_gap: float, fare_row: pd.Series | None,
                        res: dict | None) -> str:
    if gap_hours:
        wins = ", ".join(f"{fmt.hhmm(a)}-{fmt.hhmm(b)}" for a, b in fmt.contiguous_windows(gap_hours))
        a = (f"On {corridor} ({day_type}) private operators depart in {wins} when the state timetable has no departure "
             f"({private_dep_in_gap:.0f} private departures). ")
    else:
        a = f"On {corridor} ({day_type}) every hour with private departures also has a state departure. "
    b = ""
    if fare_row is not None and pd.notna(fare_row.get("fare_index")):
        b = (f"For {str(fare_row['bus_type']).replace('_', ' ')} the illustrative state fare is {fmt.ratio_pct(fare_row['fare_index'])} of the private base fare. ")
    c = ""
    if res is not None:
        c = (f"In the what-if, a fare of {fmt.inr(res['new_fare_inr'], 0)} ({res['fare_change_pct']:+.0f}%) changes daily ticket revenue by "
             f"{fmt.inr(res['revenue_change_inr'])} at an assumed elasticity of {res['elasticity']:.1f}; the elasticity is an assumption, not a fitted value. ")
    return a + b + c + "Competitor services and fares are synthetic."


def infra_meaning(s: dict) -> str:
    return (f"Across {s['n_assets']} assessed assets the average infrastructure score is {fmt.number(s['mean_asset_score'], 1)} of 5, and "
            f"{str(s['lowest_dimension']).replace('_', ' ')} is the weakest dimension ({fmt.number(s['lowest_dimension_score'], 1)}). "
            f"Digital maturity averages {fmt.number(s['mean_digital_maturity'], 1)} of 5 with {str(s['weakest_capability']).replace('_', ' ')} lowest "
            f"({fmt.number(s['weakest_capability_score'], 1)}). {s['n_below_threshold']} item(s) score below the illustrative attention threshold. "
            f"These are synthetic assessments, not field audits.")


def cctv_meaning(peak_loc: str | None, peak_hour: int | None, peak_val: float, detector_available: bool) -> str:
    a = (f"The synthetic footfall stream peaks at {peak_loc} around {fmt.hhmm(peak_hour)} with about {fmt.number(peak_val)} inbound persons per hour. "
         if peak_hour is not None else "No synthetic footfall rows match the current filters. ")
    b = ("The real-video detector is installed but has produced no output yet." if detector_available else
         "The real-video detector is unavailable in this environment, so no real counts are shown.")
    return a + "This profile is simulated, not detector output. " + b


def reports_meaning(n_tables: int, total_rows: int, scope: str) -> str:
    return (f"{n_tables} table(s) are ready for CSV download, filtered to the current scope ({scope}); {fmt.number(total_rows)} rows in total. "
            f"Each file starts with provenance lines (source, seed, generation time, filters and limitations), and the numbers equal "
            f"those shown on the dashboard pages for the same filters.")
