"""Rebuild the M4 processed tables from CACHED graphs: ``python -m modules.routing.run``.

Runs ``build_paths`` then ``candidates`` (in that order: candidates read ``route_paths``). Never downloads: if the graph
caches (``data/raw/osm_graph_*.graphml``) are missing, paths are written as labelled ``straight_line_fallback`` and fallback
candidates are flagged ``not_comparable_fallback``. Use ``python -m modules.routing.fetch_network`` to download the graphs.
Intended as the follow-up step after ``python -m modules.analytics.run`` (``rebuild`` can also be called from it).
"""
from __future__ import annotations

import sys

from modules.routing import build_paths, candidates


def rebuild(base_dir=None, raw_dir=None, write: bool = True):
    """Return (route_paths_df, route_candidates_df); write both tables when ``write``."""
    from modules.data import io
    from modules.data.provenance import make_provenance

    paths = build_paths.build(base_dir, raw_dir)
    cands = None
    if write:
        io.write_table(paths, build_paths.TABLE, "processed", base_dir=base_dir,
                       provenance=make_provenance("model_output", seed=None, description=build_paths.DESCRIPTION,
                                                  assumptions=build_paths.assumptions()))
    cands = candidates.build(base_dir, raw_dir, route_paths=paths)
    if write:
        io.write_table(cands, candidates.TABLE, "processed", base_dir=base_dir,
                       provenance=make_provenance("model_output", seed=None, description=candidates.DESCRIPTION,
                                                  assumptions=candidates.assumptions()))
    return paths, cands


def main(argv: list[str] | None = None) -> int:
    paths, cands = rebuild()
    print(paths[["route_id", "synthetic_length_km", "osm_length_km", "length_ratio", "path_source"]].to_string(index=False))
    print(cands[["candidate_id", "score", "rank_flag", "path_source"]].to_string(index=False))
    n_fb = int((paths["path_source"] != "openstreetmap").sum())
    print(f"Wrote route_paths ({len(paths)} routes, {n_fb} fallback) and route_candidates ({len(cands)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
