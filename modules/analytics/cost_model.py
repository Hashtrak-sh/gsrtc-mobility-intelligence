"""Bus cost model (illustrative): trip operating cost layer + fixed/overhead layer, seven bus classes.

ALL DEFAULTS ARE ILLUSTRATIVE, EDITABLE ASSUMPTIONS - orders of magnitude typical of Indian state transport undertakings,
NOT GSRTC data. Every number is labelled "illustrative" wherever it is shown (RULES.md). No Streamlit, no file I/O in the
core functions (``load_cost_inputs`` is the only helper that reads parquet).

Two layers, per vehicle-km (``L`` = route length in km, a "trip" is one one-way run of length ``L``)
-----------------------------------------------------------------------------------------------
(a) TRIP OPERATING COST (the only cost in today's ``contribution`` on every other page)::

        trip_operating_per_km = energy + tyres + maintenance_and_other_running + crew
        energy   = diesel_inr_per_l / fuel_km_per_l x (1 + ac_fuel_penalty)        [diesel classes]
                 = electricity_inr_per_kwh x kwh_per_km                            [e_bus]
        crew     = (driver_inr_per_hour + conductor_inr_per_hour) / speed_kmph x peak_factor
        peak_factor = peak_running_time_factor in the peak band, 1.0 otherwise.

    CONSISTENCY WITH THE BASE RATE: for the 4 timetable classes the *maintenance and other running costs* line is the
    documented BALANCING ITEM. At default parameters and normal hours::

        maintenance = constants.OPERATING_COST_PER_KM_INR[class] - energy - tyres - crew      (INR/vehicle-km)

    so ``trip_operating_per_km == constants.OPERATING_COST_PER_KM_INR[class]`` exactly (same rate that
    ``trips.operating_cost_inr`` and every contribution figure use). The crew line uses the class REFERENCE SPEED =
    vehicle-km-weighted mean running speed of that class's routes in ``trips``:
    ``sum(length_km) / sum(scheduled_minutes / 60)`` over the class's trips (includes dwell; ordinary = local routes only).
    Changing a parameter (diesel price, crew rate ...) then moves the total away from the base rate; maintenance stays fixed.

(b) FIXED AND OVERHEAD COSTS (NOT in today's contribution)::

        dead_km_uplift  = dead_km_share x (energy + tyres + maintenance)   [dead km per revenue km; crew not scaled]
        depreciation    = price x (1 - residual_pct) / life_years / (daily_km x working_days_per_year)
                          (or ``lease_inr_per_km`` when set; the lease REPLACES depreciation)
        insurance_etc   = insurance_tax_permit_inr_per_year / (daily_km x working_days_per_year)
        tolls           = corridor_toll_inr_per_trip x class toll multiplier / L        (per one-way trip)
        overhead        = overhead_share x (trip operating + dead_km_uplift + depreciation + insurance_etc + tolls)
        full_cost_per_km = trip_operating_per_km + (all of the above)

Peak effect: crew cost is multiplied by ``peak_running_time_factor`` in the peak band. Default 1.0 (no effect) because the
synthetic timetable has CONSTANT running times per route (``trips.scheduled_minutes`` takes exactly one value per route and
is identical in both directions and all hours - verified from the data and tested), so the data carry no peak slow-down.

Bus classes: 4 timetable classes (ordinary, express, AC_seater, AC_sleeper) and 3 WHAT-IF-ONLY classes that are not in the
timetable: ``volvo_ac`` (multi-axle premium AC seater), ``non_ac_sleeper``, ``e_bus`` (electric AC seater, GCC-style lease:
the per-km lease replaces depreciation and covers bus + battery capital recovery; energy, crew, tyres, maintenance and
insurance stay with the operator).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

import pandas as pd

from modules.data_gen import constants as C

ILLUSTRATIVE_LABEL = "Illustrative assumption - not GSRTC data"
EXISTING_CLASSES: tuple[str, ...] = ("ordinary", "express", "AC_seater", "AC_sleeper")
WHAT_IF_CLASSES: tuple[str, ...] = ("volvo_ac", "non_ac_sleeper", "e_bus")
ALL_CLASSES: tuple[str, ...] = EXISTING_CLASSES + WHAT_IF_CLASSES
CLASS_LABELS: dict[str, str] = {
    "ordinary": "Ordinary", "express": "Express", "AC_seater": "AC seater", "AC_sleeper": "AC sleeper",
    "volvo_ac": "Volvo AC seater (what-if)", "non_ac_sleeper": "Non-AC sleeper (what-if)", "e_bus": "Electric AC bus (what-if)",
}

LAYER_TRIP = "trip_operating"
LAYER_FIXED = "fixed_and_overhead"
TRIP_COMPONENTS: tuple[str, ...] = ("energy", "tyres", "maintenance_and_other_running", "crew")
FIXED_COMPONENTS: tuple[str, ...] = ("dead_km_uplift", "depreciation_or_lease", "insurance_tax_permits", "tolls", "overhead")
COMPONENT_LABELS: dict[str, str] = {
    "energy": "Fuel / electricity", "tyres": "Tyres", "maintenance_and_other_running": "Maintenance and other running costs",
    "crew": "Crew (driver + conductor)", "dead_km_uplift": "Dead-km uplift", "depreciation_or_lease": "Depreciation / lease",
    "insurance_tax_permits": "Insurance, MV tax, permits", "tolls": "Tolls", "overhead": "Depot / admin overhead",
}


@dataclass(frozen=True)
class GlobalParams:
    """Parameters common to all classes. Every default is illustrative."""

    diesel_inr_per_l: float = 92.0              # INR/litre; Gujarat retail diesel is roughly INR 90-95
    electricity_inr_per_kwh: float = 9.0        # INR/kWh; commercial EV charging tariff about INR 8-10
    dead_km_share: float = 0.05                 # dead km (garage runs, positioning) per revenue km; STUs typically 3-8 %
    overhead_share: float = 0.12                # depot/admin overhead as a share of direct cost; typically 10-15 %
    driver_inr_per_hour: float = 180.0          # INR per duty hour incl. allowances (about INR 45-55k/month loaded)
    conductor_inr_per_hour: float = 150.0       # INR per duty hour incl. allowances
    peak_running_time_factor: float = 1.0       # crew-hours multiplier in peak; 1.0 because timetable running times are constant
    working_days_per_year: float = 330.0        # operating days per bus per year (rest = maintenance / holidays)

    def __post_init__(self) -> None:
        for n in ("diesel_inr_per_l", "electricity_inr_per_kwh", "driver_inr_per_hour", "conductor_inr_per_hour",
                  "peak_running_time_factor", "working_days_per_year"):
            if getattr(self, n) <= 0:
                raise ValueError(f"{n} must be > 0")
        for n in ("dead_km_share", "overhead_share"):
            if not 0 <= getattr(self, n) < 1:
                raise ValueError(f"{n} must be in [0, 1)")


@dataclass(frozen=True)
class FareParams:
    """Per-passenger fare = max(min_fare, base + per_km x km), rounded to a multiple of round_to (as ``constants.FARE_TABLE``)."""

    base: float
    per_km: float
    min_fare: float
    round_to: float = 5.0


@dataclass(frozen=True)
class ClassParams:
    """Per bus class parameters. Defaults are illustrative (see ``default_class_params``)."""

    name: str
    seats: int                                   # seats (berths for sleepers)
    fare: FareParams
    energy: str = "diesel"                       # "diesel" | "electric"
    fuel_km_per_l: float = 4.2                   # km per litre, non-AC base (diesel classes)
    kwh_per_km: float = 0.0                      # kWh per vehicle-km (electric)
    ac_fuel_penalty: float = 0.0                 # extra fuel use of the AC load, share of base fuel (e.g. 0.10 = +10 %)
    tyres_inr_per_km: float = 2.5
    maintenance_inr_per_km: float = 0.0          # maintenance and other running costs (balancing item for timetable classes)
    bus_price_inr: float = 4_000_000.0
    lease_inr_per_km: float | None = None        # when set, replaces depreciation (GCC-style lease)
    life_years: float = 10.0
    residual_pct: float = 0.10                   # residual (scrap) value as a share of price
    insurance_tax_permit_inr_per_year: float = 120_000.0
    daily_km: float = 350.0                      # revenue km per bus per operating day
    toll_multiplier: float = 1.0                 # vehicle-class toll factor vs the corridor bus toll
    speed_kmph: float | None = None              # None -> reference speed from the timetable (timetable classes only)
    intercity_speed_kmph: float | None = None    # overrides the speed for what-if runs on intercity corridors
    is_what_if: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if self.energy not in ("diesel", "electric"):
            raise ValueError("energy must be 'diesel' or 'electric'")
        if self.seats <= 0 or self.daily_km <= 0 or self.life_years <= 0:
            raise ValueError("seats, daily_km and life_years must be > 0")
        if self.energy == "diesel" and self.fuel_km_per_l <= 0:
            raise ValueError("fuel_km_per_l must be > 0 for diesel classes")


# Illustrative one-way bus toll per corridor trip (INR). Order of magnitude: INR 150-350 per plaza per bus per direction,
# 1-3 plazas on each national-highway corridor. Not actual NHAI rates.
DEFAULT_TOLLS_INR_PER_TRIP: dict[str, float] = {
    "Rajkot-Somnath": 500.0, "Rajkot-Junagadh": 250.0, "Rajkot-Jamnagar": 250.0, "Rajkot-Ahmedabad": 600.0,
}

# Fare parameters of the three what-if classes (illustrative); timetable classes use constants.FARE_TABLE.
_WHAT_IF_FARES: dict[str, FareParams] = {
    "volvo_ac": FareParams(base=15.0, per_km=2.30, min_fare=40.0, round_to=5.0),
    "non_ac_sleeper": FareParams(base=15.0, per_km=1.90, min_fare=40.0, round_to=5.0),
    "e_bus": FareParams(base=10.0, per_km=1.90, min_fare=30.0, round_to=5.0),
}


def _fare_params(cls: str) -> FareParams:
    if cls in C.FARE_TABLE:
        return FareParams(**C.FARE_TABLE[cls])
    return _WHAT_IF_FARES[cls]


@dataclass(frozen=True)
class CostModel:
    """Parameter bundle: global params, per-class params, reference speeds (km/h) and corridor tolls (INR per one-way trip).

    Override with ``dataclasses.replace`` or the helpers ``with_global`` / ``with_class`` / ``with_toll``.
    """

    global_params: GlobalParams
    class_params: Mapping[str, ClassParams]
    ref_speeds: Mapping[str, float]
    tolls: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TOLLS_INR_PER_TRIP))

    def with_global(self, **kw: float) -> "CostModel":
        return replace(self, global_params=replace(self.global_params, **kw))

    def with_class(self, name: str, **kw) -> "CostModel":
        cp = dict(self.class_params)
        cp[name] = replace(cp[name], **kw)
        return replace(self, class_params=cp)

    def with_toll(self, corridor: str, inr_per_trip: float) -> "CostModel":
        t = dict(self.tolls)
        t[corridor] = float(inr_per_trip)
        return replace(self, tolls=t)


# ------------------------------------------------------------------ reference speeds and defaults
def reference_speeds(trips: pd.DataFrame, routes: pd.DataFrame) -> dict[str, float]:
    """Vehicle-km-weighted mean running speed (km/h) per timetable class: ``sum(length_km) / sum(scheduled_minutes / 60)``.

    Computed over all trips of the class (state operator), includes dwell time. Ordinary is local-routes only.
    """
    t = trips[["route_id", "bus_type", "scheduled_minutes"]].merge(routes[["route_id", "length_km"]], on="route_id", how="left")
    g = t.groupby("bus_type").agg(km=("length_km", "sum"), minutes=("scheduled_minutes", "sum"))
    out = {str(b): float(r.km / (r.minutes / 60.0)) for b, r in g.iterrows() if r.minutes > 0}
    missing = [c for c in EXISTING_CLASSES if c not in out]
    if missing:
        raise ValueError(f"no trips for timetable class(es) {missing}; cannot derive reference speeds")
    return out


def energy_per_km(gp: GlobalParams, cp: ClassParams) -> float:
    """Fuel or electricity cost, INR per vehicle-km."""
    if cp.energy == "electric":
        return gp.electricity_inr_per_kwh * cp.kwh_per_km
    return gp.diesel_inr_per_l / cp.fuel_km_per_l * (1.0 + cp.ac_fuel_penalty)


def _crew_per_km(gp: GlobalParams, speed_kmph: float, peak: bool) -> float:
    f = gp.peak_running_time_factor if peak else 1.0
    return (gp.driver_inr_per_hour + gp.conductor_inr_per_hour) / speed_kmph * f


def _base_classes() -> dict[str, ClassParams]:
    """Class defaults before the maintenance balancing of the timetable classes. All illustrative."""
    return {
        # Ordinary: stop-go, 40 seats, lower-spec bus (INR 30 lakh), city/short-haul duty.
        "ordinary": ClassParams("ordinary", C.BUS_TYPE_SEATS["ordinary"], _fare_params("ordinary"), fuel_km_per_l=4.5,
                                tyres_inr_per_km=2.5, bus_price_inr=3_000_000.0, insurance_tax_permit_inr_per_year=90_000.0,
                                daily_km=220.0, intercity_speed_kmph=38.0,
                                note="what-if on intercity corridors uses 38 km/h (ordinary intercity running speed assumption)"),
        # Express: ~45 seats, INR 38 lakh, 4.2 km/l typical for BS-VI 12 m diesel on highways.
        "express": ClassParams("express", C.BUS_TYPE_SEATS["express"], _fare_params("express"), fuel_km_per_l=4.2,
                               tyres_inr_per_km=2.5, bus_price_inr=3_800_000.0, insurance_tax_permit_inr_per_year=120_000.0,
                               daily_km=350.0),
        # AC seater: INR 55 lakh, AC load +10 % fuel, higher AC upkeep (inside the balancing item).
        "AC_seater": ClassParams("AC_seater", C.BUS_TYPE_SEATS["AC_seater"], _fare_params("AC_seater"), fuel_km_per_l=4.2,
                                 ac_fuel_penalty=0.10, tyres_inr_per_km=3.0, bus_price_inr=5_500_000.0,
                                 insurance_tax_permit_inr_per_year=150_000.0, daily_km=350.0),
        # AC sleeper: heavier body (3.8 km/l), INR 75 lakh, longer night duty.
        "AC_sleeper": ClassParams("AC_sleeper", C.BUS_TYPE_SEATS["AC_sleeper"], _fare_params("AC_sleeper"), fuel_km_per_l=3.8,
                                  ac_fuel_penalty=0.10, tyres_inr_per_km=3.5, bus_price_inr=7_500_000.0,
                                  insurance_tax_permit_inr_per_year=180_000.0, daily_km=400.0),
        # Volvo-type multi-axle AC seater: INR 1.2 crore, 3.5 km/l, more tyres and maintenance, higher toll category.
        "volvo_ac": ClassParams("volvo_ac", 45, _fare_params("volvo_ac"), fuel_km_per_l=3.5, ac_fuel_penalty=0.10,
                                tyres_inr_per_km=4.0, maintenance_inr_per_km=26.0, bus_price_inr=12_000_000.0,
                                insurance_tax_permit_inr_per_year=250_000.0, daily_km=450.0, toll_multiplier=1.5,
                                speed_kmph=52.0, is_what_if=True),
        # Non-AC sleeper: INR 45 lakh, 30 berths, 4.0 km/l, no AC load.
        "non_ac_sleeper": ClassParams("non_ac_sleeper", 30, _fare_params("non_ac_sleeper"), fuel_km_per_l=4.0,
                                      tyres_inr_per_km=3.0, maintenance_inr_per_km=18.0, bus_price_inr=4_500_000.0,
                                      insurance_tax_permit_inr_per_year=140_000.0, daily_km=400.0, speed_kmph=48.0,
                                      is_what_if=True),
        # E-bus: 12 m AC, 1.2 kWh/km, few moving parts (low maintenance); GCC-style lease INR 30/km replaces depreciation.
        "e_bus": ClassParams("e_bus", 40, _fare_params("e_bus"), energy="electric", kwh_per_km=1.2, tyres_inr_per_km=3.0,
                             maintenance_inr_per_km=8.0, bus_price_inr=14_000_000.0, lease_inr_per_km=30.0, life_years=12.0,
                             insurance_tax_permit_inr_per_year=100_000.0, daily_km=300.0, speed_kmph=48.0, is_what_if=True,
                             note="lease replaces depreciation; set lease_inr_per_km=None to model ownership from bus_price_inr"),
    }


def default_class_params(ref_speeds: Mapping[str, float], gp: GlobalParams | None = None) -> dict[str, ClassParams]:
    """Class defaults with the maintenance line of the 4 timetable classes set as the balancing item::

        maintenance = OPERATING_COST_PER_KM_INR[class] - energy - tyres - crew     (at ``gp`` and reference speeds, normal hours)
    """
    gp = gp or GlobalParams()
    out = _base_classes()
    for cls in EXISTING_CLASSES:
        cp = out[cls]
        maint = C.OPERATING_COST_PER_KM_INR[cls] - energy_per_km(gp, cp) - cp.tyres_inr_per_km - _crew_per_km(gp, ref_speeds[cls], False)
        if maint <= 0:
            raise ValueError(f"default parameters leave no maintenance margin for {cls} ({maint:.2f} INR/km)")
        out[cls] = replace(cp, maintenance_inr_per_km=maint)
    return out


def build_cost_model(trips: pd.DataFrame, routes: pd.DataFrame, gp: GlobalParams | None = None,
                     tolls: Mapping[str, float] | None = None) -> CostModel:
    """Cost model with reference speeds from ``trips``/``routes`` and calibrated defaults (see module docstring)."""
    gp = gp or GlobalParams()
    rs = reference_speeds(trips, routes)
    return CostModel(gp, default_class_params(rs, gp), rs, dict(DEFAULT_TOLLS_INR_PER_TRIP if tolls is None else tolls))


def running_speed(model: CostModel, bus_class: str, *, intercity: bool = False) -> float:
    """Speed (km/h) used for the crew cost: intercity override (what-if) > class speed > timetable reference speed."""
    cp = model.class_params[bus_class]
    if intercity and cp.intercity_speed_kmph:
        return float(cp.intercity_speed_kmph)
    if cp.speed_kmph:
        return float(cp.speed_kmph)
    return float(model.ref_speeds[bus_class])


# ------------------------------------------------------------------ cost components
def components_per_km(model: CostModel, bus_class: str, *, corridor: str | None = None, length_km: float | None = None,
                      peak: bool = False, speed_kmph: float | None = None) -> dict[str, float]:
    """All nine cost components for one class, INR per vehicle-km (formulas in the module docstring).

    ``tolls`` is 0 unless both ``corridor`` (known in ``model.tolls``) and ``length_km`` are given. ``speed_kmph`` overrides
    the running speed used for crew (default: :func:`running_speed`).
    """
    gp, cp = model.global_params, model.class_params[bus_class]
    sp = speed_kmph if speed_kmph is not None else running_speed(model, bus_class)
    energy = energy_per_km(gp, cp)
    crew = _crew_per_km(gp, sp, peak)
    trip_op = energy + cp.tyres_inr_per_km + cp.maintenance_inr_per_km + crew
    annual_km = cp.daily_km * gp.working_days_per_year
    dep = cp.lease_inr_per_km if cp.lease_inr_per_km is not None else cp.bus_price_inr * (1.0 - cp.residual_pct) / cp.life_years / annual_km
    ins = cp.insurance_tax_permit_inr_per_year / annual_km
    dead = gp.dead_km_share * (energy + cp.tyres_inr_per_km + cp.maintenance_inr_per_km)
    toll = 0.0
    if corridor is not None and length_km and corridor in model.tolls:
        toll = model.tolls[corridor] * cp.toll_multiplier / float(length_km)
    overhead = gp.overhead_share * (trip_op + dead + dep + ins + toll)
    return {"energy": energy, "tyres": cp.tyres_inr_per_km, "maintenance_and_other_running": cp.maintenance_inr_per_km,
            "crew": crew, "dead_km_uplift": dead, "depreciation_or_lease": dep, "insurance_tax_permits": ins,
            "tolls": toll, "overhead": overhead}


def trip_operating_cost_per_km(model: CostModel, bus_class: str, *, peak: bool = False, speed_kmph: float | None = None) -> float:
    """Layer (a), INR per vehicle-km. Equals ``constants.OPERATING_COST_PER_KM_INR[class]`` for the 4 timetable classes at defaults."""
    c = components_per_km(model, bus_class, peak=peak, speed_kmph=speed_kmph)
    return sum(c[k] for k in TRIP_COMPONENTS)


def full_cost_per_km(model: CostModel, bus_class: str, *, corridor: str | None = None, length_km: float | None = None,
                     peak: bool = False, speed_kmph: float | None = None) -> float:
    """Layer (a) + layer (b), INR per vehicle-km."""
    c = components_per_km(model, bus_class, corridor=corridor, length_km=length_km, peak=peak, speed_kmph=speed_kmph)
    return sum(c.values())


def trip_costs(model: CostModel, bus_class: str, length_km: float, *, corridor: str | None = None, peak: bool = False,
               speed_kmph: float | None = None) -> dict[str, float]:
    """Per one-way trip of ``length_km``: ``trip_operating_cost_inr``, ``full_cost_inr`` and the component INR per trip."""
    c = components_per_km(model, bus_class, corridor=corridor, length_km=length_km, peak=peak, speed_kmph=speed_kmph)
    per_trip = {k: v * length_km for k, v in c.items()}
    return {"trip_operating_cost_inr": sum(per_trip[k] for k in TRIP_COMPONENTS), "full_cost_inr": sum(per_trip.values()),
            **{f"{k}_inr": v for k, v in per_trip.items()}}


def component_table(model: CostModel, *, classes: tuple[str, ...] | None = None, corridor: str | None = None,
                    length_km: float | None = None, peak: bool = False) -> pd.DataFrame:
    """Tidy table for a stacked bar: ``bus_class, bus_class_label, component, component_label, layer, inr_per_km``.

    Sums per class to ``full_cost_per_km`` (same corridor/length/peak arguments); the ``trip_operating`` rows sum to
    ``trip_operating_cost_per_km``. Tolls rows are included only when corridor and length are given.
    """
    rows = []
    for cls in classes or ALL_CLASSES:
        c = components_per_km(model, cls, corridor=corridor, length_km=length_km, peak=peak,
                              speed_kmph=running_speed(model, cls, intercity=corridor is not None))
        for comp, v in c.items():
            if comp == "tolls" and not (corridor and length_km):
                continue
            rows.append({"bus_class": cls, "bus_class_label": CLASS_LABELS[cls], "component": comp,
                         "component_label": COMPONENT_LABELS[comp], "layer": LAYER_TRIP if comp in TRIP_COMPONENTS else LAYER_FIXED,
                         "inr_per_km": float(v)})
    return pd.DataFrame(rows, columns=["bus_class", "bus_class_label", "component", "component_label", "layer", "inr_per_km"])


def cost_summary(model: CostModel, *, corridor: str | None = None, length_km: float | None = None) -> pd.DataFrame:
    """One row per class: ``bus_class, is_what_if, seats, energy_type, base_rate_inr_per_km`` (constants, NaN for what-if),
    ``trip_operating_per_km, fixed_and_overhead_per_km, full_cost_per_km, speed_kmph``."""
    rows = []
    for cls in ALL_CLASSES:
        sp = running_speed(model, cls, intercity=corridor is not None)
        c = components_per_km(model, cls, corridor=corridor, length_km=length_km, speed_kmph=sp)
        a = sum(c[k] for k in TRIP_COMPONENTS)
        b = sum(c[k] for k in FIXED_COMPONENTS)
        rows.append({"bus_class": cls, "is_what_if": cls in WHAT_IF_CLASSES, "seats": model.class_params[cls].seats,
                     "energy_type": model.class_params[cls].energy,
                     "base_rate_inr_per_km": C.OPERATING_COST_PER_KM_INR.get(cls, float("nan")),
                     "trip_operating_per_km": a, "fixed_and_overhead_per_km": b, "full_cost_per_km": a + b, "speed_kmph": sp})
    return pd.DataFrame(rows)


def fare_per_passenger(model: CostModel, bus_class: str, length_km: float) -> float:
    """Full-route adult fare (INR per passenger, no concession): ``max(min_fare, base + per_km x km)`` rounded to ``round_to``."""
    f = model.class_params[bus_class].fare
    raw = max(f.min_fare, f.base + f.per_km * length_km)
    return float(round(raw / f.round_to) * f.round_to)


def timetable_running_time_check(trips: pd.DataFrame) -> pd.DataFrame:
    """Per route: number of distinct ``scheduled_minutes`` values (1 = constant running time, so no peak slow-down in the data)."""
    return trips.groupby("route_id")["scheduled_minutes"].nunique().rename("distinct_scheduled_minutes").reset_index()


def load_cost_inputs(base_dir=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Helper (file I/O): ``(trips, routes)`` from the synthetic layer."""
    from modules.data import io

    return io.read_table("trips", "synthetic", base_dir), io.read_table("routes", "synthetic", base_dir)
