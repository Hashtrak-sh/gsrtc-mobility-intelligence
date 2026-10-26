"""Detect the planted synthetic findings (F1, F2, F3, F4, F6) from the ANALYTICS outputs only.

Independent of ``modules.data_gen.checks`` (which uses plain pandas on source tables); this module reads the derived tables
produced by the M2 functions, so it proves the analytics surface what was planted. F5 (survey) is an M5 topic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

import config
from modules.analytics import gaps as G
from modules.analytics.od import top_od_pairs
from modules.analytics.common import n_days_by_day_type

EXPECTED_HIGH_LOAD = {("L05", 7), ("L05", 8), ("L05", 17), ("L07", 7)}


@dataclass
class Finding:
    name: str
    ok: bool
    detail: str
    values: dict[str, Any] = field(default_factory=dict)


def zone_window_supply_demand(trips_sum: pd.DataFrame, legs: pd.DataFrame, stops: pd.DataFrame, route_stops: pd.DataFrame,
                              zone_id: str, hour: int, day_type: str = "weekday") -> dict[str, Any]:
    """Trips/seats per average day departing in ``hour`` on routes that serve ``zone_id``, and passengers alighting in the zone."""
    zstops = set(stops.loc[stops["zone_id"] == zone_id, "stop_id"])
    routes_ = sorted(set(route_stops.loc[route_stops["stop_id"].isin(zstops), "route_id"]))
    nd = float(n_days_by_day_type(trips_sum).get(day_type, 0))
    sel = trips_sum[trips_sum["route_id"].isin(routes_) & (trips_sum["day_type"] == day_type) & (trips_sum["dep_hour"] == hour)]
    lg = legs[legs["trip_id"].isin(sel["trip_id"]) & legs["dest_stop_id"].isin(zstops)]
    return {
        "serving_routes": routes_,
        "trips_per_day": len(sel) / nd if nd else float("nan"),
        "seats_per_day": float(sel["seats"].sum()) / nd if nd else float("nan"),
        "pax_to_zone_per_day": float(lg["passenger_count"].sum()) / nd if nd else float("nan"),
        "peak_load_factor": float(sel["peak_onboard"].sum() / sel["seats"].sum()) if len(sel) else float("nan"),
    }


def detect_planted(res: dict[str, pd.DataFrame], tables: dict[str, pd.DataFrame]) -> list[Finding]:
    """``res`` = analytics outputs (trips_sum, legs, hourly_demand_supply, od_flows, cctv_hourly_profile)."""
    out: list[Finding] = []
    ts, legs, hourly, od = res["trips_sum"], res["legs"], res["hourly_demand_supply"], res["od_flows"]
    zones = tables["zones"].set_index("zone_id")["zone_type"]

    # F1a: high peak-load local route-hours
    rh = G.route_hour_load(ts, config.PEAK_DAY_TYPE)
    hi = rh[rh["peak_load_factor"] > config.HIGH_PEAK_LOAD_FACTOR]
    got = {(r, int(h)) for r, h in zip(hi["route_id"], hi["hour"])}
    crowded = hourly[(hourly["level"] == "route_direction") & (hourly["day_type"] == config.PEAK_DAY_TYPE) & (hourly["status"] == G.STATUS_CROWDED)]
    out.append(Finding("F1a high peak-load local route-hours (L05 07/08/17, L07 07)", got == EXPECTED_HIGH_LOAD,
                       "peak load factor: " + ", ".join(f"{r} {int(h):02d}h={v:.2f}" for r, h, v in zip(hi["route_id"], hi["hour"], hi["peak_load_factor"])),
                       {"route_hours": sorted(got), "crowded_route_direction_rows": len(crowded)}))

    # F1b: IC02 outbound 08:30 at its seat cap on every weekend date
    t = ts[(ts["route_id"] == "IC02") & (ts["departure_time"] == "08:30") & (ts["direction"] == "outbound")]
    wk = t[t["day_type"] == "weekend"]
    wd = t[t["day_type"] == "weekday"]
    ok = len(wk) >= 10 and wk["peak_load_factor"].min() >= config.AT_CAPACITY_LOAD_FACTOR and wd["peak_load_factor"].mean() < 0.8
    flagged = hourly[(hourly["route_id"] == "IC02") & (hourly["direction"] == "outbound") & (hourly["hour"] == 8) & (hourly["status"] == G.STATUS_AT_CAPACITY)]
    out.append(Finding("F1b IC02 Rajkot->Somnath 08:30 AC seater at capacity every weekend", bool(ok) and set(flagged["day_type"]) >= {"weekend"},
                       f"weekend dates={len(wk)} min peak LF={wk['peak_load_factor'].min():.2f}; weekday mean peak LF={wd['peak_load_factor'].mean():.2f}",
                       {"weekend_min_peak_load_factor": float(wk["peak_load_factor"].min()), "weekday_mean_peak_load_factor": float(wd["peak_load_factor"].mean())}))

    # F2: Z13 weekday 07h served by one trip
    z = zone_window_supply_demand(ts, legs, tables["stops"], tables["route_stops"], "Z13", 7)
    l07 = hourly[(hourly["route_id"] == "L07") & (hourly["day_type"] == config.PEAK_DAY_TYPE) & (hourly["hour"] == 7) & (hourly["direction"] == "outbound")]
    ok = (z["serving_routes"] == ["L07"] and z["trips_per_day"] == 1.0 and z["pax_to_zone_per_day"] >= z["seats_per_day"]
          and len(l07) == 1 and l07.iloc[0]["status"] == G.STATUS_CROWDED)
    out.append(Finding("F2 Shapar-Veraval (Z13) weekday 07h: demand with one state trip", bool(ok),
                       f"trips/day={z['trips_per_day']:.1f} seats/day={z['seats_per_day']:.0f} pax to Z13/day={z['pax_to_zone_per_day']:.0f} "
                       f"peak LF={z['peak_load_factor']:.2f}", z))

    # F3: top weekday 07-10 O-D pair
    top = top_od_pairs(od, "weekday", (7, 10), top=10)
    first = top.iloc[0]
    other = top[zones.reindex(top["dest_zone_id"]).to_numpy() != "employment"]["passengers_total"].max()
    ok = (zones.get(first["origin_zone_id"]) == "residential" and zones.get(first["dest_zone_id"]) == "employment"
          and first["passengers_total"] >= 1.2 * other)
    out.append(Finding("F3 top weekday 07-10 O-D pair is residential -> employment", bool(ok),
                       f"{first['origin_zone_id']}->{first['dest_zone_id']} passengers={int(first['passengers_total'])} (best non-employment destination {int(other)})",
                       {"origin_zone_id": first["origin_zone_id"], "dest_zone_id": first["dest_zone_id"], "passengers_total": int(first["passengers_total"])}))

    # F4: Rajkot-Somnath evening corridor window
    c = hourly[(hourly["level"] == "corridor") & (hourly["corridor"] == config.PRIMARY_CORRIDOR) & (hourly["day_type"] == "weekday")]
    ev = c[(c["hour"] >= 18) & (c["hour"] <= 21)]
    ok = (len(ev) == 4 and (ev["status"] == G.STATUS_NO_CAPACITY).all() and (ev["seats_offered"] == 0).all()
          and ev["gap_index"].isna().all() and (ev["private_demand_proxy"] > 0).all() and ev["private_departures"].sum() >= 5)
    out.append(Finding("F4 Rajkot-Somnath evening: no scheduled state capacity, private-market proxy demand", bool(ok),
                       f"hours 18-21 weekday: state seats={ev['seats_offered'].sum():.0f}, private departures={ev['private_departures'].sum():.0f}, "
                       f"proxy demand={ev['private_demand_proxy'].sum():.0f} pax/day", {"proxy_demand_per_day": float(ev["private_demand_proxy"].sum())}))

    # F6: CCTV
    prof = res["cctv_hourly_profile"]
    p = prof[(prof["location_id"] == "S01") & (prof["day_type"] == "weekday")].set_index("hour")["mean_inbound_persons"]
    ratio = float(p.loc[[7, 8]].mean() / p.drop([7, 8]).mean())
    out.append(Finding("F6 Rajkot Central (S01) synthetic CCTV weekday footfall peaks 07:00-09:00", int(p.idxmax()) in (7, 8) and ratio >= 2.0,
                       f"peak hour={int(p.idxmax())} ratio vs other hours={ratio:.2f}", {"peak_hour": int(p.idxmax()), "ratio": ratio}))
    return out
