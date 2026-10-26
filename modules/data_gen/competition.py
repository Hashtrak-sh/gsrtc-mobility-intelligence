"""Synthetic private competitor services (never scraped; not real operators or fares)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.data_gen import constants as C

OPERATORS = ("Synthetic Operator A", "Synthetic Operator B", "Synthetic Operator C", "Synthetic Operator D", "Synthetic Operator E")
SEATS = {"ordinary": 45, "AC_seater": 40, "AC_sleeper": 30, "premium": 26}
# private fare = base + per_km * km (illustrative; deliberately above the state tariff for the same bus class)
FARE = {"ordinary": (10.0, 1.40), "AC_seater": (25.0, 2.60), "AC_sleeper": (40.0, 3.60), "premium": (60.0, 4.30)}
SURGE = {"weekday": (1.00, 1.10), "weekend": (1.20, 1.35), "festival": (1.50, 1.80)}

# (HH:MM, bus_type) departures from the corridor origin (Rajkot). Both directions are assumed to mirror these slots.
SERVICES: dict[str, tuple[tuple[str, str], ...]] = {
    "Rajkot-Somnath": (
        ("06:00", "AC_seater"), ("07:30", "ordinary"), ("09:30", "AC_seater"), ("12:30", "AC_seater"), ("15:30", "ordinary"),
        # PLANTED: evening slot 18:00-22:30 where the state runs nothing on this corridor
        ("18:45", "AC_seater"), ("19:30", "AC_sleeper"), ("20:15", "AC_sleeper"), ("21:00", "AC_seater"),
        ("21:30", "AC_sleeper"), ("22:00", "premium"), ("22:15", "AC_sleeper"),
    ),
    "Rajkot-Junagadh": (("06:30", "AC_seater"), ("09:00", "AC_seater"), ("12:00", "ordinary"), ("15:00", "AC_seater"),
                        ("18:00", "AC_seater"), ("20:00", "premium")),
    "Rajkot-Jamnagar": (("06:00", "ordinary"), ("08:00", "AC_seater"), ("10:00", "AC_seater"), ("13:00", "ordinary"),
                        ("16:00", "AC_seater"), ("18:30", "AC_seater"), ("21:00", "premium")),
    "Rajkot-Ahmedabad": (("06:00", "AC_seater"), ("08:00", "AC_seater"), ("10:30", "ordinary"), ("13:00", "AC_seater"),
                         ("15:30", "AC_seater"), ("17:30", "AC_seater"), ("20:00", "AC_sleeper"), ("21:00", "AC_sleeper"),
                         ("22:00", "AC_sleeper"), ("22:30", "premium"), ("23:00", "AC_sleeper"), ("23:30", "AC_sleeper")),
}
EVENING_SLOT = ("18:00", "22:30")  # the Rajkot-Somnath planted gap window (inclusive)


def generate_competitors(corridor_km: dict[str, float], rng: np.random.Generator) -> pd.DataFrame:
    rows, k = [], 0
    for pair, services in SERVICES.items():
        km = corridor_km[pair]
        for hhmm, bt in services:
            op = OPERATORS[int(rng.integers(0, len(OPERATORS)))]
            base_fare = (FARE[bt][0] + FARE[bt][1] * km) * float(rng.uniform(0.94, 1.06))
            base_fare = round(base_fare / 10.0) * 10.0
            evening = hhmm >= "18:00"
            lo, hi = (4.3, 4.7) if (evening and bt != "ordinary") else ((3.4, 4.0) if bt == "ordinary" else (3.8, 4.5))
            rating = round(float(rng.uniform(lo, hi)), 1)
            for dt in C.DAY_TYPES:
                mult = float(rng.uniform(*SURGE[dt])) * (1.1 if (evening and bt != "ordinary") else 1.0)
                if pair == "Rajkot-Somnath" and dt == "festival":
                    mult *= 1.2
                k += 1
                rows.append({
                    "service_id": f"CS{k:04d}", "route_pair": pair, "operator": op, "departure_time": hhmm,
                    "day_type": dt, "bus_type": bt, "base_fare_inr": float(base_fare),
                    "surge_fare_inr": float(round(base_fare * mult / 10.0) * 10.0),
                    "seats": SEATS[bt], "rating": rating, "source_type": "synthetic",
                })
    return pd.DataFrame(rows)
