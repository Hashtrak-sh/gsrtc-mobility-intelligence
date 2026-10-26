"""Cost-Benefit & Fares: intercity cost per bus-km by class, peak vs normal economics, break-even and recommended fares,
a peak / off-peak fare scenario, a new-bus-class what-if and an illustrative social cost-benefit appraisal.

All numbers come from modules.analytics.cost_model / fare_analysis / socio_economic; this page only chooses parameters and
presents results. Every cost and appraisal parameter is an ILLUSTRATIVE, editable assumption (not GSRTC data).
"""
import dataclasses

import pandas as pd
import streamlit as st

import config
from modules.analytics import cost_model as cm
from modules.analytics import fare_analysis as FA
from modules.analytics import socio_economic as SE
from modules.data import io
from modules.ui import cost_charts as CC
from modules.ui import filters as F
from modules.ui import fmt
from modules.ui import layout as L

spec, f = L.page_setup("costbenefit", show_filters=("corridor", "day_type"))
t = L.require_tables(spec)
ss = st.session_state
DASH = CC.DASH

corridor = f.corridor if f.corridor in config.INTERCITY_CORRIDORS else config.PRIMARY_CORRIDOR
if corridor != f.corridor:
    st.info(f"Cost-benefit is analysed on intercity corridors. Showing {corridor}; choose another corridor in the sidebar.")
day_type = f.day_type

_TABLES = (("synthetic", "trips"), ("synthetic", "tickets"), ("synthetic", "route_stops"), ("synthetic", "routes"),
           ("synthetic", "competitor_services"), ("processed", "route_summary"))


def _stamp() -> tuple:
    """Cache key: file modification times of the tables used, so regenerated data invalidates the caches."""
    return tuple(io.table_path(n, ly).stat().st_mtime_ns for ly, n in _TABLES)


@st.cache_resource(show_spinner="Preparing intercity trip economics...")
def get_inputs(stamp: tuple) -> dict:  # noqa: ARG001 - stamp is the cache key
    return FA.load_inputs()


STAMP = _stamp()
inputs = get_inputs(STAMP)
base_model: cm.CostModel = inputs["model"]
GP0 = cm.GlobalParams()
n_days_total = float(inputs["tm"]["service_date"].nunique())


# ---------------------------------------------------------------- parameters (read from widget state so the headline can sit on top)
def val(key, default):
    return ss.get(key, default)


gp_items = (
    ("diesel_inr_per_l", float(val("cb_c_diesel", GP0.diesel_inr_per_l))),
    ("electricity_inr_per_kwh", float(val("cb_c_elec", GP0.electricity_inr_per_kwh))),
    ("dead_km_share", float(val("cb_c_dead", GP0.dead_km_share * 100)) / 100),
    ("overhead_share", float(val("cb_c_over", GP0.overhead_share * 100)) / 100),
    ("driver_inr_per_hour", float(val("cb_c_driver", GP0.driver_inr_per_hour))),
    ("conductor_inr_per_hour", float(val("cb_c_cond", GP0.conductor_inr_per_hour))),
    ("peak_running_time_factor", float(val("cb_c_peakf", GP0.peak_running_time_factor))),
)
target_lf = float(val("cb_c_target", config.SERVICE_TARGET_LOAD_FACTOR * 100)) / 100
ov_cls = val("cb_c_class", "express")
_cp0 = base_model.class_params[ov_cls]
_ov: dict = {}


def _chk(field: str, key: str, default: float) -> None:
    v = ss.get(key, default)
    if v is not None and abs(float(v) - float(default)) > 1e-6:
        _ov[field] = float(v)


_chk("kwh_per_km" if _cp0.energy == "electric" else "fuel_km_per_l", f"cb_c_ov_{ov_cls}_eff",
     _cp0.kwh_per_km if _cp0.energy == "electric" else _cp0.fuel_km_per_l)
_chk("bus_price_inr", f"cb_c_ov_{ov_cls}_price", _cp0.bus_price_inr)
_chk("daily_km", f"cb_c_ov_{ov_cls}_daily", _cp0.daily_km)
_chk("maintenance_inr_per_km", f"cb_c_ov_{ov_cls}_maint", _cp0.maintenance_inr_per_km)
_lease0 = _cp0.lease_inr_per_km or 0.0
_lv = ss.get(f"cb_c_ov_{ov_cls}_lease", _lease0)
if abs(float(_lv) - _lease0) > 1e-6:
    _ov["lease_inr_per_km"] = float(_lv) if float(_lv) > 0 else None
ov_items = tuple(sorted(_ov.items(), key=lambda kv: kv[0]))


def build_model(inp: dict, gpi: tuple, o_cls: str, o_items: tuple) -> cm.CostModel:
    """Model at DEFAULT calibration (maintenance balancing item fixed) with the chosen overrides applied on top."""
    m = inp["model"].with_global(**dict(gpi))
    return m.with_class(o_cls, **dict(o_items)) if o_items else m


try:
    model = build_model(inputs, gp_items, ov_cls, ov_items)
    model_ok = True
except ValueError as exc:
    L.error_state(f"These cost assumptions are not valid ({exc}); showing the defaults instead.", exc)
    gp_items, ov_items, target_lf = tuple((k, float(getattr(GP0, k))) for k, _ in gp_items), (), config.SERVICE_TARGET_LOAD_FACTOR
    model, model_ok = build_model(inputs, gp_items, ov_cls, ov_items), False


@st.cache_data(show_spinner=False, max_entries=64)
def core(stamp: tuple, gpi: tuple, o_cls: str, o_items: tuple, tlf: float):
    """Band economics, private comparison and recommended fare band for every intercity route (keyed by the parameter values)."""
    inp = get_inputs(stamp)
    m = build_model(inp, gpi, o_cls, o_items)
    econ = FA.band_economics(inp["tm"], m, inp["routes"], target_load_factor=tlf)
    pc = FA.private_comparison(econ, inp["competitors"])
    return econ, pc, FA.recommend_fare_band(pc)


econ_all, pc_all, rec_all = core(STAMP, gp_items, ov_cls, ov_items, target_lf)


def _scope(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["corridor"] == corridor) & (df["day_type"] == day_type)].reset_index(drop=True)


sel, pc_sel, rec_sel = _scope(econ_all), _scope(pc_all), _scope(rec_all)
if sel.empty:
    L.empty_state("No intercity service for this corridor and day type", f"No trips were found for {corridor} on a {day_type}.")
    st.stop()
bsel = inputs["bands"][(inputs["bands"]["corridor"] == corridor) & (inputs["bands"]["day_type"] == day_type)]
H = CC.headline(sel)
len_km = CC.corridor_length(sel)

# ---- socio-economic parameters
SE0 = SE.SocioEconomicParams()
_share_items: dict = {}
for _fld in SE.SHARE_FIELDS:
    _pv = float(ss.get(f"cb_s_{_fld}", round(getattr(SE0, _fld) * 100))) / 100
    if abs(_pv - getattr(SE0, _fld)) > 1e-9:
        _share_items[_fld] = _pv
share_warning = None
if sum(_share_items.values()) > 1 + 1e-9:
    share_warning = "The diversion shares you pinned add up to more than 100%; the default shares are used instead."
    _share_items = {}
_se: dict = dict(_share_items)
for _fld, _key in (("value_of_time_inr_per_hour", "cb_s_vot"), ("carbon_price_inr_per_tonne", "cb_s_carbon"),
                   ("occupancy_car", "cb_s_occ"), ("voc_car_inr_per_km", "cb_s_voc")):
    _v = float(ss.get(_key, getattr(SE0, _fld)))
    if abs(_v - getattr(SE0, _fld)) > 1e-9:
        _se[_fld] = _v
se_items = tuple(sorted(_se.items()))


def build_se(items: tuple) -> SE.SocioEconomicParams:
    d = dict(items)
    p = SE.SocioEconomicParams()
    fixed = {k: v for k, v in d.items() if k in SE.SHARE_FIELDS}
    if fixed:
        p = SE.rebalance_shares(p, **fixed)  # the other shares are scaled so all shares always sum to 1
    return dataclasses.replace(p, **{k: v for k, v in d.items() if k not in SE.SHARE_FIELDS})


@st.cache_data(show_spinner=False, max_entries=32)
def cba_core(stamp: tuple, gpi: tuple, o_cls: str, o_items: tuple, tlf: float, sei: tuple):
    econ, _, _ = core(stamp, gpi, o_cls, o_items, tlf)
    inp = CC.cba_inputs(io.read_table("route_summary", "processed"), econ, float(get_inputs(stamp)["tm"]["service_date"].nunique()))
    p = build_se(sei)
    res = SE.compute_cba(inp, p)
    corr = SE.aggregate_to_corridor(res, p)
    sens = SE.sensitivity_table(inp, p)
    return {"inputs": inp, "route": res, "corr": corr, "sens": sens, "tornado": SE.tornado_table(sens), "comp": SE.component_table(corr)}


try:
    cba = cba_core(STAMP, gp_items, ov_cls, ov_items, target_lf, se_items)
    se_params = build_se(se_items)
except ValueError as exc:
    L.error_state(f"These appraisal assumptions are not valid ({exc}); showing the defaults instead.", exc)
    se_items = ()
    cba = cba_core(STAMP, gp_items, ov_cls, ov_items, target_lf, se_items)
    se_params = build_se(se_items)
corr_all = cba["corr"]
corr_row = corr_all[corr_all["corridor"] == corridor]
bcr = float(corr_row["bcr"].iloc[0]) if len(corr_row) else float("nan")

# ================================================================ 1. headline
st.header("Headline")
lf_peak, lf_norm = H.get("lf_peak"), H.get("lf_normal")
if lf_peak is not None and CC.ok(lf_peak):
    lf_val = f"{CC.d_pct(lf_peak)} vs {CC.d_pct(lf_norm)}"
else:
    lf_val = f"no peak hours; normal {CC.d_pct(lf_norm)}"
L.kpi_row([
    {"label": "Full cost per bus-km", "value": CC.d_inr(H["full_cost_per_km"], 1),
     "help": f"{corridor}, {day_type}: trip operating + fixed and overhead cost per vehicle-km, weighted by bus-km of the corridor's routes (illustrative cost model)."},
    {"label": "Contribution per day (not profit)", "value": CC.d_inr(H["contribution_per_day"]),
     "help": "Ticket revenue minus TRIP OPERATING cost only, per average day of this day type. Fixed and overhead costs are not included."},
    {"label": "Load factor: peak vs normal hours", "value": lf_val,
     "help": "Passenger-km / seat-km in peak departure hours vs all other hours (peak hours are derived from the data, see the next sections)."},
    {"label": "Benefit-cost ratio (illustrative)", "value": CC.d_x(bcr, 2),
     "help": f"{corridor}: (social benefits + ticket revenue) / full cost, averaged over all 42 service days (not filtered by day type). 1.0 means break-even for society."},
])
cover = CC._ratio(H["revenue_per_km"], H["full_cost_per_km"])
st.markdown(
    f"**Takeaway.** On {corridor} ({day_type}) a bus-km costs {CC.d_inr(H['full_cost_per_km'], 1)} in full "
    f"({CC.d_inr(H['trip_cost_per_km'], 1)} trip operating) and earns {CC.d_inr(H['revenue_per_km'], 1)} in tickets, so fares cover "
    f"{CC.d_pct(cover)} of full cost; the full-cost margin is {CC.d_inr(H['full_margin_per_day'])} per day "
    f"({'a gap that needs support' if CC.ok(H['full_margin_per_day']) and H['full_margin_per_day'] < 0 else 'fares cover full cost'}). "
    f"Illustrative cost parameters, simulated data.")
if not model_ok:
    st.caption("Default parameters are in use because the edited ones were invalid.")

# ================================================================ 2. cost per bus-km by class
st.header("What a bus-km costs, by class")
ct = cm.component_table(model, corridor=corridor, length_km=len_km)
L.show_chart(CC.cost_stack_chart(ct, title=f"Cost per bus-km by class (₹, illustrative; {corridor} toll, {fmt.number(len_km, 0)} km)"), key="cb_stack")
summ = cm.cost_summary(model, corridor=corridor, length_km=len_km)
st.dataframe(pd.DataFrame({
    "Bus class": [cm.CLASS_LABELS[c] for c in summ["bus_class"]],
    "Seats": summ["seats"].map(CC.d_num),
    "Trip operating (₹/km)": summ["trip_operating_per_km"].map(lambda v: CC.d_num(v, 1)),
    "Fixed and overhead (₹/km)": summ["fixed_and_overhead_per_km"].map(lambda v: CC.d_num(v, 1)),
    "Full cost (₹/km)": summ["full_cost_per_km"].map(lambda v: CC.d_num(v, 1)),
    "Rate used for contribution elsewhere (₹/km)": summ["base_rate_inr_per_km"].map(lambda v: CC.d_num(v, 1)),
    "Crew speed assumed (km/h)": summ["speed_kmph"].map(lambda v: CC.d_num(v, 0)),
}), hide_index=True, width="stretch")
L.note("Illustrative cost model, not GSRTC data. The trip operating layer (blue/teal) of the four timetable classes equals the per-km rate behind "
       "'contribution' on every other page (at default parameters; ordinary is shown at its intercity what-if speed and is not run on intercity corridors today); "
       "'maintenance and other running costs' is the balancing item. The fixed and overhead layer (orange/brown) - dead km, depreciation or lease, insurance/tax/permits, "
       "tolls, depot overhead - is NOT in contribution anywhere else. Hatched bars are what-if classes that do not exist in the timetable.")


def _reset_costs() -> None:
    for k in [k for k in ss.keys() if str(k).startswith("cb_c_")]:
        del ss[k]


with st.expander("Cost assumptions (illustrative, editable)"):
    st.caption(f"{cm.ILLUSTRATIVE_LABEL}. Changing a value re-prices every table and chart on this page.")
    c1, c2, c3, c4 = st.columns(4)
    c1.number_input("Diesel (₹/litre)", 40.0, 200.0, GP0.diesel_inr_per_l, 1.0, key="cb_c_diesel")
    c2.number_input("Electricity (₹/kWh)", 2.0, 30.0, GP0.electricity_inr_per_kwh, 0.5, key="cb_c_elec")
    c3.number_input("Dead km (% of revenue km)", 0.0, 30.0, GP0.dead_km_share * 100, 0.5, key="cb_c_dead")
    c4.number_input("Depot / admin overhead (% of direct cost)", 0.0, 40.0, GP0.overhead_share * 100, 0.5, key="cb_c_over")
    c5, c6, c7, c8 = st.columns(4)
    c5.number_input("Driver (₹/duty hour)", 50.0, 600.0, GP0.driver_inr_per_hour, 5.0, key="cb_c_driver")
    c6.number_input("Conductor (₹/duty hour)", 50.0, 600.0, GP0.conductor_inr_per_hour, 5.0, key="cb_c_cond")
    c7.number_input("Peak running-time factor", 0.5, 2.0, GP0.peak_running_time_factor, 0.05, key="cb_c_peakf",
                    help="Crew-hours multiplier in peak hours. 1.0 because the synthetic timetable has constant running times (no peak slow-down in the data).")
    c8.number_input("Target load factor for break-even (%)", 40.0, 100.0, config.SERVICE_TARGET_LOAD_FACTOR * 100, 1.0, key="cb_c_target",
                    help="Used for the break-even and recommended fares in section 4.")
    st.caption("The timetable has constant running times per route, so the peak running-time factor defaults to 1.0 (peak and normal hours then differ in load and revenue, not in cost per trip).")
    st.markdown("**Override one bus class**")
    sel_cls = st.selectbox("Bus class", list(cm.ALL_CLASSES), index=list(cm.ALL_CLASSES).index(ov_cls), format_func=cm.CLASS_LABELS.get, key="cb_c_class")
    cp = base_model.class_params[sel_cls]
    o1, o2, o3, o4, o5 = st.columns(5)
    if cp.energy == "electric":
        o1.number_input("Energy use (kWh/km)", 0.2, 4.0, float(cp.kwh_per_km), 0.05, key=f"cb_c_ov_{sel_cls}_eff")
    else:
        o1.number_input("Fuel economy (km/litre)", 1.0, 10.0, float(cp.fuel_km_per_l), 0.1, key=f"cb_c_ov_{sel_cls}_eff")
    o2.number_input("Bus price (₹)", 500_000.0, 30_000_000.0, float(cp.bus_price_inr), 100_000.0, key=f"cb_c_ov_{sel_cls}_price")
    o3.number_input("Lease (₹/km, 0 = own the bus)", 0.0, 200.0, float(cp.lease_inr_per_km or 0.0), 1.0, key=f"cb_c_ov_{sel_cls}_lease",
                    help="When above 0 the lease replaces depreciation.")
    o4.number_input("Daily km per bus", 100.0, 800.0, float(cp.daily_km), 10.0, key=f"cb_c_ov_{sel_cls}_daily")
    o5.number_input("Maintenance and other running (₹/km)", 0.0, 100.0, float(cp.maintenance_inr_per_km), 0.5, key=f"cb_c_ov_{sel_cls}_maint",
                    help="For the four timetable classes the default is the balancing item that reconciles the trip cost with the base rate.")
    st.button("Reset to defaults", on_click=_reset_costs, key="cb_c_reset")

# ================================================================ 3. peak vs normal
st.header("Peak vs normal hours")
peak_hours = [int(h) for h in bsel.loc[bsel["band"] == "peak", "dep_hour"]]
if peak_hours:
    wins = ", ".join(fmt.hour_window(a, b) for a, b in fmt.contiguous_windows(peak_hours))
    st.markdown(f"**Peak departure hours on {corridor} ({day_type}), derived from the data:** {wins}.")
else:
    st.markdown(f"**No peak departure hours on {corridor} ({day_type})**: the corridor has fewer than two served hours or all hours have the same load.")
if len(bsel):
    st.caption("Rule: " + str(bsel["rule"].iloc[0]) + ". Departure hours are shown as the hour in which the bus leaves; windows are start-inclusive.")
L.show_chart(CC.band_hours_chart(bsel), key="cb_hours")
metric_key = st.selectbox("Compare peak and normal by", list(CC.BAND_METRICS), format_func=lambda k: CC.BAND_METRICS[k][0], key="cb_band_metric")
L.show_chart(CC.band_compare_chart(sel, metric_key), key="cb_band_cmp")
bt = sel.copy()
bt["Route / class"] = bt.apply(CC.route_label, axis=1)
st.dataframe(pd.DataFrame({
    "Route / class": bt["Route / class"], "Band": bt["band"], "Trips per day": bt["trips_per_day"].map(lambda v: CC.d_num(v, 1)),
    "Load factor": bt["load_factor"].map(CC.d_pct), "Revenue per trip": bt["revenue_per_trip_inr"].map(CC.d_inr),
    "Trip operating cost per trip": bt["trip_operating_cost_per_trip_inr"].map(CC.d_inr),
    "Full cost per trip": bt["full_cost_per_trip_inr"].map(CC.d_inr),
    "Contribution per trip (not profit)": bt["contribution_per_trip_inr"].map(CC.d_inr),
    "Full-cost margin per trip": bt["full_cost_margin_per_trip_inr"].map(CC.d_inr),
    "Contribution per seat-km": bt["contribution_per_seat_km_inr"].map(lambda v: CC.d_num(v, 2)),
    "Full-cost margin per seat-km": bt["full_cost_margin_per_seat_km_inr"].map(lambda v: CC.d_num(v, 2)),
}), hide_index=True, width="stretch")
L.note("Contribution = ticket revenue - trip operating cost; full-cost margin = ticket revenue - full cost (trip operating + fixed and overhead). Neither is profit and neither "
       "includes subsidy. Trip costs are the same in peak and normal hours unless the peak running-time factor is changed.")

# ================================================================ 4. break-even and recommended fares
st.header("Break-even and recommended fares")
L.show_chart(CC.fare_range_chart(rec_sel), key="cb_fares")


def _band_text(r) -> str:
    if CC.ok(r["band_low_inr"]) and CC.ok(r["band_high_inr"]):
        return f"{fmt.inr(r['band_low_inr'])} to {fmt.inr(r['band_high_inr'])}"
    if CC.ok(r["band_low_inr"]):
        return f"from {fmt.inr(r['band_low_inr'])} (no cap)"
    return DASH


rt = rec_sel.copy()
st.dataframe(pd.DataFrame({
    "Route / class": rt.apply(CC.route_label, axis=1), "Band": rt["band"], "Current fare": rt["current_fare_inr"].map(CC.d_inr),
    f"Break-even fare at {target_lf:.0%} load": rt["break_even_fare_inr"].map(CC.d_inr),
    "Private comparator": rt["private_comparator_inr"].map(CC.d_inr), "Recommended band": rt.apply(_band_text, axis=1),
    "Status": rt["status"], "Evidence": rt["evidence"],
}), hide_index=True, width="stretch")
n_nv = int((~rec_sel["viable"]).sum())
if n_nv:
    st.warning(
        f"**Not viable on fare alone for {n_nv} of {len(rec_sel)} route-and-band rows.** In plain words: even at the target load factor of {target_lf:.0%}, the fare "
        "needed to cover full cost is higher than the competitive cap (a share of the private fare), so raising the fare would lose passengers to private operators. "
        "The options are: cut costs, raise the load factor, fund the gap through viability-gap support, or justify the service on social grounds (see section 7).")
else:
    st.success("All route-and-band rows have a viable fare band at these assumptions.")
with st.expander("Assumptions behind the fare band"):
    if len(rec_sel):
        st.markdown("- " + str(rec_sel["assumptions"].iloc[0]))
    notes = sorted(set(pc_sel["private_note"])) if len(pc_sel) else []
    for n in notes:
        st.markdown(f"- Private comparator: {n}")
    st.markdown(f"- Competitive cap = {config.COMPETITION_FARE_POSITION:.0%} of the private median; the band never recommends a cut below today's tariff unless today's fare is above the cap.")

# ================================================================ 5. peak / off-peak fare scenario
st.header("Peak / off-peak fare scenario")
st.caption(FA.WHAT_IF_LABEL)
s1, s2, s3, s4 = st.columns(4)
peak_chg = s1.slider("Peak fare change (%)", -30, 50, 10, 1, key="cb_scn_peak")
norm_chg = s2.slider("Normal-hours fare change (%)", -30, 50, 0, 1, key="cb_scn_norm")
peak_el = s3.slider("Peak elasticity (assumed)", -3.0, 0.0, float(FA.DEFAULT_PEAK_ELASTICITY), 0.1, key="cb_scn_pel",
                    help="Percentage change in demand for a 1% fare change. An assumption; peak travellers are assumed less price-sensitive.")
norm_el = s4.slider("Normal elasticity (assumed)", -3.0, 0.0, float(FA.DEFAULT_NORMAL_ELASTICITY), 0.1, key="cb_scn_nel")
cap_on = st.toggle(f"Cap fare increases at {config.COMPETITION_FARE_POSITION:.0%} of the private fare", value=True, key="cb_scn_cap")
try:
    scn = FA.differential_fares(pc_sel, peak_change_pct=float(peak_chg), normal_change_pct=float(norm_chg), peak_elasticity=float(peak_el),
                                normal_elasticity=float(norm_el), private_cap_ratio=config.COMPETITION_FARE_POSITION if cap_on else None)
except ValueError as exc:
    L.error_state(f"This scenario cannot be evaluated: {exc}")
    scn = None
if scn is not None:
    bands_present = [b for b in ("peak", "normal") if b in set(scn["band"])]
    by_band = FA.differential_totals(scn, by=["band"]).set_index("band")
    spill = scn.groupby("band")["spilled_passengers_per_day"].sum()
    total = FA.differential_totals(scn, by=None).iloc[0]
    rows = [(b.capitalize(), by_band.loc[b], float(spill.get(b, float("nan")))) for b in bands_present]
    rows.append(("Total", total, float(scn["spilled_passengers_per_day"].sum())))

    def _ba(r, b, a, fn) -> str:
        return f"{fn(r[b])} → {fn(r[a])}"

    st.dataframe(pd.DataFrame({
        "Band": [n for n, _, _ in rows],
        "Passengers per day": [_ba(r, "baseline_passengers_per_day", "passengers_per_day", CC.d_num) for _, r, _ in rows],
        "Load factor": [_ba(r, "baseline_load_factor", "load_factor", CC.d_pct) for _, r, _ in rows],
        "Ticket revenue per day": [_ba(r, "baseline_revenue_per_day_inr", "revenue_per_day_inr", CC.d_inr) for _, r, _ in rows],
        "Contribution per day (not profit)": [_ba(r, "baseline_contribution_per_day_inr", "contribution_per_day_inr", CC.d_inr) for _, r, _ in rows],
        "Full-cost margin per day": [_ba(r, "baseline_full_cost_margin_per_day_inr", "full_cost_margin_per_day_inr", CC.d_inr) for _, r, _ in rows],
        "Demand turned away per day": [CC.d_num(s, 1) for _, _, s in rows],
    }), hide_index=True, width="stretch")
    n_cap = int(scn["capped"].sum())
    L.note(f"Before → after, per average {day_type}. Illustrative scenario: fare changes apply to the average realised fare, demand responds by the assumed elasticities, "
           "seats are the cap, and service and costs are unchanged. "
           + (f"The private-fare cap limited the increase on {n_cap} of {len(scn)} route-and-band rows." if cap_on else "No private-fare cap is applied."))

# ================================================================ 6. new-bus what-if
st.header("What if this corridor ran a different bus?")
st.caption(FA.WHAT_IF_LABEL)
present = [b for b in ("peak", "normal") if b in set(sel["band"])]
w1, w2, w3, w4 = st.columns(4)
w_band = w1.selectbox("Time band", present, format_func=str.capitalize, key="cb_w_band")
w_cls = w2.selectbox("Bus class", list(cm.ALL_CLASSES), index=list(cm.ALL_CLASSES).index("volvo_ac"), format_func=cm.CLASS_LABELS.get, key="cb_w_class")
w_fare = w3.slider("Fare change (%)", -30, 50, 0, 1, key="cb_w_fare")
w_el = w4.slider("Elasticity (assumed)", -3.0, 0.0, float(FA.DEFAULT_PEAK_ELASTICITY if w_band == "peak" else FA.DEFAULT_NORMAL_ELASTICITY), 0.1,
                 key=f"cb_w_el_{w_band}")
what = None
try:
    what = FA.new_class_whatif(inputs["tm"], model, corridor=corridor, day_type=day_type, band=w_band, bus_class=w_cls,
                               elasticity=float(w_el), fare_change_pct=float(w_fare), target_load_factor=target_lf).iloc[0]
except ValueError as exc:
    L.empty_state("This what-if cannot be evaluated", str(exc))
if what is not None:
    bb = sel[sel["band"] == w_band]
    w = bb["trips"].astype(float)

    def wavg(col: str) -> float:
        return float((bb[col] * w).sum() / w.sum())

    inc = ", ".join(cm.CLASS_LABELS[c] for c in what["baseline_incumbent_classes"].split(", "))
    rows = [
        ("Bus class", inc, cm.CLASS_LABELS[w_cls]),
        ("Seats per bus", CC.d_num(wavg("seats"), 1), CC.d_num(what["seats"])),
        ("Full-route adult fare", CC.d_inr(what["incumbent_fare_full_length_inr"]), CC.d_inr(what["new_fare_full_length_inr"])),
        ("Passengers per day (served)", CC.d_num(what["baseline_passengers_per_day"], 1), CC.d_num(what["served_passengers_per_day"], 1)),
        ("Demand at this fare (passengers per day)", CC.d_num(what["baseline_passengers_per_day"], 1), CC.d_num(what["demand_passengers_per_day"], 1)),
        ("Trips per day", CC.d_num(what["baseline_trips_per_day"], 1), f"{CC.d_num(what['trips_per_day'])} (needed at {target_lf:.0%} load: {CC.d_num(what['trips_needed_per_day'])})"),
        ("Load factor", CC.d_pct(CC._ratio(bb["passenger_km"].sum(), bb["seat_km"].sum())), CC.d_pct(what["load_factor"])),
        ("Ticket revenue per day", CC.d_inr(what["baseline_revenue_per_day_inr"]), CC.d_inr(what["revenue_per_day_inr"])),
        ("Trip operating cost per day", CC.d_inr(what["baseline_trip_operating_cost_per_day_inr"]), CC.d_inr(what["trip_operating_cost_per_day_inr"])),
        ("Full cost per day", CC.d_inr(what["baseline_full_cost_per_day_inr"]), CC.d_inr(what["full_cost_per_day_inr"])),
        ("Contribution per day (not profit)", CC.d_inr(what["baseline_contribution_per_day_inr"]), CC.d_inr(what["contribution_per_day_inr"])),
        ("Full-cost margin per day", CC.d_inr(what["baseline_full_cost_margin_per_day_inr"]), CC.d_inr(what["full_cost_margin_per_day_inr"])),
        ("Break-even load factor (full cost)", CC.d_pct(wavg("be_load_factor_full")), CC.d_pct(what["be_load_factor_full"])),
        (f"Break-even adult fare at {target_lf:.0%} load", CC.d_inr(wavg("be_adult_fare_target_full_inr")), CC.d_inr(what["be_adult_fare_target_full_inr"])),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Measure", f"Baseline: current service ({w_band})", f"WHAT-IF: {cm.CLASS_LABELS[w_cls]}"]),
                 hide_index=True, width="stretch")
    L.note("WHAT-IF: the corridor's existing demand in this band is run on the chosen class (its fare table, seats, cost and speed). The baseline averages all current routes "
           "on the corridor (Rajkot-Somnath mixes express, AC seater and AC sleeper, so its baseline is trip-weighted and the what-if only approximates a like-for-like swap). "
           "Volvo, non-AC sleeper and e-bus are not in the timetable data; their parameters are illustrative.")

# ================================================================ 7. social cost-benefit
st.header("Social cost-benefit (illustrative appraisal)")
st.caption(SE.ILLUSTRATIVE_LABEL)
st.markdown("**How to read the BCR:** the benefit-cost ratio is (social benefits + ticket revenue) divided by full cost; above 1.0 the service returns more to society than it costs, "
            "below 1.0 it does not, even though fares alone may not cover its cost.")
if share_warning:
    st.warning(share_warning)
view = corr_all.copy()
st.dataframe(pd.DataFrame({
    "Corridor": view["corridor"], "Passengers per day": view["passengers_per_day"].map(CC.d_num),
    "Ticket revenue per day": view["revenue_per_day_inr"].map(CC.d_inr), "Full cost per day": view["full_cost_per_day_inr"].map(CC.d_inr),
    "Social benefit per day": view["social_benefit_per_day_inr"].map(CC.d_inr),
    "Net social benefit per day": view["net_social_benefit_per_day_inr"].map(CC.d_inr),
    "Net social benefit per year": view["net_social_benefit_per_year_inr"].map(fmt.inr_compact),
    "BCR": view["bcr"].map(CC.d_x),
}), hide_index=True, width="stretch")
L.show_chart(CC.cba_summary_chart(corr_all), key="cb_cba")
L.show_chart(CC.cba_waterfall(cba["comp"][cba["comp"]["corridor"] == corridor], corridor), key="cb_waterfall")
L.show_chart(CC.tornado_chart(cba["tornado"], corridor), key="cb_tornado")
st.markdown("**Takeaway.** " + SE.takeaway(corr_all))
L.note("Basis: full cost per day = full cost (trip operating + fixed and overhead) summed over ALL day types and bands of each route / all 42 service dates, matching how the "
       "route summary derives passengers, revenue and trip operating cost per day. The appraisal therefore does not change with the day-type filter.")


def _reset_se() -> None:
    for k in [k for k in ss.keys() if str(k).startswith("cb_s_")]:
        del ss[k]


with st.expander("Appraisal assumptions (illustrative, editable)"):
    st.caption(SE.ILLUSTRATIVE_LABEL + " Pin any diversion share; the others rescale so all shares always sum to 100%.")
    sc = st.columns(6)
    labels = {"share_car": "Car", "share_two_wheeler": "Two-wheeler", "share_private_bus": "Private bus", "share_shared_taxi": "Shared taxi",
              "share_rail": "Rail", "share_no_travel": "Would not travel"}
    for col, fld in zip(sc, SE.SHARE_FIELDS):
        col.slider(f"{labels[fld]} (%)", 0, 100, int(round(getattr(SE0, fld) * 100)), 5, key=f"cb_s_{fld}")
    eff = SE.rebalance_shares(SE0, **_share_items) if _share_items else SE0
    st.caption("Effective diversion shares of bus passengers: " + "; ".join(f"{labels[k]} {getattr(eff, k):.0%}" for k in SE.SHARE_FIELDS))
    a1, a2, a3, a4 = st.columns(4)
    a1.number_input("Value of time (₹/hour)", 10.0, 500.0, SE0.value_of_time_inr_per_hour, 10.0, key="cb_s_vot")
    a2.number_input("Carbon price (₹/tonne CO2)", 0.0, 20000.0, SE0.carbon_price_inr_per_tonne, 500.0, key="cb_s_carbon")
    a3.number_input("Car occupancy (persons)", 1.0, 6.0, SE0.occupancy_car, 0.1, key="cb_s_occ")
    a4.number_input("Car running cost (₹/km)", 2.0, 30.0, SE0.voc_car_inr_per_km, 0.5, key="cb_s_voc")
    st.button("Reset to defaults", on_click=_reset_se, key="cb_s_reset")
    st.markdown("**How each component is calculated**")
    for k, v in SE.component_assumptions(se_params).items():
        st.markdown(f"- {k.replace('_', ' ')}: {v}")

# ================================================================ 8. what this means + evidence
n_rows = len(rec_sel)
n_v = n_rows - n_nv
if CC.ok(bcr):
    bcr_txt = (f"The illustrative social benefit-cost ratio is {bcr:.2f}, so benefits plus revenue "
               f"{'cover' if bcr >= 1 else 'do not cover'} full cost.")
else:
    bcr_txt = "The social benefit-cost ratio cannot be computed for this corridor."
L.what_this_means(
    f"On {corridor} ({day_type}) a bus-km costs about {CC.d_inr(H['full_cost_per_km'], 1)} in full against {CC.d_inr(H['revenue_per_km'], 1)} of ticket revenue, so fares cover "
    f"{CC.d_pct(cover)} of full cost. {n_nv} of {n_rows} route-and-band rows are not viable on fare alone at a {target_lf:.0%} load and {n_v} have a recommended fare band"
    f"{' (' + wins + ' are the peak departure hours)' if peak_hours else ''}. {bcr_txt} "
    "Contribution is not profit; every cost and appraisal parameter is an illustrative assumption on simulated data.")
L.evidence_expander(
    sources=["trips, tickets, route_stops (synthetic): passengers, passenger-km, seat-km, revenue and trip operating cost per route, day type and time band (same definitions as route_kpis)",
             "routes (synthetic): corridor, length and bus class", "route_summary (processed): per-day passengers, passenger-km, bus-km, revenue and trip operating cost for the appraisal",
             "route_kpis (processed): load-factor and revenue definitions reused by the band economics",
             "competitor_services (synthetic): private operator fares used as the comparator",
             "Cost, fare-scenario and appraisal parameter defaults: manual_demo_input (authored, illustrative, editable on this page)"],
    formulas=["Cost per bus-km = trip operating (energy + tyres + maintenance and other running + crew) + fixed and overhead (dead km, depreciation or lease, insurance/tax/permits, tolls, overhead).",
              "Break-even load factor = cost per trip / (seats x route km x yield); break-even adult fare at target load = today's fare x (cost / (target x seat-km)) / yield.",
              "Recommended band = [max(current fare, break-even fare), cap] with cap = competitive share x private median; no band when break-even exceeds the cap.",
              "Fare scenario: demand = baseline x (new fare / old fare) ^ elasticity, capped at seats; revenue = served x new fare.",
              "BCR = (social benefits + ticket revenue) / full cost; net social benefit = social benefits + ticket revenue - full cost."],
    assumptions=["All cost, fare-scenario and appraisal defaults are illustrative orders of magnitude, not GSRTC data.",
                 "Maintenance and other running costs is a balancing item that reconciles the trip cost with the base per-km rate behind contribution on every other page.",
                 "The peak running-time factor defaults to 1.0 because the synthetic timetable has constant running times, so peak and normal trips cost the same by default.",
                 "Volvo, non-AC sleeper and e-bus (what-if classes) are not in the timetable data; their results are modelled, not observed.",
                 "Elasticities are assumptions, not fitted values. Private fares are synthetic, not verified competitor data.",
                 "Trips are one-way; return legs are assumed symmetric. Whole bus-km are charged for emissions, accidents and congestion (conservative).",
                 "Contribution (revenue - trip operating cost) and full-cost margin (revenue - full cost) are not profit; no subsidy is included.",
                 config.SIMULATION_BADGE_TEXT + "."],
    filters=f"Corridor: {corridor} | Day type: {day_type} (appraisal uses all 42 service days)")
