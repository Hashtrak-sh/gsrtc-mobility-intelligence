"""Cached OSM road network + routing helpers (Milestone 4).

Everything here READS the graph cache written by ``python -m modules.routing.fetch_network``; nothing downloads.
osmnx / networkx are optional: when they are missing, or the cache file is absent, ``graph_available`` is False and
``route_path`` returns a clearly labelled straight-line fallback (haversine x ``STRAIGHT_LINE_DETOUR_FACTOR``).

Path sources: ``"openstreetmap"`` (shortest path on the cached real road graph) or ``"straight_line_fallback"``.
Road geometry is REAL OSM geography; bus routes/stops/travel times on top of it are illustrative.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

import config
from modules.routing import settings as S

try:  # guarded: the app must import without the optional geo extras
    import networkx as nx
except Exception:  # pragma: no cover - exercised via monkeypatch in tests
    nx = None
try:
    import osmnx as ox
except Exception:  # pragma: no cover
    ox = None

SOURCE_OSM = "openstreetmap"
SOURCE_FALLBACK = "straight_line_fallback"


def geo_available() -> bool:
    return nx is not None and ox is not None


def graph_path(kind: str, raw_dir: Path | None = None) -> Path:
    if kind not in S.GRAPH_FILES:
        raise ValueError(f"unknown graph kind {kind!r}; expected one of {S.GRAPH_KINDS}")
    return Path(raw_dir or config.RAW_DIR) / S.GRAPH_FILES[kind]


def graph_available(kind: str, raw_dir: Path | None = None) -> bool:
    """True when osmnx+networkx import AND the cached graph file exists (no network access)."""
    return geo_available() and graph_path(kind, raw_dir).is_file()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def _prepare(G):
    """Add speeds / travel times (documented defaults) to a raw graph."""
    G = ox.add_edge_speeds(G, hwy_speeds=S.SPEED_FALLBACKS_KPH, fallback=S.DEFAULT_SPEED_KPH)
    for _, _, d in G.edges(data=True):
        d["speed_kph"] = float(d["speed_kph"]) * S.BUS_SPEED_FACTOR
    return ox.add_edge_travel_times(G)


def _largest_scc(G):
    comp = max(nx.strongly_connected_components(G), key=len)
    return G.subgraph(comp).copy()


def supplements_available(raw_dir: Path | None = None) -> list[str]:
    return [k for k in S.SUPPLEMENT_BBOXES if graph_path(k, raw_dir).is_file()]


@lru_cache(maxsize=4)
def _load_cached(kind: str, raw_dir: str | None):
    rd = Path(raw_dir) if raw_dir else None
    G = _prepare(ox.load_graphml(graph_path(kind, rd)))  # reads files only; never touches the network
    if kind == "city":  # compose the supplementary Metoda / Shapar link graphs when cached
        parts = [G] + [_prepare(ox.load_graphml(graph_path(k, rd))) for k in supplements_available(rd)]
        G = nx.compose_all(parts) if len(parts) > 1 else G
    return _largest_scc(G)


def load_graph(kind: str, raw_dir: Path | None = None):
    """Cached graph (lru_cache) with ``length`` (m), ``speed_kph`` and ``travel_time`` (s) on edges; None if unavailable.

    ``"city"`` is the drive graph composed with the supplementary link graphs if they are cached.
    """
    if not graph_available(kind, raw_dir):
        return None
    return _load_cached(kind, str(raw_dir) if raw_dir else None)


def clear_graph_cache() -> None:
    _load_cached.cache_clear()
    _NODE_INDEX.clear()


_NODE_INDEX: dict[int, tuple[Any, np.ndarray, np.ndarray]] = {}


def _node_index(G):
    hit = _NODE_INDEX.get(id(G))
    if hit is None or hit[0] is not G:
        ids = np.array(list(G.nodes))
        xy = np.array([[G.nodes[n]["y"], G.nodes[n]["x"]] for n in ids])
        hit = (G, ids, xy)
        _NODE_INDEX[id(G)] = hit
    return hit[1], hit[2]


def _nearest_node(G, lat: float, lon: float) -> tuple[Any, float]:
    ids, xy = _node_index(G)
    k = 111_320.0
    dy = (xy[:, 0] - lat) * k
    dx = (xy[:, 1] - lon) * k * math.cos(math.radians(lat))
    i = int(np.argmin(dx * dx + dy * dy))
    return ids[i], float(math.hypot(dx[i], dy[i]))


def snap_stops(stops_df: pd.DataFrame, G) -> pd.DataFrame:
    """Nearest graph node per stop. Columns: stop_id, node, snap_m, snapped (False if > MAX_SNAP_M or no graph)."""
    rows = []
    for r in stops_df.itertuples(index=False):
        if G is None:
            rows.append((r.stop_id, None, float("nan"), False))
            continue
        node, d = _nearest_node(G, float(r.lat), float(r.lon))
        rows.append((r.stop_id, node, d, d <= S.MAX_SNAP_M))
    return pd.DataFrame(rows, columns=["stop_id", "node", "snap_m", "snapped"])


def _edge_best(G, u, v) -> dict:
    return min(G[u][v].values(), key=lambda d: d.get("length", float("inf")))


def _edge_coords(G, u, v, d) -> list[list[float]]:
    g = d.get("geometry")
    if g is not None:
        return [[float(x), float(y)] for x, y in g.coords]
    return [[G.nodes[u]["x"], G.nodes[u]["y"]], [G.nodes[v]["x"], G.nodes[v]["y"]]]


def _dedupe(coords: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for c in coords:
        c = [round(c[0], 6), round(c[1], 6)]
        if not out or c != out[-1]:
            out.append(c)
    return out


def _fallback(pts: list[tuple[float, float]], note: str) -> dict:
    length = 0.0
    minutes = 0.0
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        leg = haversine_km(la1, lo1, la2, lo2) * S.STRAIGHT_LINE_DETOUR_FACTOR
        length += leg
        sp = S.FALLBACK_INTERCITY_SPEED_KPH if leg > S.INTERCITY_LEG_KM else S.FALLBACK_SPEED_KPH
        minutes += leg / sp * 60.0
    minutes += S.DWELL_MIN_PER_STOP * max(len(pts) - 2, 0)
    return {"path": [[round(lo, 6), round(la, 6)] for la, lo in pts], "length_km": round(length, 3),
            "travel_time_min": round(minutes, 2), "source": SOURCE_FALLBACK, "graph_kind": None, "note": note,
            "max_snap_m": None}


def _leg_on_graph(G, p1: tuple[float, float], p2: tuple[float, float], kind: str) -> dict | str:
    """Shortest path (by length) between two points on G; a result dict, or a string explaining why it failed."""
    a, d1 = _nearest_node(G, *p1)
    b, d2 = _nearest_node(G, *p2)
    if max(d1, d2) > S.MAX_SNAP_M:
        return f"{kind}: stop {max(d1, d2):.0f} m from graph (> {S.MAX_SNAP_M:.0f} m)"
    coords: list[list[float]] = []
    length_m = seconds = 0.0
    if a != b:
        try:
            nodelist = nx.shortest_path(G, a, b, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return f"{kind}: no path between snapped nodes"
        for u, v in zip(nodelist, nodelist[1:]):
            d = _edge_best(G, u, v)
            length_m += float(d["length"])
            seconds += float(d.get("travel_time", 0.0))
            coords.extend(_edge_coords(G, u, v, d))
    return {"coords": coords, "length_m": length_m, "seconds": seconds, "snap_m": max(d1, d2), "kind": kind}


def route_path(route_stop_ids: Sequence[str], stops_df: pd.DataFrame, kind: str = "auto",
               raw_dir: Path | None = None) -> dict:
    """Road path through the ordered stops.

    Returns ``{path: [[lon, lat], ...], length_km, travel_time_min, source, graph_kind, note, max_snap_m}``.
    ``kind``: ``"city"`` | ``"corridor"`` | ``"auto"``. With ``auto`` each leg (consecutive stop pair) uses the first graph
    that can serve both stops (city, then corridor); ``graph_kind`` is e.g. ``"city"`` or ``"city+corridor"``.
    ``source`` is ``"openstreetmap"`` only if EVERY leg was routed on a graph; otherwise the whole route is the labelled
    ``"straight_line_fallback"`` (graph missing / stop too far from the graph / no path) with the reasons in ``note``.
    travel_time_min = driving time at OSM-derived speeds x bus factor + dwell per intermediate stop (illustrative).
    """
    idx = stops_df.set_index("stop_id")
    missing = [s for s in route_stop_ids if s not in idx.index]
    if missing:
        raise KeyError(f"stop ids not in stops table: {missing}")
    pts = [(float(idx.at[s, "lat"]), float(idx.at[s, "lon"])) for s in route_stop_ids]
    if len(pts) < 2:
        raise ValueError("a route needs at least two stops")
    kinds = list(S.GRAPH_KINDS) if kind == "auto" else [kind]
    graphs = {k: load_graph(k, raw_dir) for k in kinds}
    why = [f"{k} graph unavailable" for k, g in graphs.items() if g is None]
    legs = []
    for p1, p2 in zip(pts, pts[1:]):
        leg = None
        for k in kinds:
            if graphs[k] is None:
                continue
            res = _leg_on_graph(graphs[k], p1, p2, k)
            if isinstance(res, dict):
                leg = res
                break
            why.append(res)
        if leg is None:
            return _fallback(pts, "; ".join(dict.fromkeys(why)))
        legs.append(leg)
    coords = [c for leg in legs for c in leg["coords"]]
    if not coords:
        return _fallback(pts, "degenerate path")
    minutes = sum(leg["seconds"] for leg in legs) / 60.0 + S.DWELL_MIN_PER_STOP * max(len(pts) - 2, 0)
    used = "+".join(k for k in kinds if any(leg["kind"] == k for leg in legs))
    return {"path": _dedupe(coords), "length_km": round(sum(leg["length_m"] for leg in legs) / 1000.0, 3),
            "travel_time_min": round(minutes, 2), "source": SOURCE_OSM, "graph_kind": used, "note": "",
            "max_snap_m": round(max(leg["snap_m"] for leg in legs), 1)}


def path_to_geojson(path: list[list[float]]) -> str:
    return json.dumps({"type": "LineString", "coordinates": path})


def path_length_km(path: list[list[float]]) -> float:
    return sum(haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(path, path[1:]))
