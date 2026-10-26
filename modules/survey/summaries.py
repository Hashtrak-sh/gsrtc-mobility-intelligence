"""Descriptive survey summaries (counts and shares only; no model).

Input: the synthetic ``survey_responses`` table. List columns (``reasons``, ``switch_conditions``) are JSON strings.
"Private mode" = ``car`` or ``two_wheeler`` (the respondents for whom ``switch_intent`` is defined). All results are
descriptive shares of the synthetic sample and say nothing about the real GSRTC catchment.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

PRIVATE_MODES: tuple[str, ...] = ("car", "two_wheeler")

LABELS = {
    "two_wheeler": "Two-wheeler", "car": "Car", "bus": "Bus", "rail": "Rail", "shared_taxi": "Shared taxi", "other": "Other",
    "work": "Work", "education": "Education", "shopping": "Shopping", "health": "Health", "leisure": "Leisure",
    "ac_comfort": "Air-conditioned, comfortable bus", "frequency": "More frequent service", "reliability": "Reliable timings",
    "lower_fare": "Lower fare", "real_time_info": "Real-time information", "safety": "Safety",
    "no_ac_on_bus": "No AC on bus", "low_bus_frequency": "Low bus frequency", "door_to_door": "Door-to-door travel",
    "carries_goods_or_family": "Carries goods or family", "no_direct_route": "No direct route",
}


def label(code: str) -> str:
    return LABELS.get(code, str(code).replace("_", " ").capitalize())


def _parse(cell: Any) -> list[str]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    try:
        v = json.loads(cell) if isinstance(cell, str) else list(cell)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def private_mode_users(s: pd.DataFrame) -> pd.DataFrame:
    return s[s["current_mode"].isin(PRIVATE_MODES)]


def share_table(values: pd.Series, order: list[str] | None = None) -> pd.DataFrame:
    """Count and share (%) per category, descending (or in ``order``); NaN categories are excluded and not counted."""
    v = values.dropna()
    vc = v.value_counts()
    if order is not None:
        vc = vc.reindex(order, fill_value=0)
    out = vc.rename_axis("category").reset_index(name="responses")
    out["share_pct"] = out["responses"] / len(v) * 100 if len(v) else float("nan")
    out["label"] = out["category"].map(label)
    return out


def mode_summary(s: pd.DataFrame) -> pd.DataFrame:
    return share_table(s["current_mode"])


def purpose_summary(s: pd.DataFrame) -> pd.DataFrame:
    return share_table(s["trip_purpose"])


def multi_select_summary(s: pd.DataFrame, column: str) -> pd.DataFrame:
    """Share of respondents in ``s`` that selected each item of a JSON-list column (items are not mutually exclusive)."""
    n = len(s)
    counts: dict[str, int] = {}
    for cell in s[column]:
        for item in set(_parse(cell)):
            counts[item] = counts.get(item, 0) + 1
    out = pd.DataFrame({"category": list(counts), "responses": list(counts.values())})
    if out.empty:
        return pd.DataFrame(columns=["category", "responses", "share_pct", "label"])
    out["share_pct"] = out["responses"] / n * 100
    out["label"] = out["category"].map(label)
    return out.sort_values(["responses", "category"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def private_use_reasons(s: pd.DataFrame) -> pd.DataFrame:
    """Reasons given by private-mode users (share of private-mode respondents naming each reason)."""
    return multi_select_summary(private_mode_users(s), "reasons")


def switch_conditions(s: pd.DataFrame) -> pd.DataFrame:
    """Conditions that might make private-mode users switch (share of private-mode respondents naming each)."""
    return multi_select_summary(private_mode_users(s), "switch_conditions")


def stated_switch_intent(s: pd.DataFrame) -> dict[str, Any]:
    """Descriptive share of private-mode respondents whose recorded ``switch_intent`` is 1 (None if no private users)."""
    p = private_mode_users(s).dropna(subset=["switch_intent"])
    if p.empty:
        return {"n_private": 0, "share_pct": float("nan")}
    return {"n_private": int(len(p)), "share_pct": float(p["switch_intent"].mean() * 100)}


def intent_by_purpose(s: pd.DataFrame) -> pd.DataFrame:
    p = private_mode_users(s).dropna(subset=["switch_intent"])
    g = p.groupby("trip_purpose")["switch_intent"].agg(["mean", "count"]).reset_index()
    g["share_pct"] = g["mean"] * 100
    g["label"] = g["trip_purpose"].map(label)
    return g.rename(columns={"count": "respondents"}).sort_values("share_pct", ascending=False, kind="mergesort").reset_index(drop=True)


def survey_meta(s: pd.DataFrame) -> dict[str, Any]:
    ts = pd.to_datetime(s["timestamp"], errors="coerce") if len(s) else pd.Series(dtype="datetime64[ns]")
    sources = sorted(s["source_type"].dropna().unique().tolist()) if len(s) else []
    return {"n": int(len(s)), "n_private": int(len(private_mode_users(s))),
            "first": None if ts.empty or ts.isna().all() else ts.min().date().isoformat(),
            "last": None if ts.empty or ts.isna().all() else ts.max().date().isoformat(), "source_types": sources}


# ---------------------------------------------------------------------------------------------- M5 cross-tabs
INCOME_ORDER: tuple[str, ...] = ("low", "lower_middle", "middle", "upper_middle", "high")
LABELS.update({"low": "Low income", "lower_middle": "Lower-middle income", "middle": "Middle income", "upper_middle": "Upper-middle income",
               "high": "High income", "income_band": "Income band", "current_mode": "Current mode", "trip_purpose": "Trip purpose"})
GROUP_COLUMNS = {"current_mode": "Current mode", "trip_purpose": "Trip purpose", "income_band": "Income band"}


def _group_order(s: pd.DataFrame, group_col: str) -> list[str]:
    present = [g for g in s[group_col].dropna().unique()]
    if group_col == "income_band":
        return [g for g in INCOME_ORDER if g in present]
    return sorted(present, key=lambda g: (-int((s[group_col] == g).sum()), g))


def group_sizes(s: pd.DataFrame, group_col: str) -> dict[str, int]:
    """Respondents per group value (NaN group values excluded)."""
    return {g: int((s[group_col] == g).sum()) for g in _group_order(s, group_col)}


def mode_by_purpose(s: pd.DataFrame) -> pd.DataFrame:
    """Trip purpose (rows) by current mode (columns): % of each mode's respondents. Columns are in descending group size."""
    modes = _group_order(s, "current_mode")
    out = {}
    for m in modes:
        g = s[s["current_mode"] == m]["trip_purpose"].dropna()
        out[f"{label(m)} (n={len(g)})"] = g.value_counts(normalize=True).mul(100) if len(g) else pd.Series(dtype=float)
    wide = pd.DataFrame(out).reindex([p for p in sorted(s["trip_purpose"].dropna().unique())]).fillna(0.0)
    wide.index = [label(p) for p in wide.index]
    return wide


def multi_select_by_group(s: pd.DataFrame, column: str, group_col: str, *, private_only: bool = True, top: int = 8,
                          min_group_n: int = 10) -> pd.DataFrame:
    """Share (%) of each group's respondents naming each item of a JSON-list column (``reasons`` / ``switch_conditions``).

    Rows = the ``top`` items overall (by number of mentions), columns = group values with at least ``min_group_n``
    respondents (smaller groups are dropped, not shown with unstable percentages). ``private_only`` limits to car and
    two-wheeler users, the group the questions are about.
    """
    base = private_mode_users(s) if private_only else s
    overall = multi_select_summary(base, column)
    if overall.empty:
        return pd.DataFrame()
    items = list(overall["category"].head(top))
    cols = {}
    for g in _group_order(base, group_col):
        sub = base[base[group_col] == g]
        if len(sub) < min_group_n:
            continue
        shares = multi_select_summary(sub, column).set_index("category")["share_pct"]
        cols[label(g)] = shares.reindex(items).fillna(0.0)
    wide = pd.DataFrame(cols, index=items)
    wide.index = [label(i) for i in items]
    return wide
