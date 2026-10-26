# Milestone 3 — Dashboard and Decision Story

Build the Streamlit UI using processed tables. Follow `docs/UX_AND_DEMO.md`.

## Required pages

- Overview
- Demand & Surveys
- Route Intelligence
- Demand–Supply Gaps
- Passenger Flow & O-D
- Competition & Pricing
- Infrastructure & Digital
- CCTV Analytics
- Reports

Use a clear, restrained visual system with readable typography and meaningful spacing. Avoid technical clutter. Each page should have no more than 3–4 primary KPI cards, one main visual, one supporting visual, and a “What this means” box. Add expandable evidence and assumptions sections.

Add shared filters for corridor, day type, and date/time where applicable. Keep filter semantics consistent across pages. A map is useful only if it helps the decision; include a matrix/table fallback for O-D data.

Do not invent chart values to fill empty screens. Show a clear empty/error state. All simulated data must carry the simulation badge.

## Verification

Run the app, test every page, verify filter behavior, and compare key route KPIs with processed tables. Document any page not visually verified.
