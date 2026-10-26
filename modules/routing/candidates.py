"""Bounded, ILLUSTRATIVE route-candidate generation for the demo corridors (Milestone 4).

    python -m modules.routing.candidates     # writes data/processed/route_candidates.parquet

A handful of hand-specified candidates (NOT an all-pairs search and NOT a network-wide optimisation):

* ``Residential-Industrial commute``: Kotharia / Mavdi -> Aji GIDC / Metoda GIDC / Shapar industrial (direct, express and
  pick-up-via variants).
* ``Rajkot-Somnath evening``: direct vs via-towns variants of the evening Rajkot -> Somnath service.

For each candidate: road path (cached OSM graph, else labelled straight-line fallback), travel time, zone coverage within
``WALK_BUFFER_M`` of the path (zone centroid distance; the WHOLE zone population / jobs is counted, a coarse proxy), time
penalty versus the fastest road path between the same origin and destination, overlap with existing route paths and a
transparent weighted score. All population / jobs values are SYNTHETIC; the result is a demonstration, not a plan.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from modules.data import io
from modules.data.provenance import make_provenance
from modules.routing import network as N
from modules.routing import settings as S

TABLE = "route_candidates"
LABEL = "Illustrative candidate on simulated demand; not a recommendation or a validated plan"

# Score weights (sum to 1). The orchestrator may move these into config.py. Each component is scaled 0..1 within the
# candidate's corridor group (so the best candidate in a group gets 1.0 on that component).
SCORE_WEIGHTS: Final[dict[str, float]] = {
    "population_covered": 0.30,   # more residents within the walk buffer is better
    "jobs_covered": 0.30,         # more jobs within the walk buffer is better
    "time_efficiency": 0.20,      # 1 - travel_time_penalty (capped at 100 %)
    "new_coverage": 0.20,         # 1 - overlap with existing route paths (duplicating existing service is worse)
}
OVERLAP_BUFFER_M: Final[float] = 150.0   # a candidate point within this distance of an existing route path counts as overlap
SAMPLE_STEP_M: Final[float] = 100.0


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    corridor: str
    name: str
    stops: tuple[str, ...]


CANDIDATE_SPECS: Final[tuple[CandidateSpec, ...]] = (
    CandidateSpec("RC01", "Residential-Industrial commute", "Kotharia -> Aji GIDC direct express", ("S09", "S21")),
    CandidateSpec("RC02", "Residential-Industrial commute", "Mavdi -> Aji GIDC direct express", ("S11", "S21")),
    CandidateSpec("RC03", "Residential-Industrial commute", "Kotharia + Mavdi -> Aji GIDC (one pick-up via Mavdi)", ("S09", "S11", "S21")),
    CandidateSpec("RC04", "Residential-Industrial commute", "Kotharia -> Shapar industrial express", ("S09", "S25")),
    CandidateSpec("RC05", "Residential-Industrial commute", "Mavdi -> Metoda GIDC express", ("S11", "S23")),
    CandidateSpec("RS01", "Rajkot-Somnath evening", "Rajkot -> Somnath direct via Junagadh", ("S01", "S31", "S34")),
    CandidateSpec("RS02", "Rajkot-Somnath evening", "Rajkot -> Somnath via Junagadh and Veraval", ("S01", "S31", "S33", "S34")),
    CandidateSpec("RS03", "Rajkot-Somnath evening", "Rajkot -> Somnath via-towns (Gondal-Jetpur-Junagadh-Keshod-Veraval)",
                  ("S01", "S29", "S30", "S31", "S32", "S33", "S34")),
)


# --------------------------------------------------------------------------- geometry helpers
def _to_xy(coords, lat0: float) -> np.ndarray:
    a = np.asarray(coords, dtype=float)
    k = 111_320.0
    return np.column_stack([a[:, 0] * k * math.cos(math.radians(lat0)), a[:, 1] * k])


def densify(path: list[list[float]], step_m: float = SAMPLE_STEP_M) -> np.ndarray:
    """Points (lon, lat) along the polyline at about ``step_m`` spacing, vertices included."""
    pts = [path[0]]
    lat0 = path[0][1]
    xy = _to_xy(path, lat0)
    for i in range(1, len(path)):
        seg = float(np.hypot(*(xy[i] - xy[i - 1])))
        n = int(seg // step_m)
        for j in range(1, n + 1):
            t = j * step_m / seg
            pts.append([path[i - 1][0] + t * (path[i][0] - path[i - 1][0]), path[i - 1][1] + t * (path[i][1] - path[i - 1][1])])
        pts.append(path[i])
    return np.asarray(pts)


def min_dist_m(points_lonlat: np.ndarray, path: list[list[float]], chunk: int = 2000) -> np.ndarray:
    """Distance (m) from each point to the polyline ``path`` (local equirectangular projection)."""
    lat0 = float(np.mean([p[1] for p in path]))
    P = _to_xy(points_lonlat, lat0)
    L = _to_xy(path, lat0)
    A, B = L[:-1], L[1:]
    AB = B - A
    denom = np.maximum((AB ** 2).sum(1), 1e-9)
    out = np.empty(len(P))
    for s in range(0, len(P), chunk):
        p = P[s:s + chunk, None, :]
        t = np.clip(((p - A) * AB).sum(2) / denom, 0.0, 1.0)
        proj = A + t[..., None] * AB
        out[s:s + chunk] = np.sqrt(((p - proj) ** 2).sum(2)).min(1)
    return out


def coverage(path: list[list[float]], zones: pd.DataFrame, buffer_m: float = S.WALK_BUFFER_M) -> pd.DataFrame:
    """Zones whose centroid lies within ``buffer_m`` of the path."""
    d = min_dist_m(zones[["lon", "lat"]].to_numpy(), path)
    z = zones.assign(dist_m=d)
    return z[z["dist_m"] <= buffer_m]


def overlap_pct(path: list[list[float]], existing: list[list[list[float]]]) -> float:
    """Share (0-100) of the candidate path (sampled every 100 m) within ``OVERLAP_BUFFER_M`` of any existing path."""
    if not existing:
        return 0.0
    pts = densify(path)
    near = np.full(len(pts), np.inf)
    lo, hi = pts.min(0) - 0.01, pts.max(0) + 0.01
    for e in existing:
        ea = np.asarray(e)
        if (ea[:, 0].max() < lo[0]) or (ea[:, 0].min() > hi[0]) or (ea[:, 1].max() < lo[1]) or (ea[:, 1].min() > hi[1]):
            continue
        near = np.minimum(near, min_dist_m(pts, e))
    return float(100.0 * np.mean(near <= OVERLAP_BUFFER_M))


# --------------------------------------------------------------------------- scoring
def score_candidates(df: pd.DataFrame, weights: dict[str, float] = SCORE_WEIGHTS) -> pd.DataFrame:
    """Add ``score`` (0-100) and ``score_breakdown_json``; components are scaled within each corridor group."""
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError(f"score weights must sum to 1, got {sum(weights.values())}")
    out = df.copy()
    scores, breakdowns = [], []
    for _, g in out.groupby("corridor"):
        pm, jm = max(g["population_covered"].max(), 1), max(g["jobs_covered"].max(), 1)
        for i, r in g.iterrows():
            comp = {
                "population_covered": r["population_covered"] / pm,
                "jobs_covered": r["jobs_covered"] / jm,
                "time_efficiency": max(0.0, 1.0 - min(r["travel_time_penalty_pct"], 100.0) / 100.0),
                "new_coverage": 1.0 - r["existing_route_overlap_pct"] / 100.0,
            }
            contrib = {k: round(weights[k] * v, 4) for k, v in comp.items()}
            scores.append((i, round(100.0 * sum(contrib.values()), 2)))
            breakdowns.append((i, json.dumps({
                "components_0_1": {k: round(v, 4) for k, v in comp.items()}, "weights": weights,
                "weighted_contribution": contrib, "scaling": "population/jobs scaled to the max within the corridor group",
            })))
    out["score"] = pd.Series(dict(scores))
    out["score_breakdown_json"] = pd.Series(dict(breakdowns))
    return out


# --------------------------------------------------------------------------- build
def build(base_dir=None, raw_dir=None) -> pd.DataFrame:
    stops = io.read_table("stops", "synthetic", base_dir)
    zones = io.read_table("zones", "synthetic", base_dir)
    if io.table_exists("route_paths", "processed", base_dir):
        rp = io.read_table("route_paths", "processed", base_dir)
    else:
        from modules.routing import build_paths
        rp = build_paths.build(base_dir, raw_dir)
    existing = [json.loads(g)["coordinates"] for g, s in zip(rp["path_geojson"], rp["path_source"]) if s == N.SOURCE_OSM]
    rows = []
    for spec in CANDIDATE_SPECS:
        res = N.route_path(spec.stops, stops, "auto", raw_dir)
        direct = N.route_path((spec.stops[0], spec.stops[-1]), stops, "auto", raw_dir)
        cov = coverage(res["path"], zones)
        # penalty vs the fastest road path of the same OD pair (shortest path between origin and destination)
        penalty = max(0.0, 100.0 * (res["travel_time_min"] - direct["travel_time_min"]) / max(direct["travel_time_min"], 1e-6))
        rows.append({
            "candidate_id": spec.candidate_id, "corridor": spec.corridor, "path_geojson": N.path_to_geojson(res["path"]),
            "travel_time_min": res["travel_time_min"], "population_covered": int(cov["population"].sum()),
            "jobs_covered": int(cov["jobs"].sum()), "travel_time_penalty_pct": round(penalty, 2),
            "existing_route_overlap_pct": round(overlap_pct(res["path"], existing), 2),
            "name": spec.name, "stop_ids_json": json.dumps(list(spec.stops)), "origin_stop_id": spec.stops[0],
            "destination_stop_id": spec.stops[-1], "length_km": res["length_km"],
            "direct_travel_time_min": direct["travel_time_min"], "zones_covered_json": json.dumps(cov["zone_id"].tolist()),
            "walk_buffer_m": S.WALK_BUFFER_M, "path_source": res["source"], "label": LABEL, "source_type": "model_output",
        })
    return score_candidates(pd.DataFrame(rows))


def main(argv: list[str] | None = None) -> int:
    df = build()
    prov = make_provenance(
        "model_output", seed=None,
        description=LABEL + ". Bounded to the demo corridors; not a network-wide optimisation.",
        assumptions={"score_weights": SCORE_WEIGHTS, "walk_buffer_m": S.WALK_BUFFER_M, "overlap_buffer_m": OVERLAP_BUFFER_M,
                     "coverage_method": "zone centroid within buffer of path; whole-zone synthetic population/jobs counted",
                     "penalty_reference": "fastest (shortest-length) road path between the candidate's origin and destination",
                     "candidates": [c.candidate_id for c in CANDIDATE_SPECS],
                     "graphs_available": {k: N.graph_available(k) for k in S.GRAPH_KINDS}},
    )
    p = io.write_table(df, TABLE, "processed", provenance=prov)
    print(df[["candidate_id", "corridor", "travel_time_min", "population_covered", "jobs_covered", "travel_time_penalty_pct",
              "existing_route_overlap_pct", "score", "path_source"]].to_string(index=False))
    print(f"Wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
