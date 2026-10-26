# UI and Demonstration Plan

## UX principle

**Show the decision first. Show the evidence when the user wants to understand it.**

Avoid technical jargon on the first screen. Provide expandable “How this was calculated” and “Data and assumptions” sections for evaluators who want details.

## Navigation

1. Overview
2. Demand & Surveys
3. Route Intelligence
4. Demand–Supply Gaps
5. Passenger Flow & O-D
6. Competition & Pricing
7. Infrastructure & Digital
8. CCTV Analytics
9. Reports

“Ask the Data” may appear as a small optional panel on Overview or Reports; it should not be a separate dependency for the demo to work.

## Page design

Every page:
- has a clear title and one-sentence purpose;
- shows the “Simulated data for demonstration” badge when synthetic data contributes;
- shows 3–4 relevant KPIs at most;
- has one primary chart/map and one supporting view;
- has a “What this means” summary;
- links recommendations to evidence and assumptions;
- uses INR, km, and 24-hour time;
- includes a clear unavailable/empty/error state.

### Overview
- Three most important findings.
- Highest-priority recommended actions.
- Corridor selector and day-type/time filters.
- Data provenance panel.
- One map or corridor visual only if useful.

### Demand & Surveys
- Passenger demand by time/purpose.
- Private-vehicle use reasons.
- Switch conditions and willingness-to-switch scenario.
- Survey size, synthetic/live status, and limitations.

### Route Intelligence
- Ranked route list with a simple score explanation.
- Select a route to view load factor, EPKM, reliability, ridership trend, and stop sequence.
- Show actual vs model-predicted values only if a fitted model exists; otherwise use “observed synthetic demand vs baseline estimate”.

### Demand–Supply Gaps
- Hour × location heatmap.
- Gap count/index and no-service locations.
- “Add service” scenario with capacity, expected occupancy, and operating-cost assumptions.

### Passenger Flow & O-D
- Top O-D pairs, peak-hour profile, O-D matrix.
- Map arcs only if readable; table/matrix is the fallback.

### Competition & Pricing
- Departure-slot comparison.
- Fare and bus-type comparison.
- Fare elasticity what-if control with assumptions shown.
- Revenue and occupancy outcomes side by side.

### Infrastructure & Digital
- Station/depot assessment by dimension.
- Digital capability maturity.
- Ranked improvements and evidence notes.

### CCTV Analytics
- Upload/select a permitted clip.
- Show whether the detector is actually available and which model was used.
- Annotated video and per-minute aggregate counts if real processing succeeded.
- If unavailable, show a clear limitation and a sample expected-output schema; do not invent counts.

### Reports
- Generate a PDF with executive summary, findings, route recommendations, scenarios, limitations, and provenance.
- Export filtered CSVs.
- Include generation timestamp and seed.
- Provide a one-page methodology/limitations note.

## Fifteen-minute demo sequence

1. Problem and scope (1 min).
2. Passenger Flow & O-D: show commute direction and peak hour (2 min).
3. CCTV: show real detector output if available and permitted; otherwise be explicit about the fallback (2 min).
4. Demand–Supply Gaps: connect crowding/gap to service recommendation (2 min).
5. Surveys: show synthetic/private-user reasons and switching conditions (2 min).
6. Route Intelligence: show route ranking and score evidence (2 min).
7. Competition & Pricing: compare state/private illustrative service slots and fare scenario (2 min).
8. Reports / Ask the Data: generate a report and answer one supported question (1 min).
9. Scale-up path: explain replacement of synthetic inputs with approved ETM/GPS/survey/CCTV data (1 min).

Never call prerecorded video “live CCTV” or synthetic figures “actual GSRTC data”.
