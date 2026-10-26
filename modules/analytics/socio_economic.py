"""Socio-economic layer of the intercity cost-benefit analysis (CBA).

ILLUSTRATIVE, transport-appraisal style. The parameters in ``SocioEconomicParams``
are orders of magnitude commonly used in Indian transport appraisal; they are NOT
GSRTC data and NOT official values. Passenger / km / revenue inputs come from the
SIMULATED route tables ("Simulated data for demonstration"). Results are
per average service day and annualised (``operating_days_per_year``).

Every formula is deterministic and listed in ``component_assumptions``. A missing
full cost gives NaN for the financial result and BCR; nothing is invented.
"contribution" (revenue - trip operating cost) is not profit.

Sign convention: positive INR = benefit to society/operator, negative = cost.
Per average day, one-way trips: a diverted passenger's trip equals the bus
passenger's trip length (passenger-km / passengers); return legs are symmetric
and are not doubled.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

ILLUSTRATIVE_LABEL = (
    "Illustrative appraisal: parameters are typical orders of magnitude, not GSRTC data; "
    "passenger and cost inputs are simulated data for demonstration."
)

SHARE_FIELDS: tuple[str, ...] = (
    "share_car", "share_two_wheeler", "share_private_bus", "share_shared_taxi", "share_rail", "share_no_travel",
)
KEY_COLUMNS: tuple[str, ...] = ("corridor", "route_id", "bus_class")
REQUIRED_COLUMNS: tuple[str, ...] = (
    "corridor", "passengers_per_day", "passenger_km_per_day", "bus_km_per_day", "average_fare_inr",
    "trip_operating_cost_per_day_inr", "full_cost_per_day_inr", "revenue_per_day_inr",
)
ADDITIVE_OUTPUTS: tuple[str, ...] = (
    "passengers_per_day", "passenger_km_per_day", "bus_km_per_day", "car_km_avoided_per_day",
    "two_wheeler_km_avoided_per_day", "taxi_km_avoided_per_day", "private_cost_saved_inr", "fare_paid_diverted_inr",
    "induced_surplus_inr", "consumer_cost_saving_inr", "time_benefit_inr", "co2_tonnes_private_avoided",
    "co2_tonnes_bus", "co2_tonnes_saved", "co2_value_inr", "accident_benefit_inr", "congestion_benefit_inr",
    "social_benefit_per_day_inr", "social_benefit_per_year_inr", "revenue_per_day_inr",
    "trip_operating_cost_per_day_inr", "full_cost_per_day_inr",
)


@dataclass(frozen=True)
class SocioEconomicParams:
    """Editable illustrative assumptions (override with ``dataclasses.replace``)."""

    # --- diversion of bus passengers (shares of bus passengers; must sum to 1) -------------
    share_car: float = 0.25            # would otherwise drive/ride a car (illustrative intercity mix)
    share_two_wheeler: float = 0.10    # would otherwise ride a two-wheeler (less common over 100-250 km)
    share_private_bus: float = 0.25    # would otherwise take a private/omni bus
    share_shared_taxi: float = 0.05    # would otherwise take a shared taxi/jeep
    share_rail: float = 0.10           # would otherwise take rail
    share_no_travel: float = 0.25      # would not travel (induced / generated trips)
    # --- vehicle occupancy (persons per vehicle) ---------------------------------------------
    occupancy_car: float = 2.5         # typical intercity car occupancy
    occupancy_two_wheeler: float = 1.5  # rider plus occasional pillion
    occupancy_shared_taxi: float = 5.0  # shared jeep / taxi
    # --- user vehicle operating cost, INR per vehicle-km (fuel + wear; no driver for own car) -
    voc_car_inr_per_km: float = 8.0
    voc_two_wheeler_inr_per_km: float = 3.0
    voc_shared_taxi_inr_per_km: float = 15.0  # taxi tariff-like cost per vehicle-km
    private_bus_fare_inr_per_pkm: float = 1.2  # what a private/omni bus passenger pays per km (illustrative)
    rail_fare_inr_per_pkm: float = 0.8         # what a rail passenger pays per km (illustrative)
    # --- value of travel time, INR per hour (blended work / non-work) ------------------------
    value_of_time_inr_per_hour: float = 100.0
    # --- door-to-door speed (km/h) and access + wait time (hours per trip) ------------------
    speed_bus_kmph: float = 45.0
    speed_car_kmph: float = 55.0
    speed_two_wheeler_kmph: float = 40.0
    speed_shared_taxi_kmph: float = 50.0
    speed_private_bus_kmph: float = 50.0
    speed_rail_kmph: float = 55.0
    access_wait_bus_h: float = 0.50    # reach stand + wait (hours)
    access_wait_car_h: float = 0.0
    access_wait_two_wheeler_h: float = 0.0
    access_wait_shared_taxi_h: float = 0.25
    access_wait_private_bus_h: float = 0.40
    access_wait_rail_h: float = 0.90   # station access + wait
    # --- emissions, kg CO2 per vehicle-km (or per passenger-km where stated) -----------------
    co2_car_kg_per_km: float = 0.17
    co2_two_wheeler_kg_per_km: float = 0.04
    co2_shared_taxi_kg_per_km: float = 0.17
    co2_private_bus_kg_per_pkm: float = 0.03   # per passenger-km (diesel coach, typical load)
    co2_rail_kg_per_pkm: float = 0.03          # per passenger-km
    co2_diesel_bus_kg_per_km: float = 1.0      # per bus-km (about 0.38 L/km x 2.68 kg/L, rounded)
    electric_bus_share: float = 0.0            # share of bus-km run by e-buses (0 = all diesel)
    electric_bus_kwh_per_km: float = 1.2       # e-bus energy use
    grid_co2_kg_per_kwh: float = 0.71          # order of magnitude of the Indian grid factor
    carbon_price_inr_per_tonne: float = 4000.0  # social cost of carbon (illustrative)
    # --- accident cost, INR per vehicle-km (per passenger-km where stated) -------------------
    accident_car_inr_per_km: float = 1.5
    accident_two_wheeler_inr_per_km: float = 4.0
    accident_shared_taxi_inr_per_km: float = 1.5
    accident_private_bus_inr_per_pkm: float = 0.30
    accident_rail_inr_per_pkm: float = 0.10
    accident_bus_inr_per_km: float = 3.0       # attributed to every operated bus-km
    # --- congestion / noise externality ------------------------------------------------------
    congestion_inr_per_car_km: float = 0.5     # per car-equivalent vehicle-km (cars, taxis)
    bus_pcu: float = 3.0                       # passenger-car-units of a bus for the externality
    two_wheeler_pcu: float = 0.5
    # --- induced (new) travellers, rule-of-half style ----------------------------------------
    induced_surplus_share_of_fare: float = 0.5  # surplus of a generated trip = 0.5 x fare paid
    # --- annualisation -----------------------------------------------------------------------
    operating_days_per_year: float = 365.0

    def __post_init__(self) -> None:
        shares = [getattr(self, f) for f in SHARE_FIELDS]
        if any((not np.isfinite(s)) or s < 0 for s in shares):
            raise ValueError("Diversion shares must be finite and non-negative.")
        if abs(sum(shares) - 1.0) > 1e-6:
            raise ValueError(f"Diversion shares must sum to 1 (got {sum(shares):.6f}).")
        for f in ("occupancy_car", "occupancy_two_wheeler", "occupancy_shared_taxi", "speed_bus_kmph",
                  "speed_car_kmph", "speed_two_wheeler_kmph", "speed_shared_taxi_kmph", "speed_private_bus_kmph",
                  "speed_rail_kmph", "operating_days_per_year"):
            if getattr(self, f) <= 0:
                raise ValueError(f"{f} must be positive.")
        if not 0 <= self.electric_bus_share <= 1:
            raise ValueError("electric_bus_share must be in [0, 1].")

    @property
    def bus_co2_kg_per_km(self) -> float:
        """Blended bus emission factor (diesel and electric via grid factor)."""
        e = self.electric_bus_share
        return (1 - e) * self.co2_diesel_bus_kg_per_km + e * self.electric_bus_kwh_per_km * self.grid_co2_kg_per_kwh


def rebalance_shares(params: SocioEconomicParams, **fixed: float) -> SocioEconomicParams:
    """Set the named shares (e.g. ``share_car=0.4``) and scale the other shares proportionally to sum to 1."""
    for k in fixed:
        if k not in SHARE_FIELDS:
            raise ValueError(f"{k!r} is not a diversion share field.")
    fixed_total = sum(fixed.values())
    if fixed_total > 1 + 1e-9 or any(v < 0 for v in fixed.values()):
        raise ValueError("Fixed shares must be non-negative and sum to at most 1.")
    others = [f for f in SHARE_FIELDS if f not in fixed]
    other_total = sum(getattr(params, f) for f in others)
    new = dict(fixed)
    for f in others:
        new[f] = (getattr(params, f) / other_total) * (1 - fixed_total) if other_total > 0 else 0.0
    return dataclasses.replace(params, **new)


def survey_car_two_wheeler_split(survey: pd.DataFrame) -> float:
    """Car share of (car + two-wheeler) respondents in ``survey_responses.current_mode``.

    This is a Rajkot CITY survey (simulated). It is NOT used by default; the intercity
    defaults above are kept separate. Raises ValueError if neither mode is present.
    """
    modes = survey["current_mode"]
    car, tw = int((modes == "car").sum()), int((modes == "two_wheeler").sum())
    if car + tw == 0:
        raise ValueError("No car or two_wheeler respondents in the survey.")
    return car / (car + tw)


def params_with_survey_split(params: SocioEconomicParams, survey: pd.DataFrame) -> SocioEconomicParams:
    """Optional: keep ``share_car + share_two_wheeler`` but split it as the (city) survey's car : two-wheeler ratio."""
    total = params.share_car + params.share_two_wheeler
    car_part = survey_car_two_wheeler_split(survey)
    return dataclasses.replace(params, share_car=total * car_part, share_two_wheeler=total * (1 - car_part))


# ---------------------------------------------------------------------------------------------
# Input frame from the committed tables
# ---------------------------------------------------------------------------------------------
def build_default_inputs(route_summary: pd.DataFrame, by: str = "corridor") -> pd.DataFrame:
    """Per-corridor (``by='corridor'``) or per-route (``by='route'``) input frame from ``route_summary``.

    Intercity routes only. Per-day values = 42-day totals / number of service dates, where the
    number of dates is derived as ``boardings / avg_boardings_per_day`` (so it always reconciles
    with ``route_summary``). ``full_cost_per_day_inr`` is NaN here: the page fills it from the cost model.
    """
    rs = route_summary[route_summary["route_type"] == "intercity"].copy()
    if rs.empty:
        raise ValueError("route_summary has no intercity routes.")
    rs["n_days"] = rs["boardings"] / rs["avg_boardings_per_day"]
    rs["passengers_per_day"] = rs["avg_boardings_per_day"]
    rs["passenger_km_per_day"] = rs["estimated_passenger_km"] / rs["n_days"]
    rs["bus_km_per_day"] = rs["vehicle_km"] / rs["n_days"]
    rs["trip_operating_cost_per_day_inr"] = rs["operating_cost_inr"] / rs["n_days"]
    rs["revenue_per_day_inr"] = rs["ticket_revenue_inr"] / rs["n_days"]
    keys = ["corridor"] if by == "corridor" else ["corridor", "route_id", "bus_class"]
    if by == "route":
        rs["bus_class"] = rs["bus_type"]
    elif by != "corridor":
        raise ValueError("by must be 'corridor' or 'route'.")
    add = ["passengers_per_day", "passenger_km_per_day", "bus_km_per_day", "trip_operating_cost_per_day_inr",
           "revenue_per_day_inr"]
    out = rs.groupby(keys, as_index=False, sort=True)[add].sum()
    out["average_fare_inr"] = out["revenue_per_day_inr"] / out["passengers_per_day"].where(out["passengers_per_day"] > 0)
    out["full_cost_per_day_inr"] = np.nan
    out["source_type"] = "synthetic"
    return out[[*keys, "passengers_per_day", "passenger_km_per_day", "bus_km_per_day", "average_fare_inr",
                "trip_operating_cost_per_day_inr", "full_cost_per_day_inr", "revenue_per_day_inr", "source_type"]]


# ---------------------------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------------------------
def _validate_inputs(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing input columns: {missing}")
    for c in ("passengers_per_day", "passenger_km_per_day", "bus_km_per_day"):
        v = pd.to_numeric(df[c], errors="coerce")
        if v.isna().any() or (v < 0).any():
            raise ValueError(f"{c} must be present and non-negative.")


def compute_cba(inputs: pd.DataFrame, params: SocioEconomicParams | None = None) -> pd.DataFrame:
    """Socio-economic CBA per input row (see module docstring for the formulas). Returns one row per input row."""
    p = params or SocioEconomicParams()
    _validate_inputs(inputs)
    df = inputs.reset_index(drop=True)
    keys = [c for c in KEY_COLUMNS if c in df.columns]
    pax = df["passengers_per_day"].astype(float)
    pkm = df["passenger_km_per_day"].astype(float)
    bus_km = df["bus_km_per_day"].astype(float)
    fare = pd.to_numeric(df["average_fare_inr"], errors="coerce").fillna(0.0)
    revenue = pd.to_numeric(df["revenue_per_day_inr"], errors="coerce")
    op_cost = pd.to_numeric(df["trip_operating_cost_per_day_inr"], errors="coerce")
    full_cost = pd.to_numeric(df["full_cost_per_day_inr"], errors="coerce")
    trip_km = (pkm / pax.where(pax > 0)).fillna(0.0)
    bus_time_h = trip_km / p.speed_bus_kmph + p.access_wait_bus_h

    # vehicle modes: (share, occupancy, voc, speed, access, co2/km, accident/km, pcu)
    vehicle = {
        "car": (p.share_car, p.occupancy_car, p.voc_car_inr_per_km, p.speed_car_kmph, p.access_wait_car_h,
                p.co2_car_kg_per_km, p.accident_car_inr_per_km, 1.0),
        "two_wheeler": (p.share_two_wheeler, p.occupancy_two_wheeler, p.voc_two_wheeler_inr_per_km,
                        p.speed_two_wheeler_kmph, p.access_wait_two_wheeler_h, p.co2_two_wheeler_kg_per_km,
                        p.accident_two_wheeler_inr_per_km, p.two_wheeler_pcu),
        "taxi": (p.share_shared_taxi, p.occupancy_shared_taxi, p.voc_shared_taxi_inr_per_km,
                 p.speed_shared_taxi_kmph, p.access_wait_shared_taxi_h, p.co2_shared_taxi_kg_per_km,
                 p.accident_shared_taxi_inr_per_km, 1.0),
    }
    veh_km: dict[str, pd.Series] = {}
    cost_saved = pd.Series(0.0, index=df.index)
    time_benefit = pd.Series(0.0, index=df.index)
    co2_private_kg = pd.Series(0.0, index=df.index)
    accident_avoided = pd.Series(0.0, index=df.index)
    congestion_avoided = pd.Series(0.0, index=df.index)
    for name, (share, occ, voc, spd, acc, co2, acd, pcu) in vehicle.items():
        pax_m = pax * share
        vk = pax_m * trip_km / occ
        veh_km[name] = vk
        cost_saved += vk * voc
        time_benefit += pax_m * ((trip_km / spd + acc) - bus_time_h) * p.value_of_time_inr_per_hour
        co2_private_kg += vk * co2
        accident_avoided += vk * acd
        congestion_avoided += vk * pcu * p.congestion_inr_per_car_km

    # passenger-km modes (private bus, rail): cost, time, emissions, accidents per passenger-km
    for share, fare_pkm, spd, acc, co2_pkm, acd_pkm in (
        (p.share_private_bus, p.private_bus_fare_inr_per_pkm, p.speed_private_bus_kmph,
         p.access_wait_private_bus_h, p.co2_private_bus_kg_per_pkm, p.accident_private_bus_inr_per_pkm),
        (p.share_rail, p.rail_fare_inr_per_pkm, p.speed_rail_kmph, p.access_wait_rail_h,
         p.co2_rail_kg_per_pkm, p.accident_rail_inr_per_pkm),
    ):
        pkm_m = pkm * share
        pax_m = pax * share
        cost_saved += pkm_m * fare_pkm
        time_benefit += pax_m * ((trip_km / spd + acc) - bus_time_h) * p.value_of_time_inr_per_hour
        co2_private_kg += pkm_m * co2_pkm
        accident_avoided += pkm_m * acd_pkm

    diverted_share = 1.0 - p.share_no_travel
    fare_paid = pax * diverted_share * fare
    induced_surplus = pax * p.share_no_travel * fare * p.induced_surplus_share_of_fare

    co2_bus_kg = bus_km * p.bus_co2_kg_per_km
    accident_bus = bus_km * p.accident_bus_inr_per_km
    congestion_bus = bus_km * p.bus_pcu * p.congestion_inr_per_car_km
    price_per_kg = p.carbon_price_inr_per_tonne / 1000.0

    comp = {
        "private_travel_cost_saved": cost_saved,
        "fare_paid_diverted_users": -fare_paid,
        "induced_traveller_surplus": induced_surplus,
        "travel_time": time_benefit,
        "co2_private_avoided": co2_private_kg * price_per_kg,
        "co2_bus_emissions": -co2_bus_kg * price_per_kg,
        "accidents_avoided": accident_avoided,
        "accidents_bus": -accident_bus,
        "congestion_avoided": congestion_avoided,
        "congestion_bus": -congestion_bus,
    }
    social = sum(comp.values())
    out = df[keys].copy()
    out["passengers_per_day"] = pax
    out["passenger_km_per_day"] = pkm
    out["bus_km_per_day"] = bus_km
    out["trip_length_km"] = trip_km
    out["car_km_avoided_per_day"] = veh_km["car"]
    out["two_wheeler_km_avoided_per_day"] = veh_km["two_wheeler"]
    out["taxi_km_avoided_per_day"] = veh_km["taxi"]
    out["private_cost_saved_inr"] = cost_saved
    out["fare_paid_diverted_inr"] = -fare_paid
    out["induced_surplus_inr"] = induced_surplus
    out["consumer_cost_saving_inr"] = cost_saved - fare_paid
    out["time_benefit_inr"] = time_benefit
    out["co2_tonnes_private_avoided"] = co2_private_kg / 1000.0
    out["co2_tonnes_bus"] = co2_bus_kg / 1000.0
    out["co2_tonnes_saved"] = (co2_private_kg - co2_bus_kg) / 1000.0
    out["co2_value_inr"] = comp["co2_private_avoided"] + comp["co2_bus_emissions"]
    out["accident_benefit_inr"] = accident_avoided - accident_bus
    out["congestion_benefit_inr"] = congestion_avoided - congestion_bus
    out["social_benefit_per_day_inr"] = social
    out["social_benefit_per_year_inr"] = social * p.operating_days_per_year
    out["revenue_per_day_inr"] = revenue
    out["trip_operating_cost_per_day_inr"] = op_cost
    out["full_cost_per_day_inr"] = full_cost
    out["financial_result_per_day_inr"] = revenue - full_cost  # negative = support needed
    out["net_social_benefit_per_day_inr"] = social + revenue - full_cost
    out["net_social_benefit_per_year_inr"] = out["net_social_benefit_per_day_inr"] * p.operating_days_per_year
    bcr = (social + revenue) / full_cost.where(full_cost > 0)
    out["bcr"] = bcr
    # component columns kept for the long table
    for k, v in comp.items():
        out[f"comp_{k}"] = v
    return out


def aggregate_to_corridor(result: pd.DataFrame, params: SocioEconomicParams | None = None) -> pd.DataFrame:
    """Sum per-route/class rows to corridors (additive columns); recompute financial result and BCR."""
    p = params or SocioEconomicParams()
    comp_cols = [c for c in result.columns if c.startswith("comp_")]
    cols = [c for c in (*ADDITIVE_OUTPUTS, *comp_cols) if c in result.columns]
    g = result.groupby("corridor", as_index=False, sort=True)
    out = g[cols].sum(min_count=1)
    out["trip_length_km"] = out["passenger_km_per_day"] / out["passengers_per_day"].where(out["passengers_per_day"] > 0)
    # full cost: NaN if any row of the corridor is NaN
    fc = result.groupby("corridor")["full_cost_per_day_inr"].apply(lambda s: np.nan if s.isna().any() else s.sum())
    out["full_cost_per_day_inr"] = out["corridor"].map(fc).to_numpy()
    out["financial_result_per_day_inr"] = out["revenue_per_day_inr"] - out["full_cost_per_day_inr"]
    out["net_social_benefit_per_day_inr"] = (out["social_benefit_per_day_inr"] + out["revenue_per_day_inr"]
                                            - out["full_cost_per_day_inr"])
    out["net_social_benefit_per_year_inr"] = out["net_social_benefit_per_day_inr"] * p.operating_days_per_year
    out["bcr"] = (out["social_benefit_per_day_inr"] + out["revenue_per_day_inr"]) / out[
        "full_cost_per_day_inr"].where(out["full_cost_per_day_inr"] > 0)
    return out


_COMPONENT_LABELS = {
    "private_travel_cost_saved": "Vehicle operating cost saved (former private/alternative users)",
    "fare_paid_diverted_users": "Bus fare paid by diverted users",
    "induced_traveller_surplus": "Surplus of new (induced) travellers",
    "travel_time": "Travel time (door-to-door; negative if bus is slower)",
    "co2_private_avoided": "CO2 value: other modes avoided",
    "co2_bus_emissions": "CO2 value: bus emissions",
    "accidents_avoided": "Accident cost avoided (other modes)",
    "accidents_bus": "Accident cost of bus operation",
    "congestion_avoided": "Congestion/noise avoided (other modes)",
    "congestion_bus": "Congestion/noise of bus operation",
}


def component_table(result: pd.DataFrame) -> pd.DataFrame:
    """Tidy long table: corridor [, route_id, bus_class], component, label, group, INR_per_day, sign.

    ``group`` = 'social' (components summing to ``social_benefit_per_day_inr``) or 'financial'
    (ticket revenue +, full cost -; full cost is NaN when missing). All rows together sum to
    ``net_social_benefit_per_day_inr``. ``sign`` = +1 for a benefit/revenue, -1 for a cost.
    """
    keys = [c for c in KEY_COLUMNS if c in result.columns]
    rows = []
    for _, r in result.iterrows():
        base = {k: r[k] for k in keys}
        for comp, label in _COMPONENT_LABELS.items():
            rows.append({**base, "component": comp, "label": label, "group": "social", "INR_per_day": r[f"comp_{comp}"]})
        rows.append({**base, "component": "ticket_revenue", "label": "Ticket revenue", "group": "financial",
                     "INR_per_day": r["revenue_per_day_inr"]})
        rows.append({**base, "component": "full_cost", "label": "Full cost of service", "group": "financial",
                     "INR_per_day": -r["full_cost_per_day_inr"]})
    t = pd.DataFrame(rows)
    t["sign"] = np.where(t["INR_per_day"].fillna(0) >= 0, 1, -1)
    return t


def component_assumptions(params: SocioEconomicParams | None = None) -> dict[str, str]:
    """Per-component assumption / formula strings (shown with the chart)."""
    p = params or SocioEconomicParams()
    return {
        "private_travel_cost_saved": (
            f"Sum over car/two-wheeler/shared taxi of vehicle-km avoided x VOC (car {p.voc_car_inr_per_km:g}, "
            f"two-wheeler {p.voc_two_wheeler_inr_per_km:g}, taxi {p.voc_shared_taxi_inr_per_km:g} INR/km), plus "
            f"private-bus ({p.private_bus_fare_inr_per_pkm:g}) and rail ({p.rail_fare_inr_per_pkm:g} INR/pkm) "
            "fares avoided. Vehicle-km avoided = passengers x mode share x trip length / occupancy "
            f"(car {p.occupancy_car:g}, two-wheeler {p.occupancy_two_wheeler:g}, taxi {p.occupancy_shared_taxi:g})."),
        "fare_paid_diverted_users": (
            f"Passengers x (1 - no-travel share {p.share_no_travel:g}) x average fare; users pay it, the operator "
            "receives it (counted again as revenue, so it nets out)."),
        "induced_traveller_surplus": (
            f"Passengers x no-travel share x fare x {p.induced_surplus_share_of_fare:g} (rule-of-half style: "
            "marginal new travellers value the trip at about fare + half a fare)."),
        "travel_time": (
            f"Diverted passengers x (time by other mode - bus time) x {p.value_of_time_inr_per_hour:g} INR/h. "
            f"Door-to-door time = trip km / speed + access/wait; bus {p.speed_bus_kmph:g} km/h + "
            f"{p.access_wait_bus_h:g} h. Negative when the bus is slower."),
        "co2_private_avoided": (
            f"Vehicle-km avoided x kg CO2/km (car {p.co2_car_kg_per_km:g}, two-wheeler {p.co2_two_wheeler_kg_per_km:g}, "
            f"taxi {p.co2_shared_taxi_kg_per_km:g}) + pkm x {p.co2_private_bus_kg_per_pkm:g}/{p.co2_rail_kg_per_pkm:g} "
            f"(private bus/rail), valued at {p.carbon_price_inr_per_tonne:g} INR/tonne."),
        "co2_bus_emissions": (
            f"ALL operated bus-km x {p.bus_co2_kg_per_km:.3g} kg CO2/km (diesel {p.co2_diesel_bus_kg_per_km:g}; "
            f"e-bus share {p.electric_bus_share:g} via grid {p.grid_co2_kg_per_kwh:g} kg/kWh), same carbon price. "
            "Conservative: the whole bus-km is charged to the passengers it carries."),
        "accidents_avoided": (
            f"Vehicle-km avoided x accident cost (car {p.accident_car_inr_per_km:g}, two-wheeler "
            f"{p.accident_two_wheeler_inr_per_km:g}, taxi {p.accident_shared_taxi_inr_per_km:g} INR/km) + pkm x "
            f"{p.accident_private_bus_inr_per_pkm:g}/{p.accident_rail_inr_per_pkm:g} (private bus/rail)."),
        "accidents_bus": f"Bus-km x {p.accident_bus_inr_per_km:g} INR/bus-km.",
        "congestion_avoided": (
            f"Vehicle-km avoided x PCU (car 1, taxi 1, two-wheeler {p.two_wheeler_pcu:g}) x "
            f"{p.congestion_inr_per_car_km:g} INR per car-km."),
        "congestion_bus": f"Bus-km x bus PCU {p.bus_pcu:g} x {p.congestion_inr_per_car_km:g} INR per car-km.",
        "ticket_revenue": "Ticket revenue per average day from the simulated tickets table.",
        "full_cost": "Full cost per average day from the cost model (missing -> shown as missing, BCR is NaN).",
        "bcr": "BCR = (social benefits + ticket revenue) / full cost. Net social benefit = social benefits + revenue - full cost.",
        "general": ILLUSTRATIVE_LABEL + f" Annualised x {p.operating_days_per_year:g} days.",
    }


# ---------------------------------------------------------------------------------------------
# Sensitivity and takeaway
# ---------------------------------------------------------------------------------------------
DEFAULT_SENSITIVITY: dict[str, tuple[float, float, float]] = {
    "value_of_time_inr_per_hour": (50.0, 100.0, 200.0),
    "share_car": (0.10, 0.25, 0.40),
    "carbon_price_inr_per_tonne": (1000.0, 4000.0, 10000.0),
}


def _apply(params: SocioEconomicParams, name: str, value: float) -> SocioEconomicParams:
    if name in SHARE_FIELDS:
        return rebalance_shares(params, **{name: value})
    return dataclasses.replace(params, **{name: value})


def sensitivity_table(
    inputs: pd.DataFrame,
    params: SocioEconomicParams | None = None,
    ranges: dict[str, tuple[float, float, float]] | None = None,
) -> pd.DataFrame:
    """BCR and net social benefit per corridor at low/central/high of each parameter (one at a time).

    ``ranges`` maps parameter name -> (low, central, high); the central entry is replaced by the
    value in ``params`` so the 'central' row always equals the base case. Changing ``share_car``
    rescales the other diversion shares proportionally.
    """
    base = params or SocioEconomicParams()
    rng = ranges or DEFAULT_SENSITIVITY
    rows = []
    for name, (lo, _mid, hi) in rng.items():
        for level, value in (("low", lo), ("central", getattr(base, name)), ("high", hi)):
            res = compute_cba(inputs, _apply(base, name, value))
            if "corridor" in res.columns and res["corridor"].duplicated().any():
                res = aggregate_to_corridor(res, base)
            for _, r in res.iterrows():
                rows.append({"corridor": r["corridor"], "parameter": name, "level": level, "value": value,
                             "bcr": r["bcr"], "net_social_benefit_per_day_inr": r["net_social_benefit_per_day_inr"],
                             "social_benefit_per_day_inr": r["social_benefit_per_day_inr"]})
    return pd.DataFrame(rows)


def tornado_table(sens: pd.DataFrame) -> pd.DataFrame:
    """Wide tornado table per corridor and parameter: bcr_low/central/high, swing (|high-low|), social benefit low/high."""
    piv = sens.pivot_table(index=["corridor", "parameter"], columns="level",
                           values=["bcr", "social_benefit_per_day_inr"], aggfunc="first", dropna=False)
    out = pd.DataFrame({
        "bcr_low": piv[("bcr", "low")], "bcr_central": piv[("bcr", "central")], "bcr_high": piv[("bcr", "high")],
        "social_benefit_low_inr": piv[("social_benefit_per_day_inr", "low")],
        "social_benefit_high_inr": piv[("social_benefit_per_day_inr", "high")],
    }).reset_index()
    out["bcr_swing"] = (out["bcr_high"] - out["bcr_low"]).abs()
    out["social_benefit_swing_inr"] = (out["social_benefit_high_inr"] - out["social_benefit_low_inr"]).abs()
    return out.sort_values(["corridor", "social_benefit_swing_inr"], ascending=[True, False]).reset_index(drop=True)


def takeaway(result: pd.DataFrame) -> str:
    """One-sentence takeaway from a corridor-level result, marked illustrative."""
    r = result.reset_index(drop=True)
    if r.empty:
        return "No corridor results available. (Illustrative.)"
    tag = " (Illustrative appraisal on simulated data; assumptions editable.)"
    valid = r.dropna(subset=["bcr"])
    if valid.empty:
        best = r.loc[r["social_benefit_per_day_inr"].idxmax()]
        worst = r.loc[r["social_benefit_per_day_inr"].idxmin()]
        return (f"Full cost is not available, so BCR cannot be computed; social benefit per day is highest on "
                f"{best['corridor']} (INR {best['social_benefit_per_day_inr']:,.0f}) and lowest on "
                f"{worst['corridor']} (INR {worst['social_benefit_per_day_inr']:,.0f})." + tag)
    best = valid.loc[valid["bcr"].idxmax()]
    worst = valid.loc[valid["bcr"].idxmin()]
    if len(valid) == 1:
        return f"{best['corridor']} has an illustrative BCR of {best['bcr']:.2f}." + tag
    return (f"Illustrative BCR is highest on {best['corridor']} ({best['bcr']:.2f}) and lowest on "
            f"{worst['corridor']} ({worst['bcr']:.2f}); a BCR below 1 means benefits plus revenue do not cover full cost." + tag)
