# Milestone 0 — Scaffold and Shared Contract

Read `CLAUDE.md`, `RULES.md`, and all required documents before editing.

## Task

1. Inspect the repository. Preserve useful existing code; do not overwrite it blindly.
2. Create the smallest complete project scaffold from `docs/ARCHITECTURE.md`.
3. Add `config.py` with:
   - `PILOT_CITY = "Rajkot, Gujarat, India"`
   - a small documented bounding box suitable for a demo;
   - `SEED = 42`;
   - optional H3 resolution (default 8 only if H3 is installed);
   - route scoring weights in one configuration object.
4. Create `docs/DATA_SCHEMA.md` as the shared table contract if it does not already exist. Do not add columns silently.
5. Create `requirements.txt` with only P0 dependencies first. Document optional extras separately; do not force YOLO/Prophet/SHAP/LLM dependencies during the scaffold.
6. Create one Streamlit entry point and all navigation pages with titles, simulation badges, and a consistent layout.
7. Add `.gitignore` and `.env.example`. Ensure `.env`, video files, and large model weights are not committed.
8. Add a health/diagnostics section that shows missing optional dependencies without crashing.
9. Add basic tests for configuration and app imports where feasible.
10. Update README with exact setup/run commands.

## Verification

Run the test suite and launch or smoke-test the app. Do not continue to synthetic data until the scaffold is runnable. Report the exact commands and outcomes; do not claim a visual launch was tested if it was not.
