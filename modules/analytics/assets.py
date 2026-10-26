"""Infrastructure and digital-maturity summaries from ``assets_assessment`` and ``digital_assessment``.

Scores are on the documented 0-5 scale (higher is better). All values are synthetic demonstration assessments, not field
audits. The improvement ranking is a transparent sort: lowest score first, ties broken by name.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

SCALE_MAX = 5.0
LOW_SCORE_THRESHOLD = 2.5  # scores below this are counted as "needs attention" (illustrative cut-off)

DIM_LABELS = {"cleanliness": "Cleanliness", "accessibility": "Accessibility", "safety": "Safety", "amenities": "Amenities",
              "digital": "Digital", "other": "Other"}


def asset_matrix(assets: pd.DataFrame) -> pd.DataFrame:
    """Asset (rows, by name) x dimension (columns) matrix of scores; missing assessments stay NaN."""
    m = assets.pivot_table(index="asset_name", columns="dimension", values="score", aggfunc="mean")
    m = m[[c for c in DIM_LABELS if c in m.columns]]
    return m.assign(_mean=m.mean(axis=1)).sort_values("_mean").drop(columns="_mean")


def digital_matrix(digital: pd.DataFrame, asset_names: dict[str, str]) -> pd.DataFrame:
    """Asset (rows) x capability (columns) maturity matrix (0-5)."""
    d = digital.assign(asset_name=digital["asset_id"].map(asset_names).fillna(digital["asset_id"]))
    return d.pivot_table(index="asset_name", columns="capability", values="maturity_score", aggfunc="mean")


def improvement_list(assets: pd.DataFrame, digital: pd.DataFrame, asset_names: dict[str, str], top: int | None = None) -> pd.DataFrame:
    """Combined ranked list of the lowest scores (infrastructure dimensions and digital capabilities).

    Columns: ``rank``, ``area`` (Infrastructure/Digital), ``asset``, ``item``, ``score`` (0-5), ``points_to_target`` (5 - score),
    ``evidence_note``.
    """
    a = pd.DataFrame({"area": "Infrastructure", "asset": assets["asset_name"], "item": assets["dimension"].map(DIM_LABELS).fillna(assets["dimension"]),
                      "score": assets["score"], "evidence_note": assets["evidence_note"]})
    d = pd.DataFrame({"area": "Digital", "asset": digital["asset_id"].map(asset_names).fillna(digital["asset_id"]),
                      "item": digital["capability"].str.capitalize(), "score": digital["maturity_score"],
                      "evidence_note": digital["evidence_note"]})
    out = pd.concat([a, d], ignore_index=True).dropna(subset=["score"])
    out = out.sort_values(["score", "asset", "item"], kind="mergesort").reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    out["points_to_target"] = SCALE_MAX - out["score"]
    return out if top is None else out.head(top)


def assets_summary(assets: pd.DataFrame, digital: pd.DataFrame) -> dict[str, Any]:
    dim = assets.groupby("dimension")["score"].mean()
    cap = digital.groupby("capability")["maturity_score"].mean()
    return {
        "n_assets": int(assets["asset_id"].nunique()),
        "mean_asset_score": float(assets["score"].mean()) if len(assets) else float("nan"),
        "lowest_dimension": None if dim.empty else str(dim.idxmin()),
        "lowest_dimension_score": float(dim.min()) if len(dim) else float("nan"),
        "mean_digital_maturity": float(digital["maturity_score"].mean()) if len(digital) else float("nan"),
        "weakest_capability": None if cap.empty else str(cap.idxmin()),
        "weakest_capability_score": float(cap.min()) if len(cap) else float("nan"),
        "n_below_threshold": int((assets["score"] < LOW_SCORE_THRESHOLD).sum() + (digital["maturity_score"] < LOW_SCORE_THRESHOLD).sum()),
    }
