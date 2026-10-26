"""PDF report (ReportLab) for the current dashboard filters.

``build_report_pdf(filters, tables=None) -> bytes`` is pure: it reads the processed tables (or the ``tables`` passed in), applies the
same filter functions and query helpers the dashboard pages use, and returns a PDF. Totals therefore equal the dashboard's for the
same filters (see :func:`report_totals`). Every page footer carries the simulation statement and the page number.

Fonts: if a TrueType font containing the rupee sign is found (Arial on Windows, DejaVu Sans on Linux) it is registered and used;
otherwise the built-in Helvetica is used and every rupee sign is written as ``Rs.`` (see :func:`setup_fonts`).

CLI: ``python -m modules.reporting.pdf --out data/processed/reports/report.pdf [--corridor ... --day-type ... --hours 7 22]``
"""
from __future__ import annotations

import argparse
import io
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import config
from modules.analytics import assets as AS
from modules.analytics import queries as Q
from modules.analytics import scenarios as SC
from modules.competition import analysis as CA
from modules.competition import gap_score as CG
from modules.reporting import sources
from modules.reporting import text as TXT
from modules.survey import summaries as SV
from modules.ui import filters as F
from modules.ui import fmt
from modules.ui import narrative as N

NAVY = colors.HexColor("#1f4e79")
AMBER = colors.HexColor("#e0a030")
LIGHT = colors.HexColor("#f3f6fa")
GREY = colors.HexColor("#5a6978")
RULE = colors.HexColor("#d5dbe1")

# ---------------------------------------------------------------------------------------------------------------- fonts
_FONT_SETS = [  # (regular, bold, italic)
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuii.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf"),
]


@dataclass(frozen=True)
class Fonts:
    regular: str
    bold: str
    italic: str
    unicode: bool  # True: a TTF with the rupee sign is registered; False: Helvetica + "Rs." fallback

    @property
    def rupee(self) -> str:
        return fmt.RUPEE if self.unicode else "Rs."


_FONTS: Fonts | None = None


def setup_fonts() -> Fonts:
    """Register a TTF family that contains the rupee sign, else fall back to Helvetica with ``Rs.`` (result is cached)."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    for reg, bold, ital in _FONT_SETS:
        if not (os.path.isfile(reg) and os.path.isfile(bold)):
            continue
        try:
            probe = TTFont("GSRTC-Probe", reg)
            if ord(fmt.RUPEE) not in probe.face.charToGlyph:
                continue
            pdfmetrics.registerFont(TTFont("GSRTC-Regular", reg))
            pdfmetrics.registerFont(TTFont("GSRTC-Bold", bold))
            pdfmetrics.registerFont(TTFont("GSRTC-Italic", ital if os.path.isfile(ital) else reg))
            pdfmetrics.registerFontFamily("GSRTC", normal="GSRTC-Regular", bold="GSRTC-Bold", italic="GSRTC-Italic", boldItalic="GSRTC-Bold")
            _FONTS = Fonts("GSRTC-Regular", "GSRTC-Bold", "GSRTC-Italic", True)
            return _FONTS
        except Exception:  # noqa: BLE001 - any font problem means: try the next set, then fall back
            continue
    _FONTS = Fonts("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", False)
    return _FONTS


def fallback_text(s: str) -> str:
    """Helvetica-safe text: rupee sign -> ``Rs.``, dashes/symbols to ASCII, anything else outside cp1252 -> ``?``."""
    s = (s.replace(fmt.RUPEE, "Rs.").replace("\u2013", "-").replace("\u2014", "-").replace("\u00d7", "x")
         .replace("\u2265", ">=").replace("\u2264", "<=").replace("\u2192", "->"))
    return s.encode("cp1252", "replace").decode("cp1252")


def _short(name: Any) -> str:
    return N._short(str(name))


# ---------------------------------------------------------------------------------------------------------------- totals
def report_totals(f: F.Filters, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Headline totals for the filtered scope, computed with the dashboard's own query functions (used by the PDF and tests)."""
    rs = tables["route_summary"]
    scope = F.scope_routes(rs, f.corridor)
    kp = Q.scope_kpis(scope)
    out: dict[str, Any] = {"kpis": kp, "n_routes": int(len(scope)), "boardings": int(scope["boardings"].sum())}
    recs = tables.get("recommendations")
    out["n_recommendations"] = 0 if recs is None else int(len(F.filter_recommendations(recs, f, rs)))
    if "hourly_demand_supply" in tables:
        h = F.filter_hourly(tables["hourly_demand_supply"], f, rs)
        out["gap"] = Q.gap_summary(h)
        dvs = Q.demand_vs_seats_by_hour(h)
        out["demand_sum"] = float(dvs["demand"].sum()) if len(dvs) else 0.0
        out["seats_sum"] = float(dvs["seats"].sum()) if len(dvs) else 0.0
    if "od_flows" in tables:
        out["od_passengers"] = float(F.filter_od(tables["od_flows"], f, rs)["passenger_count"].sum())
    return out


# ---------------------------------------------------------------------------------------------------------------- builder
class _Builder:
    def __init__(self, f: F.Filters, tables: dict[str, pd.DataFrame], now: datetime):
        self.f, self.t, self.now = f, tables, now
        self.fonts = fn = setup_fonts()
        self.body = ParagraphStyle("body", fontName=fn.regular, fontSize=9, leading=12.5, spaceAfter=4)
        self.small = ParagraphStyle("small", parent=self.body, fontSize=7.5, leading=10, textColor=GREY)
        self.cell = ParagraphStyle("cell", parent=self.body, fontSize=7.5, leading=9.5, spaceAfter=0)
        self.cell_r = ParagraphStyle("cell_r", parent=self.cell, alignment=2)
        self.cell_h = ParagraphStyle("cell_h", parent=self.cell, fontName=fn.bold, textColor=colors.white)
        self.cell_hr = ParagraphStyle("cell_hr", parent=self.cell_h, alignment=2)
        self.h1 = ParagraphStyle("h1", fontName=fn.bold, fontSize=14, leading=18, textColor=NAVY, spaceBefore=6, spaceAfter=6, keepWithNext=1)
        self.h2 = ParagraphStyle("h2", fontName=fn.bold, fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=6, spaceAfter=3, keepWithNext=1)
        self.title = ParagraphStyle("title", fontName=fn.bold, fontSize=24, leading=29, textColor=NAVY, spaceAfter=6)
        self.bullet = ParagraphStyle("bullet", parent=self.body, leftIndent=10, bulletIndent=0, spaceAfter=1, fontSize=8.5, leading=11)
        self.bullet_s = ParagraphStyle("bullet_s", parent=self.bullet, fontSize=7.5, leading=9.5)
        self.warn = ParagraphStyle("warn", parent=self.body, fontName=fn.bold, fontSize=11, leading=14, textColor=colors.HexColor("#7a4b00"))
        self.story: list = []

    # -- text helpers
    def tx(self, s: Any) -> str:
        s = "" if s is None else str(s)
        return s if self.fonts.unicode else fallback_text(s)

    def e(self, s: Any) -> str:
        """Escaped, font-safe text for use inside inline markup."""
        return escape(self.tx(s))

    def p(self, s: Any, style: ParagraphStyle | None = None) -> Paragraph:
        return Paragraph(self.e(s), style or self.body)

    def add(self, *flowables) -> None:
        self.story.extend(flowables)

    def para(self, s: str, style: ParagraphStyle | None = None) -> None:
        self.add(self.p(s, style))

    def bullet_p(self, s: str, style: ParagraphStyle | None = None) -> Paragraph:
        return Paragraph(self.e(s), style or self.bullet, bulletText="\u2022" if self.fonts.unicode else "-")

    def bullets(self, items: list[str], style: ParagraphStyle | None = None) -> None:
        self.add(*[self.bullet_p(it, style) for it in items])

    def heading(self, text: str, level: int = 1) -> None:
        self.add(self.p(text, self.h1 if level == 1 else self.h2))

    def table(self, header: list[str], rows: list[list[Any]], widths: list[float] | None = None, right: tuple[int, ...] = ()) -> Table:
        data = [[Paragraph(self.e(h), self.cell_hr if i in right else self.cell_h) for i, h in enumerate(header)]]
        for r in rows:
            data.append([Paragraph(self.e(c), self.cell_r if i in right else self.cell) for i, c in enumerate(r)])
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                               ("GRID", (0, 0), (-1, -1), 0.25, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return t

    def notice(self, s: str) -> None:
        t = Table([[self.p(s, self.cell)]], colWidths=[174 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff4e0")), ("BOX", (0, 0), (-1, -1), 0.6, AMBER),
                               ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        self.add(t, Spacer(1, 4))

    def unavailable(self, what: str, command: str = "python -m modules.analytics.run") -> None:
        self.para(f"Not available: {what}. Nothing has been substituted for it. Generate it with: {command}", self.small)

    # -- derived frames
    @property
    def rs(self) -> pd.DataFrame:
        return self.t["route_summary"]

    @property
    def scope(self) -> pd.DataFrame:
        return F.scope_routes(self.rs, self.f.corridor)

    def hourly(self) -> pd.DataFrame | None:
        h = self.t.get("hourly_demand_supply")
        return None if h is None else F.filter_hourly(h, self.f, self.rs)

    def recs(self) -> pd.DataFrame:
        r = self.t.get("recommendations")
        if r is None:
            return pd.DataFrame()
        return F.filter_recommendations(r, self.f, self.rs).sort_values("priority_rank")

    def names(self, name: str, key: str, val: str) -> dict[str, str]:
        d = self.t.get(name)
        return {} if d is None else dict(zip(d[key], d[val]))

    # -- sections
    def build(self) -> list:
        self.cover()
        self.executive_summary()
        self.pilot_scope()
        self.route_findings()
        self.gaps_and_recs()
        self.competition()
        self.cost_benefit()
        self.infrastructure()
        self.survey()
        self.model_and_cctv()
        self.methodology()
        self.scale_up()
        return self.story

    def cover(self) -> None:
        f = self.f
        self.add(Spacer(1, 22 * mm), self.p("GSRTC Mobility Intelligence", self.title),
                 self.p("Pilot findings and recommendations: Rajkot and the Rajkot\u2013Somnath corridor", self.h2), Spacer(1, 6 * mm))
        t = Table([[self.p(config.SIMULATION_BADGE_TEXT.upper(), self.warn)], [self.p(TXT.SIM_STATEMENT, self.cell)]], colWidths=[174 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff4e0")), ("BOX", (0, 0), (-1, -1), 1.2, AMBER),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        self.add(t, Spacer(1, 6 * mm))
        meta = [["Report generated (UTC)", self.now.strftime("%Y-%m-%d %H:%M:%S UTC")],
                ["Processed data generated (UTC)", sources.data_generated_at().replace("T", " ")[:19]],
                ["Random seed", str(sources.data_seed())],
                ["Selected corridor", f.corridor], ["Selected day type", f.day_type], ["Selected hours (24-hour clock)", f.hours_label],
                ["Filters (as shown on the dashboard)", f.describe()]]
        self.add(self.table(["Item", "Value"], meta, [58 * mm, 116 * mm]), Spacer(1, 5 * mm))
        self.heading("Data provenance summary", 2)
        rows = []
        for layer, names in (("processed", ("route_summary", "route_scores", "recommendations", "hourly_demand_supply", "od_flows",
                                            "competition_analysis", "ridership_model_metrics", "survey_model_metrics")),
                             ("synthetic", ("routes", "tickets", "survey_responses", "competitor_services", "cctv_counts"))):
            for name in names:
                pr = sources.provenance(name, layer)
                if pr:
                    rows.append([name, layer, pr.get("source_type", ""), pr.get("seed", ""), str(pr.get("generated_at", ""))[:19].replace("T", " ")])
        if rows:
            self.add(self.table(["Table", "Layer", "Source type", "Seed", "Generated (UTC)"], rows, [48 * mm, 22 * mm, 40 * mm, 14 * mm, 50 * mm]))
        stops = self.t.get("stops")
        if stops is not None and "coord_source" in stops.columns:
            cs = stops["coord_source"].value_counts()
            self.add(Spacer(1, 3 * mm), self.p(
                f"Real geography versus simulated mobility. Of {len(stops)} stops, {int(cs.get('openstreetmap', 0))} use coordinates taken from "
                f"OpenStreetMap, {int(cs.get('openstreetmap_offset', 0))} are synthetic points placed near a real OpenStreetMap place and "
                f"{int(cs.get('manual_demo_input', 0))} are hand-entered approximations. Everything about passengers, tickets, fares, surveys, "
                "competitors and routes is synthetic; the routes are demonstration routes, not real GSRTC routes.", self.cell))
        self.add(PageBreak())

    def executive_summary(self) -> None:
        f, rs = self.f, self.rs
        self.heading("1. Executive summary")
        self.notice(TXT.SIM_STATEMENT)
        scope = self.scope
        if scope.empty:
            self.para("The selected corridor has no routes in the generated data, so there is nothing to summarise.")
            return
        kp = Q.scope_kpis(scope)
        self.para(f"Scope: {f.describe()}. {kp['n_routes']} route(s) in scope carry about {fmt.number(kp['avg_boardings_per_day'])} simulated boardings a day "
                  f"at a {fmt.pct(kp['load_factor_pct'])} load factor and {fmt.pct(kp['reliability_pct'])} on-time departures; contribution is "
                  f"{fmt.inr(kp['contribution_per_day_inr'])} a day (revenue minus operating cost, not profit).")
        self.heading("Three key findings", 2)
        h = self.hourly()
        od = self.t.get("od_flows")
        if h is not None and od is not None:
            o = F.filter_od(od, f, rs)
            pairs = Q.od_pairs(o, top=10)
            findings = N.key_findings(h, pairs, dict(zip(rs["route_id"], rs["name"])), self.names("stops", "stop_id", "name"),
                                      self.names("zones", "zone_id", "name"), f.day_type, float(o["passenger_count"].sum()))
            for i, fd in enumerate(findings, 1):
                self.add(Paragraph(f"<b>{i}. {self.e(fd['title'])}.</b> {self.e(fd['text'])} "
                                   f"<font color='#5a6978' size='7'>Source: {self.e(fd['source'])}.</font>", self.body))
        else:
            self.unavailable("hourly_demand_supply and od_flows (needed for the key findings)")
        self.heading("Top recommended actions", 2)
        recs = self.recs()
        if recs.empty:
            self.para("No rule-generated recommendation applies to the selected corridor.")
        for _, r in recs.head(3).iterrows():
            self.add(Paragraph(f"<b>{self.e(r['recommendation_id'])} ({self.e(r['priority'])} priority).</b> {self.e(r['title'])}. "
                               f"{self.e(N.impact_summary(r))} <i>{self.e(r['confidence_label'])}.</i>", self.body))
        self.para("Evidence, assumptions and constraints for every recommendation are in section 5. Recommendations are indicative and based on simulated data.", self.small)

    def pilot_scope(self) -> None:
        self.heading("2. Pilot scope and data provenance")
        rs = self.rs
        n_local = int((rs["route_type"] == "local").sum())
        n_ic = int((rs["route_type"] == "intercity").sum())
        others = ", ".join(c for c in config.INTERCITY_CORRIDORS if c != config.PRIMARY_CORRIDOR)
        self.para(f"Pilot geography: {config.PILOT_CITY}, with the {config.PRIMARY_CORRIDOR} corridor as the primary intercity corridor, the other intercity "
                  f"corridors ({others}) and a local Rajkot network. The generated network has {n_local} local and {n_ic} intercity demonstration routes, "
                  f"simulated over 42 days (seed {sources.data_seed()}).")
        self.bullets([
            "Real (OpenStreetMap): place coordinates for stops and the road geometry used to route paths.",
            "Synthetic: routes and timetables, tickets and boardings, fares, delays, survey responses, competitor services, reviews, station and digital assessments, the CCTV stream.",
            "Model output: ridership model, route scores, competitive gap scores, switch-intent model, recommendations (all derived from the synthetic data).",
            "Manual demo input: a few hand-entered stop coordinates when OpenStreetMap places were unavailable.",
        ])
        self.para(f"Filters applied to this report: {self.f.describe()}. Route-level tables use the corridor only and always cover all 42 days; hourly, stop, "
                  "origin-destination and CCTV tables also use the day type and hours.", self.small)

    def route_findings(self) -> None:
        f, scope = self.f, self.scope
        self.heading("3. Route and demand findings")
        if scope.empty:
            self.para("No routes in scope.")
            return
        kp = Q.scope_kpis(scope)
        sc = self.t.get("route_scores")
        rank = {} if sc is None else dict(zip(sc["route_id"], sc["rank"]))
        rows = []
        for _, r in scope.sort_values("route_id").iterrows():
            rows.append([r["route_id"], _short(r["name"])[:34], fmt.number(r["avg_boardings_per_day"]), fmt.pct(r["load_factor_pct"]),
                         fmt.pct(r["reliability_pct"]), fmt.times(r["peak_load_factor_max"]), fmt.inr(r["contribution_per_day_inr"]),
                         "" if r["route_id"] not in rank else fmt.number(rank[r["route_id"]])])
        rows.append(["Total", f"{kp['n_routes']} routes", fmt.number(kp["avg_boardings_per_day"]), fmt.pct(kp["load_factor_pct"]),
                     fmt.pct(kp["reliability_pct"]), "", fmt.inr(kp["contribution_per_day_inr"]), ""])
        self.add(self.table(["ID", "Route", "Avg boardings/day", "Load factor", "On-time", "Peak load (x seats)", "Contribution/day (not profit)", "Score rank"],
                            rows, [11 * mm, 46 * mm, 24 * mm, 17 * mm, 15 * mm, 18 * mm, 30 * mm, 13 * mm], right=(2, 3, 4, 5, 6, 7)))
        self.para(f"Route KPIs come from route_summary over all 42 simulated days (total boardings {fmt.number(kp['boardings'])}). Score rank is the rule-based "
                  "route potential rank across all routes (1 = highest), not an AI prediction.", self.small)
        h = self.hourly()
        if h is not None:
            dvs = Q.demand_vs_seats_by_hour(h)
            if len(dvs):
                self.add(KeepTogether([self.p(f"Estimated demand versus seats offered by hour, {f.describe(hours=False)} (average day)", self.h2),
                                       self._demand_chart(dvs),
                                       self.p("Hours without any scheduled state departure are not drawn. Demand is estimated from ticketed boardings and is "
                                              "censored at capacity.", self.small)]))
            else:
                self.para("No scheduled departures with estimated demand fall in the selected hours.", self.small)
        if sc is not None:
            top = sc[sc["route_id"].isin(set(scope["route_id"]))].sort_values(["total_score", "route_id"], ascending=[False, True]).head(8)
            if len(top):
                self.add(KeepTogether([self.p("Top route potential scores (rule-based, weights demo-v1)", self.h2), self._score_chart(top),
                                       self.p("Score = weighted index of demand, unmet demand, load, reliability gap, revenue potential, social importance and "
                                              "feasibility. Minimum-service routes are protected regardless of score.", self.small)]))
        od = self.t.get("od_flows")
        if od is not None:
            pairs = Q.od_pairs(F.filter_od(od, f, self.rs), top=5)
            zn = self.names("zones", "zone_id", "name")
            if len(pairs):
                self.heading("Busiest origin-destination pairs", 2)
                self.add(self.table(["Origin", "Destination", f"Passengers per average {f.day_type}"],
                                    [[zn.get(a, a), zn.get(b, b), fmt.number(c)] for a, b, c in
                                     zip(pairs["origin_zone_id"], pairs["dest_zone_id"], pairs["passengers_per_day"])],
                                    [64 * mm, 64 * mm, 46 * mm], right=(2,)))

    def _demand_chart(self, dvs: pd.DataFrame) -> Drawing:
        d = Drawing(170 * mm, 62 * mm)
        c = VerticalBarChart()
        c.x, c.y, c.width, c.height = 12 * mm, 12 * mm, 150 * mm, 42 * mm
        c.data = [[float(x) for x in dvs["demand"]], [float(x) for x in dvs["seats"]]]
        c.categoryAxis.categoryNames = [f"{int(x):02d}" for x in dvs["hour"]]
        c.categoryAxis.labels.fontName = c.valueAxis.labels.fontName = self.fonts.regular
        c.categoryAxis.labels.fontSize = c.valueAxis.labels.fontSize = 6.5
        c.valueAxis.valueMin = 0
        c.bars[0].fillColor, c.bars[1].fillColor = colors.HexColor("#c4551b"), colors.HexColor("#9fb6cd")
        c.barWidth, c.groupSpacing = 3, 4
        d.add(c)
        leg = Legend()
        leg.x, leg.y, leg.fontName, leg.fontSize = 100 * mm, 60 * mm, self.fonts.regular, 7
        leg.colorNamePairs = [(c.bars[0].fillColor, "Estimated demand"), (c.bars[1].fillColor, "Seats offered")]
        leg.columnMaximum, leg.deltax, leg.alignment = 1, 40, "right"
        d.add(leg)
        d.add(String(2 * mm, 56 * mm, "Passengers / seats per day", fontName=self.fonts.regular, fontSize=7))
        d.add(String(60 * mm, 2 * mm, "Departure hour (24-hour clock)", fontName=self.fonts.regular, fontSize=7))
        return d

    def _score_chart(self, top: pd.DataFrame) -> Drawing:
        top = top.iloc[::-1]  # horizontal charts draw the first category at the bottom
        d = Drawing(170 * mm, 55 * mm)
        c = HorizontalBarChart()
        c.x, c.y, c.width, c.height = 22 * mm, 6 * mm, 138 * mm, 46 * mm
        c.data = [[float(x) for x in top["total_score"]]]
        c.categoryAxis.categoryNames = list(top["route_id"])
        c.categoryAxis.labels.fontName = c.valueAxis.labels.fontName = self.fonts.regular
        c.categoryAxis.labels.fontSize = c.valueAxis.labels.fontSize = 7
        c.valueAxis.valueMin, c.valueAxis.valueMax = 0, 100
        c.bars[0].fillColor = NAVY
        c.barLabelFormat = "%.0f"
        c.barLabels.fontName, c.barLabels.fontSize, c.barLabels.nudge = self.fonts.regular, 6.5, 8
        d.add(c)
        return d

    def gaps_and_recs(self) -> None:
        f = self.f
        self.heading("4. Supply-gap findings")
        h = self.hourly()
        if h is None:
            self.unavailable("hourly_demand_supply")
        else:
            g = Q.gap_summary(h)
            self.para(f"{f.describe()}. {g['crowded_route_hours']} route-direction hour(s) are crowded or at capacity (peak gap index {fmt.times(g['max_gap_index'])}); "
                      f"{g['uncovered_corridor_hours']} corridor hour(s) in {g['uncovered_windows']} window(s) have private operators but no scheduled state seats "
                      f"(assumed proxy demand about {fmt.number(g['uncovered_proxy_demand'])} passengers a day, an assumption not an observation).")
            cr = Q.crowded_route_hours(h).head(8)
            if len(cr):
                names = dict(zip(self.rs["route_id"], self.rs["name"]))
                self.add(self.table(["Route", "Direction", "Hour", "Demand / seats", "Status"],
                                    [[f"{r['route_id']} {_short(names.get(r['route_id'], ''))}"[:44], r["direction"], fmt.hhmm(r["hour"]), fmt.times(r["gap_index"]), r["status"]]
                                     for _, r in cr.iterrows()], [76 * mm, 24 * mm, 18 * mm, 28 * mm, 28 * mm], right=(2, 3)))
            unc = Q.uncovered_windows(h)
            if len(unc):
                self.add(Spacer(1, 3 * mm), self.table(
                    ["Corridor", "Window", "Private departures", "Proxy demand / day (assumed)"],
                    [[r["corridor"], fmt.hour_window(int(r["start_hour"]), int(r["end_hour"])), fmt.number(r["private_departures"]), fmt.number(r["proxy_demand"])]
                     for _, r in unc.iterrows()], [50 * mm, 36 * mm, 40 * mm, 48 * mm], right=(2, 3)))
        self.add(PageBreak())
        self.heading("5. Service recommendations")
        self.para("Each recommendation is rule-generated from the tables above. It states its evidence, assumptions, expected impact (illustrative; contribution is "
                  "not profit) and constraints. Minimum-service routes are protected, never cut for a low commercial score.", self.small)
        recs = self.recs()
        if recs.empty:
            self.para("No recommendation applies to the selected corridor.")
        for _, r in recs.iterrows():
            self.add(self._rec_block(r))

    def _rec_block(self, r: pd.Series) -> KeepTogether:
        ev = N.json_dict(r["evidence_json"])
        figs: dict[str, Any] = dict(ev.get("figures", {}))
        for v in ev.values():
            if isinstance(v, dict) and isinstance(v.get("figures"), dict):
                figs.update(v["figures"])
        ev_lines = [x for x in (N.describe_value(k, v) for k, v in figs.items()) if x][:7]
        asm_lines = [x for x in (N.describe_value(k, v) for k, v in N.json_dict(r["assumptions_json"]).items()) if x][:6]
        cons = N.json_list(r["constraints_json"])
        fl: list = [self.p(f"{r['recommendation_id']}: {r['title']}", self.h2),
                    Paragraph(f"<b>Priority:</b> {self.e(r['priority'])} &nbsp; <b>Window:</b> {self.e(r['time_window'])} &nbsp; "
                              f"<b>Day type:</b> {self.e(str(r['day_type']).replace('+', ' and '))} &nbsp; "
                              f"<b>Confidence:</b> {self.e(r['confidence_label'])}", self.cell),
                    self.p(r["action"], self.body),
                    Paragraph("<b>Expected impact:</b> " + self.e(N.impact_summary(r)), self.body)]
        sens = N.capture_sensitivity_lines(r)
        if sens:
            fl.append(self.p("Capture-share sensitivity (share of private-market demand the state is assumed to capture):", self.cell))
            fl += [self.bullet_p(x) for x in sens]
        if ev_lines:
            fl.append(self.p("Evidence:", self.cell))
            fl += [self.bullet_p(x) for x in ev_lines]
        if asm_lines:
            fl.append(self.p("Assumptions:", self.cell))
            fl += [self.bullet_p(x) for x in asm_lines]
        if cons:
            fl.append(Paragraph("<b>Constraints:</b> " + self.e("; ".join(cons)), self.cell))
        fl.append(Spacer(1, 3 * mm))
        return KeepTogether(fl)

    def competition(self) -> None:
        f = self.f
        self.add(PageBreak())
        self.heading("6. Competition and pricing scenario")
        comp = self.t.get("competition_analysis")
        if comp is None:
            self.unavailable("competition_analysis")
        else:
            c = comp[comp["day_type"] == f.day_type]
            if f.corridor != F.ALL:
                c = c[c["route_pair"] == f.corridor]
            if c.empty:
                self.para("The competition analysis covers intercity corridors only; there is no private-operator comparison for the selected scope.")
            else:
                rows = []
                for corr, g in c.groupby("route_pair"):
                    fi, fs = g["fare_index"].dropna(), g["fare_index_surge"].dropna()
                    rows.append([corr, fmt.number(g["state_departures"].sum()), fmt.number(g["private_departures"].sum()),
                                 f"{fi.mean():.2f}" if len(fi) else fmt.NA, f"{fs.mean():.2f}" if len(fs) else fmt.NA,
                                 f"{g['competitive_gap_score'].max():.0f}"])
                self.para(f"Fare index = state fare / median private fare (below 1.00 means the state fare is lower). {f.describe(hours=False)}. "
                          "Private-operator services and fares are synthetic assumptions, not verified competitor data.", self.small)
                self.add(self.table(["Corridor", "State departures (hour-slots)", "Private departures (hour-slots)", "Mean fare index", "Mean surge fare index",
                                     "Peak gap score (0-100)"], rows, [40 * mm, 28 * mm, 28 * mm, 24 * mm, 26 * mm, 28 * mm], right=(1, 2, 3, 4, 5)))
                top = CG.top_gap_slots(comp, None if f.corridor == F.ALL else f.corridor, f.day_type, top=5)
                self.heading("Highest competitive-gap slots", 2)
                self.add(self.table(["Corridor", "Hour", "Gap score", "State dep.", "Private dep.", "Fare index"],
                                    [[r["route_pair"], fmt.hhmm(r["hour"]), f"{r['competitive_gap_score']:.1f}", fmt.number(r["state_departures"]),
                                      fmt.number(r["private_departures"]), "n/a" if pd.isna(r["fare_index"]) else f"{r['fare_index']:.2f}"]
                                     for _, r in top.iterrows()], [48 * mm, 20 * mm, 24 * mm, 26 * mm, 26 * mm, 30 * mm], right=(1, 2, 3, 4, 5)))
        self.heading("Pricing sensitivity (illustrative)", 2)
        kpis = self.t.get("route_kpis")
        cand = self.scope[self.scope["route_type"] == "intercity"]
        if kpis is None or cand.empty:
            self.para("No intercity route in scope (or route_kpis missing), so no pricing scenario is shown.", self.small)
            return
        route = cand.sort_values(["avg_boardings_per_day", "route_id"], ascending=[False, True]).iloc[0]
        try:
            base = CA.pricing_baseline(kpis, route, f.day_type)
            new_fare = round(base["baseline_fare"] * 1.10, 2)
            sens = SC.pricing_sensitivity(base["baseline_demand"], base["baseline_fare"], new_fare, base["seats_offered"], base["operating_cost"])
        except ValueError as exc:
            self.para(f"No pricing scenario for {route['route_id']}: {exc}.", self.small)
            return
        self.para(f"Route {route['route_id']} ({_short(route['name'])}), average {f.day_type}: baseline fare about {fmt.inr(base['baseline_fare'], 2)} per passenger-trip "
                  f"equivalent, +10% fare scenario ({fmt.inr(new_fare, 2)}). Demand responds as demand x (new fare / old fare) ^ elasticity, capped at seats offered. "
                  f"Elasticity is an assumption (default {config.PRICING_ELASTICITY_DEFAULT}); contribution is revenue minus operating cost, not profit.")
        self.add(self.table(["Elasticity (assumed)", "Demand", "Served", "Occupancy", "Revenue/day", "Revenue change/day", "Contribution/day"],
                            [[f"{r['elasticity']:.1f}", fmt.number(r["demand_unconstrained"]), fmt.number(r["served_demand"]), fmt.ratio_pct(r["occupancy"]),
                              fmt.inr(r["revenue_inr"]), fmt.inr(r["revenue_change_inr"]), fmt.inr(r["contribution_inr"])] for _, r in sens.iterrows()],
                            [26 * mm, 20 * mm, 20 * mm, 22 * mm, 28 * mm, 30 * mm, 28 * mm], right=(0, 1, 2, 3, 4, 5, 6)))

    def cost_benefit(self) -> None:
        """Section 6a: cost per km by class, peak vs normal, recommended fare bands and BCR at DEFAULT illustrative parameters."""
        from modules.ui import cost_charts as CC

        f = self.f
        self.add(PageBreak())
        self.heading("6a. Cost-benefit and fares (illustrative)")
        corridor = f.corridor if f.corridor in config.INTERCITY_CORRIDORS else config.PRIMARY_CORRIDOR
        try:
            from modules.analytics import cost_model as CM
            from modules.analytics import fare_analysis as FA

            pl = CC.default_report_payload(FA.load_inputs(), self.rs, corridor, f.day_type)
            out: list = []
            summ, sel, rec, corr = pl["summary"], pl["sel"], pl["rec"], pl["corr"]
            if sel.empty:
                raise ValueError(f"no intercity trips for {corridor} on a {f.day_type}")
            out.append(self.p(f"{corridor}, {f.day_type}, default parameters (the dashboard page 'Cost-Benefit & Fares' lets every parameter be edited). "
                              "Illustrative cost model and appraisal: orders of magnitude, not GSRTC data; passenger and revenue inputs are simulated.", self.small))
            if corridor != f.corridor:
                out.append(self.p(f"Cost-benefit covers intercity corridors only; {corridor} is shown instead of the selected scope.", self.small))
            out.append(self.p("Cost per bus-km by class", self.h2))
            out.append(self.table(["Bus class", "Seats", "Trip operating (INR/km)", "Fixed and overhead (INR/km)", "Full cost (INR/km)"],
                                  [[CM.CLASS_LABELS[r["bus_class"]], fmt.number(r["seats"]), CC.d_num(r["trip_operating_per_km"], 1),
                                    CC.d_num(r["fixed_and_overhead_per_km"], 1), CC.d_num(r["full_cost_per_km"], 1)] for _, r in summ.iterrows()],
                                  [56 * mm, 16 * mm, 34 * mm, 36 * mm, 32 * mm], right=(1, 2, 3, 4)))
            out.append(self.p(f"Includes the illustrative {corridor} toll at {fmt.number(pl['length_km'], 0)} km. Trip operating cost is the only cost in 'contribution'; "
                              "fixed and overhead costs (dead km, depreciation or lease, insurance/tax/permits, tolls, depot overhead) are not. "
                              "Volvo, non-AC sleeper and e-bus are what-if classes that are not in the timetable.", self.small))
            peak = [int(h) for h in pl["bands"].loc[pl["bands"]["band"] == "peak", "dep_hour"]]
            out.append(self.p("Peak vs normal hours", self.h2))
            wins = ", ".join(fmt.hour_window(a, b) for a, b in fmt.contiguous_windows(peak)) if peak else "none"
            rule = str(pl["bands"]["rule"].iloc[0]) if len(pl["bands"]) else ""
            out.append(self.p(f"Peak departure hours derived from the data: {wins}. Rule: {rule}.", self.body))
            out.append(self.table(["Route / class", "Band", "Trips per day", "Load factor", "Contribution per trip (not profit)", "Full-cost margin per trip"],
                                  [[CC.route_label(r), r["band"], CC.d_num(r["trips_per_day"], 1), CC.d_pct(r["load_factor"]),
                                    CC.d_inr(r["contribution_per_trip_inr"]), CC.d_inr(r["full_cost_margin_per_trip_inr"])] for _, r in sel.iterrows()],
                                  [38 * mm, 18 * mm, 24 * mm, 24 * mm, 36 * mm, 34 * mm], right=(2, 3, 4, 5)))

            def band_txt(r) -> str:
                if CC.ok(r["band_low_inr"]) and CC.ok(r["band_high_inr"]):
                    return f"{fmt.inr(r['band_low_inr'])} to {fmt.inr(r['band_high_inr'])}"
                return f"from {fmt.inr(r['band_low_inr'])}" if CC.ok(r["band_low_inr"]) else CC.DASH

            out.append(self.p(f"Recommended fare band (break-even at {pl['target_load_factor']:.0%} load on full cost)", self.h2))
            out.append(self.table(["Route / class", "Band", "Current fare", "Break-even fare", "Private comparator", "Recommended band", "Status"],
                                  [[CC.route_label(r), r["band"], CC.d_inr(r["current_fare_inr"]), CC.d_inr(r["break_even_fare_inr"]),
                                    CC.d_inr(r["private_comparator_inr"]), band_txt(r), r["status"]] for _, r in rec.iterrows()],
                                  [28 * mm, 14 * mm, 18 * mm, 21 * mm, 22 * mm, 30 * mm, 41 * mm], right=(2, 3, 4)))
            out.append(self.p("'Not viable on fare alone' means the fare needed to cover full cost at the target load exceeds the competitive cap; the options are cost "
                              "reduction, a higher load factor, viability-gap support or a social justification.", self.small))
            out.append(self.p("Illustrative social benefit-cost ratio per corridor", self.h2))
            out.append(self.table(["Corridor", "Ticket revenue per day", "Full cost per day", "Net social benefit per day", "BCR"],
                                  [[r["corridor"], CC.d_inr(r["revenue_per_day_inr"]), CC.d_inr(r["full_cost_per_day_inr"]),
                                    CC.d_inr(r["net_social_benefit_per_day_inr"]), CC.d_x(r["bcr"])] for _, r in corr.iterrows()],
                                  [44 * mm, 34 * mm, 34 * mm, 38 * mm, 24 * mm], right=(1, 2, 3, 4)))
            out.append(self.p("BCR = (social benefits + ticket revenue) / full cost, averaged over all 42 simulated service days; above 1.0 the service returns more to society "
                              "than it costs. Parameters (value of time, diversion shares, carbon price) are illustrative; contribution and margins are not profit; "
                              "elasticities and private fares are assumptions on simulated data.", self.small))
        except Exception as exc:  # the report must still build
            self.para(f"Not available: the cost-benefit analysis could not be computed ({type(exc).__name__}: {exc}). Nothing has been substituted for it.", self.small)
            return
        self.add(*out)

    def infrastructure(self) -> None:
        self.heading("7. Infrastructure and digital findings")
        a, d = self.t.get("assets_assessment"), self.t.get("digital_assessment")
        if a is None or d is None:
            self.unavailable("assets_assessment / digital_assessment", "python -m modules.data_gen.generate")
            return
        s = AS.assets_summary(a, d)
        self.para(f"{s['n_assets']} synthetic stations/depots assessed (0-5 scale). Mean infrastructure score {s['mean_asset_score']:.2f}; weakest dimension: "
                  f"{AS.DIM_LABELS.get(s['lowest_dimension'], s['lowest_dimension'])} ({s['lowest_dimension_score']:.2f}). Mean digital maturity "
                  f"{s['mean_digital_maturity']:.2f}; weakest capability: {s['weakest_capability']} ({s['weakest_capability_score']:.2f}). "
                  f"{s['n_below_threshold']} item(s) score below the low-score threshold. All scores are simulated assessments, not audits.")
        names = dict(zip(a["asset_id"], a["asset_name"]))
        top = AS.improvement_list(a, d, names, top=8)
        self.add(self.table(["Rank", "Area", "Asset", "Item", "Score (0-5)", "Evidence note"],
                            [[r["rank"], r["area"], r["asset"], r["item"], f"{r['score']:.1f}", r["evidence_note"]] for _, r in top.iterrows()],
                            [10 * mm, 22 * mm, 40 * mm, 24 * mm, 17 * mm, 61 * mm], right=(0, 4)))

    def survey(self) -> None:
        self.heading("8. Survey findings")
        sv = self.t.get("survey_responses")
        if sv is None:
            self.unavailable("survey_responses", "python -m modules.data_gen.generate")
            return
        self.heading("8a. Descriptive findings (synthetic sample, unweighted)", 2)
        meta = SV.survey_meta(sv)
        intent = SV.stated_switch_intent(sv)
        self.para(f"{meta['n']} simulated responses ({meta['n_private']} private-vehicle users), {meta['first']} to {meta['last']}. "
                  f"{fmt.pct(intent['share_pct'], 0)} of private-vehicle users have a recorded switch intent of yes. These shares describe the synthetic sample only.")
        reasons, conds = SV.private_use_reasons(sv).head(5), SV.switch_conditions(sv).head(5)
        two = Table([[self.table(["Reason for private-vehicle use", "Share"], [[r["label"], fmt.pct(r["share_pct"], 0)] for _, r in reasons.iterrows()], [58 * mm, 20 * mm], right=(1,)),
                      self.table(["What would make them switch", "Share"], [[r["label"], fmt.pct(r["share_pct"], 0)] for _, r in conds.iterrows()], [58 * mm, 20 * mm], right=(1,))]],
                    colWidths=[87 * mm, 87 * mm])
        two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        self.add(two)
        self.para("Respondents may name several items, so shares add up to more than 100%.", self.small)
        self.heading("8b. Illustrative model (model-based, not descriptive)", 2)
        m = self.t.get("survey_model_metrics")
        if m is None:
            self.unavailable("survey_model_metrics (needs scikit-learn to generate)", "python -m modules.survey.mode_choice")
            return
        self.notice("Model-based and illustrative. The model is fitted to a synthetic survey whose answers were generated by a known formula, so it can only "
                    "recover that formula. It is not a forecast of real behaviour.")
        ms = m.set_index("metric")
        rows = []
        for key, lab in (("accuracy", "Accuracy"), ("roc_auc", "ROC-AUC"), ("brier_score", "Brier score (lower is better)")):
            if key in ms.index:
                x = ms.loc[key]
                rows.append([lab, f"{x['model']:.3f}", f"{x['baseline']:.3f}", "yes" if bool(x["beats_baseline"]) else "no", x["baseline_definition"]])
        self.add(self.table(["Metric (held-out test)", "Model", "Baseline", "Beats baseline", "Baseline definition"], rows,
                            [38 * mm, 18 * mm, 18 * mm, 24 * mm, 76 * mm], right=(1, 2)))
        self.para(f"Stratified {int(m['n_train'].iloc[0])} train / {int(m['n_test'].iloc[0])} test split.", self.small)

    def model_and_cctv(self) -> None:
        self.heading("9. Model and CCTV evidence status")
        self.heading("Ridership model versus baselines", 2)
        m = self.t.get("ridership_model_metrics")
        if m is None:
            self.unavailable("ridership_model_metrics (needs scikit-learn to generate)", "python -m modules.ml.ridership")
        else:
            self.notice("Synthetic demonstration metrics: the model predicts simulated demand from simulated history. They do not show how it would perform on real GSRTC data.")
            t = m[(m["split"] == "test") & (m["group"] == "all") & (m["metric"].isin(["mae", "rmse", "mape_pct"]))]
            piv = t.pivot_table(index=["model", "model_label", "model_kind"], columns="metric", values="value").reset_index()
            piv["_k"] = piv["model_kind"].map({"model": 0, "baseline": 1, "forecasting_baseline": 2}).fillna(3)
            piv = piv.sort_values(["_k", "model"])
            nan = float("nan")
            self.add(self.table(["Model", "Kind", "MAE (passengers/day)", "RMSE", "MAPE"],
                                [[r["model_label"], r["model_kind"], f"{r.get('mae', nan):.1f}", f"{r.get('rmse', nan):.1f}", fmt.pct(r.get("mape_pct", nan))]
                                 for _, r in piv.iterrows()], [66 * mm, 30 * mm, 30 * mm, 24 * mm, 24 * mm], right=(2, 3, 4)))
            n = int(t["n"].iloc[0]) if len(t) else 0
            self.para(f"Held-out test rows: {n}. Lower is better. Compare each model with the baselines before reading anything into the gap.", self.small)
        self.heading("CCTV detector status", 2)
        self.para(self._cctv_text())

    def _cctv_text(self) -> str:
        try:
            from modules.analytics import cctv as CC
            st = CC.detector_output_status()
        except Exception as exc:  # noqa: BLE001 - optional module must never break the report
            return f"CCTV detector status could not be read ({type(exc).__name__}). No CCTV counts are reported here."
        if st.get("state") != "available":
            return ("Detector output: not available. No detector run has produced counts, so none are shown. The synthetic CCTV stream (cctv_counts) is a simulation "
                    "and is not detector output.")
        prov = st.get("provenance") or {}
        model = (prov.get("model") or {}).get("name", "unknown model")
        spot = st.get("spot_check") or {}
        txt = (f"Detector output: available for a separate pre-recorded clip (model {model}; source type {prov.get('source_type', 'unknown')}; "
               f"time basis {prov.get('time_basis', 'unknown')}). It is aggregate counting only, kept apart from the synthetic CCTV stream, and its figures are not "
               "reproduced in this report. See the CCTV Analytics page for the counts and their method.")
        if spot:
            txt += f" Spot-check status: {spot.get('label', 'recorded')} {spot.get('result_text', '')}"
        else:
            txt += " No manual spot-check is recorded, so the counts are not claimed to be accurate."
        return txt

    def methodology(self) -> None:
        self.add(PageBreak())
        self.heading("10. Methodology and limitations")
        for h, t in TXT.methodology():
            self.add(Paragraph(f"<b>{self.e(h)}.</b> {self.e(t)}", self.cell), Spacer(1, 1.2 * mm))
        self.heading("Limitations", 2)
        self.bullets(TXT.limitations(), self.bullet_s)

    def scale_up(self) -> None:
        self.add(PageBreak())
        self.heading("11. What a scale-up needs")
        self.para("To move from this demonstration to decisions, simulated inputs must be replaced by real ones:", self.body)
        self.add(*[Paragraph(f"<b>{self.e(h)}.</b> {self.e(t)}", self.bullet, bulletText="\u2022" if self.fonts.unicode else "-") for h, t in TXT.SCALE_UP])


# ---------------------------------------------------------------------------------------------------------------- entry points
def build_report_pdf(filters: F.Filters | None = None, tables: dict[str, pd.DataFrame] | None = None, *, now: datetime | None = None) -> bytes:
    """Build the PDF report for ``filters`` and return its bytes. ``tables`` defaults to the processed/synthetic tables on disk."""
    f = filters if filters is not None else F.Filters()
    t = tables if tables is not None else sources.load_tables()
    if "route_summary" not in t:
        raise FileNotFoundError("route_summary is missing; run `python -m modules.data_gen.generate` and `python -m modules.analytics.run` first.")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    b = _Builder(f, t, now)
    fn = b.fonts
    footer = b.tx(TXT.FOOTER)

    def on_page(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
        canvas.setFont(fn.regular, 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 9.5 * mm, footer)
        canvas.drawRightString(A4[0] - 18 * mm, 9.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
                            title="GSRTC Mobility Intelligence - pilot report (simulated data)", author="GSRTC Mobility Intelligence prototype",
                            subject=config.SIMULATION_BADGE_TEXT, invariant=1)
    doc.build(b.build(), onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the PDF report from the processed tables.")
    ap.add_argument("--out", default=str(config.PROCESSED_DIR / "reports" / "report.pdf"))
    ap.add_argument("--corridor", default=F.ALL, choices=list(F.CORRIDOR_OPTIONS))
    ap.add_argument("--day-type", default=config.PEAK_DAY_TYPE, choices=list(F.DAY_TYPES))
    ap.add_argument("--hours", nargs=2, type=int, default=[0, 24], metavar=("START", "END_EXCLUSIVE"))
    a = ap.parse_args(argv)
    try:
        data = build_report_pdf(F.Filters(a.corridor, a.day_type, a.hours[0], a.hours[1]))
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot build the report: {exc}")
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"Wrote {out} ({len(data):,} bytes). {config.SIMULATION_BADGE_TEXT}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
