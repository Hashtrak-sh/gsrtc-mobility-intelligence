"""Explicit network command: fetch a small set of real OpenStreetMap features and cache them.

    python -m modules.data_gen.fetch_osm

Writes ``data/raw/osm_places.parquet`` (+ ``osm_places.provenance.json``). This is the ONLY part of the
data pipeline that touches the network; ``generate`` and the dashboard read the cache and never download.

Method (few requests, osmnx caching on, Nominatim/Overpass politeness via osmnx rate limiting):
* ``bus_station`` targets: ``osmnx.features_from_point`` (amenity=bus_station) around the town's approximate
  centre; the feature whose name best matches the hint (else the nearest) is used.
* ``place`` targets: ``osmnx.geocode_to_gdf`` (Nominatim).
A match is accepted only if it lies within ``max_km`` of the hand-entered approximation in
``geography.MANUAL_COORDS``, so a wrong Nominatim hit is rejected (``matched=False``) and the generator uses the
labelled ``manual_demo_input`` fallback for that key instead.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

import config
from modules.data import io
from modules.data.provenance import make_provenance
from modules.data_gen import geography as G

ALT_OVERPASS = "https://overpass.kumi.systems/api"
COLUMNS = ["key", "kind", "query", "osm_name", "lat", "lon", "osm_type", "osm_id", "distance_km_from_approx", "matched", "note"]


def _row(t: G.OsmTarget, **kw) -> dict:
    base = {"key": t.key, "kind": t.kind, "query": t.query, "osm_name": None, "lat": float("nan"),
            "lon": float("nan"), "osm_type": None, "osm_id": None, "distance_km_from_approx": float("nan"),
            "matched": False, "note": ""}
    base.update(kw)
    return base


def _fetch_bus_station(ox, t: G.OsmTarget) -> dict:
    alat, alon = G.MANUAL_COORDS[t.key]
    gdf = ox.features_from_point((alat, alon), tags={"amenity": "bus_station"}, dist=int(t.max_km * 1000))
    if gdf is None or len(gdf) == 0:
        return _row(t, note="no amenity=bus_station within search radius")
    gdf = gdf.reset_index()
    cent = gdf.geometry.to_crs(3857).centroid.to_crs(4326)
    gdf["lat"], gdf["lon"] = cent.y.values, cent.x.values
    gdf["d"] = [G.haversine_km(alat, alon, a, b) for a, b in zip(gdf["lat"], gdf["lon"])]
    names = gdf["name"].fillna("") if "name" in gdf.columns else pd.Series([""] * len(gdf))
    hint = t.query.lower()
    gdf["name_hit"] = names.str.lower().str.contains(hint, regex=False)
    best = gdf.sort_values(["name_hit", "d"], ascending=[False, True]).iloc[0]
    ok = float(best["d"]) <= t.max_km
    return _row(t, osm_name=(str(best["name"]) if "name" in gdf.columns and pd.notna(best["name"]) else None),
                lat=float(best["lat"]), lon=float(best["lon"]), osm_type=str(best.get("element", best.get("element_type", ""))),
                osm_id=int(best["id"]) if "id" in gdf.columns else None,
                distance_km_from_approx=float(best["d"]), matched=ok,
                note=f"{len(gdf)} bus_station feature(s) found; name_hit={bool(best['name_hit'])}")


def _nominatim(ox, q: str) -> dict | None:
    """First Nominatim hit for ``q`` as a dict (display_name, lat, lon, osm_type, osm_id), or None."""
    try:
        from osmnx import _nominatim as nm  # osmnx >= 2 internal helper used by osmnx.geocoder
        res = nm._nominatim_request(params={"q": q, "format": "json", "limit": 1})
        return res[0] if res else None
    except Exception:
        try:
            lat, lon = ox.geocode(q)
            return {"display_name": None, "lat": lat, "lon": lon, "osm_type": None, "osm_id": None}
        except Exception:
            return None


def _query_variants(q: str) -> list[str]:
    alts = [a.strip() for a in q.split("|")]
    out = list(alts)
    if len(alts) == 1:
        head = q.split(",")[0].strip()
        out += [f"{head}, Rajkot", f"{head}, Rajkot, Gujarat"]
    return list(dict.fromkeys(out))


def _fetch_place(ox, t: G.OsmTarget) -> dict:
    alat, alon = G.MANUAL_COORDS[t.key]
    notes = []
    for q in _query_variants(t.query):
        hit = _nominatim(ox, q)
        if hit is None:
            notes.append(f"no hit for '{q}'")
            continue
        lat, lon = float(hit["lat"]), float(hit["lon"])
        d = G.haversine_km(alat, alon, lat, lon)
        if d <= t.max_km:
            oid = hit.get("osm_id")
            return _row(t, query=q, osm_name=hit.get("display_name"), lat=lat, lon=lon, osm_type=hit.get("osm_type"),
                        osm_id=int(oid) if oid is not None else None, distance_km_from_approx=d, matched=True,
                        note="accepted")
        notes.append(f"rejected '{q}': {d:.1f} km from approximation (> {t.max_km} km)")
    return _row(t, note="; ".join(notes) or "no match")


def _attempt(fn, ox, t, tries: int = 2):
    last = None
    for i in range(tries):
        try:
            return fn(ox, t)
        except Exception as exc:
            last = exc
            if "InsufficientResponse" in type(exc).__name__:
                break
            time.sleep(8)
            if i == 0:
                ox.settings.overpass_url = ALT_OVERPASS  # second try on an alternative public endpoint
    return _row(t, note=f"error: {type(last).__name__}: {str(last)[:100]}")


def fetch(out_dir: Path | None = None, refresh: bool = False) -> pd.DataFrame:
    import osmnx as ox  # optional dependency (requirements-optional.txt, 'geo' group)

    base = Path(out_dir) if out_dir else config.DATA_DIR
    raw_dir = (base / "raw") if out_dir else config.RAW_DIR
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(config.RAW_DIR / "osmnx_cache")
    ox.settings.log_console = False
    ox.settings.requests_timeout = 60
    ox.settings.overpass_rate_limit = False  # we sleep between requests ourselves
    default_overpass = ox.settings.overpass_url
    prior: dict[str, dict] = {}
    cache_file = raw_dir / f"{G.OSM_CACHE_TABLE}.parquet"
    if cache_file.is_file() and not refresh:
        for r in pd.read_parquet(cache_file).to_dict("records"):
            if r["matched"]:
                prior[r["key"]] = r
    rows = []
    for t in G.OSM_TARGETS:
        if t.key in prior:
            rows.append(prior[t.key])
            print(f"  {t.key:24s} cached (use --refresh to refetch)")
            continue
        ox.settings.overpass_url = default_overpass
        fn = _fetch_bus_station if t.kind == "bus_station" else _fetch_place
        rows.append(_attempt(fn, ox, t))
        r = rows[-1]
        print(f"  {t.key:24s} matched={str(r['matched']):5s} {str(r['note'])[:110]}")
        time.sleep(1.5)
    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.astype({"matched": bool})
    prov = make_provenance(
        "openstreetmap", seed=None,
        description="Real OpenStreetMap features (c) OpenStreetMap contributors, ODbL: bus stations and named places "
                    "used only as coordinate anchors for the synthetic demo network.",
        assumptions={"method": "osmnx features_from_point (amenity=bus_station) / Nominatim search", "osmnx": ox.__version__,
                     "matched_keys": [r["key"] for r in rows if r["matched"]],
                     "unmatched_keys": [r["key"] for r in rows if not r["matched"]]},
    )
    path = io.write_table(df, G.OSM_CACHE_TABLE, "raw", base_dir=base if out_dir else None, provenance=prov)
    print(f"Wrote {path} ({int(df['matched'].sum())}/{len(df)} matched)")
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="refetch keys that are already cached")
    args = ap.parse_args(argv)
    try:
        df = fetch(refresh=args.refresh)
    except ImportError:
        print("osmnx is not installed. Run: pip install osmnx   (see requirements-optional.txt)", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"OSM fetch failed ({type(exc).__name__}: {exc}). The generator will use manual_demo_input fallback.", file=sys.stderr)
        return 1
    return 0 if df["matched"].any() else 1


if __name__ == "__main__":
    sys.exit(main())
