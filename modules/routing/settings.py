"""Routing constants (documented assumptions; the orchestrator may move these into ``config.py`` later)."""
from __future__ import annotations

from typing import Final

import config

# --- graph extents (west, south, east, north) ---------------------------------------------------------------
# City graph: full "drive" network over the dense Rajkot core that contains the local stops S01-S22, S27, S28.
CITY_BBOX: Final[tuple[float, float, float, float]] = (70.71, 22.23, 70.86, 22.35)
# Regional graph: major roads only (motorway/trunk/primary/secondary + links; secondary was added because primary-only left gaps), covering Rajkot -> Gondal -> Jetpur -> Junagadh -> Keshod -> Veraval -> Somnath,
# the Metoda / Shapar industrial stops and Jamnagar (just west of PILOT_BBOX; documented exception).
# Ahmedabad (IC06) is NOT covered: that route uses the labelled straight-line fallback.
CORRIDOR_BBOX: Final[tuple[float, float, float, float]] = (
    min(config.PILOT_BBOX.west, 70.00), config.PILOT_BBOX.south, config.PILOT_BBOX.east, 22.50,
)
CORRIDOR_FILTER: Final[str] = (
    '["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"]'
)

GRAPH_KINDS: Final[tuple[str, ...]] = ("city", "corridor")
GRAPH_FILES: Final[dict[str, str]] = {"city": "osm_graph_city.graphml", "corridor": "osm_graph_corridor.graphml"}

ATTRIBUTION: Final[str] = "(c) OpenStreetMap contributors, ODbL 1.0"

# --- travel-time assumptions (km/h) used by ox.add_edge_speeds as fallback for untagged highway classes ----------
# Illustrative bus speeds: lower than car free-flow. Applied per highway class; NOT measured.
SPEED_FALLBACKS_KPH: Final[dict[str, float]] = {
    "motorway": 90.0, "trunk": 75.0, "primary": 60.0, "secondary": 50.0, "tertiary": 40.0,
    "unclassified": 30.0, "residential": 25.0, "service": 15.0,
}
DEFAULT_SPEED_KPH: Final[float] = 30.0
# Bus speed = this fraction of OSM maxspeed / fallback speed (stops, signals, congestion)
BUS_SPEED_FACTOR: Final[float] = 0.7
DWELL_MIN_PER_STOP: Final[float] = 0.5  # added per intermediate stop when estimating travel time

# --- fallback ---------------------------------------------------------------------------------------------------
STRAIGHT_LINE_DETOUR_FACTOR: Final[float] = 1.3   # road length ~ 1.3 x haversine (typical for Indian road networks)
FALLBACK_SPEED_KPH: Final[float] = 30.0           # local fallback speed
FALLBACK_INTERCITY_SPEED_KPH: Final[float] = 45.0  # used when straight leg > 25 km
INTERCITY_LEG_KM: Final[float] = 25.0

# --- snapping --------------------------------------------------------------------------------------------------
MAX_SNAP_M: Final[float] = 1500.0   # a stop farther than this from the graph is not snapped (uses fallback for the route)

# --- candidates ------------------------------------------------------------------------------------------------
WALK_BUFFER_M: Final[float] = 800.0
