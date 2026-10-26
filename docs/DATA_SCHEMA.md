# Shared Data Schema

This file is the data contract. Before adding or renaming a column, update this document, the generator, all consumers, and tests in one change.

All source tables are stored as Parquet under `data/synthetic/`. Derived tables are stored under `data/processed/`. Column names use `snake_case`; timestamps use ISO-compatible datetime values; times are local to the synthetic scenario unless a timezone is explicitly included.

## Source tables

### `zones`
| Column | Type | Meaning |
|---|---|---|
| `zone_id` | string | Stable zone identifier |
| `h3_id` | string/null | H3 cell if the H3 enhancement is enabled |
| `name` | string | Human-readable zone name |
| `lat`, `lon` | float | Representative point |
| `population` | integer | Synthetic resident population estimate |
| `workers_resident` | integer | Synthetic resident workers |
| `jobs` | integer | Synthetic jobs/employment proxy |
| `poi_counts` | JSON/string | Counts by POI type, or use a documented long-form companion table |
| `zone_type` | string | residential / employment / mixed / education / religious / other |
| `source_type` | string | synthetic / openstreetmap / manual_demo_input |
| `seed` | integer | Generation seed for synthetic values |
| `coord_source` | string | **(M1)** Provenance of `lat`/`lon`: `openstreetmap` (exactly the cached OSM value), `openstreetmap_offset` (OSM anchor + fixed hand-entered offset, i.e. a synthetic point near a real place) or `manual_demo_input` (hand-entered approximation used when the OSM cache is missing/unmatched). Never OSM-labelled unless it came from the cache. |

Zones are synthetic demo entities (`source_type = synthetic`; population/jobs/POIs are synthetic); only the coordinate may be real. `h3_id` is null (H3 not enabled). Zones Z01-Z14 are Rajkot-area localities (Z01 = Rajkot Central/Bus Port, Z11-Z13 = employment/industrial estates); Z15-Z22 are one zone per intercity town.

### `stops`
| Column | Type | Meaning |
|---|---|---|
| `stop_id` | string | Stable stop ID |
| `name` | string | Display name |
| `lat`, `lon` | float | Coordinates |
| `zone_id` | string | Related zone |
| `is_bus_stand` | boolean | Whether this is a stand/station in the demo |
| `stop_type` | string | local_stop / bus_stand / intercity_terminal |
| `source_type` | string | Entity provenance: `openstreetmap` only for real OSM bus stations/stands used as-is; `manual_demo_input` for fallback coordinates; otherwise `synthetic` (demo stops placed near real places) |
| `coord_source` | string | **(M1)** Same enum as `zones.coord_source` |

### `routes`
| Column | Type | Meaning |
|---|---|---|
| `route_id` | string | Stable route ID |
| `name` | string | Display name |
| `route_type` | string | local / intercity |
| `origin_stop_id` | string | Origin stop |
| `destination_stop_id` | string | Destination stop |
| `stop_sequence` | JSON/string | Ordered stop IDs |
| `length_km` | float | Route distance in km |
| `bus_type` | string | ordinary / express / AC_seater / AC_sleeper / other |
| `minimum_service` | boolean | Protects essential service in recommendations |
| `source_type` | string | synthetic / openstreetmap / manual_demo_input |
| `corridor` | string/null | **(M1)** Corridor key for intercity routes (`Rajkot-Somnath`, `Rajkot-Junagadh`, `Rajkot-Jamnagar`, `Rajkot-Ahmedabad`); null for local routes. Joins to `competitor_services.route_pair` and `reviews.route_pair`. |

`stop_sequence` is a JSON list of stop IDs in OUTBOUND order (identical to `route_stops` order). All routes are **synthetic demonstration routes** (names end in "(demo)"), not real GSRTC/RMTS routes. One route = one bus type; a corridor can have several routes (e.g. Rajkot-Somnath express / AC_seater / AC_sleeper). `length_km` = sum of straight-line stop-to-stop distance x road factor (local 1.35, intercity 1.15), see `modules/data_gen/constants.py`. `minimum_service = true` marks the two essential low-ridership routes (L09, L10).

### `route_stops` (new in M1)
| Column | Type | Meaning |
|---|---|---|
| `route_id` | string | Route foreign key |
| `stop_seq` | integer | 1-based position in OUTBOUND order |
| `stop_id` | string | Stop foreign key |
| `cum_km` | float | Cumulative km from the origin (outbound frame) |
| `cum_minutes` | float | Scheduled minutes from origin departure to arrival at this stop (outbound frame; includes dwell) |

For an INBOUND trip the position of stop `k` is `n_stops + 1 - stop_seq`, `cum_km_inbound = length_km - cum_km` and `cum_minutes_inbound = trips.scheduled_minutes - cum_minutes`. A ticket is valid only if its boarding position is strictly before its alighting position in the trip's direction. Occupancy after a stop = previous occupancy + boardings - alightings.

### `trips`
| Column | Type | Meaning |
|---|---|---|
| `trip_id` | string | Stable trip ID |
| `route_id` | string | Route foreign key |
| `service_date` | date | Synthetic service date |
| `departure_time` | string | Local HH:MM |
| `day_type` | string | weekday / weekend / festival |
| `seats` | integer | Available seats |
| `operator` | string | state / private |
| `bus_type` | string | ordinary / express / AC_seater / AC_sleeper |
| `scheduled_minutes` | float | Planned trip duration |
| `operating_cost_inr` | float | Synthetic cost for the trip |
| `source_type` | string | Provenance |
| `direction` | string | **(M1)** `outbound` (route `stop_sequence` order) / `inbound` (reverse) |
| `actual_departure_time` | string | **(M1)** Local HH:MM of the synthetic actual departure (`departure_time` + delay, rounded to the minute; clipped before midnight) |
| `departure_delay_min` | float | **(M1)** Synthetic departure delay in minutes, negative = early. Suggested on-time tolerance: `DELAY_ON_TIME_TOLERANCE_MIN = 5` (`modules/data_gen/constants.py`); define reliability as the share of trips with delay <= tolerance |

Every trip in this table is a **state (GSRTC demonstration) service** with tickets (`operator = state`); private competitor supply lives only in `competitor_services`. `seats` come from `BUS_TYPE_SEATS` (ordinary 40, express 45, AC_seater 40, AC_sleeper 30). `operating_cost_inr = OPERATING_COST_PER_KM_INR[bus_type] x routes.length_km` (M2.5 calibration: ordinary 52, express 46, AC_seater 54, AC_sleeper 60 INR/vehicle-km; illustrative assumptions). **Standing rule:** local ordinary buses allow standees up to `LOCAL_CRUSH_FACTOR = 1.6 x seats` onboard; intercity reserved buses never exceed `seats`. `boardings / seats` is called **boardings per seat** (passenger turnover; it can exceed 1.6 on local routes where passengers board and alight along the route) and is NOT a load factor. Load factors are defined in the derived-table section below (`peak_load_factor`, `load_factor_pct`). For intercity, excess latent demand is unmet and NOT ticketed (it is visible only indirectly, e.g. in `cctv_counts`).

### `tickets`
| Column | Type | Meaning |
|---|---|---|
| `ticket_id` | string | Unique synthetic ticket ID |
| `trip_id` | string | Trip foreign key |
| `origin_stop_id` | string | Boarding stop |
| `dest_stop_id` | string | Alighting stop |
| `timestamp` | datetime | Boarding timestamp = trip actual departure (service date + `departure_time` + exact delay) + `cum_minutes` of the boarding stop (direction-aware) + 0-59 s jitter |
| `fare_inr` | float | Total fare paid for the ticket (all `passenger_count` passengers), INR. Per passenger = max(min_fare, base + per_km x km) rounded, x concession (`FARE_TABLE`, `CONCESSION_FACTOR` in `modules/data_gen/constants.py`: student 0.5, senior 0.5, other 0.75, adult 1.0). Illustrative demo tariff, NOT an actual GSRTC tariff |
| `passenger_type` | string | adult / student / senior / other |
| `passenger_count` | integer | 1 for ~98% of tickets; same-OD adult/other tickets are sometimes merged into group bookings of 2-4. Passengers = `sum(passenger_count)` |
| `source_type` | string | synthetic |

### `cctv_counts`
| Column | Type | Meaning |
|---|---|---|
| `location_id` | string | Camera/zone label; not a person identifier |
| `timestamp_min` | datetime | Minute bucket |
| `direction` | string | inbound / outbound / unknown |
| `class` | string | person / car / two_wheeler / auto / bus / truck / other |
| `count` | integer | Aggregate count in bucket (>= 0) |
| `measurement_method` | string | actual_detector / manual_demo_input / synthetic |
| `source_type` | string | Provenance |

M1 generates **synthetic** counts only (`measurement_method = synthetic`) at `location_id` in {`S01` Rajkot Central Bus Stand, `S31` Junagadh Bus Stand, `S34` Somnath Bus Stand} (these are stop IDs). `timestamp_min` is the START of a **5-minute bucket** (05:00-22:55); classes `person` and `bus`; directions `inbound` / `outbound` (entering / leaving the stand). Real detector output from M6 is a separate stream and must not be merged with this one.

**M6-CCTV `cctv_detector_counts`** (processed layer, separate from `cctv_counts`; written by `python -m modules.cv.count_video`): `location_id`, `timestamp_min`, `clip_minute`, `direction`, `class`, `count`, `measurement_method = actual_detector`, `source_type`, `time_basis = clip_relative`. Minute buckets of **clip time**: `timestamp_min` = 1970-01-01 00:00 + clip offset (a reference, NOT a recording date; `clip_minute` is the integer minute). Zeros are explicit. No track ids or any person-level column. Provenance sidecar `cctv_detector_counts.provenance.json` (model, weights hash, versions, thresholds, stride, line config, clip hash, segment, timings).

### `survey_responses`
| Column | Type | Meaning |
|---|---|---|
| `response_id` | string | Synthetic or anonymous response ID |
| `timestamp` | datetime | Response time |
| `current_mode` | string | car / two_wheeler / bus / rail / shared_taxi / other |
| `trip_purpose` | string | work / education / shopping / health / leisure / other |
| `origin_zone_id`, `dest_zone_id` | string | O-D zone references |
| `reasons` | JSON/string | Structured reasons for current mode |
| `open_text` | string | Synthetic response text or consented anonymous text |
| `switch_conditions` | JSON/string | Conditions that might trigger a switch |
| `income_band` | string | Synthetic broad band; optional |
| `switch_intent` | integer/null | Synthetic response target, 0/1; null for respondents who do not use a private mode (bus, rail). Generated by the logistic mechanism documented in `data/synthetic/planted_findings.md` |
| `source_type` | string | synthetic / live_demo_response |

### `competitor_services`
| Column | Type | Meaning |
|---|---|---|
| `service_id` | string | Stable service ID |
| `route_pair` | string | Corridor key |
| `operator` | string | Synthetic operator label |
| `departure_time` | string | Local HH:MM |
| `day_type` | string | weekday / weekend / festival |
| `bus_type` | string | ordinary / AC_seater / AC_sleeper / premium |
| `base_fare_inr` | float | Synthetic fare |
| `surge_fare_inr` | float | Synthetic illustrative peak fare |
| `seats` | integer | Capacity |
| `rating` | float/null | Synthetic rating |
| `source_type` | string | synthetic / manual_demo_input |

### `reviews`
| Column | Type | Meaning |
|---|---|---|
| `review_id` | string | Stable review ID |
| `operator_type` | string | state / private |
| `route_pair` | string | Corridor key (as `routes.corridor`; state-only local reviews use `Rajkot-Local`) |
| `rating` | float | Synthetic rating |
| `text` | string | Synthetic review text |
| `themes` | JSON/string | JSON list of `{"theme": <theme>, "polarity": "positive" or "negative"}`; tagged at generation time (method: synthetic template, recorded in provenance). Themes: punctuality, cleanliness, comfort_ac, staff_behaviour, booking_ease, safety, value |
| `sentiment` | string/null | Optional tagged sentiment |
| `source_type` | string | synthetic / manual_demo_input |

### `assets_assessment`
| Column | Type | Meaning |
|---|---|---|
| `asset_id` | string | Station/depot/stop asset ID |
| `asset_name` | string | Display name |
| `asset_type` | string | station / depot / stop |
| `dimension` | string | cleanliness / accessibility / safety / amenities / digital / other |
| `score` | float | Assessment score on documented 0–5 scale |
| `evidence_note` | string | Synthetic or manually supplied note |
| `source_type` | string | synthetic / manual_demo_input |

### `digital_assessment`
| Column | Type | Meaning |
|---|---|---|
| `assessment_id` | string | Stable record ID |
| `asset_id` | string | Related asset |
| `capability` | string | e-ticketing / live tracking / passenger information / payments / analytics / other |
| `maturity_score` | float | Documented 0–5 scale |
| `evidence_note` | string | Synthetic or manually supplied note |
| `source_type` | string | synthetic / manual_demo_input |

## Derived tables

### Load-factor and KPI definitions (M2; names are explicit on purpose)
| Measure | Level | Definition |
|---|---|---|
| `peak_load_factor` | trip (and seat-weighted for route-hours) | max onboard on any link / seats. At most 1.6 on local buses (standing allowed), 1.0 on intercity |
| `load_factor_pct` | route-day (`route_kpis`) and route (`route_summary`) | passenger-km / seat-km x 100, seat-km = sum(seats x route `length_km`) over the trips; ratios of sums, never averaged percentages |
| `boardings_per_seat` | trip / route / route-day | `sum(passenger_count)` / seats: passenger turnover, a supporting metric, NOT a load factor |
| `epkm_inr` | route-day / route | **ticket** revenue / vehicle-km (no subsidy, advertising or other income) |
| `revenue_per_passenger_inr` | route-day / route | ticket revenue / `sum(passenger_count)` |
| `contribution_inr` | route-day / route | ticket revenue - trip `operating_cost_inr`. NOT profit: depot overheads, staff, depreciation, taxes, subsidy are not in the cost model |
| `reliability_pct` | route-day / route | % of trips with -1 <= `departure_delay_min` <= +5 (inclusive; `config.RELIABILITY_ON_TIME_BAND_MIN`). Missing delays are excluded; none -> NaN |
| `mean_delay_min` | route-day / route | mean `departure_delay_min` |

### `route_kpis` (route x service_date; 672 rows)
Contract columns: `route_id`, `service_date`, `boardings`, `estimated_passenger_km`, `vehicle_km`, `ticket_revenue_inr`, `operating_cost_inr`, `available_seats`, `load_factor_pct`, `epkm_inr`, `revenue_per_passenger_inr`, `contribution_inr`, `reliability_pct`, `source_type`, `assumptions_json`.
Added in M2: `day_type`, `trips`, `seat_km`, `mean_delay_min`, `boardings_per_seat`, `peak_load_factor_max` (max trip peak load factor that day). Reconciles with the sources: `sum(ticket_revenue_inr) = sum(tickets.fare_inr)`, `sum(boardings) = sum(tickets.passenger_count)`, `vehicle_km = sum(trips x route length_km)`.

### `route_summary` (new in M2; one row per route; single source of truth for route KPIs)
`route_id`, `name`, `route_type`, `corridor`, `bus_type`, `length_km`, `minimum_service`, `trips`, `boardings`, `estimated_passenger_km`, `vehicle_km`, `seat_km`, `ticket_revenue_inr`, `operating_cost_inr`, `available_seats`, `load_factor_pct`, `epkm_inr`, `revenue_per_passenger_inr`, `contribution_inr`, `reliability_pct`, `mean_delay_min`, `boardings_per_seat`, `peak_load_factor_max`, `boardings_per_day_weekday`, `boardings_per_day_weekend`, `boardings_per_day_festival` (total passengers of the day type / number of service dates of that type), `avg_boardings_per_day`, `revenue_per_day_inr`, `contribution_per_day_inr`, `trips_per_day_weekday`, `peak_hour`, `peak_hour_window`, `peak_hour_load_factor` (weekday departure hour with the highest seat-weighted peak load factor, both directions), `source_type`, `assumptions_json`. Computed from trip-level sums, never by averaging percentages.

### `hourly_demand_supply`
Contract columns: `zone_id`, `location_id`, `service_date`, `hour`, `demand_estimate`, `seats_offered`, `gap_count`, `gap_index`, `crowding_flag`, `source_type`, `assumptions_json`.
Added in M2: `level` (`route_direction` | `corridor`), `route_id` (null on corridor rows), `corridor`, `direction`, `day_type`, `status` (`ok` | `crowded` | `at_capacity` | `no_scheduled_capacity`), `trips_per_day`, `ticketed_boardings_per_day`, `state_demand`, `private_seats`, `private_demand_proxy`, `private_departures` (the last four only on corridor rows).
Semantics (M2): **`service_date` is null** because every value is for the *average service day* of `day_type` (sum over that day type's dates / number of dates). `hour` = clock hour of departure.
* `route_direction` rows: `demand_estimate` = average-day sum over trips departing in the hour of the **critical-link onboard load**; `seats_offered` = average-day sum of their seats; `location_id` = stop where the average bus is fullest, `zone_id` its zone. Ticketed demand is **censored** at capacity (crush / seats), so `gap_count`/`gap_index` are **lower bounds**. Hours inside a route's service span (first..last departure of the direction/day type) with no departure get `seats_offered = 0`, `status = no_scheduled_capacity` and null demand/gap (demand is not observable without service).
* `corridor` rows (intercity, outbound departures from the origin terminal = `location_id`): `demand_estimate = state_demand + private_demand_proxy`, where the proxy = competitor seats departing in the hour x `config.PRIVATE_MARKET_OCCUPANCY_ASSUMPTION` (0.75; an assumption, labelled in `assumptions_json`). `seats_offered` = **state** seats only. No state seats -> `gap_index` null, `status = no_scheduled_capacity`, `gap_count` = the proxy demand. `crowding_flag` on corridor rows is based on state buses only (state load / state seats).
* `gap_count = max(0, demand_estimate - seats_offered)`, `gap_index = demand_estimate / seats_offered` where seats > 0, `crowding_flag = gap_index > config.CROWDING_GAP_INDEX_THRESHOLD` (1.2), `at_capacity` = intercity gap_index >= `config.AT_CAPACITY_LOAD_FACTOR` (0.95).

### `stop_occupancy` (new in M2)
`route_id`, `direction`, `day_type`, `hour`, `stop_seq` (route_stops outbound frame), `position` (in direction of travel), `stop_id`, `n_trips`, `trips_per_day`, `avg_boardings`, `avg_alightings`, `avg_onboard` (all per trip; onboard = load on the link leaving the stop), `seats` (mean per trip), `onboard_pct` (avg_onboard / seats x 100), `max_onboard`, `negative_flag`, `over_capacity_flag` (any trip in the group has an impossible value; values are flagged, never clamped), `source_type`. Progression: `onboard_after = previous + boardings - alightings`.

### `od_flows`
Contract columns: `origin_zone_id`, `dest_zone_id`, `hour`, `passenger_count`, `estimated_passenger_km`, `source_type`.
Added in M2: `day_type`, `passengers_total`, `passenger_km_total`, `n_days`, `is_intra_zone`. `hour` = boarding hour (ticket `timestamp`); `passenger_count` and `estimated_passenger_km` are **per average day of the `day_type`** (= totals / `n_days`); passenger-km = passengers x route km between the boarding and alighting stop.
Added in M5: `route_id` and `corridor` (the route's `routes.corridor`, null for local routes). **The grain is now zone pair x route x day type x boarding hour.** Corridor / network scope is route membership, so a zone pair shared by several corridors is no longer counted under each of them. Reconciliation (tested for every route and corridor, per day type): `sum(passenger_count)` over a route's rows = `route_summary.boardings_per_day_<day_type>` of that route, and `sum(passengers_total)` = the route's ticketed boardings.

### `route_scores`
Contract columns: `route_id`, `demand_score`, `unmet_demand_score`, `load_factor_score`, `reliability_gap_score`, `revenue_potential_score`, `social_importance_score`, `feasibility_score`, `total_score`, `weight_version`, `explanation`, `source_type`.
Added in M2: `route_type`, `rank`, `rank_within_type`, `minimum_service`, `protected_minimum_service`, `missing_components`, `weights_json`, `normalisation`, `inputs_json` (raw inputs per component). Rule-based index (weights `demo-v1`), not an AI prediction. Components are min-max normalised to 0-100 *within `route_type`*; social importance is rule-based (50 if minimum_service + 50 x share of served zones that are residential/education/religious); feasibility is a PROXY (shorter scheduled minutes and higher weekday frequency); a missing component is re-weighted and named in `explanation`/`missing_components`. Full definitions: `modules/analytics/scoring.py`.

### `cctv_hourly_profile` (new in M2)
`location_id`, `day_type`, `hour`, `mean_inbound_persons`, `n_days`, `measurement_method`, `source_type`: mean inbound `person` count per hour per day from the SYNTHETIC `cctv_counts` stream.

### `route_candidates`
`candidate_id`, `corridor`, `path_geojson`, `travel_time_min`, `population_covered`, `jobs_covered`, `travel_time_penalty_pct`, `existing_route_overlap_pct`, `score`, `score_breakdown_json`, `source_type`.

**M4 additions (additive; no contract column renamed or removed).** Extra columns: `name`, `stop_ids_json` (ordered stop ids; all resolve to `stops`), `origin_stop_id`, `destination_stop_id`, `length_km`, `direct_travel_time_min` (fastest road path origin to destination; the reference for `travel_time_penalty_pct`), `zones_covered_json`, `walk_buffer_m`, `path_source` (`openstreetmap` | `straight_line_fallback`), `rank_flag` (`ranked` | `not_comparable_fallback`), `rank_in_corridor`, `label` (illustrative disclaimer). `source_type = model_output`. `score` (0-100) and `score_breakdown_json` use `config.CANDIDATE_SCORE_WEIGHTS` (versioned; components scaled within the corridor group). A candidate on a straight-line fallback path is **not scored or ranked** (`score` null, `rank_flag = not_comparable_fallback`). Coverage = zone centroid within `config.CANDIDATE_WALK_BUFFER_M` of the path, whole-zone synthetic population/jobs counted. Candidates are a bounded, hand-specified set for the demo corridors, illustrative only.
Migration: tables written before M4 (if any) lack the extra columns; rerun `python -m modules.routing.candidates` (or `python -m modules.routing.run`, which rebuilds both M4 tables from cached graphs).

### `route_paths` (new in M4)
`route_id`, `path_geojson` (JSON LineString, [lon, lat]), `osm_length_km`, `synthetic_length_km` (= `routes.length_km`), `length_ratio` (osm / synthetic), `travel_time_min` (illustrative: OSM speeds x bus factor + dwell), `path_source` (`openstreetmap` | `straight_line_fallback`), `graph_kind` (`city`, `corridor`, `city+corridor`, null), `note` (why a fallback was used), `source_type = model_output`. When `path_source` is the fallback, `osm_length_km` is a haversine x 1.3 estimate and NOT OSM-derived. Built from cached graphs only (`python -m modules.routing.fetch_network` downloads them; nothing else does). Road geometry is real OpenStreetMap data (c) OpenStreetMap contributors, ODbL; routes and stops are synthetic.

### `predictions`
`entity_type`, `entity_id`, `service_date`, `hour`, `actual_demand`, `predicted_demand`, `lower_bound`, `upper_bound`, `model_name`, `model_version`, `source_type`, `limitations`.

**M6-ML additions to `predictions` (additive).** Written by `python -m modules.ml.ridership` (also by `python -m modules.analytics.run` when scikit-learn is installed; otherwise skipped with a note and no table is written). `source_type = model_output`. One row per route x TEST-window service date (2026-08-31..2026-09-13; 16 x 14 = 224 rows), `hour` null (daily), `entity_type = "route"`, `entity_id` -> `routes.route_id`, `actual_demand` = `route_kpis.boardings`, `predicted_demand` = HistGradientBoostingRegressor (`model_name = hgb_route_day_boardings`, version `ridership-hgb-v1`), `lower_bound`/`upper_bound` = quantile-HGB 10/90 % (nominal 80 %; post-processed so lower <= predicted <= upper, lower >= 0). Extra columns: `split` (always `test`), `day_type`, `route_type`, `baseline_route_daytype_mean`, `baseline_seasonal_naive_lag7`. Target = route-day boardings; features = route attributes, planned supply (trips/seats per day from the timetable), calendar, corridor private-service count; NO same-day ticket outcomes (see `modules/ml/ridership.py`). Train = first 28 dates (2026-08-03..08-30). **Synthetic-data demonstration metrics - not evidence of real-world accuracy.**

### `ridership_model_metrics` (M6-ML; `model_output`)
Long format: `model`, `model_label`, `model_kind` (`model` | `baseline` | `forecasting_baseline` | `interval` | `diagnostic` | `diagnostic_baseline`), `split` (`train` | `test` | `test_leave_route_out`), `group` (`all`, `local`, `intercity`, `weekday`, `weekend`, `festival`), `metric` (`mae`, `rmse`, `mape_pct` [rows with zero actual skipped], `interval_coverage`, `interval_mean_width`, `interval_nominal_coverage`), `value`, `n`, `source_type`. Models `hgb`, `ridge`; baselines `route_daytype_mean`, `seasonal_naive_lag7` (lagged boardings: forecasting baseline only, NaN where the lag falls before the data). `test_leave_route_out` = secondary diagnostic (each route held out of training).

### `ridership_feature_importance` (M6-ML; `model_output`)
`rank`, `feature`, `label`, `importance_mae_increase` (permutation importance of the HGB on the test window: increase in MAE, passengers/day, when the feature is shuffled), `importance_std`, `method`, `note`, `model_name`, `model_version`, `source_type`. Not causal. SHAP not used.

### `baseline_forecast` (M6-ML; `model_output`; NOT a model)
Next 7 days after the data (2026-09-14..09-20) per route: `route_id`, `service_date`, `day_type` (calendar; no festival assumed), `forecast_boardings` (same-weekday mean of the last 4 weeks, festival days excluded), `lower_bound`/`upper_bound` (+/-1.2816 x pooled relative spread `pooled_relative_spread`; approximate 80 %), `history_days_used`, `history_weeks`, `method`, `label`, `source_type`. Written by `python -m modules.analytics.run` (pandas only). Prophet not used (only 6 weeks of synthetic history); H3 not used (zones are the spatial unit).

### `recommendations`
Contract columns: `recommendation_id`, `priority`, `category`, `title`, `route_id`, `location_id`, `time_window`, `action`, `evidence_json`, `assumptions_json`, `expected_impact_json`, `constraints_json`, `confidence_label`, `source_type`.
Added in M2: `priority_rank` (1 = first), `day_type`, `corridor`, `direction`. `category` in `add_service_peak`, `add_service_corridor_slot`, `add_capacity_weekend`, `protect_minimum_service` (minimum-service routes are only ever *retained and reviewed*). `time_window` is `HH:00-HH:00` built from the hours of the evidence rows, so it equals the gap-table window exactly (`protect_minimum_service` uses `all service hours`). `evidence_json` = `{table, filter, gap_rows[], figures, route_summary, route_score}`; `expected_impact_json` = `scenarios.service_frequency_scenario` output.

### `competition_analysis` (M5)
One row per intercity corridor (`route_pair`) x clock `hour` x `day_type`, for hours with at least one state or private departure. **Competitor departures are from the corridor origin (Rajkot) only; both directions are assumed to mirror those slots (M1 convention), so state departures are the OUTBOUND (from Rajkot) trips.** Competitors are synthetic.
Contract columns: `route_pair`, `hour`, `state_departures`, `private_departures`, `state_seats`, `private_seats`, `state_fare_inr`, `median_private_fare_inr`, `fare_index`, `premium_bus_gap`, `review_theme_summary`, `competitive_gap_score`, `source_type`.
Added in M5: `day_type`, `median_private_surge_fare_inr`, `fare_index_surge`, the five 0-1 component columns `departure_slot_gap`, `seat_share_gap`, `premium_gap_component`, `fare_disadvantage`, `review_theme_deficit`, `missing_components`, `weight_version`, `weights_json`, `assumptions_json`.

| Column | Definition |
|---|---|
| `state_departures`, `state_seats` | outbound trips (and their seats) of the corridor's state routes in the clock hour / number of service dates of the day type (average day) |
| `private_departures`, `private_seats` | competitor services of the corridor and day type departing in the hour (one row per service in `competitor_services`) |
| `state_fare_inr` | median over the hour's private services of the illustrative state tariff for the SAME bus class (`premium` -> state `AC_sleeper`; no such state class -> not counted, NaN if none); with no private service, the mean tariff of the state routes departing that hour |
| `median_private_fare_inr`, `fare_index` | median private `base_fare_inr` in the hour; `fare_index = state_fare_inr / median_private_fare_inr` (NaN where either side is missing; below 1.0 = state cheaper) |
| `median_private_surge_fare_inr`, `fare_index_surge` | median private `surge_fare_inr` of the day type (illustrative peak fare); the state tariff does not surge |
| `premium_bus_gap` | count of private services of type `AC_sleeper` / `premium` in the hour when no state `AC_sleeper` trip departs in that hour, else 0 |
| `review_theme_summary` | JSON `{method, route_pair, state: {n_reviews, themes: {theme: {positive, negative}}}, private: {...}}` for the corridor (method `generator_tags` = `reviews.themes`; the keyword tagger of `modules/survey/themes.py` is the deterministic alternative) |
| `competitive_gap_score` | 0-100 = 100 x sum(weight x component) over the available components (weights in `config.COMPETITIVE_GAP_WEIGHTS`, version `demo-comp-v1`, copied to `weights_json`): departure-slot gap 0.30 (1 if private departs and state has none, else max(0, p - s) / p), seat-share gap 0.20 (max(0, ps - ss) / (ps + ss)), premium-bus gap 0.20 (`premium_bus_gap` / 2, capped), fare disadvantage 0.10 ((`fare_index` - 1) / 0.25 clipped to 0-1; state fare above private only), review-theme deficit 0.20 (corridor mean over themes of max(0, state - private negative-mention share) / 0.15, capped; NaN if either operator type has < 10 reviews). A NaN component is dropped and the rest re-weighted (listed in `missing_components`). Hours with no private departure score 0. Index with visible weights, not a forecast |

### `survey_model_coefficients`, `survey_model_metrics` (new in M5; OPTIONAL, `source_type = model_output`)
Written by `python -m modules.survey.mode_choice` (also called by `python -m modules.analytics.run` when scikit-learn is installed; otherwise skipped with a note). Illustrative logistic regression of `survey_responses.switch_intent` on the nine switch conditions, `mode_car`, `purpose_work`, `income_high`; trained on a stratified train split (seed 42), evaluated on the test split. **Illustrative, conditional on the synthetic training setup - not a forecast of real behaviour.**
* `survey_model_coefficients`: `feature`, `label`, `true_coefficient` (the generator's TRUE coefficient from `modules/data_gen/constants.py`; 0 for conditions that do not enter the mechanism), `coef_train_fit`, `coef_full_fit` (all labelled rows; used by the page scenario), `abs_error_full_fit`, `sign_matches_truth` (null where the true value is 0), `source_type`. Includes the `intercept` row.
* `survey_model_metrics`: `metric` (`accuracy`, `roc_auc`, `brier_score`), `model`, `baseline` (majority class / chance / training base rate), `higher_is_better`, `baseline_definition`, `beats_baseline`, `n_train`, `n_test`, `source_type`.

## M1 conventions (generator contract)

**JSON encoding.** Every list/dict column (`zones.poi_counts`, `routes.stop_sequence`, `survey_responses.reasons`, `survey_responses.switch_conditions`, `reviews.themes`) is a string produced by `json.dumps` (double quotes). Never a Python repr. Parse with `json.loads`.

**Competitor services.** One row per (service, `day_type`); `departure_time` is the departure from the corridor origin (Rajkot), both directions are assumed to mirror the slots. `base_fare_inr` is constant across day types; `surge_fare_inr >= base_fare_inr` varies by day type.

**Enumerations.** `zone_type`: residential / employment / mixed / education / religious / other. `stop_type`: local_stop / bus_stand / intercity_terminal. `route_type`: local / intercity. `bus_type` (routes/trips): ordinary / express / AC_seater / AC_sleeper (routes also allow other); competitor adds premium. `day_type`: weekday / weekend / festival. `direction`: outbound / inbound. `passenger_type`: adult / student / senior / other. `coord_source`: openstreetmap / openstreetmap_offset / manual_demo_input. `survey.current_mode`: car / two_wheeler / bus / rail / shared_taxi / other; `trip_purpose`: work / education / shopping / health / leisure / other; `income_band`: low / lower_middle / middle / upper_middle / high. JSON values: `reasons` (private users) from flexibility, door_to_door, comfort, bus_unreliable, no_ac_on_bus, low_bus_frequency, crowding, safety, no_direct_route, carries_goods_or_family (transit users: low_cost, no_private_vehicle, direct_route, avoid_parking_hassle, safety); `switch_conditions` from reliability, ac_comfort, frequency, lower_fare, safety, cleanliness, real_time_info, parking_cost_or_hassle, direct_route. `assets_assessment.dimension`: cleanliness / accessibility / safety / amenities / digital; `digital_assessment.capability`: e-ticketing / live tracking / passenger information / payments / analytics. Authoritative lists live in `modules/data_gen/constants.py` and are enforced by `python -m modules.data_gen.validate`.

**Calendar.** 42 service dates, Monday 2026-08-03 to Sunday 2026-09-13: 29 weekday, 11 weekend, 2 festival (2026-09-04 and 2026-09-05; an illustrative Janmashtami period with elevated Somnath pilgrimage demand; synthetic).

**Geography.** Real OpenStreetMap coordinates are fetched ONLY by `python -m modules.data_gen.fetch_osm` into `data/raw/osm_places.parquet`; the generator and the dashboard never download. Coordinates lie inside `config.PILOT_BBOX` except the documented exceptions: the Jamnagar and Ahmedabad bus stands (and their zones), which are intercity endpoints outside the box.

**Source-table provenance.** Every source table has a `source_type` column and a provenance sidecar (`<table>.provenance.json`) with seed, assumptions and description. Generation timestamps appear only in sidecars, never in table contents.

## Schema rules

- Foreign keys must resolve or be explicitly nullable.
- Store lists/JSON consistently and document the encoding; do not mix Python repr strings and JSON.
- Validate units and allowed enum values.
- Never infer real people or identities from CCTV counts.
- Add a schema migration note when changing a published table.

## Migration notes

### M5 (competition, pricing, survey intelligence)
| Table | Change |
|---|---|
| `od_flows` | + `route_id`, `corridor`; grain is now zone pair x route x day type x hour (4,737 rows at seed 42); sums over all rows are unchanged, so All-scope totals do not change, but corridor scopes now equal route boardings instead of double counting shared pairs |
| `competition_analysis` | **new** (contract columns + M5 extensions, see above) |
| `survey_model_coefficients`, `survey_model_metrics` | **new, optional** (`model_output`) |
| `recommendations` | no schema change; the corridor-slot recommendation (REC-001) evidence gains a `competition` block and `expected_impact_json` a `fare_scenario` |

### M2 (deterministic analytics milestone)
Derived tables (all additive; no source table or published column changed):

| Table | Change |
|---|---|
| `route_kpis` | + `day_type`, `trips`, `seat_km`, `mean_delay_min`, `boardings_per_seat`, `peak_load_factor_max` |
| `route_summary` | **new table** (route-level KPI source of truth) |
| `hourly_demand_supply` | + `level`, `route_id`, `corridor`, `direction`, `day_type`, `status`, `trips_per_day`, `ticketed_boardings_per_day`, `state_demand`, `private_seats`, `private_demand_proxy`, `private_departures`; `service_date` is null (average day) |
| `stop_occupancy` | **new table** |
| `od_flows` | + `day_type`, `passengers_total`, `passenger_km_total`, `n_days`, `is_intra_zone` |
| `route_scores` | + `route_type`, `rank`, `rank_within_type`, `minimum_service`, `protected_minimum_service`, `missing_components`, `weights_json`, `normalisation`, `inputs_json` |
| `recommendations` | + `priority_rank`, `day_type`, `corridor`, `direction` |
| `cctv_hourly_profile` | **new table** |

Terminology fix: M1 documents called `boardings / seats` a "load factor". It is now named **boardings per seat** (turnover); load factors are `peak_load_factor` and `load_factor_pct` as defined above. `competition_analysis` was added in M5.

### M1 (synthetic data milestone)
Published-table changes relative to the M0 contract (all additive; no column renamed or removed):

| Table | Added |
|---|---|
| `zones` | `coord_source` |
| `stops` | `coord_source` |
| `routes` | `corridor` |
| `trips` | `direction`, `actual_departure_time`, `departure_delay_min` (needed for the reliability KPI and direction-aware occupancy) |
| `route_stops` | **new table** (`route_id`, `stop_seq`, `stop_id`, `cum_km`, `cum_minutes`) |

Documented semantics tightened (no schema change): `tickets.fare_inr` is the total for the ticket, `cctv_counts.timestamp_min` is a 5-minute bucket start, `survey_responses.switch_intent` is null for non-private-mode respondents, `reviews.themes` is a list of theme/polarity objects.
