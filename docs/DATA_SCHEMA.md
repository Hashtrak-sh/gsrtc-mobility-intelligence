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

Every trip in this table is a **state (GSRTC demonstration) service** with tickets (`operator = state`); private competitor supply lives only in `competitor_services`. `seats` come from `BUS_TYPE_SEATS` (ordinary 40, express 45, AC_seater 40, AC_sleeper 30). `operating_cost_inr = OPERATING_COST_PER_KM_INR[bus_type] x routes.length_km` (ordinary 52, express 58, AC_seater 70, AC_sleeper 80 INR/vehicle-km; illustrative assumptions). **Standing rule:** local ordinary buses allow standees up to `LOCAL_CRUSH_FACTOR = 1.6 x seats` onboard; intercity reserved buses never exceed `seats`. Load factor = boardings / seats and can exceed 100% on local routes; for intercity, excess latent demand is unmet and NOT ticketed (it is visible only indirectly, e.g. in `cctv_counts`).

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

### `route_kpis`
`route_id`, `service_date`, `boardings`, `estimated_passenger_km`, `vehicle_km`, `ticket_revenue_inr`, `operating_cost_inr`, `available_seats`, `load_factor_pct`, `epkm_inr`, `revenue_per_passenger_inr`, `contribution_inr`, `reliability_pct`, `source_type`, `assumptions_json`.

### `hourly_demand_supply`
`zone_id`, `location_id`, `service_date`, `hour`, `demand_estimate`, `seats_offered`, `gap_count`, `gap_index`, `crowding_flag`, `source_type`, `assumptions_json`.

### `od_flows`
`origin_zone_id`, `dest_zone_id`, `hour`, `passenger_count`, `estimated_passenger_km`, `source_type`.

### `route_scores`
`route_id`, `demand_score`, `unmet_demand_score`, `load_factor_score`, `reliability_gap_score`, `revenue_potential_score`, `social_importance_score`, `feasibility_score`, `total_score`, `weight_version`, `explanation`, `source_type`.

### `route_candidates`
`candidate_id`, `corridor`, `path_geojson`, `travel_time_min`, `population_covered`, `jobs_covered`, `travel_time_penalty_pct`, `existing_route_overlap_pct`, `score`, `score_breakdown_json`, `source_type`.

### `predictions`
`entity_type`, `entity_id`, `service_date`, `hour`, `actual_demand`, `predicted_demand`, `lower_bound`, `upper_bound`, `model_name`, `model_version`, `source_type`, `limitations`.

### `recommendations`
`recommendation_id`, `priority`, `category`, `title`, `route_id`, `location_id`, `time_window`, `action`, `evidence_json`, `assumptions_json`, `expected_impact_json`, `constraints_json`, `confidence_label`, `source_type`.

### `competition_analysis`
`route_pair`, `hour`, `state_departures`, `private_departures`, `state_seats`, `private_seats`, `state_fare_inr`, `median_private_fare_inr`, `fare_index`, `premium_bus_gap`, `review_theme_summary`, `competitive_gap_score`, `source_type`.

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
