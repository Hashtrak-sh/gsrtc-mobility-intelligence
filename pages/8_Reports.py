"""Reports: PDF report, CSV downloads with provenance, methodology note, and the optional "Ask the Data" panel."""
from datetime import datetime, timezone

import streamlit as st

from modules.llm import ui as llm_ui
from modules.reporting import exports as X
from modules.reporting import pdf as P
from modules.reporting import sources
from modules.reporting import text as TXT
from modules.ui import data as D
from modules.ui import fmt, narrative as N
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("reports")
t = L.require_tables(spec)
ctx = {"route_summary": t["route_summary"], "route_stops": t["route_stops"], "stops": t["stops"]}
# Required tables come from the page spec; the M7 additions are optional and simply skipped when not generated.
tables = {}
missing_optional = []
for name, (layer, _d, _s) in X.EXPORTS.items():
    df = t.get(name)
    if df is None:
        df = D.try_load(name, layer)
    if df is None:
        missing_optional.append(name)
    else:
        tables[name] = df
built = X.build_exports(tables, f, ctx, lambda n: D.provenance(n, X.EXPORTS[n][0]))

scope = F.scope_routes(t["route_summary"], f.corridor)
total_rows = sum(len(df) for df, _ in built.values())
boardings = int(scope["boardings"].sum())
L.kpi_row([
    {"label": "Tables ready to download", "value": fmt.number(len(built)), "help": "Processed tables that can be exported as CSV for the current filters."},
    {"label": "Routes in scope", "value": fmt.number(len(scope)), "help": "Routes included by the corridor filter (route_summary)."},
    {"label": "Passengers in scope (42 days)", "value": fmt.number(boardings),
     "help": "Sum of route boardings over all 42 synthetic days; equals the route_summary export total, the PDF report and the dashboard KPIs."},
    {"label": "Rows in all exports", "value": fmt.number(total_rows), "help": "Total rows across the filtered tables."},
])

# ------------------------------------------------------------------------------------------------ PDF report
st.subheader("PDF report")
st.markdown("A multi-page report for the current filters: executive summary, route and demand findings, supply gaps and recommendations (with evidence, "
            "assumptions and constraints), competition and pricing, infrastructure and digital, survey findings, model and CCTV status, methodology, limitations "
            "and scale-up needs. Every page is marked as simulated data.")
fkey = f.describe()
if st.button("Generate PDF report", key="gen_pdf", type="primary"):
    try:
        with st.spinner("Building the report..."):
            now = datetime.now(timezone.utc)
            st.session_state["report_pdf"] = {"filters": fkey, "bytes": P.build_report_pdf(f, sources.load_tables(), now=now),
                                              "stamp": now.strftime("%Y%m%d-%H%M%S")}
    except Exception as exc:  # noqa: BLE001 - show a readable error instead of a stack trace
        L.error_state("The PDF report could not be built.", exc)
rep = st.session_state.get("report_pdf")
if rep and rep["filters"] == fkey:
    st.download_button("Download PDF report", data=rep["bytes"], file_name=f"gsrtc_mobility_report_{rep['stamp']}.pdf", mime="application/pdf", key="dl_pdf")
    st.caption(f"Built for: {rep['filters']} ({len(rep['bytes']) / 1024:.0f} KB).")
elif rep:
    st.caption("The filters changed since the last report was built. Generate it again to match the current filters.")
note_md = TXT.methodology_markdown(f.describe(), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
st.download_button("Download methodology and limitations note (Markdown)", data=note_md.encode("utf-8"), file_name="methodology_and_limitations.md",
                   mime="text/markdown", key="dl_method")

# ------------------------------------------------------------------------------------------------ CSV downloads
st.subheader("CSV downloads")
for name, (layer, desc, scope_note) in X.EXPORTS.items():
    c1, c2, c3 = st.columns([4, 1, 2])
    with c1:
        st.markdown(f"**{name}**  \n{desc}")
        st.caption(f"Filtered by: {scope_note}")
    if name not in built:
        with c2:
            st.markdown("not generated")
        with c3:
            st.download_button("Download CSV", data=b"", file_name=f"{name}.csv", key=f"dl_{name}", disabled=True,
                               help="This table has not been generated yet (run the analytics / optional model commands).")
        continue
    df, data = built[name]
    with c2:
        st.markdown(f"{fmt.number(len(df))} rows")
    with c3:
        st.download_button("Download CSV", data=data, file_name=f"{name}.csv", mime="text/csv", key=f"dl_{name}",
                           disabled=df.empty, help="Starts with # provenance lines; read with pandas.read_csv(path, comment='#').")

st.subheader("Provenance")
bundle = X.provenance_bundle(f, {n: D.provenance(n, X.EXPORTS[n][0]) for n in built}, {n: len(df) for n, (df, _) in built.items()})
st.download_button("Download provenance and filters (JSON)", data=bundle, file_name="provenance.json", mime="application/json", key="dl_prov")
st.caption("Each CSV begins with comment lines giving the source type, seed, generation time, active filters, row count and limitations.")
if missing_optional:
    st.caption("Not generated (optional): " + ", ".join(missing_optional) + ".")

# ------------------------------------------------------------------------------------------------ optional LLM panel
st.divider()
llm_ui.ask_the_data_panel(sources.load_tables())

L.what_this_means(N.reports_meaning(len(built), total_rows, f.describe()))
L.evidence_expander(
    sources=[f"Processed tables: {', '.join(X.EXPORTS)}", "Provenance sidecars (`*.provenance.json`) for seed and generation time"],
    formulas=["Rows are filtered with the same functions the dashboard pages use, so exported rows equal the rows behind the charts.",
              "The PDF report calls the same query functions as the pages, so its totals equal the dashboard KPIs for the same filters."],
    assumptions=X.LIMITATIONS + ["Filters: route-level tables use the corridor only; hourly, stop, O-D, competition and CCTV tables also use the day type and hours; "
                                 "model and survey-model tables are not filtered.",
                                 "Ask the Data (optional) answers only from a compact summary of the processed tables and is checked against it; without an API key "
                                 "only fixed, labelled rule-based lookups are offered."],
    filters=f.describe())
