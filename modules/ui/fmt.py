"""Number/label formatting helpers for the UI: INR with Indian digit grouping, percentages, 24-hour times.

Pure functions (no Streamlit import). Missing values render as ``n/a``, never as ``nan``/``None``.
"""
from __future__ import annotations

import math
from typing import Any

NA = "n/a"
RUPEE = "\u20b9"


def _ok(x: Any) -> bool:
    if x is None or isinstance(x, bool):
        return False
    try:
        return not (math.isnan(float(x)) or math.isinf(float(x)))
    except (TypeError, ValueError):
        return False


def indian_group(digits: str) -> str:
    """Group a string of digits in the Indian system: ``1234567`` -> ``12,34,567``."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def number(x: Any, decimals: int = 0) -> str:
    """Plain number with Indian grouping (``1,23,456`` / ``1,234.5``)."""
    if not _ok(x):
        return NA
    v = round(float(x), decimals)
    sign = "-" if v < 0 else ""
    s = f"{abs(v):.{decimals}f}"
    whole, _, frac = s.partition(".")
    out = indian_group(whole) + (f".{frac}" if frac else "")
    if float(out.replace(",", "")) == 0:
        sign = ""
    return sign + out


def inr(x: Any, decimals: int = 0) -> str:
    """Rupees with Indian grouping: ``inr(123456) == '₹1,23,456'``; negatives as ``-₹4,37,150``."""
    if not _ok(x):
        return NA
    n = number(x, decimals)
    if n.startswith("-"):
        return f"-{RUPEE}{n[1:]}"
    return f"{RUPEE}{n}"


def inr_compact(x: Any) -> str:
    """Rupees in lakh/crore for large amounts (``₹18.50 lakh``); small amounts use :func:`inr`."""
    if not _ok(x):
        return NA
    v = float(x)
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e7:
        return f"{sign}{RUPEE}{a / 1e7:.2f} crore"
    if a >= 1e5:
        return f"{sign}{RUPEE}{a / 1e5:.2f} lakh"
    return inr(v)


def pct(x: Any, decimals: int = 1) -> str:
    """A value that is already a percentage (64.4 -> '64.4%')."""
    return NA if not _ok(x) else f"{float(x):.{decimals}f}%"


def ratio_pct(x: Any, decimals: int = 0) -> str:
    """A 0-1 ratio shown as a percentage (0.85 -> '85%')."""
    return NA if not _ok(x) else f"{float(x) * 100:.{decimals}f}%"


def km(x: Any, decimals: int = 1) -> str:
    return NA if not _ok(x) else f"{number(x, decimals)} km"


def times(x: Any, decimals: int = 2) -> str:
    """A multiple, e.g. peak load 1.58 x seats -> '1.58x'."""
    return NA if not _ok(x) else f"{float(x):.{decimals}f}x"


def hhmm(hour: Any) -> str:
    """24-hour clock label for a whole hour: 7 -> '07:00'."""
    return NA if not _ok(hour) else f"{int(hour):02d}:00"


def hour_window(lo: int, hi_exclusive: int) -> str:
    """``hour_window(7, 9) == '07:00-09:00'`` (en dash)."""
    return f"{hhmm(lo)}\u2013{hhmm(hi_exclusive)}"


def contiguous_windows(hours: list[int]) -> list[tuple[int, int]]:
    """Group sorted whole hours into ``(start, end_exclusive)`` runs: [18,19,20,21] -> [(18, 22)]."""
    hs = sorted({int(h) for h in hours})
    out: list[tuple[int, int]] = []
    for h in hs:
        if out and out[-1][1] == h:
            out[-1] = (out[-1][0], h + 1)
        else:
            out.append((h, h + 1))
    return out


def direction_label(d: str | None) -> str:
    return {"outbound": "outbound", "inbound": "inbound", "both": "both directions"}.get(str(d), str(d) if d else "")
