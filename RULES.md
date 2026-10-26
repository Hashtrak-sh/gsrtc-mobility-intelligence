# Project Rules — GSRTC Mobility Intelligence

## Purpose and scope

Build a polished local-first Streamlit prototype for the GSRTC professional market survey scope. It demonstrates how synthetic data, transport analytics, survey evidence, route intelligence, competition analysis, and optional CCTV counting can support decisions. It is not a production transport-planning system.

## Non-negotiable data integrity

- All synthetic data and all derived results must be clearly labelled **“Simulated data for demonstration”**.
- Do not imply that synthetic values are real GSRTC measurements, actual passenger counts, official schedules, or verified competitor fares.
- Use a fixed seed (`SEED = 42`) for data generation and reproducible tests.
- Every chart/KPI must be calculated from source tables or a documented deterministic transformation. No decorative hardcoded KPI cards.
- Maintain provenance metadata: source type (`synthetic`, `openstreetmap`, `manual_demo_input`, `model_output`), generation timestamp, seed, and assumptions where relevant.
- Real geography and synthetic mobility data must be visually and textually distinguished.
- Missing or invalid data must be shown as missing, not silently replaced with plausible numbers.
- The same entity must have consistent values across pages.

## Architecture

- Python 3.11.
- Streamlit is the UI; analytics live in importable Python modules, not page scripts.
- Parquet is the primary table format; DuckDB/pandas are the query layer.
- Dashboard pages read processed outputs and may apply small interactive filters. They must not regenerate the full dataset or download large datasets on every rerun.
- Cache expensive loads/computations, but make cache invalidation clear.
- Keep external network operations in explicit data-preparation commands, not in normal dashboard rendering.
- Optional modules (CCTV, LLM, forecasting, advanced optimisation) must fail gracefully and must not prevent core app startup.
- No authentication, production database, real-time streaming, or multi-city production architecture in this prototype.

## Analytics and explainability

- Prefer deterministic, explainable baselines before advanced models.
- Every model must have a documented target, feature list, train/test or validation strategy, and limitations.
- Do not describe a rule-based score as an AI prediction.
- Do not use SHAP unless a fitted compatible model exists. If unavailable, show feature importance or a transparent score breakdown and label it correctly.
- Forecasts are demonstrations on synthetic history; show uncertainty and assumptions where supported.
- All recommendations must identify the evidence, assumptions, expected effect, and any constraints.
- Never recommend removing an essential service solely because its commercial score is low. Include minimum-service/social-importance constraints in route scoring and optimisation.
- Distinguish revenue from contribution/profit. Do not claim profit unless all relevant costs are represented.
- Use INR, kilometres, 24-hour time, and Indian transport terminology.

## CCTV/privacy

- Count aggregate people/vehicle movements only.
- No face recognition, identity recognition, or identity tracking.
- Do not retain person-level identifiers.
- If exporting annotated video, blur faces where technically feasible; describe the method and its limits.
- Do not claim counts are accurate without a manual spot-check against the clip.
- If a detector/model/weights are unavailable, clearly show the module as unavailable. Do not replace real inference with fabricated counts.
- Use only video the developer is permitted to process.

## LLM usage

- LLM features are optional and must be isolated behind one client interface.
- API keys come from environment variables or Streamlit secrets; never hardcode secrets or commit `.env`.
- Cache survey/review theme results. The app must still run without an API key.
- “Ask the Data” must answer only from supplied processed data summaries, identify the source table/page, and say when the answer is unsupported. Never invent a number or cite a source that was not queried.
- If no API key is configured, provide a clear unavailable message or a deterministic, explicitly labelled demo response—not a fake live LLM response.

## UI/UX

- Prioritise clarity for a nontechnical evaluator.
- The first screen should answer: what is happening, where is the problem, and what action is recommended?
- Every page should have a clear takeaway, readable units, useful empty/error states, and an evidence/assumptions disclosure.
- Avoid clutter, developer jargon, and charts that do not support a decision.
- Keep navigation labels simple and consistent.
- Every simulated-data page shows the simulation badge.
- No misleading “live” wording for prerecorded video or static/synthetic data.

## Engineering workflow

- Read `docs/DATA_SCHEMA.md` before changing data tables.
- Every module has a clear input/output contract and a validation command or tests.
- Add tests for formulas, edge cases, reproducibility, and cross-page consistency.
- Run the relevant tests after each milestone and the full test suite before declaring the prototype complete.
- Do not leave placeholder/TODO logic presented as working functionality.
- Do not start multiple AI tools editing the same files concurrently.
- Keep the README accurate and document exact run commands.
