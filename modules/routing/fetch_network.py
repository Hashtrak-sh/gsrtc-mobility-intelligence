"""Explicit network command: download and cache the OSM road graphs used for route paths and candidates.

    python -m modules.routing.fetch_network [--refresh] [--only city|corridor]

Writes ``data/raw/osm_graph_city.graphml`` (drive network, Rajkot core) and ``data/raw/osm_graph_corridor.graphml``
(motorway/trunk/primary + links, Rajkot-Somnath corridor), each with a ``*.provenance.json`` sidecar. This is the ONLY
routing code that touches the network; the dashboard and ``build_paths`` read the cache. osmnx HTTP caching is on
(``data/raw/osmnx_cache``) so a retried run does not re-download finished queries.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import config
from modules.data.provenance import make_provenance
from modules.routing import settings as S

ALT_OVERPASS = ["https://overpass.kumi.systems/api", "https://overpass-api.de/api"]


def _download(ox, kind: str):
    if kind == "city":
        return ox.graph_from_bbox(S.CITY_BBOX, network_type="drive", simplify=True, retain_all=False, truncate_by_edge=True)
    return ox.graph_from_bbox(S.CORRIDOR_BBOX, network_type="drive", custom_filter=S.CORRIDOR_FILTER, simplify=True,
                              retain_all=True, truncate_by_edge=True)


def fetch_one(kind: str, tries: int = 5, out_dir: Path | None = None) -> Path:
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = str(config.RAW_DIR / "osmnx_cache")
    ox.settings.log_console = False
    ox.settings.requests_timeout = 180
    ox.settings.overpass_rate_limit = True
    endpoints = [ox.settings.overpass_url] + ALT_OVERPASS
    last = None
    t0 = time.time()
    for i in range(tries):
        ox.settings.overpass_url = endpoints[i % len(endpoints)]
        try:
            G = _download(ox, kind)
            break
        except Exception as exc:  # network flakiness: back off, rotate endpoint
            last = exc
            wait = min(60, 5 * 2 ** i)
            print(f"  [{kind}] attempt {i + 1}/{tries} failed ({type(exc).__name__}: {str(exc)[:90]}); retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    else:
        raise RuntimeError(f"could not fetch {kind} graph: {last}")
    out = Path(out_dir) if out_dir else config.RAW_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / S.GRAPH_FILES[kind]
    ox.save_graphml(G, path)
    prov = make_provenance(
        "openstreetmap", seed=None,
        description=f"Real OpenStreetMap road network ({kind}) {S.ATTRIBUTION}. Geography only; no GSRTC route data.",
        assumptions={
            "fetched_at_unix": int(t0), "osmnx": ox.__version__, "network_type": "drive", "simplify": True,
            "bbox_west_south_east_north": list(S.CITY_BBOX if kind == "city" else S.CORRIDOR_BBOX),
            "custom_filter": None if kind == "city" else S.CORRIDOR_FILTER,
            "nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "size_bytes": path.stat().st_size,
            "attribution": "© OpenStreetMap contributors", "license": "ODbL 1.0",
        },
    )
    path.with_name(path.stem + ".provenance.json").write_text(prov.to_json(), encoding="utf-8")
    print(f"  [{kind}] {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {path.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f}s -> {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="refetch graphs that already exist")
    ap.add_argument("--only", choices=S.GRAPH_KINDS)
    args = ap.parse_args(argv)
    rc = 0
    try:
        import osmnx  # noqa: F401
    except ImportError:
        print("osmnx is not installed. Run: pip install -r requirements-optional.txt", file=sys.stderr)
        return 2
    for kind in ([args.only] if args.only else S.GRAPH_KINDS):
        if (config.RAW_DIR / S.GRAPH_FILES[kind]).is_file() and not args.refresh:
            print(f"  [{kind}] cached (use --refresh to refetch)")
            continue
        try:
            fetch_one(kind)
        except Exception as exc:
            print(f"  [{kind}] FAILED: {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
