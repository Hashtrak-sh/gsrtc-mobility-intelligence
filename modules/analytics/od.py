"""Origin-destination flows between zones (``od_flows``).

Tickets are mapped from stops to zones. Hour = clock hour of the ticket's boarding timestamp. ``passenger_count`` is the
AVERAGE per service day of the ``day_type`` (total passengers / number of service dates of that day type); totals are
kept in ``passengers_total``. ``estimated_passenger_km`` is likewise the per-day average
(``passenger_km_total / n_days``) with passenger-km = passengers x route km between boarding and alighting stops.
Intra-zone pairs (origin == destination zone) are kept and flagged ``is_intra_zone``. Tickets whose stops are not on the
route (invalid legs) are counted in passengers but contribute no passenger-km.

M5: rows are keyed by ``route_id`` (and carry the route's ``corridor``, null for local routes), so corridor/network scope
is route membership and a zone pair shared by several corridors is no longer double counted:
``sum(passengers_total)`` over a route's rows equals that route's ticketed boardings (same day-type basis).
"""
from __future__ import annotations

import pandas as pd

from modules.analytics.common import SOURCE_TYPE, n_days_by_day_type

OD_COLUMNS = ["origin_zone_id", "dest_zone_id", "day_type", "hour", "passenger_count", "estimated_passenger_km", "source_type",
              "passengers_total", "passenger_km_total", "n_days", "is_intra_zone", "route_id", "corridor"]


def od_flows(legs: pd.DataFrame, trips: pd.DataFrame, stops: pd.DataFrame, routes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Zone-pair x route x hour x day-type flows. ``routes`` (optional) supplies ``corridor``; without it corridor is null."""
    if legs.empty:
        return pd.DataFrame(columns=OD_COLUMNS)
    z = stops.set_index("stop_id")["zone_id"]
    tk = legs.drop(columns=["route_id"], errors="ignore").merge(trips[["trip_id", "route_id", "day_type"]], on="trip_id", how="left")
    tk["origin_zone_id"] = tk["origin_stop_id"].map(z)
    tk["dest_zone_id"] = tk["dest_stop_id"].map(z)
    tk["hour"] = tk["timestamp"].dt.hour
    g = tk.groupby(["origin_zone_id", "dest_zone_id", "route_id", "day_type", "hour"], dropna=False).agg(
        passengers_total=("passenger_count", "sum"), passenger_km_total=("pax_km", "sum")).reset_index()
    nd = n_days_by_day_type(trips)
    g["n_days"] = g["day_type"].map(nd).astype(int)
    g["passenger_count"] = g["passengers_total"] / g["n_days"]
    g["estimated_passenger_km"] = g["passenger_km_total"] / g["n_days"]
    g["is_intra_zone"] = g["origin_zone_id"] == g["dest_zone_id"]
    g["corridor"] = g["route_id"].map(routes.set_index("route_id")["corridor"]) if routes is not None else None
    g["source_type"] = SOURCE_TYPE
    g = g.sort_values(["day_type", "hour", "passengers_total", "origin_zone_id", "dest_zone_id", "route_id"],
                      ascending=[True, True, False, True, True, True], kind="mergesort").reset_index(drop=True)
    return g[OD_COLUMNS]


def top_od_pairs(od: pd.DataFrame, day_type: str = "weekday", hours: tuple[int, int] = (7, 10), top: int = 5,
                 include_intra_zone: bool = True) -> pd.DataFrame:
    """Top zone pairs by total passengers for ``day_type`` and boarding hours in [hours[0], hours[1])."""
    s = od[(od["day_type"] == day_type) & (od["hour"] >= hours[0]) & (od["hour"] < hours[1])]
    if not include_intra_zone:
        s = s[~s["is_intra_zone"]]
    g = s.groupby(["origin_zone_id", "dest_zone_id"], dropna=False).agg(
        passengers_total=("passengers_total", "sum"), passenger_count=("passenger_count", "sum")).reset_index()
    return g.sort_values(["passengers_total", "origin_zone_id", "dest_zone_id"], ascending=[False, True, True],
                         kind="mergesort").head(top).reset_index(drop=True)
