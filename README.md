# GSRTC Mobility Intelligence — Claude Code Starter Kit

This kit defines a local-first, synthetic-data prototype for demonstrating the approved GSRTC professional market survey scope through a connected, explainable decision-support workflow.

## Start here

1. Open this folder as the project root in Claude Code.
2. Read `CLAUDE.md`, `RULES.md`, and all documents listed in `CLAUDE.md`.
3. Start with `prompts/00_BOOTSTRAP.md`.
4. Run one milestone prompt at a time, in order. Do not ask Claude Code to implement every module in one giant pass.
5. After each milestone, run the app/tests, inspect the result, and commit the working state.

## Pilot and demo story

- **Primary corridor:** Rajkot–Somnath.
- **Local pilot:** Rajkot-area local routes and stops.
- **Long-distance comparison:** Rajkot–Somnath and a small set of other synthetic intercity corridors.
- **Data:** synthetic passenger, ticketing, operations, survey, and competitor records; real geography may be sourced from OpenStreetMap and must be labelled separately.
- **Core demo story:** demand and survey evidence + observed crowding/counts + supply gap + route/service/fare scenario + projected outcomes + evidence-backed report.

Every simulated output must carry the visible label **“Simulated data for demonstration”**. Do not present synthetic values as GSRTC facts.

## Recommended stack

- Python 3.11
- Streamlit
- pandas, NumPy, DuckDB, PyArrow
- Plotly; pydeck only where it adds real value
- scikit-learn for baseline models; XGBoost/SHAP only after the deterministic pipeline works
- NetworkX; OSMnx for cached geography/routing where practical
- OpenCV + Ultralytics + supervision as an optional, isolated CCTV proof of concept
- ReportLab for PDF reports
- pytest

Prophet, H3, external LLM APIs, and cloud deployment are optional enhancements, not blockers for a working prototype. Do not install or require every library before the first end-to-end path works.

## Local setup (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```

If the generated repository uses `app/Home.py` instead, use the exact command documented by the implementation. Prefer a single clear entry point and avoid maintaining two competing Streamlit entry points.

## Important boundaries

This is a tender demonstration, not a production system. It does not prove model accuracy, operational feasibility, or actual GSRTC demand. All assumptions must be visible. Never fabricate live inference, model results, CCTV counts, or source citations.
