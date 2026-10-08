from pathlib import Path

import yaml

from .models import Scores


def weights(path: Path = Path("config/scoring.yaml")) -> dict[str, float]:
    result = yaml.safe_load(path.read_text())
    expected = set(Scores.model_fields) - {"rationales"}
    if set(result) != expected or any(
        not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in result.values()
    ):
        raise ValueError("Invalid scoring dimensions or weights")
    if abs(sum(result.values()) - 1) > 1e-9:
        raise ValueError("Scoring weights must sum to 1")
    return result


def score(s: Scores, w: dict[str, float] | None = None) -> float:
    w = weights() if w is None else w
    if (
        set(w) != set(Scores.model_fields) - {"rationales"}
        or any(v < 0 for v in w.values())
        or abs(sum(w.values()) - 1) > 1e-9
    ):
        raise ValueError("Invalid weights")
    # Anchors: all 1 -> 0; all 5 -> 100.
    return round(sum((getattr(s, k) - 1) / 4 * v * 100 for k, v in w.items()), 2)


def needs_review(s: Scores) -> bool:
    return (
        s.evidence_quality <= 2
        and max(s.industrial_relevance, s.economic_implications, s.technical_significance) >= 4
    )
