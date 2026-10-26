# Master Build Prompt — GSRTC Mobility Intelligence

Paste this into Claude Code after placing this file and the companion project documents in the repository. It defines the overall mission; use the milestone prompts for actual implementation.

---

You are the lead engineer and technical planner building **GSRTC Mobility Intelligence**, a polished, local-first tender demonstration for a professional market survey and bus mobility planning workflow.

## Mission

Build an end-to-end working prototype that demonstrates the approved survey scope through a coherent, evidence-backed story. The main pilot is the Rajkot–Somnath corridor, supported by a small Rajkot-area local network and a few additional synthetic intercity corridors. Use real geography only where it can be fetched and cached reliably; passenger, ticketing, ridership, survey, operations, and competitor values are synthetic unless explicitly marked otherwise.

The app must be useful to a nontechnical client. Show the decision first, then make the evidence inspectable. Do not optimise for maximum feature count at the expense of a reliable, connected workflow.

## Required experience

Create a Streamlit dashboard with these modules:

1. **Executive Overview** — key findings, route/service recommendations, demand-supply alerts, data provenance.
2. **Demand & Surveys** — passenger demand, user/non-user survey findings, reasons for private vehicle use, willingness-to-switch conditions, optional LLM theme summaries.
3. **Route Intelligence** — route performance, load factor, passenger density/occupancy progression, EPKM, revenue per passenger/km, schedule reliability, route potential ranking, corridor map, evidence behind each score.
4. **Demand–Supply Gaps** — hour-by-location heatmap, overcrowded route-hours, unmet demand and recommended additional services.
5. **Passenger Flow & O-D** — origin-destination matrix, directional/peak-hour patterns, boarding/alighting progression, flow map where practical.
6. **Competition & Pricing** — state vs synthetic private services, departure slots, fare/bus-type comparison, review themes, transparent fare/demand scenarios.
7. **Infrastructure & Digital** — station/depot facility assessment and digital/IT maturity, gaps and prioritised improvements.
8. **CCTV Analytics (optional isolated module)** — process 1–2 permitted sample clips, aggregate person/vehicle counts and direction/line crossings, annotated output where a real detector is available. No face recognition or identity tracking.
9. **Reports** — downloadable PDF and CSV outputs that summarise findings, recommendations, assumptions, and provenance.
10. **Ask the Data (optional LLM)** — answer questions only from available processed summaries; no unsupported claims. The core app must work without an LLM key.

Keep the approved tender scope visible: passenger demand, route/operations analysis, revenue/commercial potential, infrastructure assessment, digital/IT systems review, stakeholder consultations, evidence-based reporting. Do not replace these with a narrower app.

## Central demonstration story

The application should be able to demonstrate a scenario such as:
- Synthetic CCTV counts indicate crowding at a selected bus stand during the morning peak.
- Synthetic ticket/O-D patterns indicate a strong flow toward an employment/industrial area.
- Synthetic survey answers indicate that reliability, AC comfort, and frequency are important switching conditions for some private-vehicle users.
- The demand-supply module identifies the time/location gap.
- Route intelligence proposes a bounded service/frequency change.
- A scenario calculator estimates occupancy and revenue effects from explicit assumptions.
- The report explains the recommendation and links it to evidence.

The scenario is a planted synthetic demonstration, not a real-world finding. Plant it transparently in `data/synthetic/planted_findings.md`; test that analytics detect it. Never hardcode the resulting chart values separately from source data.

## Technical direction

- Python 3.11, Streamlit, pandas, NumPy, DuckDB, PyArrow, Plotly.
- NetworkX/OSMnx for small, cached routing/network analysis where practical.
- GeoPandas/Shapely and/or pydeck for maps only where needed.
- scikit-learn for a simple explainable baseline. XGBoost/SHAP, Prophet, H3, OpenCV/YOLO, and LLM calls are enhancements, not prerequisites for the first end-to-end flow.
- Parquet tables under `data/`; processed outputs under `data/processed/`.
- Fixed seed in `config.py`; all demo data generation and derived analytics must be reproducible.
- Local-first; do not make deployment or internet access a blocker. If a hosted demo is attempted, preserve an offline local copy.
- Use a single clear Streamlit entry point.

## Core analytics

Implement and test deterministic calculations first:
- load factor = passenger load / available seats × 100
- occupancy progression = previous occupancy + boardings − alightings
- EPKM = ticket revenue / vehicle-kilometres, with clearly stated aggregation level
- revenue per passenger and revenue per km
- schedule adherence/reliability using a documented definition
- hourly demand vs offered capacity and a gap index
- route potential score with normalised inputs, configurable weights, and visible component breakdown
- pricing what-if using an explicit elasticity assumption; display assumptions and sensitivity, not a single supposedly certain forecast
- service-frequency scenario constrained by fleet/capacity, operating cost, and minimum-service/social importance where those fields exist.

Do not call a score a prediction. A model forecast must be separate from a transparent rule-based ranking. Avoid overclaiming accuracy on synthetic data.

## Engineering rules

Follow `CLAUDE.md`, `RULES.md`, and the documentation under `docs/`. Use milestone prompts in order. First create a runnable scaffold and schema, then synthetic data, then deterministic analytics, then UI, then route/pricing features, then optional CV/LLM/advanced ML, then reporting and final validation.

For every milestone:
1. Inspect the current repository.
2. Implement only that milestone and necessary fixes.
3. Run tests and/or validation commands.
4. Fix failures instead of just reporting them.
5. Keep the app runnable.
6. Report what was actually verified, limitations, and the next milestone.

## Definition of done

- Fresh local setup is documented and works.
- Every page clearly labels synthetic data.
- One reproducible data-generation command creates all core source tables.
- KPIs are derived from source data and consistent across pages.
- The central demo story is traceable from input tables to calculations to recommendation to report.
- Route rankings explain their score.
- Pricing and service scenarios expose assumptions and constraints.
- Tests cover formulas, reproducibility, and key cross-table invariants.
- Optional modules fail gracefully; no fake CV or LLM outputs.
- PDF/CSV exports work.
- No secrets are committed.
- The README describes actual capabilities and limitations, not aspirational features.

Start by reading the project files and executing `prompts/00_BOOTSTRAP.md`. Do not attempt the entire app in one pass.
