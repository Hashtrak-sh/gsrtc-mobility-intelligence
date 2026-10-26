"""Deterministic, rule-based lookups used when no LLM is configured.

These are NOT an LLM and are always labelled so (:data:`LABEL`). Each template is a fixed pandas lookup over a processed table;
a question that does not match a template gets an explicit "unsupported" answer, never a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

import config
from modules.survey import summaries as SV
from modules.ui import fmt
from modules.ui import narrative as N

LABEL = "Rule-based answer, not an LLM"
UNSUPPORTED_TEXT = ("This question is not one of the supported rule-based lookups, and no LLM is configured, so it cannot be answered. "
                    "Pick one of the example questions, or configure an LLM key to ask free-form questions.")


@dataclass
class RuleAnswer:
    question: str
    answer: str
    supported: bool
    cited_tables: list[str] = field(default_factory=list)
    template: str | None = None
    label: str = LABEL


def _short(name: str) -> str:
    return N._short(str(name))


def _highest_load(t: dict[str, pd.DataFrame]) -> tuple[str, list[str]]:
    rs = t["route_summary"].sort_values(["load_factor_pct", "route_id"], ascending=[False, True])
    r = rs.iloc[0]
    return (f"{r['route_id']} ({_short(r['name'])}) has the highest load factor, {fmt.pct(r['load_factor_pct'])} over all 42 simulated days "
            f"(passenger-km / seat-km)."), ["route_summary"]


def _most_boardings(t: dict[str, pd.DataFrame]) -> tuple[str, list[str]]:
    rs = t["route_summary"].sort_values(["avg_boardings_per_day", "route_id"], ascending=[False, True])
    r = rs.iloc[0]
    return (f"{r['route_id']} ({_short(r['name'])}) carries the most passengers: about {fmt.number(r['avg_boardings_per_day'])} boardings per average day."), ["route_summary"]


def _top_recommendation(t: dict[str, pd.DataFrame]) -> tuple[str, list[str]]:
    r = t["recommendations"].sort_values("priority_rank").iloc[0]
    return (f"{r['recommendation_id']} ({r['priority']} priority): {r['title']}. {N.impact_summary(r)} Confidence: {r['confidence_label']}."), ["recommendations"]


def _evening_somnath(t: dict[str, pd.DataFrame]) -> tuple[str, list[str]]:
    rec = t["recommendations"]
    hit = rec[(rec["corridor"] == config.PRIMARY_CORRIDOR) & (rec["category"] == "add_service_corridor_slot")]
    hit = hit[hit["time_window"].str[:2].astype(int) >= 17] if len(hit) else hit
    if hit.empty:
        return "No evening recommendation exists for the Rajkot-Somnath corridor in the recommendations table.", ["recommendations"]
    r = hit.sort_values("priority_rank").iloc[0]
    return f"{r['recommendation_id']} ({r['priority']} priority): {r['title']}. {N.impact_summary(r)} Confidence: {r['confidence_label']}.", ["recommendations"]


def _top_condition(t: dict[str, pd.DataFrame]) -> tuple[str, list[str]]:
    r = SV.switch_conditions(t["survey_responses"]).iloc[0]
    return (f"The most common condition for switching to the bus is '{r['label']}', named by {fmt.pct(r['share_pct'], 0)} of private-vehicle users "
            f"(synthetic, unweighted sample)."), ["survey_responses"]


def _top_gap_slot(t: dict[str, pd.DataFrame]) -> tuple[str, list[str]]:
    c = t["competition_analysis"]
    c = c[c["day_type"] == config.PEAK_DAY_TYPE].sort_values(["competitive_gap_score", "route_pair", "hour"], ascending=[False, True, True])
    r = c.iloc[0]
    return (f"The highest competitive gap score on a {config.PEAK_DAY_TYPE} is {r['competitive_gap_score']:.1f} on {r['route_pair']} at {fmt.hhmm(r['hour'])} "
            f"({fmt.number(r['state_departures'])} state vs {fmt.number(r['private_departures'])} private departures)."), ["competition_analysis"]


@dataclass(frozen=True)
class Template:
    key: str
    example: str
    pattern: re.Pattern
    needs: tuple[str, ...]
    fn: Callable[[dict[str, pd.DataFrame]], tuple[str, list[str]]]


def _p(s: str) -> re.Pattern:
    return re.compile(s, re.I)


TEMPLATES: tuple[Template, ...] = (
    Template("highest_load", "Which route has the highest load factor?", _p(r"(highest|most|best|max).*load factor|load factor.*(highest|most|best)"), ("route_summary",), _highest_load),
    Template("most_boardings", "Which route carries the most passengers?", _p(r"(most|highest|busiest|largest).*(passengers|boardings|ridership|riders)|(passengers|boardings).*(most|highest)"), ("route_summary",), _most_boardings),
    Template("evening_somnath", "What is the recommended evening Rajkot-Somnath action?", _p(r"somnath.*(evening|night)|(evening|night).*somnath"), ("recommendations",), _evening_somnath),
    Template("top_recommendation", "What is the top recommended action?", _p(r"(top|highest|first|main|biggest).*(recommend|action|priority)|(recommend|action).*(top|highest|first)"), ("recommendations",), _top_recommendation),
    Template("top_condition", "What would make private-vehicle users switch to the bus?", _p(r"(what|which|condition).*(switch|shift)|(switch|shift).*(condition|what would)"), ("survey_responses",), _top_condition),
    Template("top_gap_slot", "Where is the biggest competitive gap against private operators?", _p(r"(biggest|largest|highest|top).*(competitive|competition).*gap|competitive gap"), ("competition_analysis",), _top_gap_slot),
)

EXAMPLES: tuple[str, ...] = tuple(t.example for t in TEMPLATES)


def match(question: str) -> Template | None:
    q = " ".join(str(question or "").split())
    for t in TEMPLATES:
        if t.example.lower() == q.lower() or t.pattern.search(q):
            return t
    return None


def answer(question: str, tables: dict[str, pd.DataFrame]) -> RuleAnswer:
    """Rule-based answer for a supported template, else an explicit unsupported answer. Never guesses."""
    t = match(question)
    if t is None:
        return RuleAnswer(question, UNSUPPORTED_TEXT, False)
    missing = [n for n in t.needs if n not in tables]
    if missing:
        return RuleAnswer(question, f"The table(s) needed for this lookup are not available: {', '.join(missing)}.", False, [], t.key)
    text, cited = t.fn(tables)
    return RuleAnswer(question, text, True, cited, t.key)
