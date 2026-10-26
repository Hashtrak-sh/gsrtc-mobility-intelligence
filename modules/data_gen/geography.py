"""Geography for the pilot: zone/stop specs, OSM cache loading, manual fallback coordinates.

Coordinate provenance (``coord_source`` column on zones and stops):

* ``openstreetmap``          - coordinate exactly as cached by ``fetch_osm`` (no offset applied).
* ``openstreetmap_offset``   - an OSM-cached anchor plus a fixed, hand-entered offset (a synthetic demo stop
                               placed near a real place). Not an OSM feature in its own right.
* ``manual_demo_input``      - approximate hand-entered coordinate (``MANUAL_COORDS``); used when the OSM cache is
                               missing or did not match this place. NEVER labelled as OSM.

The zone / stop as a *demo entity* is synthetic regardless of where its coordinate came from.
This module never touches the network; ``fetch_osm`` does.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import config
from modules.data import io
from modules.data_gen import constants as C

OSM_CACHE_TABLE = "osm_places"


@dataclass(frozen=True)
class OsmTarget:
    key: str
    query: str            # Nominatim query (kind=place) or search hint (kind=bus_station)
    kind: str             # "place" | "bus_station"
    max_km: float         # accept an OSM match only if within this distance of the manual approximation


# key -> (approx lat, approx lon). Hand-entered approximations (manual_demo_input) - fallback only.
MANUAL_COORDS: dict[str, tuple[float, float]] = {
    "rajkot_bus_port": (22.2910, 70.8022),
    "rajkot_railway": (22.3124, 70.8026),
    "kalawad_road": (22.2857, 70.7710),
    "madhapar": (22.3200, 70.7500),
    "kotharia": (22.2440, 70.8177),
    "mavdi": (22.2640, 70.7650),
    "raiya": (22.2986, 70.7941),
    "gandhigram": (22.2800, 70.7750),
    "saurashtra_university": (22.2917, 70.7420),
    "ramnathpara": (22.3040, 70.8040),
    "aji_gidc": (22.2680, 70.8351),
    "metoda_gidc": (22.2384, 70.6787),
    "shapar": (22.1588, 70.7980),
    "gondal_bus_station": (21.9610, 70.7950),
    "jetpur_bus_station": (21.7540, 70.6250),
    "junagadh_bus_station": (21.5210, 70.4660),
    "keshod_bus_station": (21.3030, 70.2500),
    "veraval_bus_station": (20.9129, 70.3639),
    "somnath_bus_station": (20.8890, 70.4030),
    "jamnagar_bus_station": (22.4650, 70.0690),
    "ahmedabad_bus_station": (23.0270, 72.5810),
}

OSM_TARGETS: tuple[OsmTarget, ...] = (
    OsmTarget("rajkot_bus_port", "GSRTC Central Bus Station, Dhebar Road, Rajkot", "place", 5),
    OsmTarget("gondal_bus_station", "Gondal", "bus_station", 6),
    OsmTarget("jetpur_bus_station", "Jetpur", "bus_station", 6),
    OsmTarget("junagadh_bus_station", "Junagadh", "bus_station", 6),
    OsmTarget("keshod_bus_station", "Keshod", "bus_station", 6),
    OsmTarget("veraval_bus_station", "Veraval ST Bus Station|Veraval ST Bus Depot", "place", 6),
    OsmTarget("somnath_bus_station", "Somnath", "bus_station", 6),
    OsmTarget("jamnagar_bus_station", "Jamnagar", "bus_station", 8),
    OsmTarget("ahmedabad_bus_station", "Ahmedabad", "bus_station", 10),
    OsmTarget("rajkot_railway", "Rajkot Junction railway station, Rajkot, Gujarat, India", "place", 5),
    OsmTarget("aji_gidc", "Aji dam, Rajkot|Aji GIDC, Rajkot", "place", 8),
    OsmTarget("metoda_gidc", "Metoda GIDC, Rajkot, Gujarat, India", "place", 12),
    OsmTarget("shapar", "Shapar, Rajkot, Gujarat, India", "place", 10),
    OsmTarget("madhapar", "Madhapar, Rajkot, Gujarat, India", "place", 8),
    OsmTarget("kalawad_road", "Kalawad Road, Rajkot, Gujarat, India", "place", 8),
    OsmTarget("kotharia", "Kothariya Road Rajkot|Kotharia, Rajkot", "place", 8),
    OsmTarget("mavdi", "Mavdi, Rajkot, Gujarat, India", "place", 8),
    OsmTarget("raiya", "Raiya, Rajkot, Gujarat, India", "place", 8),
    OsmTarget("gandhigram", "Gandhigram, Rajkot, Gujarat, India", "place", 8),
    OsmTarget("saurashtra_university", "Saurashtra University, Rajkot, Gujarat, India", "place", 8),
    OsmTarget("ramnathpara", "Ramnathpara, Rajkot, Gujarat, India", "place", 8),
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_osm_cache(osm_dir: Path | str | None = None) -> pd.DataFrame | None:
    """Return the cached OSM places table (columns include key, lat, lon, matched) or None."""
    base = Path(osm_dir) if osm_dir is not None else config.RAW_DIR
    p = base / f"{OSM_CACHE_TABLE}.parquet"
    if not p.is_file():
        return None
    df = pd.read_parquet(p)
    return df[df["matched"].astype(bool)].reset_index(drop=True)


class CoordResolver:
    """Resolve anchor keys to (lat, lon, coord_source) using the OSM cache with manual fallback."""

    def __init__(self, osm: pd.DataFrame | None):
        self._osm: dict[str, tuple[float, float]] = {}
        if osm is not None:
            for r in osm.itertuples(index=False):
                self._osm[str(r.key)] = (float(r.lat), float(r.lon))

    @property
    def n_osm_keys(self) -> int:
        return len(self._osm)

    def anchor(self, key: str) -> tuple[float, float, bool]:
        """(lat, lon, from_osm)"""
        if key in self._osm:
            return (*self._osm[key], True)
        lat, lon = MANUAL_COORDS[key]
        return lat, lon, False

    def resolve(self, key: str, dlat: float = 0.0, dlon: float = 0.0) -> tuple[float, float, str]:
        lat, lon, from_osm = self.anchor(key)
        if not from_osm:
            return round(lat + dlat, 6), round(lon + dlon, 6), "manual_demo_input"
        if dlat == 0.0 and dlon == 0.0:
            return round(lat, 6), round(lon, 6), "openstreetmap"
        return round(lat + dlat, 6), round(lon + dlon, 6), "openstreetmap_offset"


# --------------------------------------------------------------------------
# Zone specs: zone_id, name, zone_type, anchor key, (pop range), (jobs range)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ZoneSpec:
    zone_id: str
    name: str
    zone_type: str
    anchor: str
    pop: tuple[int, int]
    jobs: tuple[int, int]
    pois: dict[str, tuple[int, int]]
    dlat: float = 0.0
    dlon: float = 0.0


_RES_POIS = {"school": (3, 9), "clinic": (2, 6), "market": (2, 7), "temple": (2, 6), "factory": (0, 2)}
_EMP_POIS = {"school": (0, 2), "clinic": (1, 3), "market": (1, 3), "temple": (0, 2), "factory": (25, 70)}
_MIX_POIS = {"school": (3, 8), "clinic": (4, 10), "market": (8, 20), "temple": (2, 6), "factory": (0, 4)}

ZONE_SPECS: tuple[ZoneSpec, ...] = (
    ZoneSpec("Z01", "Rajkot Central and Bus Port", "mixed", "rajkot_bus_port", (30000, 40000), (28000, 40000), _MIX_POIS),
    ZoneSpec("Z02", "Railway Station Area", "mixed", "rajkot_railway", (22000, 32000), (14000, 22000), _MIX_POIS),
    ZoneSpec("Z03", "Kalawad Road", "residential", "kalawad_road", (45000, 60000), (3000, 6000), _RES_POIS),
    ZoneSpec("Z04", "Madhapar", "residential", "madhapar", (35000, 50000), (2000, 5000), _RES_POIS),
    ZoneSpec("Z05", "Kotharia", "residential", "kotharia", (38000, 52000), (2500, 5000), _RES_POIS),
    ZoneSpec("Z06", "Mavdi", "residential", "mavdi", (50000, 65000), (3000, 6000), _RES_POIS),
    ZoneSpec("Z07", "Raiya", "residential", "raiya", (42000, 55000), (3000, 6000), _RES_POIS),
    ZoneSpec("Z08", "Gandhigram", "residential", "gandhigram", (28000, 38000), (2000, 4000), _RES_POIS),
    ZoneSpec("Z09", "Saurashtra University Area", "education", "saurashtra_university", (12000, 18000), (6000, 10000),
             {"school": (6, 12), "clinic": (1, 3), "market": (2, 5), "temple": (1, 3), "factory": (0, 1)}),
    ZoneSpec("Z10", "Ramnathpara", "religious", "ramnathpara", (14000, 20000), (3000, 6000),
             {"school": (2, 5), "clinic": (1, 3), "market": (5, 12), "temple": (10, 22), "factory": (0, 1)}),
    ZoneSpec("Z11", "Aji GIDC", "employment", "aji_gidc", (3000, 5000), (30000, 42000), _EMP_POIS, -0.0060, -0.0120),
    ZoneSpec("Z12", "Metoda GIDC", "employment", "metoda_gidc", (2500, 4500), (26000, 36000), _EMP_POIS),
    ZoneSpec("Z13", "Shapar-Veraval Industrial Area", "employment", "shapar", (3000, 5000), (28000, 38000), _EMP_POIS),
    ZoneSpec("Z14", "Bhaktinagar", "residential", "rajkot_railway", (25000, 35000), (2500, 5000), _RES_POIS,
             -0.0120, -0.0065),
    # intercity town zones (one representative zone per town)
    ZoneSpec("Z15", "Gondal", "mixed", "gondal_bus_station", (100000, 130000), (25000, 35000), _MIX_POIS),
    ZoneSpec("Z16", "Jetpur", "mixed", "jetpur_bus_station", (110000, 140000), (35000, 50000), _MIX_POIS),
    ZoneSpec("Z17", "Junagadh", "mixed", "junagadh_bus_station", (280000, 330000), (60000, 80000), _MIX_POIS),
    ZoneSpec("Z18", "Keshod", "mixed", "keshod_bus_station", (70000, 90000), (15000, 24000), _MIX_POIS),
    ZoneSpec("Z19", "Veraval", "mixed", "veraval_bus_station", (180000, 220000), (35000, 50000), _MIX_POIS),
    ZoneSpec("Z20", "Somnath", "religious", "somnath_bus_station", (30000, 45000), (10000, 18000),
             {"school": (2, 5), "clinic": (2, 5), "market": (10, 25), "temple": (15, 30), "factory": (0, 1)}),
    ZoneSpec("Z21", "Jamnagar", "mixed", "jamnagar_bus_station", (550000, 650000), (130000, 170000), _MIX_POIS),
    ZoneSpec("Z22", "Ahmedabad", "mixed", "ahmedabad_bus_station", (5500000, 6500000), (1500000, 2200000), _MIX_POIS),
)
ZONE_BY_ID = {z.zone_id: z for z in ZONE_SPECS}


@dataclass(frozen=True)
class StopSpec:
    stop_id: str
    name: str
    zone_id: str
    stop_type: str
    anchor: str
    dlat: float = 0.0
    dlon: float = 0.0


def _z(zid: str) -> str:
    return ZONE_BY_ID[zid].anchor


STOP_SPECS: tuple[StopSpec, ...] = (
    StopSpec("S01", "Rajkot Central Bus Stand", "Z01", "bus_stand", "rajkot_bus_port"),
    StopSpec("S02", "Lakhajiraj Road Stop", "Z01", "local_stop", "rajkot_bus_port", 0.0045, -0.0040),
    StopSpec("S03", "Rajkot Railway Station", "Z02", "local_stop", "rajkot_railway"),
    StopSpec("S04", "Station Road Stop", "Z02", "local_stop", "rajkot_railway", -0.0040, 0.0050),
    StopSpec("S05", "Kalawad Road Circle", "Z03", "local_stop", "kalawad_road"),
    StopSpec("S06", "Kalawad Road Crossing", "Z03", "local_stop", "kalawad_road", -0.0040, -0.0050),
    StopSpec("S07", "Madhapar Chowk", "Z04", "local_stop", "madhapar"),
    StopSpec("S08", "Madhapar Bypass Stop", "Z04", "local_stop", "madhapar", -0.0050, 0.0040),
    StopSpec("S09", "Kotharia Chokdi", "Z05", "local_stop", "kotharia"),
    StopSpec("S10", "Kotharia Road Stop", "Z05", "local_stop", "kotharia", -0.0040, 0.0050),
    StopSpec("S11", "Mavdi Circle", "Z06", "local_stop", "mavdi"),
    StopSpec("S12", "Mavdi Main Road Stop", "Z06", "local_stop", "mavdi", -0.0045, -0.0040),
    StopSpec("S13", "Raiya Circle", "Z07", "local_stop", "raiya"),
    StopSpec("S14", "Raiya Road Stop", "Z07", "local_stop", "raiya", 0.0050, -0.0040),
    StopSpec("S15", "Gandhigram Stop", "Z08", "local_stop", "gandhigram"),
    StopSpec("S16", "Gandhigram Society Stop", "Z08", "local_stop", "gandhigram", -0.0040, 0.0045),
    StopSpec("S17", "Saurashtra University Gate", "Z09", "local_stop", "saurashtra_university"),
    StopSpec("S18", "University Road Stop", "Z09", "local_stop", "saurashtra_university", 0.0045, 0.0040),
    StopSpec("S19", "Ramnathpara Temple Stop", "Z10", "local_stop", "ramnathpara"),
    StopSpec("S20", "Ramnathpara Market Stop", "Z10", "local_stop", "ramnathpara", -0.0040, -0.0045),
    StopSpec("S21", "Aji GIDC Gate", "Z11", "local_stop", "aji_gidc"),
    StopSpec("S22", "Aji GIDC Phase 2 Stop", "Z11", "local_stop", "aji_gidc", 0.0050, 0.0050),
    StopSpec("S23", "Metoda GIDC Gate", "Z12", "local_stop", "metoda_gidc"),
    StopSpec("S24", "Metoda GIDC Phase 2 Stop", "Z12", "local_stop", "metoda_gidc", -0.0050, -0.0045),
    StopSpec("S25", "Shapar Industrial Chowk", "Z13", "local_stop", "shapar"),
    StopSpec("S26", "Shapar-Veraval Industrial Gate", "Z13", "local_stop", "shapar", -0.0045, 0.0050),
    StopSpec("S27", "Bhaktinagar Stop", "Z14", "local_stop", "rajkot_railway", -0.0100, -0.0080),
    StopSpec("S28", "Bhaktinagar Circle", "Z14", "local_stop", "rajkot_railway", -0.0140, -0.0050),
    StopSpec("S29", "Gondal Bus Stand", "Z15", "intercity_terminal", "gondal_bus_station"),
    StopSpec("S30", "Jetpur Bus Stand", "Z16", "intercity_terminal", "jetpur_bus_station"),
    StopSpec("S31", "Junagadh Bus Stand", "Z17", "intercity_terminal", "junagadh_bus_station"),
    StopSpec("S32", "Keshod Bus Stand", "Z18", "intercity_terminal", "keshod_bus_station"),
    StopSpec("S33", "Veraval Bus Stand", "Z19", "intercity_terminal", "veraval_bus_station"),
    StopSpec("S34", "Somnath Bus Stand", "Z20", "intercity_terminal", "somnath_bus_station"),
    StopSpec("S35", "Jamnagar Bus Stand", "Z21", "intercity_terminal", "jamnagar_bus_station"),
    StopSpec("S36", "Ahmedabad Bus Stand", "Z22", "intercity_terminal", "ahmedabad_bus_station"),
)
STOP_BY_ID = {s.stop_id: s for s in STOP_SPECS}

CCTV_LOCATIONS: tuple[str, ...] = ("S01", "S31", "S34")  # Rajkot Central, Junagadh, Somnath stands


def _stop_source_type(stop_type: str, coord_source: str) -> str:
    """Entity provenance: only real OSM bus stations/stands are 'openstreetmap'; local demo stops are synthetic
    entities even when their coordinate was anchored on an OSM place (see coord_source for the coordinate)."""
    if coord_source == "manual_demo_input":
        return "manual_demo_input"
    if coord_source == "openstreetmap" and stop_type in ("bus_stand", "intercity_terminal"):
        return "openstreetmap"
    return "synthetic"


def build_zones(resolver: CoordResolver, rng: np.random.Generator, seed: int) -> pd.DataFrame:
    rows = []
    for z in ZONE_SPECS:
        lat, lon, cs = resolver.resolve(z.anchor, z.dlat, z.dlon)
        pop = int(rng.integers(z.pop[0], z.pop[1] + 1))
        wr_share = float(rng.uniform(0.33, 0.40))
        jobs = int(rng.integers(z.jobs[0], z.jobs[1] + 1))
        pois = {k: int(rng.integers(lo, hi + 1)) for k, (lo, hi) in z.pois.items()}
        rows.append({
            "zone_id": z.zone_id, "h3_id": None, "name": z.name, "lat": lat, "lon": lon,
            "population": pop, "workers_resident": int(pop * wr_share), "jobs": jobs,
            "poi_counts": json.dumps(pois, sort_keys=True), "zone_type": z.zone_type,
            "source_type": "synthetic", "seed": int(seed), "coord_source": cs,
        })
    return pd.DataFrame(rows)


def build_stops(resolver: CoordResolver) -> pd.DataFrame:
    rows = []
    for s in STOP_SPECS:
        lat, lon, cs = resolver.resolve(s.anchor, s.dlat, s.dlon)
        rows.append({
            "stop_id": s.stop_id, "name": s.name, "lat": lat, "lon": lon, "zone_id": s.zone_id,
            "is_bus_stand": s.stop_type in ("bus_stand", "intercity_terminal"),
            "stop_type": s.stop_type, "source_type": _stop_source_type(s.stop_type, cs), "coord_source": cs,
        })
    return pd.DataFrame(rows)


def in_bbox(lat: float, lon: float) -> bool:
    return config.PILOT_BBOX.contains(lat, lon)
