"""Digital transformation roadmap built from the digital-maturity gaps in ``digital_assessment``.

Everything about the plan except the current maturity values is an illustrative assumption written for the demo
(``source_type = manual_demo_input``): the initiative catalogue, durations, target maturities, KPIs and the parallel-working
limit. They are not GSRTC plans. Current maturity comes from the (simulated) ``digital_assessment`` table.

Deterministic scheduling rule
-----------------------------
1. Current maturity per capability = mean of ``maturity_score`` across assessed assets (the weakest asset's score is kept
   as ``current_min``). ``gap = target - current`` for each initiative.
2. An initiative whose capability already meets its target (``gap <= 0``) is marked ``not needed`` and is not scheduled;
   dependants treat it as already complete (end month 0).
3. Priority = ``gap + FOUNDATION_WEIGHT * (number of initiatives that transitively depend on it)``: larger gaps and
   foundational dependencies go first. Ties are broken by initiative id.
4. List scheduling from month 0: at each decision month, every unscheduled initiative whose dependencies have all finished
   (dependency end <= month) is a candidate; candidates start in priority order while fewer than ``MAX_PARALLEL``
   initiatives are running. The clock then advances to the next month an initiative finishes. An initiative therefore never
   starts before its dependencies end.
5. Phase is derived from the scheduled start month only: Phase 1 Foundation 0-6, Phase 2 Scale 6-18, Phase 3 Optimise 18-36
   (the last phase also takes any later start). No phase number is placed by hand.
"""
from __future__ import annotations

import pandas as pd

SOURCE_TYPE = "manual_demo_input"
MAX_PARALLEL = 3          # illustrative: at most this many initiatives run at once (organisational capacity)
FOUNDATION_WEIGHT = 0.5   # illustrative: priority bonus per transitive dependant
HORIZON_MONTHS = 36
PHASES = [(1, "Foundation", 0, 6), (2, "Scale", 6, 18), (3, "Optimise", 18, 36)]

CAPABILITIES = ["e-ticketing", "live tracking", "passenger information", "payments", "analytics"]

# id, capability, initiative, dependencies, duration (months), target maturity (0-5), KPI
CATALOGUE = pd.DataFrame([
    ("ET1", "e-ticketing", "ETM fleet upgrade and standard electronic ticketing at counters and on board", (), 4, 3.0,
     "Share of tickets issued electronically (%)"),
    ("ET2", "e-ticketing", "UPI/QR payment at counters and online advance booking", ("ET1",), 6, 4.0,
     "Share of tickets paid by UPI/QR (%)"),
    ("LT1", "live tracking", "AVL/GPS devices on the fleet", (), 6, 3.0,
     "Share of scheduled buses reporting GPS position (%)"),
    ("LT2", "live tracking", "Control-room integration and operations dashboard", ("LT1",), 6, 4.0,
     "Share of trips monitored in the control room (%)"),
    ("PI1", "passenger information", "Digital timetable displays and helpline at bus stands", (), 4, 3.0,
     "Bus stands with a working information display (count)"),
    ("PI2", "passenger information", "App and WhatsApp bus arrival information", ("LT1",), 6, 4.0,
     "Passengers using arrival information per month (count)"),
    ("PM1", "payments", "NCMC/RuPay open-loop contactless cards on buses", ("ET2",), 9, 4.0,
     "Share of fare transactions by open-loop card (%)"),
    ("AN1", "analytics", "Ticketing and AVL data warehouse", ("ET1", "LT1"), 8, 2.5,
     "Share of trips with ticketing and GPS data joined (%)"),
    ("AN2", "analytics", "Operations and planning dashboard on live feeds", ("AN1", "ET2", "LT2"), 6, 4.0,
     "Days of data latency in management reports (days)"),
    ("LT3", "live tracking", "Predictive fleet maintenance from AVL and telematics data", ("LT2", "AN1", "AN2"), 8, 4.5,
     "Share of breakdowns predicted before failure (%)"),
    ("PI3", "passenger information", "Integrated multimodal journey planner with one-ticket payment (city bus, intercity, rail)",
     ("PI2", "PM1"), 8, 4.5, "Share of journeys planned or paid through the integrated planner (%)"),
    ("AN3", "analytics", "Demand forecasting and demand-responsive scheduling of timetables", ("AN2",), 8, 4.5,
     "Forecast error of daily route demand (%)"),
], columns=["id", "capability", "initiative", "dependencies", "duration_months", "target_maturity", "kpi"]).assign(source_type=SOURCE_TYPE)


def current_maturity(digital: pd.DataFrame) -> pd.DataFrame:
    """Per capability: mean (``current``), minimum across assets (``current_min``) and the weakest asset id."""
    d = digital.dropna(subset=["maturity_score"]).sort_values(["capability", "maturity_score", "asset_id"], kind="mergesort")
    g = d.groupby("capability")["maturity_score"]
    out = pd.DataFrame({"current": g.mean(), "current_min": g.min()})
    out["weakest_asset"] = d.groupby("capability")["asset_id"].first()
    return out


def phase_for_start(month: float) -> tuple[int, str]:
    for num, name, lo, hi in PHASES:
        if lo <= month < hi:
            return num, name
    return PHASES[-1][0], PHASES[-1][1]


def _dependants(cat: pd.DataFrame) -> dict[str, int]:
    deps = {r.id: set(r.dependencies) for r in cat.itertuples()}

    def ancestors(i: str, seen: set) -> set:
        for d in deps.get(i, ()):
            if d not in seen:
                seen.add(d)
                ancestors(d, seen)
        return seen
    count = {i: 0 for i in deps}
    for i in deps:
        for a in ancestors(i, set()):
            count[a] = count.get(a, 0) + 1
    return count


def build_roadmap(digital: pd.DataFrame, catalogue: pd.DataFrame | None = None, max_parallel: int = MAX_PARALLEL) -> pd.DataFrame:
    """Schedule the catalogue against the maturity gaps (see module docstring). One row per catalogue initiative."""
    cat = (CATALOGUE if catalogue is None else catalogue).reset_index(drop=True)
    cur = current_maturity(digital)
    df = cat.copy()
    df["current"] = df["capability"].map(cur["current"])
    df["current_min"] = df["capability"].map(cur["current_min"])
    df["gap"] = df["target_maturity"] - df["current"]
    # A capability with no assessment has no evidence of a gap, so it is not scheduled either.
    needed = df["gap"].gt(0)
    df["status"] = needed.map({True: "scheduled", False: "not needed"})
    dependants = _dependants(cat)
    df["priority"] = df["gap"].fillna(0) + FOUNDATION_WEIGHT * df["id"].map(dependants)

    end: dict[str, float] = {r.id: 0.0 for r in df.itertuples() if r.status == "not needed"}
    start: dict[str, float] = {}
    dur = dict(zip(df["id"], df["duration_months"]))
    deps = dict(zip(df["id"], df["dependencies"]))
    pending = {r.id for r in df.itertuples() if r.status == "scheduled"}
    prio = dict(zip(df["id"], df["priority"]))
    t = 0.0
    while pending:
        running = sum(1 for i in start if end[i] > t)
        ready = sorted((i for i in pending if all(d in end and end[d] <= t for d in deps[i])), key=lambda i: (-prio[i], i))
        for i in ready:
            if running >= max_parallel:
                break
            start[i], end[i] = t, t + dur[i]
            pending.discard(i)
            running += 1
        if not pending:
            break
        future = [e for e in end.values() if e > t]
        if not future:
            raise ValueError(f"Cannot schedule {sorted(pending)}: unmet or cyclic dependencies.")
        t = min(future)
    df["start_month"] = df["id"].map(start)
    df["end_month"] = df["id"].map(end).where(df["status"] == "scheduled")
    ph = [phase_for_start(m) if pd.notna(m) else (None, None) for m in df["start_month"]]
    df["phase"] = pd.array([p[0] for p in ph], dtype="Int64")
    df["phase_name"] = [p[1] for p in ph]
    return df.sort_values(["start_month", "id"], na_position="last", kind="mergesort").reset_index(drop=True)


def takeaway(rm: pd.DataFrame) -> str:
    """Computed summary of the roadmap."""
    sched = rm[rm["status"] == "scheduled"]
    if sched.empty:
        return "All capabilities already meet their illustrative targets, so no initiatives are scheduled."
    caps = sched.groupby("capability")["current"].first()
    weakest = caps.idxmin()
    p1 = sched[sched["phase"] == 1]
    p1_caps = sorted(p1["capability"].unique())
    last_end = sched["end_month"].max()
    dropped = rm[rm["status"] == "not needed"]
    w_start = sched.loc[sched["capability"] == weakest, "start_month"].min()
    lead = ("so it leads Phase 1" if w_start < PHASES[0][3] else
            f"but its first initiative cannot start until month {w_start:.0f} because it depends on foundations that go first")
    txt = (f"The weakest capability is {weakest} (average maturity {caps[weakest]:.1f} of 5), {lead}. "
           f"Phase 1 starts {len(p1)} initiative(s) covering {', '.join(p1_caps)}; "
           f"{len(sched)} initiatives are scheduled and the last finishes in month {last_end:.0f}.")
    if len(dropped):
        txt += " Not needed because already at target: " + "; ".join(f"{r.id} ({r.capability})" for r in dropped.itertuples()) + "."
    return txt
