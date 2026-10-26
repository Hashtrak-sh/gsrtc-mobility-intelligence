"""M5 O-D fix: ``od_flows`` carries ``route_id``/``corridor`` so corridor scope is route membership and O-D passengers
reconcile with route boardings for every corridor (same day-type basis)."""
import pandas as pd
import pytest

import config
from modules.analytics import od as OD
from modules.ui import filters as F

DAYS = ("weekday", "weekend", "festival")


def test_od_flows_have_route_and_corridor(analytics, tables):
    od = analytics["od_flows"]
    assert {"route_id", "corridor"} <= set(od.columns)
    assert set(od["route_id"]) == set(tables["routes"]["route_id"])
    rt = tables["routes"].set_index("route_id")["corridor"]
    assert (od["corridor"].fillna("-") == od["route_id"].map(rt).fillna("-")).all()          # corridor is the route's corridor, null for local
    assert od[od["route_id"].str.startswith("L")]["corridor"].isna().all()
    assert not od.duplicated(["origin_zone_id", "dest_zone_id", "route_id", "day_type", "hour"]).any()


@pytest.mark.parametrize("day", DAYS)
def test_od_passengers_equal_route_boardings_for_every_route(analytics, day):
    od, rs = analytics["od_flows"], analytics["route_summary"].set_index("route_id")
    per_route = od[od["day_type"] == day].groupby("route_id")["passenger_count"].sum()
    want = rs[f"boardings_per_day_{day}"]
    assert set(per_route.index) == set(rs.index)
    assert (per_route - want.reindex(per_route.index)).abs().max() < 1e-6


def test_od_totals_equal_ticketed_passengers_per_route(analytics, tables):
    od = analytics["od_flows"]
    tk = tables["tickets"].merge(tables["trips"][["trip_id", "route_id"]], on="trip_id")
    want = tk.groupby("route_id")["passenger_count"].sum()
    got = od.groupby("route_id")["passengers_total"].sum()
    assert (got - want.reindex(got.index)).abs().max() == 0
    assert od["passengers_total"].sum() == tables["tickets"]["passenger_count"].sum()          # nothing lost or doubled


@pytest.mark.parametrize("day", DAYS)
def test_corridor_scope_reconciles_with_route_boardings(analytics, day):
    od, rs = analytics["od_flows"], analytics["route_summary"]
    col = f"boardings_per_day_{day}"
    for corridor in F.CORRIDOR_OPTIONS:
        f = F.Filters(corridor, day)
        scoped = F.filter_od(od, f, rs)
        want = F.filter_by_routes(rs, rs, corridor)[col].sum()
        assert scoped["passenger_count"].sum() == pytest.approx(want, abs=1e-6), corridor
    # the corridors and the local network partition the All scope: no pair is counted under two scopes
    parts = sum(F.filter_od(od, F.Filters(c, day), rs)["passenger_count"].sum() for c in (F.LOCAL, *config.INTERCITY_CORRIDORS))
    assert parts == pytest.approx(F.filter_od(od, F.Filters(F.ALL, day), rs)["passenger_count"].sum())


def test_rajkot_somnath_no_longer_double_counts(analytics):
    od, rs = analytics["od_flows"], analytics["route_summary"]
    som = F.filter_od(od, F.Filters("Rajkot-Somnath", "weekday"), rs)["passenger_count"].sum()
    ids = ["IC01", "IC02", "IC03"]
    assert som == pytest.approx(rs[rs["route_id"].isin(ids)]["boardings_per_day_weekday"].sum())
    assert som < 1523          # the pre-fix figure reported by the M3 review (zone-membership scope double counted shared pairs)


def test_filter_od_hours_and_missing_route_column(analytics):
    od, rs = analytics["od_flows"], analytics["route_summary"]
    h = F.filter_od(od, F.Filters("Rajkot-Somnath", "weekday", 7, 10), rs)
    assert h["hour"].between(7, 9).all() and set(h["route_id"]) <= {"IC01", "IC02", "IC03"}
    with pytest.raises(ValueError, match="route_id"):
        F.filter_od(od.drop(columns=["route_id"]), F.Filters(), rs)


def test_top_od_pairs_unaffected_by_route_split(analytics):
    top = OD.top_od_pairs(analytics["od_flows"], "weekday", (7, 10), top=1).iloc[0]
    assert (top["origin_zone_id"], top["dest_zone_id"]) == ("Z05", "Z11") and top["passengers_total"] == 4535        # planted F3 unchanged


def test_od_flows_without_routes_argument_has_null_corridor(analytics, tables):
    flows = OD.od_flows(analytics["legs"], tables["trips"], tables["stops"])
    assert flows["corridor"].isna().all() and "route_id" in flows.columns
    pd.testing.assert_series_equal(flows["passengers_total"].reset_index(drop=True), analytics["od_flows"]["passengers_total"].reset_index(drop=True))
