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
# Sensitivity of the corridor-slot recommendation to the (assumed) capture share; stored in expected_impact_json.
STATE_CAPTURE_SHARE_SENSITIVITY: Final[tuple[float, ...]] = (0.15, 0.25, 0.35)
# A hard-capped (intercity) route-hour is only recommended for extra capacity when its peak load factor is essentially 100%.
RECOMMENDATION_FULL_CAPACITY_INDEX: Final[float] = 0.99
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

# --------------------------------------------------------------------------
# M4 route candidates (modules/routing/candidates.py). Illustrative; shown with every candidate score.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CandidateScoreWeights:
    """Weights of the candidate-route score. Components are scaled 0-1 within a corridor group. NOT validated policy."""

    weight_version: str = "cand-demo-v1"
    population_covered: float = 0.30   # residents within the walk buffer of the path
    jobs_covered: float = 0.30         # jobs within the walk buffer of the path
    time_efficiency: float = 0.20      # 1 - travel_time_penalty (capped at 100 %)
    new_coverage: float = 0.20         # 1 - overlap with existing route paths

    def components(self) -> dict[str, float]:
        d = asdict(self)
        d.pop("weight_version")
        return d

    def total(self) -> float:
        return sum(self.components().values())

    def validate(self) -> None:
        if abs(self.total() - 1.0) > 1e-9:
            raise ValueError(f"Candidate score weights must sum to 1.0, got {self.total()}")


CANDIDATE_SCORE_WEIGHTS: Final[CandidateScoreWeights] = CandidateScoreWeights()
CANDIDATE_SCORE_WEIGHTS.validate()
CANDIDATE_WALK_BUFFER_M: Final[float] = 800.0     # zone centroid within this distance of the path counts as covered
CANDIDATE_OVERLAP_BUFFER_M: Final[float] = 150.0  # path point within this distance of an existing route path = overlap


# ==========================================================================
# M5 (competition, pricing, survey intelligence) - begin
# ==========================================================================
@dataclass(frozen=True)
class CompetitiveGapWeights:
    """Visible, versioned weights of the competitive gap score (0-100). Demo values, NOT validated policy.

    Every component is scaled to 0-1 (see ``modules/competition/analysis.py``); score = 100 x sum(weight x component) over
    the components that are available (a missing component is dropped and the rest re-weighted).
    """

    weight_version: str = "demo-comp-v1"
    departure_slot_gap: float = 0.30   # private departures with no (or fewer) state departures in the clock hour
    seat_share_gap: float = 0.20       # private seats exceeding state seats in the clock hour
    premium_gap: float = 0.20          # private premium / AC-sleeper services with no state equivalent in the slot
    fare_disadvantage: float = 0.10    # state tariff ABOVE the private median fare (0 when the state is cheaper)
    review_theme_deficit: float = 0.20  # themes where state reviews are more negative than private ones (corridor level)

    def components(self) -> dict[str, float]:
        d = asdict(self)
        d.pop("weight_version")
        return d

    def total(self) -> float:
        return sum(self.components().values())

    def validate(self) -> None:
        if abs(self.total() - 1.0) > 1e-9:
            raise ValueError(f"Competitive gap weights must sum to 1.0, got {self.total()}")


COMPETITIVE_GAP_WEIGHTS: Final[CompetitiveGapWeights] = CompetitiveGapWeights()
COMPETITIVE_GAP_WEIGHTS.validate()
# Private bus types counted as "premium" for the premium-gap component; the state equivalent is a state AC_sleeper departure.
PREMIUM_BUS_TYPES: Final[tuple[str, ...]] = ("AC_sleeper", "premium")
STATE_PREMIUM_EQUIVALENT: Final[tuple[str, ...]] = ("AC_sleeper",)
PREMIUM_GAP_SATURATION: Final[float] = 2.0        # premium_bus_gap of this many services scores 1.0
FARE_DISADVANTAGE_SATURATION: Final[float] = 0.25  # fare_index - 1 of this size scores 1.0
REVIEW_DEFICIT_SATURATION: Final[float] = 0.15    # mean per-theme negative-share deficit of this size scores 1.0
REVIEW_MIN_PER_OPERATOR: Final[int] = 10          # fewer reviews per operator type on a corridor -> component missing
# Fare scenario attached to the corridor-slot recommendation: the new service is priced at this share of the private median fare.
COMPETITION_FARE_POSITION: Final[float] = 0.85

# Survey switch-intent model (illustrative; modules/survey/mode_choice.py)
SURVEY_MODEL_TEST_SIZE: Final[float] = 0.25
SURVEY_MODEL_C: Final[float] = 1.0e6              # inverse L2 strength: effectively unregularised, so coefficients are comparable to the truth
SURVEY_MODEL_LABEL: Final[str] = ("illustrative, conditional on the synthetic training setup - not a forecast of real behaviour")
# ==========================================================================
# M5 - end
# ==========================================================================

# ==========================================================================
# M6-ML (ridership baseline model + baseline forecast) - begin
# ==========================================================================
RIDERSHIP_TRAIN_DAYS: Final[int] = 28            # first 4 weeks train, the remaining service dates (2 weeks) are the test window
RIDERSHIP_MODEL_VERSION: Final[str] = "ridership-hgb-v1"
RIDERSHIP_INTERVAL_QUANTILES: Final[tuple[float, float]] = (0.1, 0.9)   # nominal 80 % interval
RIDERSHIP_PERMUTATION_REPEATS: Final[int] = 20
RIDERSHIP_LABEL: Final[str] = "Synthetic-data demonstration metrics - not evidence of real-world accuracy"
FORECAST_HORIZON_DAYS: Final[int] = 7
FORECAST_HISTORY_WEEKS: Final[int] = 4
# ==========================================================================
# M6-ML - end
# ==========================================================================
