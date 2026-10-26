"""Trip schedule (all trips are state GSRTC-demo services) with synthetic departure delays and operating cost."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.data_gen import constants as C
from modules.data_gen import network as N


def _hhmm(minutes: np.ndarray) -> np.ndarray:
    m = np.asarray(minutes).astype(int)
    return np.array([f"{x // 60:02d}:{x % 60:02d}" for x in m], dtype=object)


def generate_trips(routes: pd.DataFrame, route_stops: pd.DataFrame, days: int, rng: np.random.Generator) -> pd.DataFrame:
    """One row per scheduled trip per direction per service date.

    Delay model (minutes, negative = early): gamma(1.6, 2.6) - 1.2, x1.4 in peak hours, x1.3 intercity,
    plus a 5% chance of an extra uniform(10, 35) disruption; clipped to [-4, 60] and to stay before midnight.
    """
    rlen = routes.set_index("route_id")["length_km"].to_dict()
    sched = route_stops.groupby("route_id")["cum_minutes"].max().to_dict()  # scheduled run time = last cum_minutes
    rows: list[tuple] = []
    for d in C.service_dates(days):
        dt = C.day_type(d)
        for spec in N.ROUTE_SPECS:
            for direction in ("outbound", "inbound"):
                for dep in N.departures(spec, direction, dt):
                    rows.append((d, spec.route_id, direction, dep, dt))
    df = pd.DataFrame(rows, columns=["service_date", "route_id", "direction", "dep_min", "day_type"])
    n = len(df)
    spec_type = df["route_id"].map({s.route_id: s.route_type for s in N.ROUTE_SPECS})
    bus_type = df["route_id"].map({s.route_id: s.bus_type for s in N.ROUTE_SPECS})
    hour = df["dep_min"] // 60
    peak = df["day_type"].eq("weekday") & (hour.between(7, 9) | hour.between(17, 19))
    scale = np.where(peak, 1.4, 1.0) * np.where(spec_type.eq("intercity"), 1.3, 1.0)
    delay = (rng.gamma(1.6, 2.6, n) - 1.2) * scale
    extra = rng.random(n) < 0.05
    delay = delay + np.where(extra, rng.uniform(10, 35, n), 0.0)
    delay = np.clip(delay, -4.0, 60.0)
    delay = np.minimum(delay, 1439 - df["dep_min"].to_numpy())
    df["departure_delay_min"] = np.round(delay, 1)
    actual = df["dep_min"].to_numpy() + df["departure_delay_min"].to_numpy()
    df["actual_departure_time"] = _hhmm(np.floor(actual + 0.5))
    df["departure_time"] = _hhmm(df["dep_min"].to_numpy())
    df["seats"] = bus_type.map(C.BUS_TYPE_SEATS).astype(int)
    df["operator"] = "state"
    df["bus_type"] = bus_type.to_numpy()
    df["scheduled_minutes"] = df["route_id"].map(sched).astype(float)
    df["operating_cost_inr"] = np.round(bus_type.map(C.OPERATING_COST_PER_KM_INR).to_numpy() * df["route_id"].map(rlen).to_numpy(), 2)
    df["source_type"] = "synthetic"
    df = df.sort_values(["service_date", "route_id", "direction", "dep_min"], kind="stable").reset_index(drop=True)
    df.insert(0, "trip_id", [f"TR{i + 1:06d}" for i in range(len(df))])
    df["service_date"] = pd.to_datetime(df["service_date"]).dt.date
    # keep dep_min and exact delay available to the ticket stage via attrs-free columns prefixed with underscore
    df = df.rename(columns={"dep_min": "_dep_min"})
    return df
