"""Tunable constants and documented assumptions for the synthetic generator.

Everything here is an *illustrative demonstration assumption*. None of it is an
actual GSRTC tariff, cost, schedule or measurement. These values are recorded in
the provenance sidecars and are imported by analytics (M2) where needed
(e.g. ``BUS_TYPE_SEATS``, ``OPERATING_COST_PER_KM_INR``, ``LOCAL_CRUSH_FACTOR``).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Final

import config

# --------------------------------------------------------------------------
# Calendar: 6 weeks (42 days), Monday 2026-08-03 .. Sunday 2026-09-13
# --------------------------------------------------------------------------
START_DATE: Final[date] = date(2026, 8, 3)
N_DAYS: Final[int] = 42
# Synthetic/illustrative festival days: Janmashtami period (2026-09-04, 2026-09-05).
FESTIVAL_DATES: Final[tuple[date, ...]] = (date(2026, 9, 4), date(2026, 9, 5))
FESTIVAL_NAME: Final[str] = "Janmashtami period (synthetic/illustrative)"


def service_dates(days: int = N_DAYS) -> list[date]:
    return [START_DATE + timedelta(days=i) for i in range(days)]


def day_type(d: date) -> str:
    if d in FESTIVAL_DATES:
        return "festival"
    return "weekend" if d.weekday() >= 5 else "weekday"


# --------------------------------------------------------------------------
# Enumerations (also enforced by validate.py)
# --------------------------------------------------------------------------
ZONE_TYPES: Final = ("residential", "employment", "mixed", "education", "religious", "other")
STOP_TYPES: Final = ("local_stop", "bus_stand", "intercity_terminal")
ROUTE_TYPES: Final = ("local", "intercity")
BUS_TYPES: Final = ("ordinary", "express", "AC_seater", "AC_sleeper", "other")
TRIP_BUS_TYPES: Final = ("ordinary", "express", "AC_seater", "AC_sleeper")
COMPETITOR_BUS_TYPES: Final = ("ordinary", "AC_seater", "AC_sleeper", "premium")
DAY_TYPES: Final = ("weekday", "weekend", "festival")
PASSENGER_TYPES: Final = ("adult", "student", "senior", "other")
SOURCE_TYPES: Final = ("synthetic", "openstreetmap", "manual_demo_input", "model_output", "live_demo_response")
COORD_SOURCES: Final = ("openstreetmap", "openstreetmap_offset", "manual_demo_input")
CCTV_CLASSES: Final = ("person", "car", "two_wheeler", "auto", "bus", "truck", "other")
CCTV_DIRECTIONS: Final = ("inbound", "outbound", "unknown")
CCTV_METHODS: Final = ("actual_detector", "manual_demo_input", "synthetic")
MODES: Final = ("car", "two_wheeler", "bus", "rail", "shared_taxi", "other")
PURPOSES: Final = ("work", "education", "shopping", "health", "leisure", "other")
ASSET_TYPES: Final = ("station", "depot", "stop")
ASSET_DIMENSIONS: Final = ("cleanliness", "accessibility", "safety", "amenities", "digital", "other")
DIGITAL_CAPABILITIES: Final = ("e-ticketing", "live tracking", "passenger information", "payments", "analytics", "other")
REVIEW_THEMES: Final = ("punctuality", "cleanliness", "comfort_ac", "staff_behaviour", "booking_ease", "safety", "value")
SWITCH_CONDITIONS: Final = (
    "reliability", "ac_comfort", "frequency", "lower_fare", "safety", "cleanliness",
    "real_time_info", "parking_cost_or_hassle", "direct_route",
)
PRIVATE_USE_REASONS: Final = (
    "flexibility", "door_to_door", "comfort", "bus_unreliable", "no_ac_on_bus",
    "low_bus_frequency", "crowding", "safety", "no_direct_route", "carries_goods_or_family",
)
SURVEY_INCOME_BANDS: Final = ("low", "lower_middle", "middle", "upper_middle", "high")

# --------------------------------------------------------------------------
# Capacity / standing rules
# --------------------------------------------------------------------------
BUS_TYPE_SEATS: Final[dict[str, int]] = {"ordinary": 40, "express": 45, "AC_seater": 40, "AC_sleeper": 30}
# Local ordinary buses allow standees: onboard load may reach LOCAL_CRUSH_FACTOR x seats.
LOCAL_CRUSH_FACTOR: Final[float] = 1.6
# Intercity reserved buses never exceed seats (excess demand is unmet).
INTERCITY_CRUSH_FACTOR: Final[float] = 1.0


def onboard_cap(route_type: str, seats: int) -> int:
    factor = LOCAL_CRUSH_FACTOR if route_type == "local" else INTERCITY_CRUSH_FACTOR
    return int(seats * factor)


# --------------------------------------------------------------------------
# Operating cost (INR per vehicle-km, illustrative; cost = rate x route length_km)
# --------------------------------------------------------------------------
OPERATING_COST_PER_KM_INR: Final[dict[str, float]] = {
    "ordinary": 52.0, "express": 58.0, "AC_seater": 70.0, "AC_sleeper": 80.0,
}

# --------------------------------------------------------------------------
# Fare table (INR; illustrative demo tariff, NOT an actual GSRTC tariff)
# fare per passenger = max(min_fare, base + per_km * km), rounded to a multiple of `round_to`
# ticket fare_inr = per-passenger fare x concession factor x passenger_count
# --------------------------------------------------------------------------
FARE_TABLE: Final[dict[str, dict[str, float]]] = {
    "ordinary":   {"base": 3.0,  "per_km": 1.00, "min_fare": 5.0,  "round_to": 1.0},
    "express":    {"base": 5.0,  "per_km": 1.25, "min_fare": 10.0, "round_to": 5.0},
    "AC_seater":  {"base": 10.0, "per_km": 1.90, "min_fare": 30.0, "round_to": 5.0},
    "AC_sleeper": {"base": 20.0, "per_km": 2.40, "min_fare": 50.0, "round_to": 5.0},
}
CONCESSION_FACTOR: Final[dict[str, float]] = {"adult": 1.0, "student": 0.5, "senior": 0.5, "other": 0.75}
PASSENGER_TYPE_PROBS_LOCAL: Final[dict[str, float]] = {"adult": 0.62, "student": 0.24, "senior": 0.08, "other": 0.06}
PASSENGER_TYPE_PROBS_INTERCITY: Final[dict[str, float]] = {"adult": 0.80, "student": 0.07, "senior": 0.09, "other": 0.04}
GROUP_MERGE_PROB: Final[float] = 0.06  # chance a same-OD adult/other ticket is merged into a group booking

# --------------------------------------------------------------------------
# Speeds / distances / timing
# --------------------------------------------------------------------------
SPEED_KMPH: Final[dict[str, float]] = {"ordinary": 18.0, "express": 46.0, "AC_seater": 52.0, "AC_sleeper": 52.0}
DWELL_MIN_LOCAL: Final[float] = 1.0
DWELL_MIN_INTERCITY: Final[float] = 4.0
ROAD_FACTOR_LOCAL: Final[float] = 1.35   # road km = straight-line km x factor
ROAD_FACTOR_INTERCITY: Final[float] = 1.15

# Documented departure delay model (minutes; negative = early)
DELAY_ON_TIME_TOLERANCE_MIN: Final[float] = 5.0  # suggested reliability tolerance for M2

# --------------------------------------------------------------------------
# Demand profiles (relative multipliers by hour of day)
# --------------------------------------------------------------------------
LOCAL_HOUR_PROFILE_WEEKDAY: Final[dict[int, float]] = {
    5: 0.4, 6: 0.8, 7: 1.8, 8: 2.0, 9: 1.2, 10: 0.8, 11: 0.7, 12: 0.7, 13: 0.7, 14: 0.7,
    15: 0.8, 16: 1.0, 17: 1.5, 18: 1.7, 19: 1.1, 20: 0.7, 21: 0.45, 22: 0.3,
}
LOCAL_HOUR_PROFILE_WEEKEND: Final[dict[int, float]] = {
    5: 0.3, 6: 0.5, 7: 0.7, 8: 0.9, 9: 1.0, 10: 1.1, 11: 1.1, 12: 1.0, 13: 0.9, 14: 0.9,
    15: 1.0, 16: 1.1, 17: 1.2, 18: 1.2, 19: 1.0, 20: 0.7, 21: 0.45, 22: 0.3,
}
LOCAL_DAY_FACTOR: Final[dict[str, float]] = {"weekday": 1.0, "weekend": 0.65, "festival": 0.75}
INTERCITY_HOUR_PROFILE: Final[dict[int, float]] = {
    5: 0.8, 6: 0.9, 7: 1.0, 8: 1.0, 9: 1.0, 10: 0.85, 11: 0.85, 12: 0.85, 13: 0.85, 14: 0.9,
    15: 0.95, 16: 0.95, 17: 1.0, 18: 0.9, 19: 0.9, 20: 0.9, 21: 0.8, 22: 0.7, 23: 0.7,
}
INTERCITY_DAY_FACTOR_DEFAULT: Final[dict[str, float]] = {"weekday": 1.0, "weekend": 1.25, "festival": 1.5}

# --------------------------------------------------------------------------
# Survey: switch_intent logistic mechanism (documented in planted_findings.md)
# logit(p) = INTENT_INTERCEPT + sum(coef * feature)
# --------------------------------------------------------------------------
INTENT_INTERCEPT: Final[float] = -2.0
INTENT_COEF: Final[dict[str, float]] = {
    "cond_reliability": 1.10,
    "cond_ac_comfort": 0.90,
    "cond_frequency": 0.95,
    "cond_lower_fare": 0.30,
    "mode_car": -0.35,          # car users somewhat less willing than two-wheeler users
    "purpose_work": 0.25,
    "income_high": -0.30,       # income_band in (upper_middle, high)
}
N_SURVEY_RESPONSES: Final[int] = 800

# --------------------------------------------------------------------------
# Coordinates exceptions (outside config.PILOT_BBOX on purpose)
# --------------------------------------------------------------------------
BBOX_EXCEPTION_STOP_NAMES: Final[tuple[str, ...]] = ("Jamnagar Bus Stand", "Ahmedabad Bus Stand")

# --------------------------------------------------------------------------
# Child-RNG stage ids (never reorder: reproducibility depends on them)
# --------------------------------------------------------------------------
STAGE_ZONES: Final[int] = 1
STAGE_TRIPS: Final[int] = 2
STAGE_TICKETS: Final[int] = 3
STAGE_CCTV: Final[int] = 4
STAGE_SURVEY: Final[int] = 5
STAGE_COMPETITION: Final[int] = 6
STAGE_REVIEWS: Final[int] = 7
STAGE_ASSETS: Final[int] = 8

PILOT_BBOX = config.PILOT_BBOX
