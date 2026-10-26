"""Batch command: road paths for every route -> ``data/processed/route_paths.parquet``.

    python -m modules.routing.build_paths

Reads ``routes`` / ``route_stops`` / ``stops`` (synthetic) and the cached OSM graphs (``fetch_network``); never downloads.
Routes whose stops the graphs cannot serve are written with ``path_source = "straight_line_fallback"``.
Columns: route_id, path_geojson, osm_length_km, synthetic_length_km, length_ratio, travel_time_min, path_source,
graph_kind, note, source_type.  ``osm_length_km`` is the fallback estimate when ``path_source`` is the fallback
(it is NOT OSM-derived then); ``length_ratio = osm_length_km / synthetic_length_km``.
"""
from __future__ import annotations

import sys

import pandas as pd

from modules.data import io
from modules.data.provenance import make_provenance
from modules.routing import network as N
from modules.routing import settings as S

TABLE = "route_paths"
COLUMNS = ["route_id", "path_geojson", "osm_length_km", "synthetic_length_km", "length_ratio", "travel_time_min",
           "path_source", "graph_kind", "note", "source_type"]


def build(base_dir=None, raw_dir=None) -> pd.DataFrame:
    routes = io.read_table("routes", "synthetic", base_dir)
    rs = io.read_table("route_stops", "synthetic", base_dir).sort_values(["route_id", "stop_seq"])
    stops = io.read_table("stops", "synthetic", base_dir)
    rows = []
    for r in routes.itertuples(index=False):
        ids = rs.loc[rs["route_id"] == r.route_id, "stop_id"].tolist()
        res = N.route_path(ids, stops, "auto", raw_dir)
        rows.append({
            "route_id": r.route_id, "path_geojson": N.path_to_geojson(res["path"]),
            "osm_length_km": res["length_km"], "synthetic_length_km": float(r.length_km),
            "length_ratio": round(res["length_km"] / float(r.length_km), 3) if r.length_km else float("nan"),
            "travel_time_min": res["travel_time_min"], "path_source": res["source"],
            "graph_kind": res["graph_kind"], "note": res["note"], "source_type": "model_output",
        })
    return pd.DataFrame(rows, columns=COLUMNS)


DESCRIPTION = ("Road paths through the ordered stops of each synthetic route: shortest path (by length) on cached real "
               f"OpenStreetMap graphs ({S.ATTRIBUTION}) or a labelled straight-line fallback. Routes/stops are synthetic "
               "demonstration data; travel times are illustrative.")


def assumptions() -> dict:
    return {"bus_speed_factor": S.BUS_SPEED_FACTOR, "speed_fallbacks_kph": S.SPEED_FALLBACKS_KPH,
            "dwell_min_per_stop": S.DWELL_MIN_PER_STOP, "detour_factor_fallback": S.STRAIGHT_LINE_DETOUR_FACTOR,
            "max_snap_m": S.MAX_SNAP_M, "graphs_available": {k: N.graph_available(k) for k in S.FETCH_KINDS},
            "supplements_composed_into_city": N.supplements_available()}


def main(argv: list[str] | None = None) -> int:
    df = build()
    p = io.write_table(df, TABLE, "processed", provenance=make_provenance("model_output", seed=None, description=DESCRIPTION,
                                                                          assumptions=assumptions()))
    show = df[["route_id", "synthetic_length_km", "osm_length_km", "length_ratio", "travel_time_min", "path_source", "graph_kind"]]
    print(show.to_string(index=False))
    print(f"Wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
