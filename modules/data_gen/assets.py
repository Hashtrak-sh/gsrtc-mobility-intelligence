"""Synthetic infrastructure (assets_assessment) and digital maturity (digital_assessment) scores, 0-5 scale."""
from __future__ import annotations

import numpy as np
import pandas as pd

ASSETS = (  # asset_id, asset_name, asset_type
    ("S01", "Rajkot Central Bus Stand", "station"),
    ("S34", "Somnath Bus Stand", "station"),
    ("S31", "Junagadh Bus Stand", "station"),
    ("D01", "Rajkot Depot (demo)", "depot"),
    ("S21", "Aji GIDC Gate", "stop"),
    ("S11", "Mavdi Circle", "stop"),
    ("S25", "Shapar Industrial Chowk", "stop"),
)
DIMENSIONS = ("cleanliness", "accessibility", "safety", "amenities", "digital")
# mean score by (asset, dimension); the clear gaps are marked
_MEAN = {
    "S01": (3.4, 2.8, 3.2, 2.2, 2.0),   # amenities and digital are gaps at the busiest stand
    "S34": (3.0, 1.5, 3.0, 2.5, 1.4),   # accessibility gap at Somnath
    "S31": (3.1, 2.6, 3.0, 2.8, 1.8),
    "D01": (2.9, 2.4, 3.3, 2.6, 1.6),
    "S21": (2.4, 1.8, 2.2, 1.2, 0.8),   # industrial stop: no shelter/lighting
    "S11": (2.6, 2.0, 2.5, 1.8, 0.9),
    "S25": (2.3, 1.6, 2.0, 1.1, 0.7),
}
_NOTE = {
    "cleanliness": "Synthetic assessment of cleanliness (0-5).",
    "accessibility": "Synthetic assessment of step-free access, ramps and tactile paving (0-5).",
    "safety": "Synthetic assessment of lighting, CCTV coverage and crowd management (0-5).",
    "amenities": "Synthetic assessment of seating, shelter, drinking water, toilets (0-5).",
    "digital": "Synthetic assessment of passenger information displays and ticketing kiosks (0-5).",
}
CAPABILITIES = ("e-ticketing", "live tracking", "passenger information", "payments", "analytics")
_DIGITAL_ASSETS = ("S01", "S34", "S31", "D01")
_DIG_MEAN = {  # per capability; low live tracking / analytics are the planted digital gaps
    "S01": (3.5, 1.2, 2.2, 3.0, 0.9), "S34": (2.8, 1.0, 1.2, 2.5, 0.6),
    "S31": (3.0, 1.1, 1.8, 2.7, 0.7), "D01": (2.5, 1.5, 1.4, 2.2, 1.3),
}


def generate_assets(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for aid, name, atype in ASSETS:
        for dim, mu in zip(DIMENSIONS, _MEAN[aid]):
            score = float(np.clip(round(rng.normal(mu, 0.25) * 2) / 2, 0.0, 5.0))
            rows.append({"asset_id": aid, "asset_name": name, "asset_type": atype, "dimension": dim, "score": score,
                         "evidence_note": _NOTE[dim], "source_type": "synthetic"})
    a = pd.DataFrame(rows)
    drows, k = [], 0
    for aid in _DIGITAL_ASSETS:
        for cap, mu in zip(CAPABILITIES, _DIG_MEAN[aid]):
            k += 1
            score = float(np.clip(round(rng.normal(mu, 0.25) * 2) / 2, 0.0, 5.0))
            drows.append({"assessment_id": f"DA{k:03d}", "asset_id": aid, "capability": cap, "maturity_score": score,
                          "evidence_note": f"Synthetic maturity score for {cap} (0 = absent, 5 = fully integrated).",
                          "source_type": "synthetic"})
    return a, pd.DataFrame(drows)
