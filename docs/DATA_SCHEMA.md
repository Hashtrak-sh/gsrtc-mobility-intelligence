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

### `stops`
| Column | Type | Meaning |
|---|---|---|
| `stop_id` | string | Stable stop ID |
| `name` | string | Display name |
| `lat`, `lon` | float | Coordinates |
| `zone_id` | string | Related zone |
| `is_bus_stand` | boolean | Whether this is a stand/station in the demo |
| `stop_type` | string | local_stop / bus_stand / intercity_terminal |
| `source_type` | string | Provenance |

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

### `tickets`
| Column | Type | Meaning |
|---|---|---|
| `ticket_id` | string | Unique synthetic ticket ID |
| `trip_id` | string | Trip foreign key |
| `origin_stop_id` | string | Boarding stop |
| `dest_stop_id` | string | Alighting stop |
| `timestamp` | datetime | Boarding timestamp |
| `fare_inr` | float | Fare paid |
| `passenger_type` | string | adult / student / senior / other |
| `passenger_count` | integer | Usually 1; permits grouped synthetic records |
| `source_type` | string | synthetic |

### `cctv_counts`
| Column | Type | Meaning |
|---|---|---|
| `location_id` | string | Camera/zone label; not a person identifier |
| `timestamp_min` | datetime | Minute bucket |
| `direction` | string | inbound / outbound / unknown |
| `class` | string | person / car / two_wheeler / auto / bus / truck / other |
| `count` | integer | Aggregate count in bucket |
| `measurement_method` | string | actual_detector / manual_demo_input / synthetic |
| `source_type` | string | Provenance |

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
| `switch_intent` | integer/null | Synthetic response target, 0/1 |
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
| `route_pair` | string | Corridor key |
| `rating` | float | Synthetic rating |
| `text` | string | Synthetic review text |
| `themes` | JSON/string | Tagged themes, with method provenance |
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

## Schema rules

- Foreign keys must resolve or be explicitly nullable.
- Store lists/JSON consistently and document the encoding; do not mix Python repr strings and JSON.
- Validate units and allowed enum values.
- Never infer real people or identities from CCTV counts.
- Add a schema migration note when changing a published table.
