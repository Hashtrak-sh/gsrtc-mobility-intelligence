# Milestone 7 — Reports, Exports and Final QA

## Reports

Generate a PDF report with:
- executive summary;
- pilot scope and data provenance;
- route/demand findings;
- supply-gap and service recommendations;
- competition/pricing scenario;
- infrastructure/digital findings;
- assumptions, limitations and scale-up needs.

Include timestamp, seed, selected filters, and an explicit statement that passenger/operations/competitor values are simulated. Export supporting CSV tables.

## Optional Ask the Data

If an LLM key is configured:
- query only concise summaries of processed data;
- cite the relevant table/page and figures used;
- state when the data does not answer the question;
- cache safe repeat requests and handle API errors.

Without a key, the app must still work. Do not pretend a rule-based response came from a live LLM.

## Final QA

Run all acceptance checks in `docs/ACCEPTANCE_TESTS.md`.
- Generate source data from a clean state.
- Run every test.
- Launch and inspect all pages.
- Verify one route/corridor end-to-end from source rows to KPIs, recommendation, scenario, and PDF report.
- Verify reproducibility.
- Check secrets and private videos are excluded from Git.
- Ensure README commands match the actual implementation.
- Create `docs/DEMO_SCRIPT.md` if not already present and rehearse the 15-minute flow.

Finish with a truthful status report: complete, partial, and unavailable features; exact commands tested; known limitations; next steps.
