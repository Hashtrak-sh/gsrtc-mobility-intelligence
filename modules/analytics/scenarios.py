"""Pure scenario functions shared by the batch runner and the UI. No I/O, no globals except config defaults.

Both scenarios are ILLUSTRATIVE. Neither models fleet, driver, depot or turnaround constraints, and the pricing
elasticity is a scenario assumption, not a fitted real-world fact.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import pandas as pd

import config

SERVICE_LABEL = "illustrative service scenario"
PRICING_LABEL = "illustrative pricing scenario (elasticity is an assumption)"


def _num(name: str, v: Any, *, minimum: float | None = None, strictly_positive: bool = False, maximum: float | None = None) -> float:
    if v is None or isinstance(v, bool):
        raise ValueError(f"{name} is required (got {v!r})")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number (got {v!r})") from None
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"{name} must be a finite number (got {v!r})")
    if strictly_positive and x <= 0:
        raise ValueError(f"{name} must be > 0 (got {x})")
    if minimum is not None and x < minimum:
        raise ValueError(f"{name} must be >= {minimum} (got {x})")
    if maximum is not None and x > maximum:
        raise ValueError(f"{name} must be <= {maximum} (got {x})")
    return x


def required_departures(projected_passengers: float, seats_per_bus: float, target_load_factor: float) -> int:
    """``ceil(projected_passengers / (seats_per_bus x target_load_factor))`` (0 passengers -> 0)."""
    p = _num("projected_passengers", projected_passengers, minimum=0)
    s = _num("seats_per_bus", seats_per_bus, strictly_positive=True)
    t = _num("target_load_factor", target_load_factor, strictly_positive=True, maximum=2.0)
    return int(math.ceil(round(p / (s * t), 9)))


def service_frequency_scenario(projected_passengers: float, seats_per_bus: float, target_load_factor: float,
                               existing_departures: int, trip_km: float, cost_per_km: float,
                               fare_per_passenger: float | None = None, available_buses: int | None = None,
                               served_by_existing: float | None = None) -> dict[str, Any]:
    """Illustrative service-frequency scenario for ONE time window.

    required_departures = ceil(projected_passengers / (seats_per_bus x target_load_factor)); additional departures =
    max(0, required - existing) (the scenario never removes service). Incremental vehicle-km = additional x trip_km;
    incremental operating cost = vehicle-km x cost_per_km. ``projected_load_factor_after`` = projected /
    (seats x (existing + additional)). Incremental passengers = projected - passengers already served by the existing
    departures (``served_by_existing``; default = min(projected, existing x seats), i.e. existing buses carry at most
    one seat each); incremental revenue = incremental passengers x fare; contribution = revenue - operating cost
    (NOT profit). ``fleet_constraint_not_modelled`` is True when ``available_buses`` is None; otherwise
    ``within_available_buses`` compares additional departures to it (one bus per departure, no turnaround logic).
    """
    p = _num("projected_passengers", projected_passengers, minimum=0)
    seats = _num("seats_per_bus", seats_per_bus, strictly_positive=True)
    tlf = _num("target_load_factor", target_load_factor, strictly_positive=True, maximum=2.0)
    existing = int(_num("existing_departures", existing_departures, minimum=0))
    km = _num("trip_km", trip_km, minimum=0)
    cpk = _num("cost_per_km", cost_per_km, minimum=0)
    fare = None if fare_per_passenger is None else _num("fare_per_passenger", fare_per_passenger, minimum=0)
    avail = None if available_buses is None else int(_num("available_buses", available_buses, minimum=0))

    required = required_departures(p, seats, tlf)
    additional = max(0, required - existing)
    total = existing + additional
    served_existing = min(p, existing * seats) if served_by_existing is None else _num("served_by_existing", served_by_existing, minimum=0)
    inc_pax = max(0.0, p - served_existing)
    inc_km = additional * km
    inc_cost = inc_km * cpk
    return {
        "label": SERVICE_LABEL,
        "required_departures": required,
        "existing_departures": existing,
        "additional_departures": additional,
        "total_departures_after": total,
        "incremental_vehicle_km": inc_km,
        "incremental_operating_cost_inr": inc_cost,
        "load_factor_before": (p / (seats * existing)) if existing > 0 else float("nan"),
        "projected_load_factor_after": (p / (seats * total)) if total > 0 else float("nan"),
        "target_load_factor": tlf,
        "seats_per_bus": seats,
        "projected_passengers": p,
        "incremental_passengers": inc_pax,
        "incremental_revenue_inr": float("nan") if fare is None else inc_pax * fare,
        "incremental_contribution_inr": float("nan") if fare is None else inc_pax * fare - inc_cost,
        "fleet_constraint_not_modelled": avail is None,
        "within_available_buses": None if avail is None else additional <= avail,
        "constraints": ["driver duty, depot capacity and bus turnaround are not modelled",
                        "contribution = ticket revenue - operating cost; not profit"],
    }


def _check_pricing(baseline_demand: float, baseline_fare: float, new_fare: float, elasticity: float, seats_offered: float,
                   operating_cost: float, fare_bounds: tuple[float, float] | None) -> tuple[float, ...]:
    bd = _num("baseline_demand", baseline_demand, minimum=0)
    bf = _num("baseline_fare", baseline_fare, strictly_positive=True)
    nf = _num("new_fare", new_fare, strictly_positive=True)
    lo_e, hi_e = config.PRICING_ELASTICITY_RANGE
    e = _num("elasticity", elasticity)
    if not lo_e <= e <= hi_e:
        raise ValueError(f"elasticity must be within [{lo_e}, {hi_e}] (got {e}); it is normally negative")
    seats = _num("seats_offered", seats_offered, minimum=0)
    cost = _num("operating_cost", operating_cost, minimum=0)
    if fare_bounds is None:
        fare_bounds = (bf * config.PRICING_FARE_BOUNDS_FACTOR[0], bf * config.PRICING_FARE_BOUNDS_FACTOR[1])
    lo, hi = float(fare_bounds[0]), float(fare_bounds[1])
    if not (0 < lo <= hi):
        raise ValueError(f"fare_bounds must satisfy 0 < min <= max (got {fare_bounds})")
    if not lo <= nf <= hi:
        raise ValueError(f"new_fare {nf:g} is outside the allowed fare bounds [{lo:g}, {hi:g}]")
    return bd, bf, nf, e, seats, cost


def pricing_scenario(baseline_demand: float, baseline_fare: float, new_fare: float, elasticity: float,
                     seats_offered: float, operating_cost: float,
                     fare_bounds: tuple[float, float] | None = None) -> dict[str, Any]:
    """Fare what-if: ``demand_new = baseline_demand x (new_fare / baseline_fare) ** elasticity``.

    Capacity caps served demand at ``seats_offered`` (the excess is reported as ``spilled_demand``, not served).
    Baseline revenue uses the same cap so the comparison is like for like. Occupancy = served / seats (NaN if no seats).
    Contribution = revenue - ``operating_cost`` (a fixed cost for the offered service; NOT profit). Default fare bounds are
    0.5x-2x the baseline fare (``config.PRICING_FARE_BOUNDS_FACTOR``).
    """
    bd, bf, nf, e, seats, cost = _check_pricing(baseline_demand, baseline_fare, new_fare, elasticity, seats_offered,
                                                operating_cost, fare_bounds)
    demand = bd * (nf / bf) ** e
    served = min(demand, seats)
    base_served = min(bd, seats)
    rev = served * nf
    base_rev = base_served * bf
    return {
        "label": PRICING_LABEL,
        "elasticity": e, "baseline_fare_inr": bf, "new_fare_inr": nf, "fare_change_pct": (nf / bf - 1.0) * 100.0,
        "baseline_demand": bd, "demand_unconstrained": demand, "served_demand": served,
        "spilled_demand": max(0.0, demand - seats), "seats_offered": seats,
        "occupancy": served / seats if seats > 0 else float("nan"),
        "baseline_occupancy": base_served / seats if seats > 0 else float("nan"),
        "revenue_inr": rev, "baseline_revenue_inr": base_rev, "revenue_change_inr": rev - base_rev,
        "operating_cost_inr": cost, "contribution_inr": rev - cost, "baseline_contribution_inr": base_rev - cost,
        "contribution_change_inr": rev - base_rev,
    }


def pricing_sensitivity(baseline_demand: float, baseline_fare: float, new_fare: float, seats_offered: float,
                        operating_cost: float, fare_bounds: tuple[float, float] | None = None,
                        elasticities: Sequence[float] | None = None) -> pd.DataFrame:
    """One row per elasticity (default ``config.PRICING_ELASTICITY_SENSITIVITY``) using :func:`pricing_scenario`."""
    es = list(config.PRICING_ELASTICITY_SENSITIVITY if elasticities is None else elasticities)
    if not es:
        raise ValueError("elasticities must not be empty")
    rows = [pricing_scenario(baseline_demand, baseline_fare, new_fare, e, seats_offered, operating_cost, fare_bounds) for e in es]
    cols = ["elasticity", "demand_unconstrained", "served_demand", "spilled_demand", "occupancy", "revenue_inr",
            "revenue_change_inr", "contribution_inr", "contribution_change_inr"]
    return pd.DataFrame(rows)[cols]
