# Project Brief — GSRTC Mobility Intelligence

## 1. Purpose

Demonstrate a connected, explainable workflow for transport market survey and service planning using synthetic data and, where useful, real cached geography. This is a tender prototype, not a production system and not an assertion about actual GSRTC performance.

## 2. Tender scope represented

The prototype should visibly cover:
1. Passenger demand and travel behaviour.
2. Route and operations performance.
3. Revenue and commercial potential.
4. Infrastructure assessment.
5. Digital and IT systems review.
6. Stakeholder/driver/conductor/official consultation concepts.
7. Evidence-based reporting and recommendations.

## 3. Pilot boundary

- Primary corridor: Rajkot–Somnath.
- Local demonstration: a small Rajkot-area network (about 8–12 local routes).
- Long-distance demonstration: Rajkot–Somnath plus a few illustrative intercity route pairs.
- Stations/stands: a small demonstrator set, including two bus-stand locations if suitable real map features can be verified.
- CCTV: one or two short, permitted recorded clips; optional and isolated from the core app.
- All ridership, ticket, schedule, survey, service, and competitor values are synthetic.
- Other corridors can be generated as clearly named synthetic scenarios if the map/geography does not support a complete local network.

## 4. Main user

A tender evaluator or transport decision-maker who is not expected to understand ML internals. They need to understand:
- Where demand appears strongest.
- Where offered capacity may be insufficient.
- Which route/service/fare change is suggested.
- What evidence supports the suggestion.
- What assumptions could change the result.

## 5. Demo narrative

Use a planted but reproducible scenario:
1. Morning crowding at a selected bus stand.
2. Strong synthetic O-D flow to a major employment/industrial zone.
3. Survey themes suggesting that reliability, AC comfort, and frequency affect switching intent.
4. A time/location supply gap.
5. A service/frequency or route candidate recommendation.
6. A scenario result showing projected occupancy/revenue under explicit assumptions.
7. A downloadable evidence-backed report.

All planted signals must be documented in `data/synthetic/planted_findings.md` and detected by tests/analytics. The application must not separately hardcode the desired final KPI values.

## 6. Scope priorities

### P0 — must work end to end
- Reproducible synthetic data generator.
- Validated, documented shared schema.
- Overview dashboard.
- Demand, route KPIs, hourly gaps, O-D analysis.
- Transparent route scoring and evidence.
- Competition/fare comparison with synthetic data.
- Simple service and pricing scenario calculators.
- CSV and PDF export.
- Tests and reliable local launch.

### P1 — implement after P0 is stable
- Real map context and bounded route candidates using cached OSM geography.
- Explainable baseline ML ridership model, with evaluation and feature importance.
- Survey themes and switch-probability scenario.
- Infrastructure/digital maturity assessment.

### P2 — optional if time and hardware permit
- YOLO/OpenCV CCTV count pipeline and annotated clip.
- Prophet forecast with interval and documented synthetic-data limitations.
- H3 spatial grid.
- SHAP explanations for a real fitted compatible model.
- Optional LLM “Ask the Data” and theme summarisation.
- Hosted demo deployment.

No P0 requirement should be sacrificed to force a P2 library into the build.
