"""Synthetic survey responses (private-vehicle users + some bus users) and synthetic reviews.

JSON encoding: every list/dict column is written with ``json.dumps`` (double quotes), never Python repr.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from modules.data_gen import constants as C
from modules.data_gen import geography as G

_MODE_P = {"car": 0.38, "two_wheeler": 0.40, "bus": 0.12, "rail": 0.03, "shared_taxi": 0.04, "other": 0.03}
_PURPOSE_P = {"work": 0.55, "education": 0.10, "shopping": 0.10, "health": 0.05, "leisure": 0.15, "other": 0.05}
_INCOME_BY_MODE = {  # low, lower_middle, middle, upper_middle, high
    "car": (0.02, 0.08, 0.25, 0.35, 0.30), "two_wheeler": (0.08, 0.27, 0.38, 0.20, 0.07),
    "bus": (0.35, 0.35, 0.20, 0.08, 0.02), "rail": (0.20, 0.30, 0.30, 0.15, 0.05),
    "shared_taxi": (0.15, 0.30, 0.30, 0.18, 0.07), "other": (0.20, 0.30, 0.30, 0.15, 0.05),
}
_REASON_BASE = {
    "flexibility": 0.60, "door_to_door": 0.50, "comfort": 0.35, "bus_unreliable": 0.45, "no_ac_on_bus": 0.30,
    "low_bus_frequency": 0.40, "crowding": 0.25, "safety": 0.12, "no_direct_route": 0.30, "carries_goods_or_family": 0.22,
}
_TRANSIT_REASONS = {"low_cost": 0.7, "no_private_vehicle": 0.55, "direct_route": 0.35, "avoid_parking_hassle": 0.3, "safety": 0.1}
# switch-condition base probability and boosted probability when the matching reason was given
_COND_BASE = {"reliability": 0.50, "ac_comfort": 0.40, "frequency": 0.38, "lower_fare": 0.26, "safety": 0.22, "cleanliness": 0.20,
              "real_time_info": 0.18, "parking_cost_or_hassle": 0.14, "direct_route": 0.17}
_COND_BOOST = {"reliability": ("bus_unreliable", 0.85), "ac_comfort": ("no_ac_on_bus", 0.80), "frequency": ("low_bus_frequency", 0.78),
               "safety": ("safety", 0.55), "direct_route": ("no_direct_route", 0.50)}

_REASON_TEXT = {
    "flexibility": ["I can leave whenever I want", "my own vehicle gives me flexibility"],
    "door_to_door": ["I need to reach the exact doorstep", "there is no walk at either end"],
    "comfort": ["it is more comfortable", "I get a seat and privacy"],
    "bus_unreliable": ["buses are often late and I cannot predict them", "bus timings are not dependable"],
    "no_ac_on_bus": ["the bus has no air conditioning in the heat", "there is no AC on most buses"],
    "low_bus_frequency": ["buses are too infrequent on my route", "I wait too long between buses"],
    "crowding": ["the bus is overcrowded", "there is no space during peak hours"],
    "safety": ["I feel safer in my own vehicle", "late-evening travel by bus feels unsafe"],
    "no_direct_route": ["there is no direct bus to my destination", "I would need to change buses"],
    "carries_goods_or_family": ["I carry family or luggage", "I need to carry goods"],
}
_COND_TEXT = {
    "reliability": ["buses ran on time", "departure times were dependable"],
    "ac_comfort": ["there was an AC option", "the bus was air conditioned and comfortable"],
    "frequency": ["buses came more often", "the service was every 10-15 minutes"],
    "lower_fare": ["the fare was lower", "there was a cheaper pass"],
    "safety": ["the ride felt safe", "stops were well lit"],
    "cleanliness": ["buses were cleaner", "seats and floors were clean"],
    "real_time_info": ["I could see live bus timings", "there was a tracking app"],
    "parking_cost_or_hassle": ["parking cost more", "parking was harder to find"],
    "direct_route": ["there was a direct route", "I did not have to change buses"],
}
_MODE_PHRASE = {"car": "my car", "two_wheeler": "my two-wheeler", "bus": "the bus", "rail": "the train",
                "shared_taxi": "a shared taxi", "other": "other transport"}

_LOCAL_ZONES = [f"Z{i:02d}" for i in range(1, 15)]
_RES_ZONES = ["Z03", "Z04", "Z05", "Z06", "Z07", "Z08", "Z14"]
_EMP_ZONES = ["Z11", "Z12", "Z13"]


def _pick(rng: np.random.Generator, ids: list[str], w: np.ndarray, size: int) -> np.ndarray:
    w = np.asarray(w, float)
    return rng.choice(np.array(ids, dtype=object), size=size, p=w / w.sum())


def generate_survey(zones: pd.DataFrame, n: int, rng: np.random.Generator, seed: int) -> pd.DataFrame:
    z = zones.set_index("zone_id")
    modes = rng.choice(list(_MODE_P), size=n, p=list(_MODE_P.values()))
    purposes = rng.choice(list(_PURPOSE_P), size=n, p=list(_PURPOSE_P.values()))
    income = np.array([rng.choice(C.SURVEY_INCOME_BANDS, p=_INCOME_BY_MODE[m]) for m in modes], dtype=object)
    intercity = rng.random(n) < 0.06
    origin = _pick(rng, _RES_ZONES + ["Z01", "Z02", "Z09"], np.array([z.loc[i, "population"] for i in _RES_ZONES + ["Z01", "Z02", "Z09"]]), n)
    dest = np.empty(n, dtype=object)
    for k in range(n):
        p = purposes[k]
        if p == "work":
            ids = _EMP_ZONES + ["Z01", "Z02", "Z09"]
            w = np.array([z.loc[i, "jobs"] for i in ids], float)
            w[:3] *= 2.2  # industrial estates dominate morning commutes (planted finding 3 support)
        elif p == "education":
            ids, w = ["Z09", "Z01"], np.array([0.8, 0.2])
        elif p == "shopping":
            ids, w = ["Z01", "Z02", "Z10"], np.array([0.6, 0.3, 0.1])
        elif p == "health":
            ids, w = ["Z01", "Z02"], np.array([0.7, 0.3])
        elif p == "leisure":
            ids, w = ["Z01", "Z10", "Z09", "Z02"], np.array([0.4, 0.3, 0.1, 0.2])
        else:
            ids, w = _LOCAL_ZONES, np.ones(len(_LOCAL_ZONES))
        dest[k] = rng.choice(np.array(ids, dtype=object), p=w / w.sum())
        if dest[k] == origin[k]:
            dest[k] = "Z01" if origin[k] != "Z01" else "Z02"
    # a small share of intercity respondents (pilgrimage/business/leisure from Rajkot)
    ic_dest = rng.choice(np.array(["Z17", "Z20", "Z21", "Z22"], dtype=object), size=n, p=[0.2, 0.5, 0.15, 0.15])
    origin = np.where(intercity, "Z01", origin)
    dest = np.where(intercity, ic_dest, dest)
    purposes = np.where(intercity & (purposes == "education"), "leisure", purposes)

    private = np.isin(modes, ["car", "two_wheeler", "shared_taxi", "other"])
    reasons_json, cond_json, texts = [], [], []
    cond_flags = {c: np.zeros(n, dtype=int) for c in C.SWITCH_CONDITIONS}
    for k in range(n):
        if private[k]:
            rs = [r for r, p in _REASON_BASE.items() if rng.random() < p]
            if not rs:
                rs = ["flexibility"]
        else:
            rs = [r for r, p in _TRANSIT_REASONS.items() if rng.random() < p] or ["low_cost"]
        cs = []
        for c, base in _COND_BASE.items():
            p = base
            if c in _COND_BOOST and _COND_BOOST[c][0] in rs:
                p = _COND_BOOST[c][1]
            if rng.random() < p:
                cs.append(c)
                cond_flags[c][k] = 1
        reasons_json.append(json.dumps(rs))
        cond_json.append(json.dumps(cs))
        if private[k] and rs and rs[0] in _REASON_TEXT:
            why = _REASON_TEXT[rs[0]][rng.integers(0, 2)]
            sent = f"I travel by {_MODE_PHRASE[modes[k]]} because {why}."
        else:
            sent = f"I usually take {_MODE_PHRASE[modes[k]]}."
        if cs:
            c0 = cs[0]
            tail = _COND_TEXT[c0][rng.integers(0, 2)]
            sent += f" I would consider the bus if {tail}."
        else:
            sent += " I am not likely to switch."
        texts.append(sent)

    logit = np.full(n, C.INTENT_INTERCEPT)
    logit += C.INTENT_COEF["cond_reliability"] * cond_flags["reliability"]
    logit += C.INTENT_COEF["cond_ac_comfort"] * cond_flags["ac_comfort"]
    logit += C.INTENT_COEF["cond_frequency"] * cond_flags["frequency"]
    logit += C.INTENT_COEF["cond_lower_fare"] * cond_flags["lower_fare"]
    logit += C.INTENT_COEF["mode_car"] * (modes == "car")
    logit += C.INTENT_COEF["purpose_work"] * (purposes == "work")
    logit += C.INTENT_COEF["income_high"] * np.isin(income, ["upper_middle", "high"])
    p_switch = 1.0 / (1.0 + np.exp(-logit))
    intent = (rng.random(n) < p_switch).astype("float")
    intent_s = pd.array(np.where(private, intent, np.nan), dtype="Int64")

    start = datetime(2026, 8, 3)
    secs = rng.integers(0, C.N_DAYS * 86400, n)
    # responses collected 08:00-20:00 local
    day = secs // 86400
    tod = 8 * 3600 + rng.integers(0, 12 * 3600, n)
    ts = [start + timedelta(days=int(d), seconds=int(t)) for d, t in zip(day, tod)]
    df = pd.DataFrame({
        "response_id": [f"SR{i + 1:04d}" for i in range(n)],
        "timestamp": pd.to_datetime(ts).astype("datetime64[ns]"),
        "current_mode": modes.astype(object), "trip_purpose": purposes.astype(object),
        "origin_zone_id": origin.astype(object), "dest_zone_id": dest.astype(object),
        "reasons": reasons_json, "open_text": texts, "switch_conditions": cond_json,
        "income_band": income, "switch_intent": intent_s, "source_type": "synthetic",
    })
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    df["response_id"] = [f"SR{i + 1:04d}" for i in range(len(df))]
    return df


# ------------------------------------------------------------------ reviews
_THEME_P_NEG = {
    "state": {"punctuality": 0.65, "cleanliness": 0.50, "comfort_ac": 0.60, "staff_behaviour": 0.40, "booking_ease": 0.45, "safety": 0.30, "value": 0.15},
    "private": {"punctuality": 0.25, "cleanliness": 0.20, "comfort_ac": 0.12, "staff_behaviour": 0.20, "booking_ease": 0.12, "safety": 0.20, "value": 0.50},
}
_THEME_MENTION = {
    "state": {"punctuality": 0.55, "cleanliness": 0.30, "comfort_ac": 0.45, "staff_behaviour": 0.30, "booking_ease": 0.25, "safety": 0.15, "value": 0.30},
    "private": {"punctuality": 0.30, "cleanliness": 0.25, "comfort_ac": 0.55, "staff_behaviour": 0.25, "booking_ease": 0.35, "safety": 0.20, "value": 0.40},
}
_TEXT = {
    ("punctuality", "negative"): ["The bus left late and reached well after the scheduled time.", "Timings are not reliable; waited a long time at the stand."],
    ("punctuality", "positive"): ["Left on time and arrived as scheduled.", "Punctual departure, no waiting."],
    ("cleanliness", "negative"): ["Seats and windows were dirty.", "The bus was not clean inside."],
    ("cleanliness", "positive"): ["The bus was clean and well kept.", "Clean seats and floor."],
    ("comfort_ac", "negative"): ["No working AC and the seats were uncomfortable.", "The air conditioning was poor and the ride was hot."],
    ("comfort_ac", "positive"): ["Comfortable seats and cool AC.", "Very comfortable ride with good air conditioning."],
    ("staff_behaviour", "negative"): ["The conductor was rude and unhelpful.", "Staff did not answer questions politely."],
    ("staff_behaviour", "positive"): ["Driver and conductor were polite and helpful.", "Courteous staff."],
    ("booking_ease", "negative"): ["Booking was difficult and the counter queue was long.", "Online booking failed twice."],
    ("booking_ease", "positive"): ["Booking was quick and easy on the app.", "Easy ticket booking and a clear confirmation."],
    ("safety", "negative"): ["Did not feel safe during the late-evening trip.", "Driving was rash at times."],
    ("safety", "positive"): ["Felt safe throughout the trip.", "Careful driving and a secure feeling."],
    ("value", "negative"): ["The fare felt too high for what was offered.", "Expensive for the service."],
    ("value", "positive"): ["Good value for the fare.", "Reasonable price for the comfort."],
}
_PAIRS = ("Rajkot-Somnath", "Rajkot-Junagadh", "Rajkot-Jamnagar", "Rajkot-Ahmedabad")


def generate_reviews(n: int, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(n):
        op = "state" if rng.random() < 0.55 else "private"
        if op == "state" and rng.random() < 0.18:
            pair = "Rajkot-Local"
        else:
            pair = _PAIRS[int(rng.choice(4, p=[0.45, 0.2, 0.15, 0.2]))]
        themes = [t for t in C.REVIEW_THEMES if rng.random() < _THEME_MENTION[op][t]]
        if not themes:
            themes = [C.REVIEW_THEMES[int(rng.integers(0, len(C.REVIEW_THEMES)))]]
        themes = themes[:3]
        tagged, sentences, score = [], [], 0
        for t in themes:
            pol = "negative" if rng.random() < _THEME_P_NEG[op][t] else "positive"
            score += 1 if pol == "positive" else -1
            tagged.append({"theme": t, "polarity": pol})
            sentences.append(_TEXT[(t, pol)][int(rng.integers(0, 2))])
        rating = float(np.clip(np.round((3.3 + 0.55 * score / len(themes) + rng.normal(0, 0.45)) * 2) / 2, 1.0, 5.0))
        sentiment = "positive" if rating >= 4.0 else ("negative" if rating <= 2.5 else "neutral")
        rows.append({
            "review_id": f"RV{i + 1:04d}", "operator_type": op, "route_pair": pair, "rating": rating,
            "text": " ".join(sentences), "themes": json.dumps(tagged), "sentiment": sentiment, "source_type": "synthetic",
        })
    return pd.DataFrame(rows)
