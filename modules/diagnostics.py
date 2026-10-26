"""Environment/data diagnostics. Pure Python (no Streamlit); never raises for missing deps.

Optional packages are probed with ``importlib.util.find_spec`` so heavy
libraries are not imported just to report that they exist.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
from dataclasses import dataclass
from typing import Any

import config
from modules.data import io

# import name -> (pip distribution name, purpose)
OPTIONAL_DEPS: dict[str, tuple[str, str]] = {
    "osmnx": ("osmnx", "real OSM geography (geo)"),
    "networkx": ("networkx", "routing graphs (geo)"),
    "sklearn": ("scikit-learn", "ridership baseline model (ml)"),
    "ultralytics": ("ultralytics", "YOLO detector (cv)"),
    "supervision": ("supervision", "line-crossing counts (cv)"),
    "cv2": ("opencv-python", "video decoding (cv)"),
    "anthropic": ("anthropic", "Ask the Data LLM client (llm)"),
    "h3": ("h3", "optional hex grid"),
    "shap": ("shap", "model explanations (only for compatible fitted models)"),
    "prophet": ("prophet", "optional forecasting"),
}

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


@dataclass(frozen=True)
class DepStatus:
    module: str
    distribution: str
    purpose: str
    available: bool
    version: str | None


def _find(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def check_optional_deps() -> list[DepStatus]:
    out: list[DepStatus] = []
    for module, (dist, purpose) in OPTIONAL_DEPS.items():
        ok = _find(module)
        version: str | None = None
        if ok:
            try:
                version = importlib.metadata.version(dist)
            except importlib.metadata.PackageNotFoundError:
                version = None
        out.append(DepStatus(module, dist, purpose, ok, version))
    return out


def api_key_configured() -> bool:
    """Whether ANTHROPIC_API_KEY is set and non-empty. The key itself is never exposed."""
    return bool(os.environ.get(config.ANTHROPIC_API_KEY_ENV, "").strip())


def data_status() -> dict[str, dict[str, bool]]:
    """{layer: {table: exists}} for expected synthetic and processed tables."""
    return {
        layer: {t: io.table_exists(t, layer) for t in tables}
        for layer, tables in io.EXPECTED_TABLES.items()
    }


def video_clips() -> list[str]:
    d = config.VIDEO_DIR
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)


def run_diagnostics() -> dict[str, Any]:
    return {
        "optional_deps": check_optional_deps(),
        "anthropic_api_key_set": api_key_configured(),
        "data": data_status(),
        "video_clips": video_clips(),
        "h3_resolution": config.H3_RESOLUTION,
        "h3_available": config.h3_available(),
    }
