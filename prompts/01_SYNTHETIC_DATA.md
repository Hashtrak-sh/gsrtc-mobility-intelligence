# Milestone 1 — Reproducible Synthetic Data

Read the schema and rules before implementation.

## Task

Implement `modules/data_gen/` to generate coherent source tables for the pilot. Use `SEED` from `config.py` everywhere. Use a modest dataset size that runs quickly; optimise for consistency and demonstrability rather than volume. Do not generate 150,000 tickets unless profiling proves it is necessary.

Generate at least:
- zones and stops;
- local and intercity routes;
- trips with capacity, scheduled duration, operating-cost assumptions and state/private operator type;
- tickets with origin, destination, time, fare, and passenger count;
- survey responses from synthetic private-vehicle users;
- competitor services and reviews;
- station/depot infrastructure and digital assessments.

The main corridor is Rajkot–Somnath. Use real map geography only when it can be fetched and cached reliably. If network access fails, use a documented small synthetic coordinate network and label it clearly; do not invent that the coordinates came from OSM.

Create `data/synthetic/planted_findings.md` with explicit, traceable planted patterns:
- 2–3 route-hours with high synthetic load factor;
- 1–2 corridors with demand but low/no state capacity;
- at least one strong morning O-D flow toward an employment zone;
- one evening intercity departure-slot gap;
- survey answers where reliability/AC/frequency are meaningful switch conditions.

Generate underlying records that cause these findings. Do not hardcode the final values in dashboard code.

## Output

Write source tables to Parquet under `data/synthetic/`. Add validation for foreign keys, allowed values, positive capacities/fares, nonnegative counts, expected peaks, and reproducibility. Add a single documented generation command.

## Verification

Run generation twice with the same seed and compare stable columns. Print row counts and validation results. Fix failures before finishing.
