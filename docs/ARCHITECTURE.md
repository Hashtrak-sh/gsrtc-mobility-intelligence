# Architecture

## Principles

- Local-first and easy to run on a developer laptop.
- A single source of truth for every KPI.
- Shared, documented data contract between generator, analytics, and UI.
- Analytics are plain Python functions; Streamlit pages orchestrate presentation only.
- Expensive preparation happens in commands, not on every page render.
- Optional ML/CV/LLM modules do not block the core application.

## Logical flow

```text
Synthetic source tables + optional cached OSM geography
                         |
                         v
              Validation / provenance
                         |
                         v
        Deterministic analytics and scenario engine
                         |
                         v
          Processed Parquet tables + report inputs
                         |
                         v
     Streamlit UI: Overview / Demand / Routes / Gaps
       O-D / Competition / Assets / CCTV / Reports
                         |
                         v
              PDF, CSV, annotated video
```

## Suggested repository

```text
gsrtc-mobility-intelligence/
├── app.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── CLAUDE.md
├── RULES.md
├── data/
│   ├── raw/                 # optional cached OSM/map inputs
│   ├── synthetic/           # generated source tables + planted_findings.md
│   └── processed/           # derived analytics for the dashboard
├── modules/
│   ├── data_gen/
│   │   ├── generate.py
│   │   └── validate.py
│   ├── data/
│   │   ├── io.py
│   │   └── provenance.py
│   ├── analytics/
│   │   ├── demand.py
│   │   ├── route_kpis.py
│   │   ├── gaps.py
│   │   ├── od.py
│   │   ├── scoring.py
│   │   └── scenarios.py
│   ├── routing/
│   │   ├── network.py
│   │   └── candidates.py
│   ├── survey/
│   │   ├── summaries.py
│   │   └── mode_choice.py
│   ├── competition/
│   │   └── analysis.py
│   ├── cv/
│   │   └── count_video.py
│   ├── llm/
│   │   └── client.py
│   └── reporting/
│       ├── pdf.py
│       └── exports.py
├── pages/
│   ├── 1_Demand_and_Surveys.py
│   ├── 2_Route_Intelligence.py
│   ├── 3_Demand_Supply_Gaps.py
│   ├── 4_Passenger_Flow_OD.py
│   ├── 5_Competition_and_Pricing.py
│   ├── 6_Infrastructure_and_Digital.py
│   ├── 7_CCTV_Analytics.py
│   └── 8_Reports.py
├── tests/
├── docs/
└── prompts/
```

Claude Code may make a small structural adjustment if required by the selected Streamlit version, but it must document it and keep one canonical entry point.

## Data storage

- Parquet is the durable table format for this prototype.
- DuckDB or pandas can query these files. Avoid a database server.
- `data/synthetic/` contains source records, not model outputs.
- `data/processed/` contains calculated metrics, predictions, and recommendations.
- Do not mix raw source columns and model outputs without documentation.
- Do not download data from external sources when the dashboard starts.
- OSMnx outputs must be cached in `data/raw/`; provide a fallback route/map experience if the network is unavailable.

## Module contract

Each module should expose:
- importable functions with type hints;
- a small runnable command (`python -m modules.<name>...` or documented `run.py`);
- explicit input/output tables;
- validation and clear errors;
- unit tests for calculations and edge cases.

The dashboard reads processed outputs. A user-triggered scenario may calculate a bounded result in memory, but it must use the same documented functions as batch processing.

## Dependency strategy

Install a minimal P0 dependency set first: Streamlit, pandas, NumPy, DuckDB, PyArrow, Plotly, pytest, ReportLab. Add mapping/ML/CV/LLM libraries only when the related milestone begins. Keep optional dependencies behind guarded imports and document installation requirements.

## Security and privacy

- No secrets in source control.
- `.env` and private video files are ignored by Git.
- LLM API key is optional.
- CCTV is aggregate counting only; no identity recognition or persistent person identifiers.
- For a public demo, do not expose raw CCTV clips unless usage rights and privacy review allow it.
