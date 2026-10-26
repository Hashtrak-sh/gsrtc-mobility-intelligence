"""Reports: CSV downloads of the processed tables for the current filters, with provenance."""
import streamlit as st

from modules.reporting import exports as X
from modules.ui import data as D
from modules.ui import fmt, narrative as N
from modules.ui import filters as F
from modules.ui import layout as L

spec, f = L.page_setup("reports")
t = L.require_tables(spec)
ctx = {"route_summary": t["route_summary"], "route_stops": t["route_stops"], "stops": t["stops"]}
tables = {name: t[name] for name in X.EXPORTS}
built = X.build_exports(tables, f, ctx, lambda n: D.provenance(n, "processed"))

scope = F.scope_routes(t["route_summary"], f.corridor)
total_rows = sum(len(df) for df, _ in built.values())
boardings = int(scope["boardings"].sum())
L.kpi_row([
    {"label": "Tables ready to download", "value": fmt.number(len(built)), "help": "Processed tables that can be exported as CSV for the current filters."},
    {"label": "Routes in scope", "value": fmt.number(len(scope)), "help": "Routes included by the corridor filter (route_summary)."},
    {"label": "Passengers in scope (42 days)", "value": fmt.number(boardings),
     "help": "Sum of route boardings over all 42 synthetic days; equals the route_summary export total and the dashboard KPIs."},
    {"label": "Rows in all exports", "value": fmt.number(total_rows), "help": "Total rows across the filtered tables."},
])

st.subheader("CSV downloads")
for name, (layer, desc, scope_note) in X.EXPORTS.items():
    df, data = built[name]
    c1, c2, c3 = st.columns([4, 1, 2])
    with c1:
        st.markdown(f"**{name}**  \n{desc}")
        st.caption(f"Filtered by: {scope_note}")
    with c2:
        st.markdown(f"{fmt.number(len(df))} rows")
    with c3:
        st.download_button("Download CSV", data=data, file_name=f"{name}.csv", mime="text/csv", key=f"dl_{name}",
                           disabled=df.empty, help="Starts with # provenance lines; read with pandas.read_csv(path, comment='#').")

st.subheader("Provenance")
bundle = X.provenance_bundle(f, {n: D.provenance(n, "processed") for n in built}, {n: len(df) for n, (df, _) in built.items()})
st.download_button("Download provenance and filters (JSON)", data=bundle, file_name="provenance.json", mime="application/json", key="dl_prov")
st.caption("Each CSV begins with comment lines giving the source type, seed, generation time, active filters, row count and limitations.")

L.what_this_means(N.reports_meaning(len(built), total_rows, f.describe()))
L.evidence_expander(
    sources=[f"Processed tables: {', '.join(X.EXPORTS)}", "Provenance sidecars (`*.provenance.json`) for seed and generation time"],
    formulas=["Rows are filtered with the same functions the dashboard pages use, so exported rows equal the rows behind the charts."],
    assumptions=X.LIMITATIONS + ["Filters: route-level tables use the corridor only; hourly, stop, O-D and CCTV tables also use the day type and hours."],
    filters=f.describe())
