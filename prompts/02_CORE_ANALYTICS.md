# Milestone 2 — Deterministic Analytics and KPI Engine

Implement the P0 analytics as importable functions, with unit tests.

## Required calculations

- route/trip/day load factor with explicit aggregation rules;
- occupancy progression by stop: previous occupancy + boardings − alightings;
- ticket revenue, revenue per passenger, EPKM, and contribution using included costs only;
- documented schedule reliability calculation;
- hourly demand vs seats offered, gap count, gap index, and crowding flags;
- O-D aggregation by zone pair and hour;
- transparent route potential score with normalised component scores and configurable weights;
- service-frequency scenario with capacity, target occupancy, incremental vehicle-km, and operating-cost assumptions;
- pricing scenario using explicit configurable fare elasticity and sensitivity values.

Handle zero denominators, no-service periods, empty tables, and missing values. Do not call route scores “AI predictions”. Write processed Parquet outputs under `data/processed/`.

Build a recommendation record with priority, action, evidence, assumptions, expected impact, constraints, and confidence label. Keep essential/minimum-service considerations visible.

## Verification

Add tests for every formula and edge case. Verify planted findings are detected from source data. Ensure derived route values reconcile with source tickets/trips and the same route produces consistent metrics across all processed tables.
