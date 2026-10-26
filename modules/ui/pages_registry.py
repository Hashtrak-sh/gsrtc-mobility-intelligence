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
BOTH_CMD = GEN_CMD + "\n" + ANALYTICS_CMD

_P, _S = "processed", "synthetic"

PAGES: tuple[PageSpec, ...] = (
    PageSpec("overview", "Overview", "pages/0_Overview.py", ":material/dashboard:",
             "What is happening on the pilot corridor, where the problem is, and what action is recommended.",
             ((_P, "route_summary"), (_P, "hourly_demand_supply"), (_P, "od_flows"), (_P, "recommendations"),
              (_S, "zones"), (_S, "stops"), (_S, "route_stops")), BOTH_CMD, "M3"),
    PageSpec("demand", "Demand & Surveys", "pages/1_Demand_and_Surveys.py", ":material/groups:",
             "How passenger demand varies by time and purpose, and what would make private-vehicle users switch to the bus.",
             ((_P, "od_flows"), (_P, "route_summary"), (_S, "survey_responses"), (_S, "zones"), (_S, "stops"), (_S, "route_stops")),
             BOTH_CMD, "M3"),
    PageSpec("routes", "Route Intelligence", "pages/2_Route_Intelligence.py", ":material/route:",
             "Which routes perform best and where the potential is highest, with a transparent score explanation.",
             ((_P, "route_summary"), (_P, "route_scores"), (_P, "route_kpis"), (_P, "stop_occupancy"), (_P, "hourly_demand_supply"),
              (_S, "stops")), BOTH_CMD, "M3"),
    PageSpec("gaps", "Demand–Supply Gaps", "pages/3_Demand_Supply_Gaps.py", ":material/bar_chart:",
             "Where and when estimated demand exceeds the seats offered, and the service change that could close the gap.",
             ((_P, "hourly_demand_supply"), (_P, "route_summary"), (_P, "recommendations"), (_S, "stops")), BOTH_CMD, "M3"),
    PageSpec("flow", "Passenger Flow & O-D", "pages/4_Passenger_Flow_OD.py", ":material/swap_horiz:",
             "Which origin-destination pairs carry the most passengers and when the peak hours occur.",
             ((_P, "od_flows"), (_P, "route_summary"), (_S, "zones"), (_S, "stops"), (_S, "route_stops")), BOTH_CMD, "M3"),
    PageSpec("competition", "Competition & Pricing", "pages/5_Competition_and_Pricing.py", ":material/sell:",
             "How state services compare with private operators on departure slots, fares and bus types, with a fare what-if.",
             ((_P, "route_summary"), (_P, "route_kpis"), (_S, "routes"), (_S, "trips"), (_S, "competitor_services")), BOTH_CMD, "M3"),
    PageSpec("infrastructure", "Infrastructure & Digital", "pages/6_Infrastructure_and_Digital.py", ":material/domain:",
             "How stations and depots, and digital systems, score on key dimensions, and which improvements rank highest.",
             ((_S, "assets_assessment"), (_S, "digital_assessment")), GEN_CMD, "M3"),
    PageSpec("cctv", "CCTV Analytics", "pages/7_CCTV_Analytics.py", ":material/videocam:",
             "Aggregate people/vehicle counts from a permitted pre-recorded clip. Optional and isolated from the core app.",
             ((_P, "cctv_hourly_profile"), (_S, "stops")), BOTH_CMD, "M3, M6"),
    PageSpec("reports", "Reports", "pages/8_Reports.py", ":material/description:",
             "Download supporting CSV tables for the current filters, with provenance and limitations.",
             ((_P, "route_summary"), (_P, "route_scores"), (_P, "recommendations"), (_P, "hourly_demand_supply"), (_P, "od_flows"),
              (_P, "stop_occupancy"), (_P, "cctv_hourly_profile"), (_S, "stops"), (_S, "route_stops")), BOTH_CMD, "M3, M7"),
)

PAGES_BY_KEY: dict[str, PageSpec] = {p.key: p for p in PAGES}
