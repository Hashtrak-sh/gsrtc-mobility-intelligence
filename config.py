"""Central configuration for GSRTC Mobility Intelligence.

Everything tunable lives here: seed, pilot geography, scoring weights,
thresholds, labels and data paths. Analytics and pages import from this
module; they must not hardcode these values.
"""
from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------
# Reproducibility
# --------------------------------------------------------------------------
SEED: Final[int] = 42

# --------------------------------------------------------------------------
# Pilot geography
# --------------------------------------------------------------------------
PILOT_CITY: Final[str] = "Rajkot, Gujarat, India"

# Reference points (approximate, decimal degrees) used for sanity checks.
RAJKOT_LAT_LON: Final[tuple[float, float]] = (22.30, 70.80)
SOMNATH_LAT_LON: Final[tuple[float, float]] = (20.89, 70.40)


@dataclass(frozen=True)
class BoundingBox:
    """Demo bounding box (WGS84 degrees).

    The primary corridor runs roughly 190 km from Rajkot (about 22.30 N, 70.80 E)
    south-west to Somnath / Veraval (about 20.89 N, 70.40 E), so the box covers
    both ends plus the Junagadh area in between, with a small margin. It is
    intentionally NOT limited to the Rajkot city limits.
    """

    south: float = 20.80
    north: float = 22.45
    west: float = 70.20
    east: float = 71.00

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    @property
    def osmnx_bbox(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) order, as used by OSMnx >= 2."""
        return (self.west, self.south, self.east, self.north)


PILOT_BBOX: Final[BoundingBox] = BoundingBox()

# Named corridors (names only; coordinates/stops are produced in Milestone 1).
# Some far endpoints (e.g. Ahmedabad) lie outside PILOT_BBOX; that is a
# documented exception - the bbox bounds cached OSM geography, not every corridor.
PRIMARY_CORRIDOR: Final[str] = "Rajkot-Somnath"
INTERCITY_CORRIDORS: Final[tuple[str, ...]] = (
    "Rajkot-Somnath",
    "Rajkot-Junagadh",
    "Rajkot-Jamnagar",
    "Rajkot-Ahmedabad",
)

# --------------------------------------------------------------------------
# H3 (optional)
# --------------------------------------------------------------------------
H3_RESOLUTION: Final[int] = 8


def h3_available() -> bool:
    """True if the optional ``h3`` package is importable."""
    return importlib.util.find_spec("h3") is not None


# --------------------------------------------------------------------------
# Route potential score (docs/ANALYTICS_AND_ALGORITHMS.md section 3)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RouteScoreWeights:
    """Initial demo weights. NOT validated policy; shown with every score."""

    weight_version: str = "demo-v1"
    demand_potential: float = 0.25
    unmet_demand: float = 0.20
    load_factor: float = 0.15
    reliability_gap: float = 0.10
    revenue_potential: float = 0.10
    social_importance: float = 0.10
    feasibility: float = 0.10

    def components(self) -> dict[str, float]:
        d = asdict(self)
        d.pop("weight_version")
        return d

    def total(self) -> float:
        return sum(self.components().values())

    def validate(self) -> None:
        if abs(self.total() - 1.0) > 1e-9:
            raise ValueError(f"Route score weights must sum to 1.0, got {self.total()}")


ROUTE_SCORE_WEIGHTS: Final[RouteScoreWeights] = RouteScoreWeights()

# --------------------------------------------------------------------------
# Thresholds and scenario defaults
# --------------------------------------------------------------------------
# Crowding is flagged when gap_index = demand_estimate / seats_offered exceeds this.
CROWDING_GAP_INDEX_THRESHOLD: Final[float] = 1.2

# --------------------------------------------------------------------------
# M2 analytics assumptions (all illustrative; recorded in assumptions_json / provenance)
# --------------------------------------------------------------------------
# Reliability: a trip is "on time" when -1 <= departure_delay_min <= +5 (inclusive band, minutes).
RELIABILITY_ON_TIME_BAND_MIN: Final[tuple[float, float]] = (-1.0, 5.0)

# Intercity private-market proxy: assumed average occupancy of private competitor seats (assumption,
# NOT an observation; competitors have no ticket data in this prototype).
PRIVATE_MARKET_OCCUPANCY_ASSUMPTION: Final[float] = 0.75

# Intercity buses are "at capacity" when peak load factor >= this (hard seat cap, no standing).
AT_CAPACITY_LOAD_FACTOR: Final[float] = 0.95

# Service-frequency scenario: target peak-link load factor (share of seats) used for required departures.
SERVICE_TARGET_LOAD_FACTOR: Final[float] = 0.85

# Pricing scenario (elasticity is a scenario assumption, not a fitted fact).
PRICING_ELASTICITY_DEFAULT: Final[float] = -0.4
PRICING_ELASTICITY_SENSITIVITY: Final[tuple[float, ...]] = (-0.2, -0.4, -0.6, -0.8, -1.0)
PRICING_ELASTICITY_RANGE: Final[tuple[float, float]] = (-3.0, 0.0)
# Allowed new fare as a multiple of the baseline fare (fare bounds when none are given explicitly).
PRICING_FARE_BOUNDS_FACTOR: Final[tuple[float, float]] = (0.5, 2.0)

# Recommendations. Day type used for peak analysis; a recommendation is "High" priority when the summed average-day
# gap_count of its evidence rows reaches RECOMMENDATION_HIGH_GAP; a corridor no-capacity window must carry at least
# RECOMMENDATION_MIN_CORRIDOR_WINDOW_GAP passengers of proxy market demand per average day to be recommended; the state is
# assumed to capture STATE_CAPTURE_SHARE of the private-market proxy demand in an uncovered window (assumption).
PEAK_DAY_TYPE: Final[str] = "weekday"
RECOMMENDATION_HIGH_GAP: Final[float] = 50.0
RECOMMENDATION_MIN_CORRIDOR_WINDOW_GAP: Final[float] = 60.0
STATE_CAPTURE_SHARE: Final[float] = 0.25
CONFIDENCE_LABEL: Final[str] = "Indicative – synthetic data"

# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------
SIMULATION_BADGE_TEXT: Final[str] = "Simulated data for demonstration"
CURRENCY: Final[str] = "INR"

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT_DIR: Final[Path] = Path(__file__).resolve().parent
DATA_DIR: Final[Path] = ROOT_DIR / "data"
RAW_DIR: Final[Path] = DATA_DIR / "raw"
SYNTHETIC_DIR: Final[Path] = DATA_DIR / "synthetic"
PROCESSED_DIR: Final[Path] = DATA_DIR / "processed"
VIDEO_DIR: Final[Path] = RAW_DIR / "video"
PLANTED_FINDINGS_PATH: Final[Path] = SYNTHETIC_DIR / "planted_findings.md"

LAYER_DIRS: Final[dict[str, Path]] = {
    "raw": RAW_DIR,
    "synthetic": SYNTHETIC_DIR,
    "processed": PROCESSED_DIR,
}

# --------------------------------------------------------------------------
# Optional LLM (key comes from the environment only; never hardcode)
# --------------------------------------------------------------------------
ANTHROPIC_API_KEY_ENV: Final[str] = "ANTHROPIC_API_KEY"
ANTHROPIC_MODEL_ENV: Final[str] = "ANTHROPIC_MODEL"

ROUTE_SCORE_WEIGHTS.validate()

# Planted-finding detection (analytics side): a route-hour counts as "high load" when its seat-weighted peak load factor
# (max-link onboard / seats) exceeds this; standing passengers start above 1.0 on local buses.
HIGH_PEAK_LOAD_FACTOR: Final[float] = 1.1
