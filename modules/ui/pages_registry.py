"""Single source of truth for the nine navigation pages (docs/UX_AND_DEMO.md order)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    file: str  # path relative to repo root, as passed to st.Page
    icon: str
    purpose: str
    # Tables (layer, name) the page will need once built.
    required: tuple[tuple[str, str], ...]
    # Command that produces those tables.
    command: str
    milestone: str


GEN_CMD = "python -m modules.data_gen.generate"
ANALYTICS_CMD = "python -m modules.analytics.run"

PAGES: tuple[PageSpec, ...] = (
    PageSpec("overview", "Overview", "pages/0_Overview.py", ":material/dashboard:",
             "What is happening on the pilot corridor, where the problem is, and what action is recommended.",
             (("processed", "recommendations"), ("processed", "route_kpis")), ANALYTICS_CMD, "M2-M3"),
    PageSpec("demand", "Demand & Surveys", "pages/1_Demand_and_Surveys.py", ":material/groups:",
             "How passenger demand varies by time and purpose, and what would make private-vehicle users switch to the bus.",
             (("synthetic", "survey_responses"), ("synthetic", "tickets")), GEN_CMD, "M1, M5"),
    PageSpec("routes", "Route Intelligence", "pages/2_Route_Intelligence.py", ":material/route:",
             "Which routes perform best and where the potential is highest, with a transparent score explanation.",
             (("processed", "route_kpis"), ("processed", "route_scores")), ANALYTICS_CMD, "M2, M4"),
    PageSpec("gaps", "Demand–Supply Gaps", "pages/3_Demand_Supply_Gaps.py", ":material/bar_chart:",
             "Where and when estimated demand exceeds the seats offered, and the service change that could close the gap.",
             (("processed", "hourly_demand_supply"),), ANALYTICS_CMD, "M2-M3"),
    PageSpec("flow", "Passenger Flow & O-D", "pages/4_Passenger_Flow_OD.py", ":material/swap_horiz:",
             "Which origin-destination pairs carry the most passengers and when the peak hours occur.",
             (("processed", "od_flows"),), ANALYTICS_CMD, "M2-M3"),
    PageSpec("competition", "Competition & Pricing", "pages/5_Competition_and_Pricing.py", ":material/sell:",
             "How state services compare with private operators on departure slots, fares and bus types, with a fare what-if.",
             (("processed", "competition_analysis"),), ANALYTICS_CMD, "M5"),
    PageSpec("infrastructure", "Infrastructure & Digital", "pages/6_Infrastructure_and_Digital.py", ":material/domain:",
             "How stations and depots, and digital systems, score on key dimensions, and which improvements rank highest.",
             (("synthetic", "assets_assessment"), ("synthetic", "digital_assessment")), GEN_CMD, "M1, M3"),
    PageSpec("cctv", "CCTV Analytics", "pages/7_CCTV_Analytics.py", ":material/videocam:",
             "Aggregate people/vehicle counts from a permitted pre-recorded clip. Optional and isolated from the core app.",
             (("synthetic", "cctv_counts"),), "python -m modules.cv.count_video", "M6"),
    PageSpec("reports", "Reports", "pages/8_Reports.py", ":material/description:",
             "Download an evidence-backed PDF report and supporting CSV tables, with provenance and limitations.",
             (("processed", "recommendations"),), ANALYTICS_CMD, "M7"),
)

PAGES_BY_KEY: dict[str, PageSpec] = {p.key: p for p in PAGES}
