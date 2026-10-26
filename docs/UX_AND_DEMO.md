# UI and Demonstration Plan

## UX principle

**Show the decision first. Show the evidence when the user wants to understand it.**

Avoid technical jargon on the first screen. Provide expandable “How this was calculated” and “Data and assumptions” sections for evaluators who want details.

## Navigation

1. Overview
2. Operations Replay (M8; simulated, not live)
3. Demand & Surveys
4. Route Intelligence
5. Demand–Supply Gaps
6. Passenger Flow & O-D
7. Competition & Pricing
8. Cost-Benefit & Fares (M9)
9. Infrastructure & Digital
10. CCTV Analytics
11. Reports

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

### Operations Replay (M8)
- Replays one synthetic service day hour by hour (date picker, clock slider, Play/Pause with speed) to show how a real-time operations view would look once ETM and AVL feeds exist.
- Four KPIs at the clock: buses in service, boardings so far, departures on time, crowded route-hours; map of stops (sized by last-hour boardings) and estimated bus positions; cumulative boardings line; computed alerts.
- Prominent "Simulated replay - not live" banner; nothing is streamed. Crowding comes from the average-day table, so it varies with day type and hour, not the date.

### Demand & Surveys
- Passenger demand by time/purpose.
- Private-vehicle use reasons.
- Switch conditions and willingness-to-switch scenario.
- Survey size, synthetic/live status, and limitations.

### Route Intelligence
- Ranked route list with a simple score explanation.
- Select a route to view load factor, EPKM, reliability, ridership trend, and stop sequence.
- Show actual vs model-predicted values only if a fitted model exists; otherwise use “observed synthetic demand vs baseline estimate”.
- M8: "Next 7 days (baseline estimate)" in the Demand tab: last 21 observed days, then the seasonal-average baseline with its approx. 80 % band (`baseline_forecast`). Labelled as a baseline, not the ML model (the model's per-day inputs such as the timetable do not exist for future dates).

### Demand–Supply Gaps
- Hour × location heatmap.
- Gap count/index and no-service locations.
- “Add service” scenario with capacity, expected occupancy, and operating-cost assumptions.

### Passenger Flow & O-D
- Top O-D pairs, peak-hour profile, O-D matrix.
- Map arcs only if readable; table/matrix is the fallback.
- M8: geographic demand heatmap: stop boardings / alightings / net per average day as a density layer plus bubbles on the OpenStreetMap base, Rajkot-city or whole-network view, following the page's day-type and hour filters. Stop positions are real or OSM-offset; passenger values are simulated.

### Competition & Pricing
- Departure-slot comparison.
- Fare and bus-type comparison.
- Fare elasticity what-if control with assumptions shown.
- Revenue and occupancy outcomes side by side.

### Cost-Benefit & Fares (M9)
- Intercity only. Cost per bus-km for 7 classes (ordinary, express, AC seater, AC sleeper; Volvo multi-axle AC, non-AC sleeper and e-bus as what-if only) split into trip operating costs (energy, tyres, maintenance and other running, crew) and fixed and overhead costs (depreciation or lease, insurance/tax/permits, tolls, dead km, overhead), with editable illustrative assumptions.
- Peak vs normal hours derived from the data (load factor quantile per corridor and day type) with per-trip and per-seat-km economics.
- Break-even fare and load factor, private-fare comparison and a recommended fare band per class and band (or an honest "not viable on fare alone" flag); peak/off-peak fare scenario with separate elasticities; new-bus what-if.
- Illustrative social cost-benefit appraisal (diverted private travel, time, CO2, accidents, congestion) with benefit-cost ratio per corridor and a sensitivity tornado.

### Infrastructure & Digital
- Station/depot assessment by dimension.
- Digital capability maturity.
- Ranked improvements and evidence notes.
- M8: digital transformation roadmap: Gantt of initiatives over 36 months in three phases (Foundation 0-6, Scale 6-18, Optimise 18-36), scheduled from the maturity gaps and initiative dependencies. The initiative catalogue, durations, targets and KPIs are authored demo assumptions (`manual_demo_input`), not GSRTC plans.

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
