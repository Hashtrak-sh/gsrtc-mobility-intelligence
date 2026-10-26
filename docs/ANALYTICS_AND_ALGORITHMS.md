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

M8 notes (as built):
- **Next 7 days view** (`modules/analytics/forecast_view.py`, Route Intelligence → Demand): displays `baseline_forecast` (same-weekday mean of the last 4 weeks, festival days excluded, approx. 80 % band from the pooled relative spread). The ML model is not used for future dates because its per-date inputs (`sched_trips`, `sched_seats`, `is_festival`, `private_services`) exist only for the 42 history dates.
- **Stop demand heatmap** (`modules/analytics/stop_activity.py`): boardings per average day at a stop = Σ over route, direction and departure hours in the window of `stop_occupancy.avg_boardings × trips_per_day` (alightings likewise; net = boardings − alightings). Summed over stops it equals `route_summary.boardings_per_day_<day_type>` (tested).
- **Operations replay** (`modules/analytics/replay.py`): buses in service = trips with actual start ≤ clock < start + `scheduled_minutes`; boardings so far = Σ ticket `passenger_count` with timestamp ≤ clock (tickets matched to the date via `trip_id`); on-time uses the shared reliability band (`config.RELIABILITY_ON_TIME_BAND_MIN`); crowded route-hours = `hourly_demand_supply.crowding_flag` on `route_direction` rows of the day type and hour (average day, not per date). Bus positions are interpolated along `route_stops.cum_minutes` (inbound = reverse order) and are estimates.
- **Digital roadmap** (`modules/analytics/roadmap.py`): current maturity = mean `digital_assessment.maturity_score` per capability; an initiative whose target is at or below the current maturity is dropped; priority = gap + 0.5 × number of transitive dependants; list scheduling from month 0 with at most 3 initiatives in parallel and every dependency finished first; phase follows the start month.

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

### M9: cost build-up, fare analysis and social cost-benefit (as built)

- **Cost model** (`modules/analytics/cost_model.py`): per class, trip operating cost per km = energy (diesel km/l x price, AC penalty; e-bus kWh/km x tariff) + tyres + maintenance and other running costs + crew (driver + conductor wage per hour / class reference speed from the timetable). For the 4 timetable classes, maintenance is the balancing item, so at default parameters the trip operating cost equals `OPERATING_COST_PER_KM_INR` exactly (tested). That keeps contribution on every other page unchanged. Fixed and overhead costs (not in contribution elsewhere) = depreciation ((price x (1 - residual)) / life / annual km) or lease (e-bus), insurance + MV tax + permits per km, corridor tolls per trip, a dead-km uplift on running costs, and an overhead share. Full cost = both layers. Peak crew cost x `peak_running_time_factor`, default 1.0 because the synthetic timetable has one running time per route.
- **Time bands** (`fare_analysis.classify_time_bands`): per intercity corridor x day type, a served departure hour is peak if its load factor (passenger-km / seat-km over all routes and directions) is at or above the 0.75 quantile of that group's hours and above the minimum.
- **Band economics**: per route x day type x band, from trips and tickets; revenue and trip cost summed over bands reconcile exactly with `route_kpis`. Break-even load factor = cost per trip / revenue per trip at full load; break-even fare at the current and target (0.85) load factor, for both cost layers.
- **Fares**: the differential scenario applies `scenarios.pricing_scenario` per band with separate elasticities (default peak -0.3, normal -0.7) and an optional cap at the private comparator x 0.85. Private comparator = median base fare (normal band) or median surge fare (peak band) of the mapped private class. Recommended band = [max(current fare, full-cost break-even at target load), 0.85 x private comparator]; if the floor exceeds the cap the row is flagged "not viable on fare alone". New-class what-if: the band's demand scaled by (new fare / incumbent fare)^elasticity on the chosen class's seats and costs.
- **Social CBA** (`modules/analytics/socio_economic.py`): diverted users by mode share (car, two-wheeler, private bus, shared taxi, rail, would not travel; sum to 1); vehicle-km avoided = passengers x share x trip length / occupancy; benefits = private travel cost saved net of the fare paid, rule-of-half surplus for induced travellers, travel time (negative when the bus is slower), CO2 (net of all bus-km, at a carbon price), accidents and congestion (net of the bus). BCR = (social benefits + revenue) / full cost; net social benefit = social benefits + revenue - full cost. On the page, full cost per day per route = full cost over all 42 dates / 42, the same basis as the other per-day inputs.
- All parameter defaults are illustrative orders of magnitude (`manual_demo_input`), editable on the page, and not GSRTC data.

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
- **Costs**: contribution = ticket revenue - trip operating cost (per-km rate x route km). Not profit. After the M2.5 calibration city routes lose money on ticket revenue alone and the strongest intercity corridors are near break-even; this is a property of the illustrative tariff and cost assumptions, not a finding about GSRTC.
- Run: `python -m modules.analytics.run` (about 2 s). Tests: `tests/test_analytics_*.py`.
