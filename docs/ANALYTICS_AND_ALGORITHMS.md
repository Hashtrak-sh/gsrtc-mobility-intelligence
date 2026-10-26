# Analytics and Algorithm Notes

All formula outputs must be tested. Show assumptions and definitions in the UI or report. The synthetic data generator should create coherent records, and all dashboard metrics should derive from those records.

## 1. Core route KPIs

- **Load factor (%)** = passenger load / available seats × 100. Define the aggregation level: trip, route-hour, or route-day. Do not average percentages without explaining the weighting.
- **Occupancy progression** = previous occupancy + boardings − alightings. Clamp only if a documented data-quality rule is applied; otherwise flag impossible negative/over-capacity results.
- **EPKM (₹/vehicle-km)** = ticket revenue / vehicle-kilometres. State whether revenue includes only ticket sales or other revenue.
- **Revenue per passenger (₹)** = ticket revenue / passenger count.
- **Contribution (₹)** = included revenue − included operating costs. Do not call it profit unless all relevant cost categories are included.
- **Reliability**: define a consistent measure, e.g. percentage of trips departing within a stated tolerance of schedule. Synthetic on-time records must be generated if this KPI is shown.

## 2. Demand-supply gap

At each route-hour or location-hour:
- `gap_count = max(0, demand_estimate - seats_offered)`
- `gap_index = demand_estimate / seats_offered` where seats offered > 0.
- Flag potential crowding when the index exceeds a configurable threshold such as 1.0 or 1.2.
- When seats offered are zero, show “no scheduled capacity” rather than dividing by zero.
- Recommendations should identify the corridor, time window, estimated gap, suggested service count, capacity assumption, and expected post-change load factor.

## 3. Route potential score

Use a transparent normalised score (0–100), not an opaque label called “AI”. Candidate components:
- demand potential: 25%
- unmet demand: 20%
- load factor/crowding: 15%
- reliability improvement opportunity: 10%
- revenue potential: 10%
- social importance/minimum-service value: 10%
- operational feasibility: 10%

These are initial demo weights, not validated policy. Put weights in config and show component scores. Normalise each input using a documented method, handle missing values explicitly, and version the weight set. A route with low commercial performance must not automatically be recommended for removal if it is marked as an essential/minimum-service route.

## 4. Forecasting

P0: deterministic historical/hourly baseline or rolling average. P1/P2: scikit-learn or Prophet if the data and schedule allow it.
- Do not claim Prophet can be trained meaningfully on a few synthetic weeks without caveat.
- Use a time-based holdout where possible.
- Show baseline comparison and error metrics (MAE/RMSE) if actual held-out values exist.
- A festival regressor may be demonstrated, but label the effect as synthetic and illustrative.
- Never present synthetic test performance as evidence of real-world predictive accuracy.

## 5. Ridership potential model

Start with a simple, explainable baseline (e.g. RandomForest/HistGradientBoosting or a regularised model) and compare against a naïve baseline. Use a train/test split that avoids leakage between near-duplicate records where feasible.
- Target: route-day boardings or route-hour demand.
- Candidate features: catchment population/jobs, route length, service frequency, seat capacity, bus type, nearby POIs, competing-service count, day type, hour.
- Do not include target-derived features that leak the answer.
- Report target definition, split method, baseline, metrics, and feature importance.
- Use SHAP only if supported by the fitted model; otherwise show permutation importance or score decomposition.

## 6. O-D analysis

Aggregate ticket origins/destinations into zone pairs and time windows. If a ticket has only a stop pair, map stops to zones via the shared schema. Display top O-D pairs and hourly patterns. Use flow arcs only when they remain legible; offer a matrix/table fallback.

## 7. Pricing scenario

Use a transparent elasticity formula:
`estimated_demand_new = baseline_demand * (new_fare / baseline_fare) ** elasticity`

Elasticity must be configurable and visible; it is normally negative. This is a scenario assumption, not a fitted real-world fact. Recalculate revenue, occupancy, and included costs under the scenario. Show sensitivity across a small range of elasticity values. Enforce sensible fare/capacity bounds.

## 8. Service-frequency scenario

Estimate required departures from projected peak demand and target load factor:
`required_departures = ceil(projected_passengers / (seats_per_bus * target_load_factor))`

Then compare incremental vehicle-km and operating cost. Account for existing fleet/available buses if the synthetic data supports it. Never promise operational feasibility if driver, vehicle, turnaround, and depot constraints are not modelled. Label the result “illustrative service scenario”.

## 9. Competitiveness

- State vs private departures/seats by hour.
- Fare index = state fare / median private fare; values below 1 indicate the state fare is lower than the private median.
- Premium bus type gap, departure-time gaps, and synthetic review themes.
- Clearly label all private competitor services/fares/reviews as synthetic or manually curated demo inputs. Do not scrape booking sites or imply live competitor pricing.

## 10. Surveys and mode choice

- Use descriptive distributions before fitting a model.
- A logistic model can illustrate switching probability if synthetic survey labels are generated with a documented mechanism.
- Report that probability is conditional on the synthetic training setup, not a validated forecast of real private-vehicle users.
- Theme tagging may be deterministic for the no-API baseline; LLM summaries are optional, cached, and marked as machine-generated.
- Live QR collection should be optional. If included, state where responses are stored and avoid collecting unnecessary personal data.

## 11. CCTV

- Count crossings/aggregate objects per time interval; never identify people.
- Validate on a manually counted sample clip and report the sample, tolerance, and observed error.
- Blur faces/upper-body regions only if the implementation actually does so. Person-box blurring is not equivalent to reliable face anonymisation; do not overstate it.
- CV results are a separate evidence stream and must not be silently merged with synthetic ticket data as if they were measured in the same period.

## M2 implementation notes (as built; `modules/analytics/`)

- **Load factors are named, not overloaded.** `peak_load_factor` = max link onboard / seats (trip; seat-weighted for route-hours; <= 1.6 local, <= 1.0 intercity). `load_factor_pct` = passenger-km / seat-km x 100 (route-day / route). `boardings_per_seat` = passenger turnover, a supporting metric only.
- **Reliability** = % of trips with -1 <= departure delay <= +5 min (`config.RELIABILITY_ON_TIME_BAND_MIN`), ratio of sums; missing delays excluded.
- **Gap table** is per average day of a day type, uses the critical-link load as demand, and is censored at capacity, so gaps are lower bounds. Intercity corridor-hours add a private-market proxy (competitor seats x assumed occupancy 0.75, `config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION`) against STATE seats; hours without state seats are `no_scheduled_capacity` (gap_index null).
- **Route score**: min-max within `route_type`, social importance rule-based, feasibility a proxy, missing components re-weighted; see `modules/analytics/scoring.py`.
- **Scenarios** (`modules/analytics/scenarios.py`): `service_frequency_scenario`, `pricing_scenario`, `pricing_sensitivity`; pure functions shared by the batch runner and the UI.
- **Costs**: contribution = ticket revenue - trip operating cost (per-km rate x route km). Not profit. Under the illustrative demo tariff and cost rates every route has negative contribution; this is a property of the synthetic assumptions, not a finding about GSRTC.
- Run: `python -m modules.analytics.run` (about 2 s). Tests: `tests/test_analytics_*.py`.
