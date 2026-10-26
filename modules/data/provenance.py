"""Provenance metadata helper (RULES.md: source type, timestamp, seed, assumptions)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import config


class SourceType(str, Enum):
    """Allowed provenance source types (docs/DATA_SCHEMA.md)."""

    SYNTHETIC = "synthetic"
    OPENSTREETMAP = "openstreetmap"
    MANUAL_DEMO_INPUT = "manual_demo_input"
    MODEL_OUTPUT = "model_output"
    LIVE_DEMO_RESPONSE = "live_demo_response"


@dataclass(frozen=True)
class Provenance:
    source_type: SourceType
    generated_at: str
    seed: int | None
    assumptions: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Provenance":
        return cls(
            source_type=SourceType(d["source_type"]),
            generated_at=d["generated_at"],
            seed=d.get("seed"),
            assumptions=dict(d.get("assumptions", {})),
            description=d.get("description", ""),
        )

    @classmethod
    def from_json(cls, s: str) -> "Provenance":
        return cls.from_dict(json.loads(s))

    @property
    def is_simulated(self) -> bool:
        """True when values must carry the simulation badge."""
        return self.source_type in (SourceType.SYNTHETIC, SourceType.MODEL_OUTPUT)


def make_provenance(
    source_type: SourceType | str,
    *,
    seed: int | None = config.SEED,
    assumptions: dict[str, Any] | None = None,
    description: str = "",
    generated_at: datetime | None = None,
) -> Provenance:
    """Build a Provenance record. Raises ValueError for an unknown source_type."""
    st = SourceType(source_type)  # raises ValueError if invalid
    ts = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return Provenance(
        source_type=st,
        generated_at=ts.isoformat(timespec="seconds"),
        seed=seed,
        assumptions=dict(assumptions or {}),
        description=description,
    )
