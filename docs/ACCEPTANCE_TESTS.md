# Acceptance Tests and Definition of Done

## P0: core end-to-end

- [ ] Fresh environment setup and run instructions work on a clean local clone.
- [ ] One command generates all required synthetic source tables.
- [ ] Same seed produces identical source tables and derived outputs, excluding explicitly volatile metadata.
- [ ] Foreign keys resolve: trip→route, ticket→trip/stops, stops→zones, survey O-D→zones.
- [ ] No negative passenger counts, fares, capacities, distances, or operating costs.
- [ ] Formula tests cover load factor, occupancy progression, EPKM, revenue/passenger, contribution, gap index, and pricing scenario.
- [ ] Zero capacity, zero passengers, missing values, and empty tables are handled without crashes or misleading numbers.
- [ ] The planted findings are documented and detected from generated source data by calculations—not hardcoded dashboard metrics.
- [ ] A route has consistent ridership/KPIs across Overview, Route Intelligence, recommendations, and report.
- [ ] Route ranking exposes component scores and weights.
- [ ] Recommendations show evidence, assumptions, expected impact, and constraints.
- [ ] Synthetic badge is visible on every relevant page.
- [ ] CSV and PDF exports open and contain provenance and limitations.
- [ ] App starts even if optional ML/CV/LLM packages or API keys are unavailable.

## P1: mapping and ML

- [ ] Map coordinates are within the pilot bounding box or have documented exceptions.
- [ ] OSM downloads are cached and not triggered on dashboard reruns.
- [ ] Route candidate score components can be inspected.
- [ ] Model uses a documented train/test strategy and is compared with a baseline.
- [ ] Model metrics are labelled as synthetic-data demonstration metrics.
- [ ] Feature importance/SHAP appears only when calculated from a fitted compatible model.

## P2: CV and LLM

- [ ] CCTV count output includes model/method provenance and minute buckets.
- [ ] A human manually counts a clip sample; count error is calculated and reported.
- [ ] No identity or face-recognition features exist.
- [ ] If face blurring is claimed, inspect output video and document method/limitations.
- [ ] LLM features fail gracefully without a key and cache successful results.
- [ ] “Ask the Data” answers a set of supported questions and refuses unsupported ones without fabricating figures.

## Cross-page consistency checks

- [ ] Selected route ID and date filters are applied consistently.
- [ ] Demand, available capacity, gap, and recommended extra service use the same units/time window.
- [ ] Fare scenarios use the selected corridor's baseline values.
- [ ] Report totals match the current dashboard filters.
- [ ] Source/provenance labels do not confuse OSM geography with synthetic mobility observations.

## Definition of done

A person unfamiliar with the application can follow the demo narrative in 15 minutes without a crash, identify that the passenger data is simulated, understand at least one recommendation, inspect the supporting evidence, and download a report. Optional advanced modules may be unavailable only if the UI says so clearly and the core P0 workflow remains complete.
