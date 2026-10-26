"""Infrastructure & Digital: station/depot assessment, digital maturity, and a ranked improvement list."""
import pandas as pd
import streamlit as st

from modules.analytics import assets as A
from modules.analytics import roadmap as RM
from modules.ui import charts, fmt, narrative as N
from modules.ui import layout as L
from modules.ui.roadmap_chart import roadmap_figure

spec, f = L.page_setup("infrastructure", show_filters=())
t = L.require_tables(spec)
assets, digital = t["assets_assessment"], t["digital_assessment"]
if assets.empty and digital.empty:
    L.empty_state("No assessments", "The assessment tables are empty.")
    st.stop()

names = dict(zip(assets["asset_id"], assets["asset_name"]))
s = A.assets_summary(assets, digital)
dim_label = A.DIM_LABELS.get(s["lowest_dimension"], str(s["lowest_dimension"]).replace("_", " ").capitalize())

L.kpi_row([
    {"label": "Average infrastructure score", "value": f"{fmt.number(s['mean_asset_score'], 1)} / 5",
     "help": f"Mean of all asset x dimension scores across {s['n_assets']} assessed assets (synthetic, 0-5)."},
    {"label": "Weakest dimension", "value": f"{dim_label} ({fmt.number(s['lowest_dimension_score'], 1)})",
     "help": "Dimension with the lowest average score across assets."},
    {"label": "Average digital maturity", "value": f"{fmt.number(s['mean_digital_maturity'], 1)} / 5",
     "help": "Mean maturity across capabilities and assessed assets (0 = absent, 5 = fully integrated)."},
    {"label": "Items below the attention threshold", "value": fmt.number(s["n_below_threshold"]),
     "help": f"Infrastructure and digital scores below {A.LOW_SCORE_THRESHOLD} of 5 (an illustrative cut-off)."},
])

st.subheader("Assessment by dimension")
L.show_chart(charts.score_heatmap(A.asset_matrix(assets), xlabels=A.DIM_LABELS), key="in_assets")
L.note("Stations, depots and stops (rows) scored 0-5 on each dimension (columns); low scores are warmer. Rows are ordered from weakest to strongest on average.")

st.subheader("Digital capability maturity")
dm = A.digital_matrix(digital, names)
L.show_chart(charts.score_heatmap(dm), key="in_digital")
L.note("Digital maturity by asset and capability on a 0-5 scale (0 = absent, 5 = fully integrated).")

st.subheader("Ranked improvements")
imp = A.improvement_list(assets, digital, names)
top_n = st.slider("Items to show", 5, min(30, len(imp)) if len(imp) > 5 else 5, min(10, len(imp)), key="in_top") if len(imp) > 5 else len(imp)
shown = imp.head(top_n)
st.dataframe(pd.DataFrame({
    "Rank": shown["rank"], "Area": shown["area"], "Asset": shown["asset"], "Item": shown["item"], "Score (0-5)": shown["score"],
    "Points to target": shown["points_to_target"], "Evidence note": shown["evidence_note"]}),
    hide_index=True, width="stretch", column_config={"Score (0-5)": st.column_config.NumberColumn(format="%.1f"),
                                                     "Points to target": st.column_config.NumberColumn(format="%.1f")})
L.note("Lowest scores first. The evidence note is the assessment note recorded with each score.")

st.subheader("Digital transformation roadmap")
rm = RM.build_roadmap(digital)
if (rm["status"] == "scheduled").any():
    L.show_chart(roadmap_figure(rm), key="in_roadmap")
    st.markdown(RM.takeaway(rm))
    rows = pd.DataFrame({
        "Phase": [f"Phase {p}: {n}" if pd.notna(p) else "Not needed (at target)" for p, n in zip(rm["phase"], rm["phase_name"])],
        "Initiative": rm["id"] + " " + rm["initiative"], "Capability": rm["capability"].str.capitalize(),
        "Maturity now": rm["current"], "Target": rm["target_maturity"],
        # Dropped (already at target) initiatives have no schedule: show a dash, never a NaN placeholder
        "Start month": rm["start_month"].map(lambda m: f"{m:.0f}" if pd.notna(m) else "—"),
        "End month": rm["end_month"].map(lambda m: f"{m:.0f}" if pd.notna(m) else "—"),
        "Depends on": rm["dependencies"].map(lambda d: ", ".join(d) if len(d) else "—"), "KPI": rm["kpi"]})
    st.dataframe(rows, hide_index=True, width="stretch", column_config={
        "Maturity now": st.column_config.NumberColumn(format="%.1f"), "Target": st.column_config.NumberColumn(format="%.1f")})
else:
    L.note("All digital capabilities already meet their illustrative targets, so no initiatives are scheduled.")
L.note("Simulated data for demonstration. Current maturity is the average of the simulated digital assessment. The initiatives, "
       "durations, target maturities and KPIs are illustrative assumptions written for this demo, not GSRTC plans. "
       "An initiative cannot start before the initiatives it depends on finish.")

L.what_this_means(N.infra_meaning(s))
L.evidence_expander(
    sources=["assets_assessment (asset x dimension scores, evidence notes)", "digital_assessment (asset x capability maturity, evidence notes)",
             "Roadmap initiative catalogue in modules/analytics/roadmap.py (manual_demo_input, authored for the demo)"],
    formulas=["Ranking = scores sorted ascending (lowest first), ties by asset name and item.", "Points to target = 5 - score.",
              "Roadmap: current maturity = mean digital maturity per capability; gap = initiative target - current; an initiative already at target is dropped.",
              f"Roadmap scheduling: priority = gap + {RM.FOUNDATION_WEIGHT} x number of dependent initiatives; initiatives start once their dependencies finish, with at most {RM.MAX_PARALLEL} running at once; phase follows the start month (Phase 1 0-6, Phase 2 6-18, Phase 3 18-36 months).",
              f"Attention threshold = score below {A.LOW_SCORE_THRESHOLD} (illustrative)."],
    assumptions=["All scores are synthetic demonstration assessments on a documented 0-5 scale, not field audits.",
                 "Evidence notes are template text recorded with the synthetic scores, not inspection findings.",
                 "The ranking is by score only: it does not weigh passenger volume, cost or feasibility of the improvement.",
                 "The roadmap is a demonstration plan: the initiative catalogue, durations, target maturities, KPIs and the parallel-working limit are illustrative assumptions (manual demo input), not GSRTC plans, budgets or commitments.",
                 "The roadmap does not model cost, procurement lead times or staff capacity beyond the parallel-working limit.",
                 "Assessments are not linked to route or corridor filters."],
    filters="No dashboard filters apply to this page.")
