# Planted Findings (synthetic demonstration)

**Simulated data for demonstration.** Everything below is planted in the *generative process* of
`python -m modules.data_gen.generate` (seed 42). None of it is a real GSRTC measurement, schedule, fare or
competitor observation. The numbers quoted are what the detection checks return on the seed-42 output; the
generator never writes these numbers anywhere, and the dashboard must recompute them from the source tables.

Detection code: `modules/data_gen/checks.py` (plain pandas, verification helpers only - not the M2 analytics) and, from
Milestone 2, `modules/analytics/findings.py` (detects the same findings from the analytics outputs; run
`python -m modules.analytics.run`).
Tests: `tests/test_data_gen.py` (`test_planted_f*`), `tests/test_analytics_planted.py`. Report: `python -m modules.data_gen.validate`.

Common definitions: *boardings* = `sum(tickets.passenger_count)` per trip; ***boardings per seat*** = boardings / seats
(seat-weighted over the trips in the group). This is passenger *turnover*, NOT a load factor: on local routes passengers
board and alight along the route, so boardings per seat can exceed the 1.6 x seats physical crush limit (seed 42 maximum:
2.51). The physical measure used by the M2 analytics is the **peak load factor** = maximum onboard on any link / seats
(at most 1.6 local, 1.0 intercity; see "Peak load factor as detected by the analytics" under F1/F2 below).
*route-hour* = all weekday trips of a route scheduled to depart in that clock hour (both directions).

---

## F1. High-load route-hours

### F1a. Local: three route-hours on the Mavdi - Aji GIDC industrial shuttle (route `L05`) plus the consequence of F2

| | |
|---|---|
| **What** | `L05` "Mavdi - Kotharia - Aji GIDC Industrial Shuttle (demo)" is heavily loaded in three weekday route-hours: 07:00, 08:00 and 17:00 (boardings per seat far above the other route-hours; standing loads on the busiest links). |
| **Where / when** | Route `L05`, weekdays, dep hours 7, 8 (morning shift change, residential south Rajkot to the Aji industrial estate) and 17 (return shift). Both directions. |
| **Mechanism** | `RouteSpec.hour_boost` in `modules/data_gen/network.py` multiplies expected demand by 2.3 (07h, 08h, 17h; M2.5 calibration) on top of the weekday hour profile and the route's commuter multipliers; demand is Poisson, served up to the 1.6 x seats crush limit, the rest is unmet (not ticketed). No other local route-hour exceeds 120% except `L07` 07h (a direct consequence of F2). |
| **Expected signal** | boardings per seat > 1.2 (all weekday trips of the route-hour). Seed 42 (after the M2.5 calibration): `L05` 08h = 1.68, 07h = 1.65, 17h = 1.54; `L07` 07h = 2.72 boardings per seat; the next-highest local route-hour is about 1.2. The detector threshold is boardings per seat > 1.4. Detected set is exactly {L05 7, L05 8, L05 17, L07 7}. **Peak load factor as detected by the analytics** (max link onboard / seats, `analytics.gaps.route_hour_load`): `L05` 08h = 1.40, 07h = 1.32, 17h = 1.23; `L07` 07h = 1.33 (all <= the 1.6 crush limit); the same four route-hours are the only weekday route-hours above 1.1. At route-direction level the gap table flags `crowded` (gap index > 1.2) for L05 outbound 07h/08h, L05 inbound 17h and L07 outbound 07h. |
| **Detection check** | `checks.high_load_route_hours(tables)`: join `tickets` to `trips`, sum `passenger_count` by (`route_id`, departure hour) over `day_type == 'weekday'`, divide by `sum(seats)`, keep > 1.4 (boardings per seat). Analytics: `findings.detect_planted` (peak load factor > `config.HIGH_PEAK_LOAD_FACTOR` = 1.1). |

### F1b. Intercity: Rajkot -> Somnath 08:30 AC seater is ~full every weekend

| | |
|---|---|
| **What** | Route `IC02` (Rajkot - Somnath AC Seater), outbound 08:30 departure is full on every weekend day. |
| **Where / when** | Corridor Rajkot-Somnath, route `IC02`, direction outbound, `departure_time = 08:30`, 11 weekend dates (festival days are higher still). |
| **Mechanism** | `RouteSpec.trip_boost` x2.8 on weekends (x2.2 on festival days) on top of the AC weekend day factor 1.3; reserved bus, cap = seats; excess demand is unmet and invisible in tickets (it shows up in `cctv_counts` footfall at `S34`/`S01`). |
| **Expected signal** | boardings per seat >= 0.95 and peak onboard per seat (= peak load factor) >= 0.95 on every weekend date; the same departure on weekdays has boardings per seat < 0.8 (peak load factor mean 0.46). Seed 42: boardings 53-62 for 40 seats, peak onboard = 40 on all 11 dates; weekdays about 0.89 boardings per seat (mean peak load factor 0.74). |
| **Detection check** | `checks.intercity_weekend_load(tables)` (uses `checks.occupancy_by_trip` for the progression board - alight along `route_stops`). |

---

## F2. Demand with low state capacity (one trip)

| | |
|---|---|
| **What** | Weekday 07:00-08:00 demand toward the Shapar-Veraval industrial area (zone `Z13`) is served by exactly one state trip. |
| **Where / when** | Route `L07` "Madhapar - Raiya - Shapar-Veraval Industrial Area (demo)"; the only route serving `Z13`; weekday schedule has a single departure in hour 7 (07:05, outbound; no inbound departure in that hour). |
| **Mechanism** | Explicit departure list for `L07` (`dep_out`/`dep_in`) with a x2.2 hour boost on the 07:05 outbound trip; the bus is full to the crush limit and further demand is unmet. |
| **Expected signal** | 1 trip per weekday in the window, 40 seats; boardings per seat >= 1.5 (seed 42: 2.72; peak load factor 1.33 in the analytics); passengers carried to `Z13` in the window >= seats offered (77 vs 40 per weekday); the other weekday hours of the same route are at <= 1.0 boardings per seat (0.83). |
| **Detection check** | `checks.capacity_gap_window(tables, zone_id='Z13', hour=7)`. |

The second capacity gap is the evening intercity slot (F4).

---

## F3. Strong morning O-D flow toward an employment/industrial zone

| | |
|---|---|
| **What** | The top weekday 07:00-10:00 zone-to-zone pair is residential -> employment. |
| **Where / when** | Seed 42: `Z05` Kotharia (residential) -> `Z11` Aji GIDC (employment), 4,535 passengers over 29 weekdays (next-best pair with a non-employment destination: 2,831). |
| **Mechanism** | Local ticket pairs are drawn with weights `0.35 gen_i gen_j + m res_i job_j + e job_i res_j` x exp(-d/6 km) (intra-zone hops x0.25), morning phase `m = 1`, `e = 0.1`; resident-worker weight `res` from `zones.workers_resident`, `job` from `zones.jobs` (employment zones have ~30,000 jobs and ~3,000 residents). Reinforced by the `L05` boosts (F1a). The survey (F5) draws work destinations with industrial estates weighted x2.2. |
| **Expected signal** | top pair has origin zone_type = residential and dest zone_type = employment and >= 1.2 x the best non-employment-destination pair. |
| **Detection check** | `checks.top_od_pairs(tables, hours=(7, 10))`: tickets of weekday trips, boarding hour 7-9, map stops to zones, sum `passenger_count`. |

---

## F4. Evening intercity departure-slot gap (Rajkot - Somnath)

| | |
|---|---|
| **What** | State services on Rajkot-Somnath leave at 17:30 and then not again until 22:45 (express) / 23:15 (AC sleeper); private AC services run through the gap at higher fares and ratings. |
| **Where / when** | Corridor Rajkot-Somnath, departures 18:00-22:30, all day types. |
| **Mechanism** | State `IC01`/`IC02`/`IC03` departure lists contain nothing in 18:00-22:30. `competitor_services` (synthetic operators) has 7 Rajkot-Somnath services in the window (18:45 AC seater, 19:30 / 20:15 / 21:30 / 22:15 AC sleeper, 21:00 AC seater, 22:00 premium) with ratings drawn from 4.3-4.7 (daytime 3.8-4.5), private fares well above the state tariff for the same class (AC sleeper about INR 700-800 vs about INR 490 state) and evening/festival surge. `reviews` give state services weaker punctuality and AC sentiment than private ones. |
| **Expected signal** | 0 state trips in the window; >= 5 private AC/premium services; mean private rating in window >= 4.3 and >= 0.3 above outside the window (seed 42: 4.57 vs 3.98); private median base fare in window INR 770, surge INR 890; state review mean rating below private (3.38 vs 3.55). |
| **Detection check** | `checks.evening_slot_gap(tables)`. |

---

## F5. Survey: switch conditions and an illustrative logistic switch-intent mechanism

| | |
|---|---|
| **What** | 800 synthetic respondents (about 80% car/two-wheeler, 12% bus, rest rail/shared taxi/other). Top-3 switch conditions are reliability, AC comfort and frequency; `switch_intent` follows a documented logistic model. |
| **Mechanism (conditions)** | Independent Bernoulli per condition: reliability 0.50, ac_comfort 0.40, frequency 0.38, lower_fare 0.26, safety 0.22, cleanliness 0.20, real_time_info 0.18, direct_route 0.17, parking_cost_or_hassle 0.14; boosted to 0.85 / 0.80 / 0.78 (reliability / ac_comfort / frequency) when the matching reason (`bus_unreliable` / `no_ac_on_bus` / `low_bus_frequency`) was given. |
| **Mechanism (intent)** | For private-mode respondents (car, two_wheeler, shared_taxi, other): `logit P(switch_intent = 1) = -2.0 + 1.10 cond_reliability + 0.90 cond_ac_comfort + 0.95 cond_frequency + 0.30 cond_lower_fare - 0.35 mode_car + 0.25 purpose_work - 0.30 income_high`, where `income_high` = income band upper_middle or high, and `cond_*` = 1 if the condition is in `switch_conditions`. `switch_intent` is null for bus and rail users. The coefficients live in `modules/data_gen/constants.py` (`INTENT_INTERCEPT`, `INTENT_COEF`). |
| **Expected signal** | Top-3 conditions by count among car/two-wheeler respondents: reliability 427, frequency 350, ac_comfort 339 (4th: direct_route 185). A logistic fit on the generated labels recovers positive coefficients for the three conditions near the true values (seed 42: 0.95 / 0.70 / 0.72 against 1.10 / 0.90 / 0.95). M5 may fit an illustrative model; its probabilities are conditional on this synthetic setup, not validated forecasts. |
| **Detection check** | `checks.switch_condition_counts`, `checks.survey_design_matrix` + `checks.fit_logistic`. |

---

## F6. Rajkot bus stand synthetic CCTV footfall peaks 07:00-09:00 on weekdays

| | |
|---|---|
| **What** | Synthetic aggregate person counts (inbound) at `S01` Rajkot Central Bus Stand peak at 07:00-09:00 on weekdays. |
| **Where / when** | `cctv_counts`, `location_id = S01`, `class = person`, weekdays; 5-minute buckets 05:00-22:55; `measurement_method = synthetic`. Locations `S31` (Junagadh) and `S34` (Somnath, pilgrimage profile, festival x1.8) are also generated. |
| **Mechanism** | Counts = ticketed boardings arriving 3-15 minutes early + alighters leaving + unmet intercity demand + an unticketed-footfall profile (`cctv._RAJKOT_WEEKDAY`: 52-58 per 5 minutes at 07-09h vs 11-15 midday), Poisson noise. Not detector output. |
| **Expected signal** | weekday peak hour in {7, 8}; mean 07-09h footfall >= 2 x mean of the other hours (seed 42: peak hour 8, ratio 2.8; mean daily inbound persons 895 at 08h vs about 200-300 midday); weekend has no such peak. |
| **Detection check** | `checks.cctv_hourly_profile(tables, 'S01', 'weekday')`. |

---

## Other deliberately planted structure (supporting)

* **Minimum-service routes.** `L09` (Madhapar - Gandhigram Village Link) and `L10` (Metoda GIDC - Mavdi - Central) have `minimum_service = True`, about 6 trips per direction, and ridership below 20% load factor, so any score that only looks at commercial performance would rank them last. Later scoring must protect them.
* **Festival.** 2026-09-04 and 2026-09-05 (`day_type = festival`, illustrative Janmashtami period) lift Rajkot-Somnath demand (day factor 1.5-1.9) and Somnath footfall.
* **Reliability.** Departure delays are synthetic (gamma, longer in peaks and on intercity); about 69% of trips depart within 5 minutes.
* **Infrastructure/digital gaps.** Somnath stand accessibility, Rajkot stand amenities and digital, industrial stops (shelter/lighting) and live-tracking/analytics maturity are scored low in `assets_assessment` / `digital_assessment`.
* **Review themes.** State reviews are more often negative on punctuality, AC/comfort and cleanliness; private reviews are more often negative on value.

---

## M2.5 economics calibration (illustrative orders of magnitude, NOT GSRTC data)

The M1 numbers were implausible (every route lost money, city-bus load factors 5-18%, intercity EPKM INR 19-38 against a
INR 58-80 per-km cost). Generator parameters were recalibrated; the analytics were not tuned. All values remain
assumptions held in `modules/data_gen/constants.py` and `network.py`, and every output still derives from the source records.

| Parameter | M1 | M2.5 | Rationale |
|---|---|---|---|
| Operating cost INR/vehicle-km (ordinary / express / AC seater / AC sleeper) | 52 / 58 / 70 / 80 | 52 / 46 / 54 / 60 | typical Indian state-transport orders of magnitude (about INR 45-60 per bus-km) |
| Fare INR/km (ordinary / express / AC seater / AC sleeper) | 1.0 / 1.25 / 1.9 / 2.4 | 1.25 / 1.2 / 1.9 / 2.5 | usual intercity ranges; Rajkot-Somnath AC sleeper is about INR 490 |
| City-bus hour profile (peak / midday) | about 3x | about 1.5x | flatter demand so route-average load factors reach 25-50% without every peak crushing |
| Local base demand per trip, counter-peak multiplier | 10-24, 0.45 | 24-34, 0.7 | more passengers per trip; counter-peak flows are real |
| Local headways (peak / off-peak / weekend, min) | 20-30 / 40-60 / 50-70 | 36-60 / 120 / 130 | fewer trips (also keeps `tickets` at about 300k rows) |
| Intercity demand base (fraction of seats) | 0.50-0.62 | 0.75-1.15 | route-average load factor 55-76% |
| Intercity timetables | IC04, IC05: 10 departures | 8 departures | realistic frequency and ticket volume |
| Planted boosts | L05 x2.0, L07 x2.6 | L05 x2.3, L07 x2.2 | peaks still stand out against the flatter background |

Resulting `route_summary` (seed 42): local routes load factor 29-36% (L05 32%), EPKM INR 15-21, all loss-making on ticket
revenue; minimum-service routes L09/L10 about 6%; intercity load factor 55-76%, EPKM INR 32-54 against a cost of INR 46-60
per km, with the strongest corridors (IC06, IC02) near break-even and the weaker ones negative. Planted-finding detection
thresholds were adjusted accordingly (boardings per seat > 1.4 for F1; other-hours <= 1.0 for F2; IC02 08:30 weekday < 0.9
boardings per seat for F1b); the F1-F6 mechanisms are unchanged.
