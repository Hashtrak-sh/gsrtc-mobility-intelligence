"""Synthetic route network: ~10 Rajkot-area local demo routes + intercity corridors, with schedules.

All routes are SYNTHETIC DEMONSTRATION ROUTES. Real place names are used for orientation only; they are not real
GSRTC or RMTS routes, timetables or stop lists.

Direction convention: ``outbound`` follows ``routes.stop_sequence`` order; ``inbound`` is the reverse.
``route_stops.cum_km`` / ``cum_minutes`` are in the OUTBOUND frame. For an inbound trip the position of stop k is
``length_km - cum_km`` and ``scheduled_minutes - cum_minutes``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from modules.data_gen import constants as C
from modules.data_gen import geography as G


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    name: str
    route_type: str
    stops: tuple[str, ...]
    bus_type: str
    minimum_service: bool = False
    corridor: str | None = None
    # --- schedule ---
    # explicit departure lists ("HH:MM") by day-class; if None, generated from headways (local only)
    dep_out: dict[str, tuple[str, ...]] | None = None
    dep_in: dict[str, tuple[str, ...]] | None = None
    first_min: int = 345
    last_min: int = 1290
    peak_headway: int = 20
    off_headway: int = 40
    weekend_headway: int = 50
    in_offset_min: int = 10
    speed_kmph: float | None = None  # override of constants.SPEED_KMPH (e.g. suburban industrial route)
    # --- demand (pax per trip at profile multiplier 1.0; for intercity: fraction of seats) ---
    base: float = 10.0
    out_morning: float = 1.0
    in_morning: float = 0.7
    out_evening: float = 0.7
    in_evening: float = 1.0
    # {(direction, hour, day_type): multiplier}   (planted route-hours)
    hour_boost: dict[tuple[str, int, str], float] = field(default_factory=dict)
    # intercity: {(direction, "HH:MM", day_type): multiplier}
    trip_boost: dict[tuple[str, str, str], float] = field(default_factory=dict)
    day_factor: dict[str, float] | None = None
    note: str = ""


def _wk(*times: str) -> tuple[str, ...]:
    return tuple(times)


_RS_EXPRESS = ("05:30", "07:00", "09:00", "11:00", "13:00", "15:30", "17:30", "22:45")
_RS_WEEKEND_DAYF = {"weekday": 1.0, "weekend": 1.2, "festival": 1.7}

ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec("L01", "Raiya - Kalawad Road - Central Bus Stand - Railway Station (demo)", "local",
              ("S14", "S13", "S05", "S02", "S01", "S03"), "ordinary", base=30, peak_headway=60, off_headway=120,
              weekend_headway=130, note="Trunk residential-to-core route; organic demand, kept below the high-load threshold."),
    RouteSpec("L02", "Kotharia - Mavdi - Central Bus Stand (demo)", "local",
              ("S10", "S09", "S11", "S02", "S01"), "ordinary", base=30, peak_headway=60, off_headway=120, weekend_headway=130, in_offset_min=7),
    RouteSpec("L03", "Madhapar - Kalawad Road - University - Central Bus Stand (demo)", "local",
              ("S07", "S06", "S17", "S01"), "ordinary", base=30, peak_headway=60, off_headway=120, weekend_headway=130, in_offset_min=14),
    RouteSpec("L04", "Central Bus Stand - Station Road - Aji GIDC (demo)", "local",
              ("S01", "S04", "S21", "S22"), "ordinary", base=28, peak_headway=60, off_headway=120, weekend_headway=130, in_offset_min=12),
    RouteSpec("L05", "Mavdi - Kotharia - Aji GIDC Industrial Shuttle (demo)", "local",
              ("S11", "S10", "S09", "S21", "S22"), "ordinary", base=24, peak_headway=36, off_headway=120, weekend_headway=130,
              in_morning=0.7, out_evening=0.7, in_offset_min=6,
              hour_boost={("outbound", 7, "weekday"): 2.3, ("outbound", 8, "weekday"): 2.3,
                          ("inbound", 7, "weekday"): 2.3, ("inbound", 8, "weekday"): 2.3,
                          ("outbound", 17, "weekday"): 2.3, ("inbound", 17, "weekday"): 2.3},
              note="Planted: residential (south) to industrial (east) shift-change shuttle; weekday 07:00-09:00 and 17:00-18:00 above crush demand."),
    RouteSpec("L06", "Gandhigram - Bhaktinagar - Railway Station - Aji GIDC (demo)", "local",
              ("S15", "S16", "S28", "S27", "S03", "S22"), "ordinary", base=32, peak_headway=60, off_headway=120, weekend_headway=130, in_offset_min=16),
    RouteSpec("L07", "Madhapar - Raiya - Shapar-Veraval Industrial Area (demo)", "local",
              ("S07", "S13", "S26", "S25"), "ordinary", base=34, speed_kmph=30.0,
              dep_out={"weekday": _wk("05:40", "07:05", "09:40", "12:10", "14:30", "16:45", "17:30", "18:15", "20:10"),
                       "weekend": _wk("06:30", "09:30", "13:00", "17:00")},
              dep_in={"weekday": _wk("06:20", "08:35", "10:30", "13:00", "15:30", "17:10", "18:00", "19:00", "20:45", "22:00"),
                      "weekend": _wk("07:30", "10:30", "14:00", "18:00")},
              hour_boost={("outbound", 7, "weekday"): 2.2},
              note="Planted capacity gap: weekday 07:00-08:00 flow to Shapar-Veraval served by ONE trip (07:05)."),
    RouteSpec("L08", "University - Central Bus Stand - Ramnathpara (demo)", "local",
              ("S18", "S01", "S19", "S20"), "ordinary", base=32, peak_headway=60, off_headway=120, weekend_headway=130, in_offset_min=9,
              in_morning=0.8, out_evening=0.8),
    RouteSpec("L09", "Madhapar - Gandhigram Village Link (demo, minimum service)", "local",
              ("S08", "S07", "S16", "S15"), "ordinary", minimum_service=True, base=3.5,
              dep_out={"weekday": _wk("06:15", "08:30", "11:00", "13:30", "16:30", "19:00"),
                       "weekend": _wk("07:30", "11:00", "15:00", "18:30")},
              dep_in={"weekday": _wk("07:15", "09:30", "12:00", "14:30", "17:30", "20:00"),
                      "weekend": _wk("08:30", "12:00", "16:00", "19:30")},
              in_morning=0.9, out_evening=0.9,
              note="Low-ridership essential/social service (minimum_service=True)."),
    RouteSpec("L10", "Metoda GIDC - Mavdi - Central Bus Stand (demo, minimum service)", "local",
              ("S24", "S23", "S12", "S01"), "ordinary", minimum_service=True, base=5,
              dep_out={"weekday": _wk("06:10", "08:40", "11:30", "15:00", "17:45", "19:45"),
                       "weekend": _wk("07:00", "12:00", "17:00")},
              dep_in={"weekday": _wk("06:55", "09:10", "12:30", "15:45", "18:15", "20:30"),
                      "weekend": _wk("08:00", "13:00", "18:00")},
              out_morning=0.45, in_morning=1.0, out_evening=1.0, in_evening=0.45,
              note="Low-ridership essential service to a peripheral industrial estate (minimum_service=True)."),
    # ------------------------------ intercity ------------------------------
    RouteSpec("IC01", "Rajkot - Somnath Express (demo)", "intercity",
              ("S01", "S29", "S30", "S31", "S32", "S33", "S34"), "express", corridor="Rajkot-Somnath",
              dep_out={k: _RS_EXPRESS for k in C.DAY_TYPES}, dep_in={k: _RS_EXPRESS for k in C.DAY_TYPES},
              base=1.15, day_factor=_RS_WEEKEND_DAYF, note="Primary corridor, express service."),
    RouteSpec("IC02", "Rajkot - Somnath AC Seater (demo)", "intercity",
              ("S01", "S31", "S33", "S34"), "AC_seater", corridor="Rajkot-Somnath",
              dep_out={k: ("06:30", "08:30", "14:30") for k in C.DAY_TYPES},
              dep_in={k: ("06:30", "08:30", "14:30") for k in C.DAY_TYPES},
              base=0.85, day_factor={"weekday": 1.0, "weekend": 1.3, "festival": 1.6},
              trip_boost={("outbound", "08:30", "weekend"): 2.8, ("outbound", "08:30", "festival"): 2.2},
              note="Planted: Rajkot->Somnath 08:30 AC departure ~full every weekend."),
    RouteSpec("IC03", "Rajkot - Somnath AC Sleeper (demo)", "intercity",
              ("S01", "S31", "S34"), "AC_sleeper", corridor="Rajkot-Somnath",
              dep_out={k: ("23:15",) for k in C.DAY_TYPES}, dep_in={k: ("23:00",) for k in C.DAY_TYPES},
              base=1.05, day_factor=_RS_WEEKEND_DAYF),
    RouteSpec("IC04", "Rajkot - Gondal - Jetpur - Junagadh Express (demo)", "intercity",
              ("S01", "S29", "S30", "S31"), "express", corridor="Rajkot-Junagadh",
              dep_out={k: ("05:30", "07:00", "09:00", "11:30", "13:15", "15:00", "17:00", "19:00") for k in C.DAY_TYPES},
              dep_in={k: ("05:30", "07:00", "09:00", "11:30", "13:15", "15:00", "17:00", "19:00") for k in C.DAY_TYPES},
              base=0.95, day_factor={"weekday": 1.0, "weekend": 1.15, "festival": 1.25}),
    RouteSpec("IC05", "Rajkot - Jamnagar Express (demo)", "intercity",
              ("S01", "S35"), "express", corridor="Rajkot-Jamnagar",
              dep_out={k: ("05:45", "07:30", "09:30", "11:30", "14:00", "16:00", "18:00", "20:00") for k in C.DAY_TYPES},
              dep_in={k: ("05:45", "07:30", "09:30", "11:30", "14:00", "16:00", "18:00", "20:00") for k in C.DAY_TYPES},
              base=0.75, day_factor={"weekday": 1.0, "weekend": 1.1, "festival": 1.2}),
    RouteSpec("IC06", "Rajkot - Ahmedabad AC Seater (demo)", "intercity",
              ("S01", "S36"), "AC_seater", corridor="Rajkot-Ahmedabad",
              dep_out={k: ("06:00", "09:00", "12:00", "15:00", "18:30", "22:00") for k in C.DAY_TYPES},
              dep_in={k: ("06:00", "09:00", "12:00", "15:00", "18:30", "22:00") for k in C.DAY_TYPES},
              base=0.85, day_factor={"weekday": 1.0, "weekend": 1.2, "festival": 1.3}),
)
ROUTE_BY_ID = {r.route_id: r for r in ROUTE_SPECS}

# Relative stop weights for intercity pair demand
_IC_STOP_WEIGHT = {"S01": 10, "S29": 2.5, "S30": 3.0, "S31": 4.5, "S32": 1.5, "S33": 2.5, "S34": 4.0, "S35": 5.0, "S36": 8.0}


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def departures(spec: RouteSpec, direction: str, dtype: str) -> list[int]:
    """Scheduled departure minutes-of-day for a route/direction/day_type."""
    lists = spec.dep_out if direction == "outbound" else spec.dep_in
    if lists is not None:
        key = dtype if dtype in lists else ("weekend" if dtype == "festival" else "weekday")
        return sorted(_hhmm_to_min(t) for t in lists[key])
    out: list[int] = []
    t = spec.first_min + (spec.in_offset_min if direction == "inbound" else 0)
    last = spec.last_min + (spec.in_offset_min if direction == "inbound" else 0)
    while t <= last:
        out.append(int(t))
        if dtype == "weekday":
            peak = 390 <= t < 570 or 990 <= t < 1170
            t += spec.peak_headway if peak else spec.off_headway
        else:
            t += spec.weekend_headway
    return out


def build_route_tables(stops: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    coords = {r.stop_id: (r.lat, r.lon) for r in stops.itertuples(index=False)}
    names = {r.stop_id: r.name for r in stops.itertuples(index=False)}
    route_rows, rs_rows = [], []
    for spec in ROUTE_SPECS:
        factor = C.ROAD_FACTOR_LOCAL if spec.route_type == "local" else C.ROAD_FACTOR_INTERCITY
        dwell = C.DWELL_MIN_LOCAL if spec.route_type == "local" else C.DWELL_MIN_INTERCITY
        speed = spec.speed_kmph or C.SPEED_KMPH[spec.bus_type]
        cum_km = [0.0]
        for a, b in zip(spec.stops[:-1], spec.stops[1:]):
            cum_km.append(cum_km[-1] + G.haversine_km(*coords[a], *coords[b]) * factor)
        for k, sid in enumerate(spec.stops):
            km = round(cum_km[k], 2)
            mins = round(cum_km[k] / speed * 60.0 + dwell * k, 2)
            rs_rows.append({"route_id": spec.route_id, "stop_seq": k + 1, "stop_id": sid, "cum_km": km, "cum_minutes": mins})
        route_rows.append({
            "route_id": spec.route_id, "name": spec.name, "route_type": spec.route_type,
            "origin_stop_id": spec.stops[0], "destination_stop_id": spec.stops[-1],
            "stop_sequence": json.dumps(list(spec.stops)), "length_km": round(cum_km[-1], 2),
            "bus_type": spec.bus_type, "minimum_service": spec.minimum_service, "source_type": "synthetic",
            "corridor": spec.corridor,
        })
        _ = names
    return pd.DataFrame(route_rows), pd.DataFrame(rs_rows)


# --------------------------------------------------------------------------
# Demand weights (used by tickets.py)
# --------------------------------------------------------------------------
def stop_attractors(zones: pd.DataFrame, stops: pd.DataFrame) -> pd.DataFrame:
    """Per-stop relative weights ``gen`` (all-purpose), ``res`` (resident workers), ``job`` (jobs); each mean-1 over local stops."""
    z = zones.set_index("zone_id")
    n_in_zone = stops.groupby("zone_id")["stop_id"].transform("count")
    df = stops[["stop_id", "zone_id"]].copy()
    df["res"] = z.loc[df["zone_id"], "workers_resident"].to_numpy() / n_in_zone.to_numpy()
    df["job"] = z.loc[df["zone_id"], "jobs"].to_numpy() / n_in_zone.to_numpy()
    df["gen"] = (z.loc[df["zone_id"], "population"].to_numpy() * 0.5 + z.loc[df["zone_id"], "jobs"].to_numpy()) / n_in_zone.to_numpy()
    local = df["zone_id"].isin([f"Z{i:02d}" for i in range(1, 15)])
    for c in ("res", "job", "gen"):
        df[c] = df[c] / df.loc[local, c].mean()
    return df.set_index("stop_id")


PHASE_WEIGHTS = {"morning": (1.0, 0.10), "evening": (0.10, 1.0), "midday": (0.25, 0.25), "offday": (0.20, 0.20)}


def local_pair_probs(spec: RouteSpec, direction: str, phase: str, attr: pd.DataFrame, cum_km_dir: np.ndarray,
                     stop_ids_dir: list[str]) -> np.ndarray:
    n = len(stop_ids_dir)
    iu, ju = np.triu_indices(n, 1)
    m, e = PHASE_WEIGHTS[phase]
    res = attr.loc[stop_ids_dir, "res"].to_numpy()
    job = attr.loc[stop_ids_dir, "job"].to_numpy()
    gen = attr.loc[stop_ids_dir, "gen"].to_numpy()
    d = cum_km_dir[ju] - cum_km_dir[iu]
    zid = attr.loc[stop_ids_dir, "zone_id"].to_numpy()
    w = (0.35 * gen[iu] * gen[ju] + m * res[iu] * job[ju] + e * job[iu] * res[ju]) * np.exp(-d / 6.0)
    w = w * np.where(zid[iu] == zid[ju], 0.25, 1.0)  # intra-zone hops are rarer than inter-zone trips
    return w / w.sum()


def intercity_pair_probs(stop_ids_dir: list[str], cum_km_dir: np.ndarray) -> np.ndarray:
    n = len(stop_ids_dir)
    iu, ju = np.triu_indices(n, 1)
    wt = np.array([_IC_STOP_WEIGHT[s] for s in stop_ids_dir])
    d = cum_km_dir[ju] - cum_km_dir[iu]
    w = wt[iu] * wt[ju] * (d / 100.0) ** 0.4
    return w / w.sum()
