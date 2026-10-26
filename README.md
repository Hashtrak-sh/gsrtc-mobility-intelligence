# GSRTC Mobility Intelligence

A local-first, synthetic-data Streamlit prototype that demonstrates the approved GSRTC professional market survey scope as a connected, explainable decision-support workflow. It is a tender demonstration, not a production system, and says nothing about actual GSRTC demand or performance.

**Every simulated output carries the label "Simulated data for demonstration".** Synthetic values are never presented as GSRTC facts.

## Current status: Milestone 0 (scaffold) only

What exists and works today:

- Project scaffold, `config.py` (seed 42, pilot bounding box, route-score weights, thresholds, paths).
- A single Streamlit entry point (`app.py`) with the nine navigation pages. Each page shows its title, purpose, the simulation badge, a "What this means" box, a "Data and assumptions" expander and a clear **"Data not yet generated"** empty state. **No page shows any numbers yet.**
- A diagnostics panel (Overview, "System health and diagnostics") showing which optional packages are installed, whether `ANTHROPIC_API_KEY` is set (the key is never displayed), the permitted CCTV clips found, and which expected data tables exist.
- Parquet I/O helpers (`modules/data/io.py`) and a provenance helper (`modules/data/provenance.py`).
- Tests (config, imports, I/O and provenance, diagnostics, page smoke tests via Streamlit `AppTest`).

**Not built yet** (later milestones, see `prompts/`): synthetic data generation (M1), analytics and KPIs (M2), dashboard content (M3), route intelligence and OSM geography (M4), competition/pricing/survey (M5), CCTV counting and ML (M6), PDF/CSV reports and "Ask the Data" (M7). The commands shown on the empty-state screens (for example `python -m modules.data_gen.generate`) are the planned commands; until their milestone they exist only as stubs that raise `NotImplementedError`.

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

Optional extras (not needed for the current milestone) are listed, grouped by purpose, in `requirements-optional.txt`.

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
  data_gen/ analytics/ routing/ survey/ competition/ cv/ llm/ reporting/   later milestones
data/
  raw/                 cached OSM inputs and permitted video (git-ignored contents)
  synthetic/           generated source tables (git-ignored) + planted_findings.md (tracked, M1)
  processed/           derived analytics tables (git-ignored)
tests/  docs/  prompts/
```

Navigation: `app.py` calls `st.navigation`, which replaces Streamlit's automatic `pages/` sidebar menu, so there is one menu only. Page file names follow `docs/ARCHITECTURE.md`; the Overview is `pages/0_Overview.py`. The page order and titles live in `modules/ui/pages_registry.py`.

Generated Parquet files are git-ignored because one command regenerates them from `SEED = 42`.

## Pilot and demo story

- **Primary corridor:** Rajkot-Somnath (about 190 km). The configured bounding box covers Rajkot and Somnath/Veraval.
- **Local pilot:** Rajkot-area local routes and stops.
- **Data:** synthetic passenger, ticketing, operations, survey and competitor records; real geography may come from OpenStreetMap and must be labelled separately.
- **Demo story:** demand and survey evidence, observed crowding/counts, supply gap, route/service/fare scenario, projected outcomes, evidence-backed report.

## Boundaries

This is a demonstration. It does not prove model accuracy, operational feasibility or actual GSRTC demand. CCTV counting (when built) is aggregate-only, with no face or identity recognition, on a clip the developer is permitted to process. See `RULES.md`.
