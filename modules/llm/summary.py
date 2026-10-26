"""Deterministic, compact data summary for "Ask the Data", and post-validation of answers against it.

The summary is the ONLY context the model receives. It is built from the processed tables (no timestamps, sorted keys, rounded
numbers) so identical data gives byte-identical JSON (stable cache keys, prompt caching). The model's answer is then checked:

* every cited table must be a table in the summary;
* every declared figure, and every number written in the answer text, must be found in the summary
  (within a small tolerance; a percentage may be written as 0-100 when the summary holds a 0-1 ratio);
* otherwise the answer is flagged unsupported and a warning lists what could not be verified.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

import config
from modules.analytics import queries as Q
from modules.competition import gap_score as CG
from modules.survey import summaries as SV
from modules.ui import filters as F

PRIVATE_NOTICE = f"{config.SIMULATION_BADGE_TEXT}: every figure below is synthetic; none is a real GSRTC measurement."


def _r(x: Any, nd: int = 1) -> Any:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, nd) if nd > 0 else int(round(v))


def _json(cell: Any) -> dict:
    try:
        v = json.loads(cell)
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def build_summary(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Compact summary keyed by processed table name. Tables that are missing are simply absent (and listed under ``missing``)."""
    s: dict[str, Any] = {"notice": PRIVATE_NOTICE, "scope": "network-wide, weekday for hourly tables, all 42 simulated days for route KPIs"}
    tabs: dict[str, Any] = {}
    rs = tables.get("route_summary")
    if rs is not None:
        kp = Q.scope_kpis(rs)
        tabs["route_summary"] = {
            "network_totals": {"routes": kp["n_routes"], "avg_boardings_per_day": _r(kp["avg_boardings_per_day"], 0),
                               "load_factor_pct": _r(kp["load_factor_pct"]), "on_time_pct": _r(kp["reliability_pct"]),
                               "contribution_per_day_inr": _r(kp["contribution_per_day_inr"], 0)},
            "routes": [{"route_id": r["route_id"], "name": r["name"], "type": r["route_type"], "corridor": r["corridor"],
                        "avg_boardings_per_day": _r(r["avg_boardings_per_day"], 0), "load_factor_pct": _r(r["load_factor_pct"]),
                        "on_time_pct": _r(r["reliability_pct"]), "peak_load_x_seats": _r(r["peak_load_factor_max"], 2),
                        "contribution_per_day_inr": _r(r["contribution_per_day_inr"], 0), "peak_hour_window": r["peak_hour_window"]}
                       for _, r in rs.sort_values("route_id").iterrows()],
        }
    sc = tables.get("route_scores")
    if sc is not None:
        top = sc.sort_values(["total_score", "route_id"], ascending=[False, True]).head(8)
        tabs["route_scores"] = {"note": "rule-based weighted score, weights demo-v1 (not an AI prediction)",
                                "top": [{"route_id": r["route_id"], "total_score": _r(r["total_score"]), "rank": _r(r["rank"], 0)} for _, r in top.iterrows()]}
    rec = tables.get("recommendations")
    if rec is not None:
        items = []
        for _, r in rec.sort_values("priority_rank").iterrows():
            e = _json(r["expected_impact_json"])
            items.append({"id": r["recommendation_id"], "priority": r["priority"], "title": r["title"], "route_id": r["route_id"],
                          "corridor": r["corridor"], "time_window": r["time_window"], "day_type": r["day_type"], "confidence": r["confidence_label"],
                          "additional_departures": e.get("additional_departures"), "projected_load_factor_after": _r(e.get("projected_load_factor_after"), 2),
                          "incremental_contribution_inr": _r(e.get("incremental_contribution_inr"), 0)})
        tabs["recommendations"] = {"items": items}
    h = tables.get("hourly_demand_supply")
    if h is not None and rs is not None:
        f = F.Filters()
        hw = F.filter_hourly(h, f, rs)
        crowded = Q.crowded_route_hours(hw).head(5)
        unc = Q.uncovered_windows(hw)
        tabs["hourly_demand_supply"] = {
            "day_type": f.day_type,
            "most_crowded_route_hours": [{"route_id": r["route_id"], "direction": r["direction"], "hour": f"{int(r['hour']):02d}:00",
                                          "demand_to_seats_x": _r(r["gap_index"], 2), "status": r["status"]} for _, r in crowded.iterrows()],
            "uncovered_windows": [{"corridor": r["corridor"], "window": f"{int(r['start_hour']):02d}:00-{int(r['end_hour']):02d}:00",
                                   "private_departures": _r(r["private_departures"], 0), "proxy_demand_per_day": _r(r["proxy_demand"], 0)} for _, r in unc.iterrows()],
        }
    comp = tables.get("competition_analysis")
    if comp is not None:
        top = CG.top_gap_slots(comp, None, config.PEAK_DAY_TYPE, top=5)
        fi = comp[comp["day_type"] == config.PEAK_DAY_TYPE].groupby("route_pair")["fare_index"].mean()
        tabs["competition_analysis"] = {
            "day_type": config.PEAK_DAY_TYPE,
            "top_gap_slots": [{"corridor": r["route_pair"], "hour": f"{int(r['hour']):02d}:00", "competitive_gap_score": _r(r["competitive_gap_score"]),
                               "state_departures": _r(r["state_departures"], 0), "private_departures": _r(r["private_departures"], 0)} for _, r in top.iterrows()],
            "mean_fare_index_by_corridor": {k: _r(v, 2) for k, v in fi.items() if pd.notna(v)},
            "fare_index_definition": "state fare / median private fare",
        }
    sv = tables.get("survey_responses")
    if sv is not None and len(sv):
        intent = SV.stated_switch_intent(sv)
        tabs["survey_responses"] = {
            "responses": int(len(sv)), "private_vehicle_users": intent["n_private"], "stated_switch_intent_pct": _r(intent["share_pct"]),
            "top_private_use_reasons_pct": {r["label"]: _r(r["share_pct"]) for _, r in SV.private_use_reasons(sv).head(5).iterrows()},
            "top_switch_conditions_pct": {r["label"]: _r(r["share_pct"]) for _, r in SV.switch_conditions(sv).head(5).iterrows()},
            "note": "descriptive shares of a synthetic, unweighted sample",
        }
    m = tables.get("ridership_model_metrics")
    if m is not None:
        t = m[(m["split"] == "test") & (m["group"] == "all") & (m["metric"].isin(["mae", "rmse", "mape_pct"]))]
        tabs["ridership_model_metrics"] = {
            "note": "synthetic demonstration metrics, test split, all routes",
            "models": {mod: {r["metric"]: _r(r["value"], 2) for _, r in g.iterrows()} for mod, g in t.groupby("model")}}
    sm = tables.get("survey_model_metrics")
    if sm is not None:
        tabs["survey_model_metrics"] = {"note": "illustrative model on a synthetic survey; held-out test",
                                        "metrics": {r["metric"]: {"model": _r(r["model"], 3), "baseline": _r(r["baseline"], 3)} for _, r in sm.iterrows()}}
    s["tables"] = tabs
    s["missing"] = sorted(n for n in ("route_summary", "route_scores", "recommendations", "hourly_demand_supply", "competition_analysis",
                                      "survey_responses", "ridership_model_metrics", "survey_model_metrics") if n not in tabs)
    return s


def summary_json(summary: dict[str, Any]) -> str:
    """Canonical text sent to the model (sorted keys, compact separators)."""
    return json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def summary_hash(summary: dict[str, Any]) -> str:
    return hashlib.sha256(summary_json(summary).encode("utf-8")).hexdigest()


def table_names(summary: dict[str, Any]) -> list[str]:
    return sorted(summary.get("tables", {}))


# ---------------------------------------------------------------------------------------------------------------- validation
_NUM = re.compile(r"(?<![A-Za-z0-9_.\-])-?\d[\d,]*(?:\.\d+)?")
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")


def _numbers(obj: Any, out: list[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if not (isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj))):
            out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)


def summary_numbers(summary: dict[str, Any]) -> list[float]:
    out: list[float] = []
    _numbers(summary.get("tables", {}), out)
    return out


def parse_number(text: Any) -> float | None:
    """First number in ``text`` (handles Indian grouping, a rupee sign, %, x, 'lakh'/'crore' are NOT expanded) or None."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    m = _NUM.search(str(text).replace("₹", " ").replace("−", "-"))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def number_supported(v: float, nums: list[float]) -> bool:
    """True if ``v`` matches a summary number within rounding tolerance (0.6% or 0.005), also as v/100 or v*100 (ratio vs percentage)."""
    for n in nums:
        tol = max(0.0051, abs(n) * 0.006)
        if any(abs(c - n) <= tol for c in (v, v / 100.0, v * 100.0)):
            return True
    return False


def text_numbers(text: str) -> list[float]:
    """Numbers written in free text, excluding clock times (checked separately as strings)."""
    t = _TIME.sub(" ", text)
    out = []
    for m in _NUM.finditer(t):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


@dataclass
class Validation:
    supported: bool
    cited_tables: list[str]
    figures: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def validate_answer(payload: dict[str, Any], summary: dict[str, Any]) -> Validation:
    """Check a parsed model payload (``answer``, ``supported``, ``cited_tables``, ``figures_used``) against the summary."""
    names = set(table_names(summary))
    blob = summary_json(summary).lower()
    nums = summary_numbers(summary)
    warnings: list[str] = []
    cited = [str(t) for t in payload.get("cited_tables") or []]
    bad_tables = [t for t in cited if t not in names]
    if bad_tables:
        warnings.append("Cited table(s) not in the data summary: " + ", ".join(bad_tables) + ".")
    figures: list[dict[str, Any]] = []
    for fg in payload.get("figures_used") or []:
        value = str(fg.get("value", ""))
        table = str(fg.get("table", ""))
        ok = table in names
        v = parse_number(value)
        if value.strip() and value.strip().lower() in blob:
            pass  # exact text present in the summary (route id, time window, label, number written as stored)
        elif v is None or _TIME.search(value):
            ok = False  # non-numeric text (or a time/window) that is not in the summary
        else:
            ok = ok and number_supported(v, nums)
        figures.append({"label": str(fg.get("label", "")), "value": value, "table": table, "verified": bool(ok)})
        if not ok:
            warnings.append(f"Figure not verified against the summary: {fg.get('label', '')} = {value} ({table or 'no table'}).")
    for t in _TIME.findall(str(payload.get("answer", ""))):
        if t not in blob and f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}" not in blob:
            warnings.append(f"Time {t} in the answer does not appear in the summary.")
    for v in text_numbers(str(payload.get("answer", ""))):
        if not number_supported(v, nums):
            warnings.append(f"Number {v:g} in the answer text was not found in the summary.")
    # dedupe, keep order
    warnings = list(dict.fromkeys(warnings))
    supported = bool(payload.get("supported", False)) and not warnings and bool(cited)
    return Validation(supported, [t for t in cited if t in names], figures, warnings)
