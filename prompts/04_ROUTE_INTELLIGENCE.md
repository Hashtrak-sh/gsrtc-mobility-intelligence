# Milestone 4 — Route Intelligence and Bounded Optimisation

Implement route intelligence on top of the stable synthetic data and analytics engine.

## Required

- Route ranking with visible score components, weights, and reasons.
- Route detail view with demand, load factor, EPKM, revenue/passenger, reliability, stop sequence, and hourly profile.
- Candidate service/frequency recommendations for selected corridor and peak period.
- Where feasible, use cached OSMnx/NetworkX geography for bounded candidate paths. Do not run large all-pairs routing on every Streamlit rerun.
- If the map download or routing dependencies are unavailable, use the documented pilot-network fallback and clearly label the source.
- Keep social/minimum-service constraints visible; do not recommend removal of essential service on commercial score alone.

Optimisation must be bounded to the demo corridor and explicitly state constraints. It must not claim to optimise the whole GSRTC network.

## Verification

Test route score ordering on known synthetic cases, verify path/stop IDs, and ensure recommendations use the same demand/capacity window as the gap analysis.
