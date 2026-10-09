"""Per-model DeepSeek prices, conservative rate ceilings and stage roles from config/models.yaml."""

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .settings import ROOT

OFFICIAL_ENDPOINTS = ("https://api.deepseek.com", "https://api.deepseek.com/v1")


@dataclass(frozen=True)
class Rates:
    """USD per million tokens. Reservations always use these ceiling rates."""

    input: float
    output: float


@dataclass(frozen=True)
class Role:
    stage: str
    model: str
    thinking: bool
    max_output_tokens: int
    rates: Rates


def load(path: Path | None = None) -> dict:
    config = yaml.safe_load((path or ROOT / "config/models.yaml").read_text())
    for name, price in config["models"].items():
        ceiling = config["rate_ceilings"].get(name)
        if not ceiling:
            raise ValueError(f"Model {name} has no rate ceiling")
        for key, official in (("input", price["input_cache_miss_peak"]), ("output", price["output_peak"])):
            value = ceiling[key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < official:
                raise ValueError(f"Rate ceiling for {name} {key} must be finite and >= official peak {official}")
    return config


def roles(config: dict | None = None) -> dict[str, Role]:
    """Resolve stage roles; LLM_SCREENING_MODEL / LLM_MODEL override the default models."""
    config = config or load()
    chosen = {
        "screening": os.getenv("LLM_SCREENING_MODEL") or config["defaults"]["screening"],
        "strong": os.getenv("LLM_MODEL") or config["defaults"]["strong"],
    }
    result = {}
    for stage, spec in config["roles"].items():
        model = chosen[spec["tier"]]
        if model not in config["models"]:
            raise ValueError(f"Model {model!r} is not in the pricing table; it cannot be budgeted")
        ceiling = config["rate_ceilings"][model]
        result[stage] = Role(stage, model, bool(spec["thinking"]), int(spec["max_output_tokens"]),
                             Rates(float(ceiling["input"]), float(ceiling["output"])))
    return result


def is_peak(moment: datetime, config: dict | None = None) -> bool:
    config = config or load()
    moment = moment.astimezone(UTC)
    if moment.weekday() >= 5:
        return False
    return any(start <= moment.hour < end for start, end in config["peak_hours_utc"])


def call_cost(model: str, usage: dict, moment: datetime | None = None, config: dict | None = None) -> dict:
    """Upper bound (peak, all input as cache miss) and time-of-day estimate with cache hits."""
    config = config or load()
    price = config["models"][model]
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    hit = min(usage.get("prompt_cache_hit_tokens", 0), prompt)
    upper = (prompt * price["input_cache_miss_peak"] + completion * price["output_peak"]) / 1_000_000
    factor = 1.0 if moment is None or is_peak(moment, config) else 0.5
    estimate = factor * (
        hit * price["input_cache_hit_peak"]
        + (prompt - hit) * price["input_cache_miss_peak"]
        + completion * price["output_peak"]
    ) / 1_000_000
    return {"upper_bound_usd": round(upper, 8), "estimate_usd": round(estimate, 8)}
