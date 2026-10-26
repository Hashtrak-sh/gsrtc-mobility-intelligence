# GSRTC Mobility Intelligence

A local-first, synthetic-data Streamlit prototype that demonstrates the approved GSRTC professional market survey scope as a connected, explainable decision-support workflow. It is a tender demonstration, not a production system, and says nothing about actual GSRTC demand or performance.

**Every simulated output carries the label "Simulated data for demonstration".** Synthetic values are never presented as GSRTC facts.

## Current status: Milestone 1 (reproducible synthetic data) on top of the M0 scaffold

What exists and works today:

- Project scaffold, `config.py` (seed 42, pilot bounding box, route-score weights, thresholds, paths).
- A single Streamlit entry point (`app.py`) with the nine navigation pages. Pages are still shells: title, purpose, simulation badge, "What this means" box, "Data and assumptions" expander and an empty state when data is missing. **No page shows numbers yet** (M3).
- Diagnostics panel, Parquet I/O helpers (`modules/data/io.py`), provenance helper (`modules/data/provenance.py`).
- **Synthetic source tables (M1)**: one offline, deterministic command generates 12 tables (zones, stops, routes, route_stops, trips, tickets, cctv_counts, survey_responses, competitor_services, reviews, assets_assessment, digital_assessment) under `data/synthetic/`, with provenance sidecars, a validation command and planted findings documented in `data/synthetic/planted_findings.md`.
- Optional, explicit, network-using command to cache real OpenStreetMap coordinates.
- Tests (config, imports, I/O and provenance, diagnostics, page smoke tests, data generation/validation/planted findings).

**Not built yet** (later milestones, see `prompts/`): analytics and KPIs (M2), dashboard content (M3), route intelligence (M4), competition/pricing/survey analysis (M5), CCTV counting and ML (M6), PDF/CSV reports and "Ask the Data" (M7). `python -m modules.analytics.run` is still a stub.

## Synthetic data commands (Milestone 1)

```powershell
# 1. (optional, needs internet + `pip install osmnx`) cache real OSM coordinates once; commit-friendly, ~5-10 min, polite rate limits
python -m modules.data_gen.fetch_osm            # add --refresh to refetch already-cached places

# 2. generate all source tables (offline, ~2-5 s, seed 42); validates at the end and exits non-zero on failure
python -m modules.data_gen.generate
#    options: --seed N   --out DIR (data root)   --days N   --no-osm (force manual_demo_input fallback)   --no-validate

# 3. validate existing tables (columns, keys, enums, non-negativity, occupancy, bbox, JSON, planted findings)
python -m modules.data_gen.validate
```

What the data is: a **synthetic demonstration** over 42 service days (2026-08-03 to 2026-09-13; 29 weekdays, 11 weekend days, 2 illustrative Janmashtami festival days) for a small Rajkot-area local network (10 demo routes, 28 stops, 14 zones) and intercity corridors Rajkot-Somnath (primary, ~190-205 km, express / AC seater / AC sleeper), Rajkot-Junagadh, Rajkot-Jamnagar and Rajkot-Ahmedabad (~290k tickets, ~17k trips). Routes are demonstration routes, not real GSRTC/RMTS routes; passenger, ticket, survey, review, competitor and CCTV values are all synthetic. The schema, enums, JSON encoding and the M1 migration note are in `docs/DATA_SCHEMA.md`; the planted findings (what, where, mechanism, detection check) are in `data/synthetic/planted_findings.md`.

Geography: real OSM bus stations/places are fetched only by `fetch_osm` into `data/raw/osm_places.parquet` (the small cache file is tracked in git so a fresh clone generates with real coordinates). `generate` never touches the network; if the cache is missing, or a place did not match, it falls back to a documented hand-entered coordinate table. Every zone/stop carries a `coord_source` column: `openstreetmap` (exact cached OSM value), `openstreetmap_offset` (synthetic point placed near an OSM anchor) or `manual_demo_input` (fallback, never labelled OSM). Stops/zones are synthetic demo entities regardless. Map and attribution: (c) OpenStreetMap contributors, ODbL. Jamnagar and Ahmedabad stands lie outside `PILOT_BBOX` by design (documented exceptions).

Reproducibility: all randomness comes from `np.random.default_rng([seed, stage])`; table contents contain no timestamps (wall-clock lives only in `*.provenance.json`), so two runs with the same seed give identical parquet bytes.

## Road network and route intelligence (Milestone 4)

Real OpenStreetMap roads are used for route paths and illustrative candidate routes (optional `geo` extras: osmnx, networkx).

```bash
python -m modules.routing.fetch_network   # explicit download, once; never run by the dashboard (public Overpass can be slow: retries/backoff built in)
python -m modules.routing.run             # rebuild data/processed/route_paths.parquet and route_candidates.parquet from the CACHED graphs
```

- Graph caches live in `data/raw/osm_graph_*.graphml` with provenance sidecars. The Rajkot city graph (about 29 MB) is git-ignored; the corridor and the two small link graphs (Metoda, Shapar) are tracked.
- Run `python -m modules.routing.run` after `python -m modules.analytics.run`. It never downloads: without osmnx or the caches, paths become labelled `straight_line_fallback` (haversine x 1.3) and fallback candidates are flagged `not_comparable_fallback` (not scored or ranked).
- Route Intelligence shows each route's road path and stop sequence, and a bounded set of illustrative candidates for two demo corridors (not a network-wide optimisation; fleet, driver, depot and turnaround are not modelled). Candidate score weights are in `config.CANDIDATE_SCORE_WEIGHTS`.
- Roads and place names are real (c) OpenStreetMap contributors, ODbL; routes, demand and candidates are simulated.

## Python version

The kit specifies Python 3.11. This repository is developed and tested on **Python 3.12** (the only interpreter available on the development machine). Python 3.11 is expected to work but has not been tested.

## Setup

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Git Bash:

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Note: `pyarrow` is pinned below 23 because pyarrow 26.x's Parquet DLL was blocked by a Windows Application Control policy on the development machine. Versions 17 to 22 were verified there.

Optional extras are listed, grouped by purpose, in `requirements-optional.txt`. For `fetch_osm` install the geo group: `pip install osmnx` (verified: osmnx 2.1.1 with geopandas 1.2, shapely 2.2, pyproj 3.8, pyogrio 0.13 on Python 3.12 / Windows; none of their DLLs were blocked). `osmnx` is deliberately not in `requirements.txt`; generation and the app run without it.

## Run

```powershell
python -m streamlit run app.py
```

Without activating the venv, use `.\.venv\Scripts\python.exe -m streamlit run app.py` (PowerShell) or `.venv/Scripts/python.exe -m streamlit run app.py` (Git Bash).

## Test

```powershell
python -m pytest
```

## Optional LLM key

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_MODEL`) to enable "Ask the Data" once it is built (M7). The app runs without it. `.env` is git-ignored. The app does not load `.env` automatically yet; set the variable in your shell for now.

## Structure

```
app.py                 single entry point: st.navigation + st.Page (nine pages)
config.py              seed, bounding box, score weights, thresholds, paths, badge text
pages/                 page scripts (0_Overview.py ... 8_Reports.py); presentation only
modules/
  ui/                  layout helpers (header, badge, empty states), health panel, page registry
  diagnostics.py       optional-dependency / API-key / data-table checks (no Streamlit)
  data/                io.py (parquet read/write), provenance.py
  data_gen/            M1: generate.py (CLI), validate.py (CLI), fetch_osm.py (network), geography/network/trips/tickets/
                       cctv/surveys/competition/assets generators, constants.py (fares, costs, crush factor, calendar), checks.py
  analytics/ routing/ survey/ competition/ cv/ llm/ reporting/   later milestones
data/
  raw/                 cached OSM places (osm_places.parquet tracked) and permitted video (git-ignored)
  synthetic/           generated source tables (git-ignored) + planted_findings.md (tracked)
  processed/           derived analytics tables (git-ignored)
tests/  docs/  prompts/
```

Navigation: `app.py` calls `st.navigation`, which replaces Streamlit's automatic `pages/` sidebar menu, so there is one menu only. Page file names follow `docs/ARCHITECTURE.md`; the Overview is `pages/0_Overview.py`. The page order and titles live in `modules/ui/pages_registry.py`.

Generated Parquet files under `data/synthetic/` are git-ignored because one command regenerates them from `SEED = 42`.

## Pilot and demo story

- **Primary corridor:** Rajkot-Somnath (about 190 km). The configured bounding box covers Rajkot and Somnath/Veraval.
- **Local pilot:** Rajkot-area local demonstration routes and stops.
- **Data:** synthetic passenger, ticketing, operations, survey, review, competitor and CCTV records; real geography comes from OpenStreetMap (cached) and is labelled separately via `coord_source`.
- **Demo story:** demand and survey evidence, observed crowding/counts, supply gap, route/service/fare scenario, projected outcomes, evidence-backed report.

## Ridership model and baseline forecast (M6, optional ML)

`python -m modules.analytics.run` also writes `baseline_forecast` (next-week same-weekday average with a band; a baseline estimate, not a model) and, when scikit-learn is installed, `predictions`, `ridership_model_metrics` and `ridership_feature_importance` (also runnable alone: `python -m modules.ml.ridership`). Route-day boardings; train 3-30 Aug 2026, test 31 Aug-13 Sep; compared with naive baselines; shown in the Route Intelligence tab "Observed vs model estimate". Synthetic-data demonstration metrics, not evidence of real-world accuracy. Prophet, SHAP and H3 are not used (see `modules/ml/ridership.py`).

## CCTV proof of concept (M6, optional, CPU)

Counts people/vehicles crossing a line on one permitted pre-recorded clip. Aggregate counts only: no face or identity recognition, no stored track ids. It runs in a separate virtualenv so the core app never imports torch/cv2. Method and honest limits: `docs/CCTV_METHOD.md`.

```powershell
py -3.12 -m venv .venv-cv        # on a deep path use a short one and `mklink /J .venv-cv C:\gsrtc_cv` (see requirements-cv.txt)
.venv-cv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv-cv\Scripts\python.exe -m pip install -r requirements-cv.txt
# the first run downloads the official yolov8n.pt (gitignored) into data/processed/cctv/ unless --model points at a file
.venv-cv\Scripts\python.exe -m modules.cv.count_video --video data/raw/video/a-morning-on-route-r014.mp4 --config modules/cv/configs/a-morning-on-route-r014.lines.json --stride 3 --annotate
```

Output: `data/processed/cctv_detector_counts.parquet` + `.provenance.json` and `data/processed/cctv/annotated_<clip>.mp4` (all gitignored). The CCTV Analytics page shows them when present and a clear "Detector output not available" state otherwise. Important: the only permitted clip is a produced explainer animation with no real pedestrians or vehicles, so the detector correctly counts zero and nothing about real-footage accuracy has been validated. `docs/cctv_spot_check_worksheet.md` is for a human count.

## Boundaries

This is a demonstration. It does not prove model accuracy, operational feasibility or actual GSRTC demand. CCTV counting (when built) is aggregate-only, with no face or identity recognition, on a clip the developer is permitted to process. See `RULES.md`.
