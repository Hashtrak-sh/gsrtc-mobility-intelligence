"""Deterministic theme tagging and theme aggregation for reviews and survey open text (no LLM, no randomness).

Two ways to obtain review themes, always labelled on the dashboard:

* ``generator_tags`` - the ``reviews.themes`` column, tagged when the synthetic review was generated (the review text is
  assembled from one template sentence per tagged theme, so these tags are the generator's ground truth).
* ``keyword_tagger`` - :func:`tag_review_text`, a transparent keyword/regex tagger that re-derives the same themes from
  ``reviews.text`` only. :func:`agreement_report` states how closely it reproduces the generator tags; because the texts
  are templates, high agreement says the tagger works on this vocabulary, NOT that it would generalise to real reviews.

Survey open text: :func:`tag_open_text` extracts the stated reason and switch condition from ``survey_responses.open_text``;
:func:`open_text_agreement` compares them with the structured ``reasons`` / ``switch_conditions`` fields.

Theme set and polarity values follow docs/DATA_SCHEMA.md (``reviews.themes``). LLM theme analysis is a later milestone.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

import pandas as pd

from modules.data_gen import constants as C

THEMES: tuple[str, ...] = tuple(C.REVIEW_THEMES)
THEME_LABELS = {"punctuality": "Punctuality", "cleanliness": "Cleanliness", "comfort_ac": "Comfort and AC",
                "staff_behaviour": "Staff behaviour", "booking_ease": "Booking ease", "safety": "Safety", "value": "Value for money"}
METHOD_GENERATOR = "generator_tags"
METHOD_KEYWORD = "keyword_tagger"
METHOD_LABELS = {METHOD_GENERATOR: "Tagged when the synthetic reviews were generated",
                 METHOD_KEYWORD: "Deterministic keyword tagger applied to the review text"}
TAGGER_VERSION = "keyword-v1"

_THEME_PATTERNS: dict[str, re.Pattern[str]] = {k: re.compile(v, re.I) for k, v in {
    "punctuality": r"\b(late(?!-)|on time|punctual\w*|timings?|scheduled time|as scheduled|waited|waiting|wait)\b",
    "cleanliness": r"\b(clean|dirty|well kept|tidy)\b",
    "comfort_ac": r"\b(ac|air[- ]condition\w*|comfortable|uncomfortable|cool|hot)\b",
    "staff_behaviour": r"\b(conductor|driver|staff|courteous|polite\w*|rude)\b",
    "booking_ease": r"\b(book\w*|app|queue|counter|confirmation)\b",
    "safety": r"\b(safe|safely|unsafe|rash|careful|secure)\b",
    "value": r"\b(fare|price|value|expensive|cheap\w*|reasonable)\b",
}.items()}
_NEG = re.compile(r"\b(not|poor|dirty|rude|unhelpful|difficult|failed|rash|long|too high|high|expensive|uncomfortable|hot|"
                  r"late(?!-)|waited|queue|unsafe)\b", re.I)
_POS = re.compile(r"\b(on time|punctual\w*|clean|well kept|comfortable|cool|polite\w*|helpful|courteous|quick|easy|safe|"
                  r"secure|careful|good|reasonable|as scheduled|no waiting)\b", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def parse_themes(cell: Any) -> list[dict[str, str]]:
    """Parse a ``reviews.themes`` JSON cell into ``[{"theme", "polarity"}]``; invalid/missing -> []."""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    try:
        v = json.loads(cell) if isinstance(cell, str) else list(cell)
    except (TypeError, ValueError):
        return []
    out = []
    for d in v if isinstance(v, list) else []:
        if isinstance(d, dict) and d.get("theme") in THEMES and d.get("polarity") in ("positive", "negative"):
            out.append({"theme": d["theme"], "polarity": d["polarity"]})
    return out


def tag_review_text(text: Any) -> list[dict[str, str]]:
    """Deterministic tagger: split into sentences; a sentence mentions every theme whose keywords it contains and carries
    one polarity (negative cue wins; otherwise positive cue; otherwise the mention is dropped as unscored)."""
    if not isinstance(text, str) or not text.strip():
        return []
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for sent in _SENT_SPLIT.split(text.strip()):
        themes = [t for t in THEMES if _THEME_PATTERNS[t].search(sent)]
        if not themes:
            continue
        pol = "negative" if _NEG.search(sent) else ("positive" if _POS.search(sent) else None)
        if pol is None:
            continue
        for t in themes:
            if (t, pol) not in seen:
                seen.add((t, pol))
                out.append({"theme": t, "polarity": pol})
    return out


def keyword_tags(reviews: pd.DataFrame) -> pd.Series:
    """Series (aligned with ``reviews``) of keyword-tagger tag lists."""
    return reviews["text"].map(tag_review_text)


def generator_tags(reviews: pd.DataFrame) -> pd.Series:
    return reviews["themes"].map(parse_themes)


def tags_for(reviews: pd.DataFrame, method: str) -> pd.Series:
    if method == METHOD_GENERATOR:
        return generator_tags(reviews)
    if method == METHOD_KEYWORD:
        return keyword_tags(reviews)
    raise ValueError(f"Unknown theme method {method!r}")


# --------------------------------------------------------------------------------------------- aggregation
def theme_counts(reviews: pd.DataFrame, method: str = METHOD_GENERATOR) -> pd.DataFrame:
    """One row per (operator_type, theme): reviews of the operator type, positive/negative mentions and shares.

    ``negative_share`` = negative mentions / all reviews of that operator type (so it is comparable between operator types
    with different review counts); ``negative_of_mentions`` = negative / (positive + negative mentions). A review is counted
    once per (theme, polarity). Operator types without reviews yield no rows.
    """
    cols = ["operator_type", "theme", "n_reviews", "positive", "negative", "mentions", "negative_share", "positive_share",
            "negative_of_mentions"]
    if reviews.empty:
        return pd.DataFrame(columns=cols)
    tags = tags_for(reviews, method)
    rows = []
    for op, idx in reviews.groupby("operator_type").groups.items():
        n = len(idx)
        pos = {t: 0 for t in THEMES}
        neg = {t: 0 for t in THEMES}
        for lst in tags.loc[idx]:
            for pol, tt in {(d["polarity"], d["theme"]) for d in lst}:
                (pos if pol == "positive" else neg)[tt] += 1
        for t in THEMES:
            m = pos[t] + neg[t]
            rows.append({"operator_type": op, "theme": t, "n_reviews": n, "positive": pos[t], "negative": neg[t], "mentions": m,
                         "negative_share": neg[t] / n, "positive_share": pos[t] / n,
                         "negative_of_mentions": neg[t] / m if m else float("nan")})
    return pd.DataFrame(rows, columns=cols)


def theme_comparison(reviews: pd.DataFrame, method: str = METHOD_GENERATOR, route_pair: str | None = None) -> pd.DataFrame:
    """Wide state-vs-private table per theme (negative-mention share per review); optionally for one corridor.

    Columns: theme, label, state_negative_share, private_negative_share, deficit (state - private; positive = state is
    more often negative), state_n_reviews, private_n_reviews. Missing operator type -> NaN (not 0).
    """
    r = reviews if route_pair is None else reviews[reviews["route_pair"] == route_pair]
    c = theme_counts(r, method)
    out = pd.DataFrame({"theme": list(THEMES)})
    out["label"] = out["theme"].map(THEME_LABELS)
    for op in ("state", "private"):
        s = c[c["operator_type"] == op].set_index("theme")
        out[f"{op}_negative_share"] = out["theme"].map(s["negative_share"]) if len(s) else float("nan")
        out[f"{op}_negative"] = out["theme"].map(s["negative"]) if len(s) else float("nan")
        out[f"{op}_n_reviews"] = int(s["n_reviews"].iloc[0]) if len(s) else 0
    out["deficit"] = out["state_negative_share"] - out["private_negative_share"]
    return out


def review_theme_summary(reviews: pd.DataFrame, route_pair: str, method: str = METHOD_GENERATOR) -> dict[str, Any]:
    """JSON-ready per-operator theme counts and polarity for one corridor (``competition_analysis.review_theme_summary``)."""
    c = theme_counts(reviews[reviews["route_pair"] == route_pair], method)
    out: dict[str, Any] = {"method": method, "route_pair": route_pair}
    for op in ("state", "private"):
        s = c[c["operator_type"] == op]
        out[op] = {"n_reviews": int(s["n_reviews"].iloc[0]) if len(s) else 0,
                   "themes": {r.theme: {"positive": int(r.positive), "negative": int(r.negative)} for r in s.itertuples()}}
    return out


def review_theme_deficit(reviews: pd.DataFrame, route_pair: str, method: str = METHOD_GENERATOR,
                         min_reviews: int = 1) -> float:
    """Mean over themes of ``max(0, state_negative_share - private_negative_share)`` on a corridor; NaN when either operator
    type has fewer than ``min_reviews`` reviews there (missing, never zero)."""
    t = theme_comparison(reviews, method, route_pair)
    if t["state_n_reviews"].iloc[0] < min_reviews or t["private_n_reviews"].iloc[0] < min_reviews:
        return float("nan")
    return float(t["deficit"].clip(lower=0).mean())


# --------------------------------------------------------------------------------------------- agreement
def agreement_report(reviews: pd.DataFrame) -> dict[str, Any]:
    """Agreement between the keyword tagger and the generator tags (theme mention and polarity)."""
    if reviews.empty:
        return {"n_reviews": 0, "exact_match_share": float("nan"), "polarity_accuracy": float("nan"), "per_theme": []}
    gen = generator_tags(reviews)
    kw = keyword_tags(reviews)
    exact = 0
    pol_ok = pol_n = 0
    per = {t: {"tp": 0, "fp": 0, "fn": 0} for t in THEMES}
    for g, k in zip(gen, kw):
        gs, ks = {(d["theme"], d["polarity"]) for d in g}, {(d["theme"], d["polarity"]) for d in k}
        exact += gs == ks
        gt, kt = {d["theme"]: d["polarity"] for d in g}, {d["theme"]: d["polarity"] for d in k}
        for t in THEMES:
            if t in gt and t in kt:
                per[t]["tp"] += 1
                pol_n += 1
                pol_ok += gt[t] == kt[t]
            elif t in kt:
                per[t]["fp"] += 1
            elif t in gt:
                per[t]["fn"] += 1
    rows = []
    for t, d in per.items():
        p = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else float("nan")
        r = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else float("nan")
        f1 = 2 * p * r / (p + r) if p == p and r == r and p + r > 0 else float("nan")
        rows.append({"theme": t, "precision": p, "recall": r, "f1": f1, **d})
    tp, fp, fn = (sum(d[k] for d in per.values()) for k in ("tp", "fp", "fn"))
    return {"n_reviews": int(len(reviews)), "tagger_version": TAGGER_VERSION,
            "exact_match_share": exact / len(reviews),
            "theme_precision": tp / (tp + fp) if tp + fp else float("nan"),
            "theme_recall": tp / (tp + fn) if tp + fn else float("nan"),
            "polarity_accuracy": pol_ok / pol_n if pol_n else float("nan"), "per_theme": rows}


# --------------------------------------------------------------------------------------------- survey open text
_REASON_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((k, re.compile(v, re.I)) for k, v in (
    ("no_ac_on_bus", r"air condition|no ac\b"),
    ("bus_unreliable", r"\blate\b|predict|not dependable"),
    ("low_bus_frequency", r"infrequent|wait too long"),
    ("crowding", r"overcrowded|no space"),
    ("no_direct_route", r"no direct bus|change buses"),
    ("carries_goods_or_family", r"luggage|goods|family"),
    ("door_to_door", r"doorstep|no walk"),
    ("flexibility", r"leave whenever|flexibility"),
    ("comfort", r"more comfortable|seat and privacy"),
    ("safety", r"safer|unsafe"),
))
_COND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((k, re.compile(v, re.I)) for k, v in (
    ("real_time_info", r"\blive\b|tracking"),
    ("ac_comfort", r"\bac\b|air condition"),
    ("frequency", r"more often|every \d+"),
    ("reliability", r"on time|dependable"),
    ("lower_fare", r"fare was lower|cheaper"),
    ("cleanliness", r"clean"),
    ("parking_cost_or_hassle", r"parking"),
    ("direct_route", r"direct route|change buses"),
    ("safety", r"\bsafe\b|well lit"),
))
_COND_CUE = re.compile(r"would consider the bus if", re.I)


def tag_open_text(text: Any) -> dict[str, list[str]]:
    """``{"reasons": [...], "switch_conditions": [...]}`` found in one open-text answer (the stated reason is the clause after
    "because"; the stated condition is the clause after "would consider the bus if"). Unmatched -> empty lists."""
    out: dict[str, list[str]] = {"reasons": [], "switch_conditions": []}
    if not isinstance(text, str):
        return out
    cue = _COND_CUE.search(text)
    head, tail = (text[:cue.start()], text[cue.end():]) if cue else (text, "")
    if "because" in head:
        clause = head.split("because", 1)[1]
        out["reasons"] = [k for k, p in _REASON_PATTERNS if p.search(clause)][:1]
    out["switch_conditions"] = [k for k, p in _COND_PATTERNS if p.search(tail)][:1]
    return out


def _json_list(cell: Any) -> list[str]:
    try:
        v = json.loads(cell) if isinstance(cell, str) else list(cell)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def open_text_agreement(survey: pd.DataFrame) -> dict[str, Any]:
    """Agreement of :func:`tag_open_text` with the structured survey fields.

    * ``condition_precision`` - tagged switch condition is among the respondent's recorded ``switch_conditions``.
    * ``condition_first_match`` - tagged condition equals the first recorded condition (the one the template sentence states).
    * ``no_condition_agreement`` - "not likely to switch" texts coincide with an empty recorded condition list.
    * ``reason_precision`` - for texts that state a reason, the tagged reason is in the recorded ``reasons``.
    """
    cond_hit = cond_first = cond_n = 0
    none_ok = none_n = 0
    reason_hit = reason_n = 0
    for text, conds, reasons in zip(survey["open_text"], survey["switch_conditions"], survey["reasons"]):
        tg, rc, rr = tag_open_text(text), _json_list(conds), _json_list(reasons)
        if tg["switch_conditions"]:
            cond_n += 1
            cond_hit += tg["switch_conditions"][0] in rc
            cond_first += bool(rc) and tg["switch_conditions"][0] == rc[0]
        if isinstance(text, str) and "not likely to switch" in text:
            none_n += 1
            none_ok += not rc
        if tg["reasons"]:
            reason_n += 1
            reason_hit += tg["reasons"][0] in rr
    nan = float("nan")
    return {"n_responses": int(len(survey)), "n_condition_texts": cond_n, "n_reason_texts": reason_n,
            "condition_precision": cond_hit / cond_n if cond_n else nan,
            "condition_first_match": cond_first / cond_n if cond_n else nan,
            "no_condition_agreement": none_ok / none_n if none_n else nan,
            "reason_precision": reason_hit / reason_n if reason_n else nan}


def iter_theme_labels(codes: Iterable[str]) -> list[str]:
    return [THEME_LABELS.get(c, c) for c in codes]
